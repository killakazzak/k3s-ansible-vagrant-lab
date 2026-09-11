#!/usr/bin/env python3
"""Loopback-only cluster console; standard library, no pip dependencies."""
import argparse
import ipaddress
import fcntl
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
ENV['PATH'] = ENV.get('PATH', '') + ':/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin'
ENV['VAGRANT_CWD'] = str(ROOT)
ENV['VAGRANT_DOTFILE_PATH'] = str(ROOT / '.vagrant')
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
JOB = None
ACTIONS = {'create', 'destroy', 'verify', 'add_master', 'add_worker', 'remove_master', 'remove_worker', 'resources', 'version'}
DESTRUCTIVE = {'destroy', 'remove_master', 'remove_worker', 'version'}


def capture(args, timeout=15):
    p = subprocess.run(args, cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Команда завершилась с ошибкой')
    return p.stdout


def config():
    code = "require 'yaml'; require 'json'; puts JSON.generate({settings: YAML.load_file('ansible/group_vars/all.yml'), inventory: YAML.load_file('ansible/inventory.yml')})"
    data = json.loads(capture(['ruby', '-e', code]))
    cfg = data['settings']
    groups = data['inventory']['all']['children']
    nodes = []
    for role, group in groups.items():
        for name, host in group['hosts'].items():
            nodes.append(dict(name=name, role=role, ip=host['ansible_host'],
                              cpu=host.get('vm_cpus', cfg['vm_cpus'][role]),
                              ram=host.get('vm_memory_mb', cfg['vm_memory_mb'][role]),
                              disk=host.get('vm_disk_gb', cfg.get('vm_disk_gb', {}).get(role,64))))
    return dict(nodes=nodes, network=str(ipaddress.ip_network(str(nodes[0]['ip'])+'/'+str(cfg['private_network_prefix']), strict=False)), version=cfg['k3s_version'], provider=cfg['vm_provider'],
                rancher=cfg.get('rancher_enabled', False), traefik=cfg.get('traefik_dashboard_enabled', False)
                and 'traefik' not in cfg['disabled_components'])


def status():
    result = config()
    result['reachable'] = False
    result['error'] = None
    try:
        live = json.loads(capture(['./kubectl.sh', 'get', 'nodes', '-o', 'json', '--request-timeout=5s'], 8))
        lookup = {n['metadata']['name']: n for n in live['items']}
        result['reachable'] = True
        for node in result['nodes']:
            n = lookup.get(node['name'])
            node['state'] = ('Ready' if any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status'].get('conditions', [])) else 'NotReady') if n else 'Absent'
            node['actual_version'] = n['status']['nodeInfo']['kubeletVersion'] if n else None
    except (RuntimeError, subprocess.TimeoutExpired, ValueError) as e:
        result['error'] = str(e)[:500]
        for node in result['nodes']:
            node['state'] = 'Unknown'
    return result


def links():
    # Render configurable Jinja hostnames with Ansible, just like deployment does.
    output = capture(['ansible', 'server', '--limit', config()['nodes'][0]['name'], '-m', 'ansible.builtin.debug', '-a',
                      json.dumps({'msg': 'RANCHER_URL=https://{{ rancher_hostname }} TRAEFIK_URL=https://{{ traefik_dashboard_hostname }}/dashboard/'})], 20)
    import re
    return {key: re.search(label + r'=(https://[^\s"\\]+)', output).group(1)
            for key, label in [('rancher', 'RANCHER_URL'), ('traefik', 'TRAEFIK_URL')]}


def execute(job, payload):
    try:
        p = subprocess.Popen(['ruby', 'scripts/web-action.rb'], cwd=ROOT, env=ENV, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        p.stdin.write(json.dumps(payload))
        p.stdin.close()
        for line in p.stdout:
            with LOCK:
                job['log'] = (job['log'] + line)[-150000:]
        rc = p.wait()
        with LOCK:
            job['state'] = 'success' if rc == 0 else 'failed'
            job['exit_code'] = rc
    except Exception as e:
        with LOCK:
            job['log'] += '\n' + str(e)
            job['state'] = 'failed'
    finally:
        with LOCK:
            job['finished'] = time.time()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, code, data, content_type='application/json; charset=utf-8'):
        body = json.dumps(data, ensure_ascii=False).encode() if not isinstance(data, bytes) else data
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        expected = '127.0.0.1:' + str(self.server.server_port)
        if self.headers.get('Host') != expected:
            self.reply(403, {'error': 'Недопустимый Host'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + expected:
            self.reply(403, {'error': 'Недопустимый Origin'})
            return False
        if not hmac.compare_digest(self.headers.get('X-Lab-Token', ''), TOKEN):
            self.reply(401, {'error': 'Откройте полный адрес из терминала запуска, включая #token=…'})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/app.js', '/style.css'):
            if self.headers.get('Host') != '127.0.0.1:' + str(self.server.server_port):
                return self.reply(403, {'error': 'Недопустимый Host'})
            file, mime = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}[path]
            return self.reply(200, (ROOT / 'web' / file).read_bytes(), mime + '; charset=utf-8')
        if not self.allowed():
            return
        try:
            if path == '/api/status':
                return self.reply(200, status())
            if path == '/api/links':
                return self.reply(200, links())
            if path == '/api/job':
                with LOCK:
                    snapshot = dict(JOB) if JOB else None
                return self.reply(200, snapshot)
            return self.reply(404, {'error': 'Не найдено'})
        except Exception as e:
            return self.reply(500, {'error': str(e)})

    def do_POST(self):
        global JOB
        if not self.allowed():
            return
        if self.path != '/api/action':
            return self.reply(404, {'error': 'Не найдено'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 8192:
                raise ValueError('Некорректный размер запроса')
            data = json.loads(self.rfile.read(length))
            action = data.get('action')
            if action not in ACTIONS or data.get('confirmed') is not True:
                raise ValueError('Неизвестная операция или нет подтверждения')
            if action in DESTRUCTIVE and data.get('confirmation') != 'УДАЛИТЬ':
                raise ValueError('Для удаления данных введите УДАЛИТЬ')
            if not isinstance(data.get('params', {}), dict):
                raise ValueError('Некорректные параметры')
            with LOCK:
                if JOB and JOB['state'] == 'running':
                    return self.reply(409, {'error': 'Дождитесь завершения текущей операции'})
                JOB = dict(id=secrets.token_hex(8), action=action, state='running', log='', started=time.time())
                threading.Thread(target=execute, args=(JOB, data), daemon=True).start()
            self.reply(202, {'ok': True})
        except (ValueError, TypeError) as e:
            self.reply(400, {'error': str(e)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    (ROOT / '.cache').mkdir(exist_ok=True)
    lock_path = ROOT / '.cache/web.lock'
    instance_lock = os.fdopen(os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600), 'r+')
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        for attempt in range(20):
            instance_lock.seek(0)
            try:
                existing = json.load(instance_lock)
                url = existing['url']
                break
            except (ValueError, KeyError):
                time.sleep(0.1)
        else:
            print('Веб-консоль уже работает. Откройте ссылку из терминала её запуска.')
            raise SystemExit(0)
        print('Веб-консоль уже работает. Откройте существующий интерфейс:')
        print(url, flush=True)
        raise SystemExit(0)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{server.server_port}/#token={TOKEN}'
    instance_lock.seek(0)
    instance_lock.truncate()
    json.dump({'url': url}, instance_lock)
    instance_lock.flush()
    print(f'\nK3s Lab → {url}', flush=True)
    print('Оставьте терминал открытым. Ctrl+C останавливает веб-сервер; дождитесь окончания операций перед выходом.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
