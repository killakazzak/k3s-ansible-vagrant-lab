#!/usr/bin/env python3
"""Loopback-only cluster console; standard library, no pip dependencies."""
import sys
import argparse
import re
import shutil
import shlex
import tempfile
import base64
import ipaddress
import fcntl
import hmac
import json
import os
from pathlib import Path
import secrets
import statistics
import math
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import terminal_sessions
import topology
import lab_apps

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
ENV['PATH'] = ENV.get('PATH', '') + ':/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin'
ENV['VAGRANT_CWD'] = str(ROOT)
ENV['VAGRANT_DOTFILE_PATH'] = str(ROOT / '.vagrant')
CONTEXT = threading.local()
YAML_PREVIEWS = {}
def active_root():
    return getattr(CONTEXT, 'root', ROOT)

def cluster_root(name):
    if name == 'default':
        return ROOT
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,30}', name):
        raise ValueError('Некорректное имя кластера')
    path = ROOT / '.clusters' / name
    if not path.is_dir() or path.is_symlink():
        raise ValueError('Кластер не найден')
    return path

def run_kubectl(command):
    if not isinstance(command, str) or len(command) > 4096:
        raise ValueError('Введите команду kubectl длиной до 4096 символов.')
    args = shlex.split(command)
    if args and args[0] == 'kubectl':
        args.pop(0)
    verbs = {'get', 'describe', 'logs', 'top', 'version', 'api-resources',
             'api-versions', 'explain', 'auth', 'delete', 'scale', 'rollout',
             'label', 'annotate', 'cordon', 'uncordon', 'taint', 'wait'}
    if not args or args[0] not in verbs:
        raise ValueError('Поддерживаются get, describe, logs, top, explain, auth, delete, scale, rollout, label, annotate, cordon, uncordon, taint и wait. Интерактивные команды запускайте в обычном терминале.')
    blocked = {'--kubeconfig', '--context', '--server', '-s', '--token', '--username',
               '--password', '--user', '--cluster', '--client-key', '--client-certificate', '--certificate-authority',
               '--proxy-url', '--request-timeout', '--filename', '-f', '--kustomize', '-k',
               '--watch', '-w', '--watch-only', '--follow', '--log-file', '--log-dir',
               '--profile', '--profile-output', '--cache-dir'}
    for arg in args[1:]:
        flag = arg.split('=', 1)[0]
        if flag in blocked or (arg.startswith('-') and not arg.startswith('--') and len(arg) > 2 and arg[1] in 'sfkw'):
            raise ValueError('Этот параметр недоступен в веб-консоли: ' + flag)
        if arg in {'|', '||', '&&', ';', '>', '>>', '<', '&'}:
            raise ValueError('Вводите одну команду kubectl без операторов shell.')
    if args[0] == 'get' and any('template-file' in a or 'jsonpath-file' in a for a in args):
        raise ValueError('Чтение локальных файлов в веб-консоли недоступно.')
    root = active_root()
    kubeconfig = root / 'kubeconfig'
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or not kubeconfig.stat().st_size:
        raise ValueError('Подключение пока не готово. Дождитесь завершения создания кластера — kubectl подключится автоматически.')
    binary = next((str(p) for p in (root / '.tools/kubectl', ROOT / '.tools/kubectl') if p.is_file() and os.access(p, os.X_OK)), None)
    binary = binary or shutil.which('kubectl', path=ENV['PATH'])
    if not binary:
        raise ValueError('kubectl пока не установлен. Завершите развёртывание кластера.')
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run([binary, '--kubeconfig=' + str(kubeconfig), '--request-timeout=30s'] + args,
                                    cwd=root, env=cluster_env(root), stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=60)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size - 65536))
        text = output.read().decode('utf-8', errors='replace')
    if size > 65536:
        text = '[Показаны последние 64 КБ вывода]\n' + text
    if code == 124:
        text += '\nКоманда остановлена: превышено время ожидания (60 секунд).'
    return {'output': text, 'exit_code': code}

def cluster_names():
    folder = ROOT / '.clusters'
    return ['default'] + sorted(p.name for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch(r'[a-z][a-z0-9-]{0,30}', p.name)) if folder.exists() else ['default']

def cluster_env(root):
    return dict(ENV, PATH=str(root/'.offline-venv/bin')+':'+str(ROOT/'.offline-venv/bin')+':'+ENV['PATH'], VAGRANT_CWD=str(root), VAGRANT_DOTFILE_PATH=str(root / '.vagrant'))

def visible_clusters():
    previous = active_root()
    visible = []
    try:
        for name in cluster_names():
            CONTEXT.root = cluster_root(name)
            try:
                if config()['nodes']: visible.append(name)
            except Exception:
                visible.append(name)  # Keep broken profiles available for diagnosis.
    finally:
        CONTEXT.root = previous
    return visible

def check_cluster_network(network, exclude=None):
    previous = active_root()
    try:
        for name in cluster_names():
            if name == exclude:
                continue
            root = cluster_root(name)
            CONTEXT.root = root
            cfg = config()
            # Deleted profiles retain settings but no longer reserve their subnet.
            # Keep the reservation if VM state remains after an incomplete deletion.
            if not cfg['nodes'] and not any((root / '.vagrant/machines').glob('*/*/id')):
                continue
            if network.overlaps(ipaddress.ip_network(cfg['network'])):
                raise ValueError('Сеть пересекается с кластером ' + name)
    finally:
        CONTEXT.root = previous

def profile_in_use(name):
    previous = active_root()
    try:
        root = cluster_root(name)
        CONTEXT.root = root
        return bool(config()['nodes']) or any((root / '.vagrant/machines').glob('*/*/id'))
    except Exception:
        return True  # Never reuse a profile whose state cannot be read.
    finally:
        CONTEXT.root = previous

def next_cluster_name():
    used = {('k8s-cluster1' if name == 'default' else name)
            for name in cluster_names() if profile_in_use(name)}
    index = 1
    while 'k8s-cluster' + str(index) in used:
        index += 1
    return 'k8s-cluster' + str(index)

def new_cluster(name, cidr, params=None):
    name = name.strip() or next_cluster_name()
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,30}', name) or name == 'default':
        raise ValueError('Имя: строчные латинские буквы, цифры и дефисы, до 31 символа')
    network = ipaddress.ip_network(cidr, strict=True)
    if network.version != 4 or network.prefixlen != 24 or not any(network.subnet_of(ipaddress.ip_network(n)) for n in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']):
        raise ValueError('Для нового профиля задайте частную IPv4-сеть /24')
    check_cluster_network(network)
    folder = ROOT / '.clusters'
    folder.mkdir(exist_ok=True, mode=0o700)
    target = folder / name
    if target.exists() and profile_in_use(name):
        raise ValueError('Такое имя уже существует')
    temp = Path(tempfile.mkdtemp(prefix='.new-', dir=folder))
    try:
        for directory in ['ansible', 'scripts', 'web']:
            shutil.copytree(ROOT / directory, temp / directory, ignore=shutil.ignore_patterns('__pycache__', '*.log', '*.retry'))
        for filename in ['Vagrantfile', 'cluster.sh', 'deploy.sh', 'kubectl.sh', 'ansible.cfg']:
            shutil.copy2(ROOT / filename, temp / filename)
        (temp / 'vendor').symlink_to(ROOT / 'vendor', target_is_directory=True)
        code = """require 'yaml';require 'json'; p=JSON.parse(STDIN.read); path='ansible/group_vars/all.yml'; s=File.read(path); {'vm_name_prefix'=>'', 'menu_node_prefix'=>p['name'], 'private_network_prefix'=>24}.each{|k,v| s=s.sub(/^#{k}:.*$/,k+': '+JSON.generate(v))}; File.write(path,s); groups={}; {'server'=>[11,'master',1], 'workers'=>[21,'worker',2]}.each{|role,(offset,label,count)| h={};count.times{|i| n=p['name']+'-'+label+(i+1).to_s;h[n]={'ansible_host'=>p['base']+(offset+i).to_s,'vagrant_id'=>n}};groups[role]={'hosts'=>h}};File.write('ansible/inventory.yml',YAML.dump({'all'=>{'children'=>groups}}))"""
        proc = subprocess.run(['ruby','-e',code], cwd=temp, input=json.dumps({'name':name,'base':str(network.network_address).rsplit('.',1)[0]+'.'}), capture_output=True, text=True)
        if proc.returncode:
            raise ValueError('Не удалось создать конфигурацию: '+proc.stderr)
        # Validate the new network against Kubernetes pod/service subnets too.
        cfg = json.loads(subprocess.check_output(['ruby','-ryaml','-rjson','-e',"puts JSON.generate(YAML.load_file('ansible/group_vars/all.yml'))"],cwd=temp,text=True))
        if any(network.overlaps(ipaddress.ip_network(cfg[k])) for k in ['pod_subnet','service_subnet']):
            raise ValueError('Сеть пересекается с pod/service сетью')
        if params is not None:
            # Validate and save the requested topology before publishing the profile.
            plan = "require File.expand_path('scripts/web-action',Dir.pwd); p=JSON.parse(STDIN.read); m=WebAction.new(Dir.pwd,[]); data,changes=m.creation_plan(p);m.set_values(changes);m.write(File.join(Dir.pwd,'ansible/inventory.yml'),YAML.dump(data))"
            proc = subprocess.run(['ruby', '-e', plan], cwd=temp, input=json.dumps(dict(params, network_mode='existing')), capture_output=True, text=True)
            if proc.returncode:
                raise ValueError('Проверьте параметры кластера: ' + proc.stderr.strip())
        archived = None
        if target.exists():
            # Preserve deleted profile settings/history before reusing its name.
            archive_root = ROOT / '.cache/archived-profiles'
            archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            archived = Path(tempfile.mkdtemp(prefix=name + '-', dir=archive_root)) / 'profile'
            target.rename(archived)
        try:
            temp.rename(target)
        except OSError:
            if archived is not None:
                archived.rename(target)
            raise
    finally:
        if temp.exists(): shutil.rmtree(temp)
    return {'name': name}

TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
JOB = None
LAB_ACTIONS = {'rabbit_plugins','app_start','app_stop','app_restart','app_delete','app_deploy','template_deploy','app_update','app_rollback','app_check','stand_stop','stand_start'}
ACTIONS = LAB_ACTIONS | {'create', 'destroy', 'verify', 'add_master', 'add_worker', 'remove_master', 'remove_worker', 'resources', 'version'}
DESTRUCTIVE = {'app_delete','destroy', 'remove_master', 'remove_worker', 'version'}


def capture(args, timeout=15):
    p = subprocess.run(args, cwd=active_root(), env=cluster_env(active_root()), capture_output=True, text=True, timeout=timeout)
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
                              disk=host.get('vm_disk_gb', cfg.get('vm_disk_gb', {}).get(role,25)), vagrant_id=host['vagrant_id']))
    return dict(node_prefix=('k8s-cluster1' if cfg.get('menu_node_prefix', 'k3s') == 'k3s' else cfg['menu_node_prefix']), nodes=nodes, defaults={role:dict(cpu=cfg['vm_cpus'][role],ram=cfg['vm_memory_mb'][role],disk=cfg.get('vm_disk_gb',{}).get(role,25)) for role in ['server','workers']}, network=str(ipaddress.ip_network(str(nodes[0]['ip'])+'/'+str(cfg['private_network_prefix']) if nodes else cfg.get('private_network_cidr','192.168.58.0/24'), strict=False)), version=cfg['k3s_version'], provider=cfg['vm_provider'],
                rancher=cfg.get('rancher_enabled', False), traefik=cfg.get('traefik_dashboard_enabled', False)
                and 'traefik' not in cfg['disabled_components'])


def verify_stamp(root):
    return [((root / name).stat().st_mtime_ns if (root / name).exists() else None) for name in ('kubeconfig','ansible/inventory.yml')]

def verify_result(root):
    try:
        data=json.loads((root/'.cache/cluster-check.json').read_text())
        return data if data.get('stamp')==verify_stamp(root) and (root/'kubeconfig').exists() else None
    except (OSError,ValueError):return None

def status():
    result = config()
    result['verification'] = verify_result(active_root())
    result['reachable'] = False
    result['error'] = None
    if not result['nodes']:
        result['exists'] = False
        return result
    try:
        output = capture(['vagrant', 'status', '--machine-readable'], 20)
        states = {line.split(',')[1]: line.split(',')[3] for line in output.splitlines() if len(line.split(',')) >= 4 and line.split(',')[2] == 'state'}
        for node in result['nodes']:
            node['vm_state'] = states.get(node['vagrant_id'], 'unknown')
        result['exists'] = any(n['vm_state'] != 'not_created' for n in result['nodes'])
    except Exception:
        result['exists'] = None
        for node in result['nodes']: node['vm_state'] = 'unknown'
    if result['exists'] is False:
        for node in result['nodes']: node['state'] = 'Absent'
        return result
    if result['nodes'] and all(n.get('vm_state') in ('poweroff', 'saved', 'paused') for n in result['nodes']):
        result['paused'] = True
        for node in result['nodes']: node['state'] = 'Paused'
        return result
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


def node_utilization():
    from concurrent.futures import ThreadPoolExecutor
    root=active_root();env=cluster_env(root)
    def run(args):
        p=subprocess.run([str(root/'kubectl.sh')]+args,cwd=root,env=env,capture_output=True,text=True,timeout=9)
        if p.returncode:raise RuntimeError('Метрики узла недоступны')
        return json.loads(p.stdout)
    nodes=run(['get','nodes','-o','json','--request-timeout=5s'])['items']
    try:
        budgets=lab_apps.allocation(nodes,run(['get','pods','-A','-o','json','--request-timeout=5s'])['items'])
    except Exception:budgets={}
    def quantity(value):
        match=re.fullmatch(r'([0-9.]+)(Ki|Mi|Gi|Ti|m)?',str(value))
        if not match:return None
        return float(match[1])*{'Ki':1024,'Mi':1024**2,'Gi':1024**3,'Ti':1024**4,'m':.001,None:1}[match[2]]
    def metric(used,total,timestamp):
        return dict(used=used,total=total,percent=100*used/total if used is not None and total else None,time=timestamp)
    def one(node):
        name=node['metadata']['name']
        try:
            data=run(['get','--raw','/api/v1/nodes/'+name+'/proxy/stats/summary','--request-timeout=5s'])['node']
            capacity=node['status']['capacity'];cpu=data.get('cpu',{});memory=data.get('memory',{});disk=data.get('fs',{})
            return dict(name=name,allocation=budgets.get(name),cpu=metric(cpu['usageNanoCores']/1e9 if 'usageNanoCores' in cpu else None,quantity(capacity.get('cpu')),cpu.get('time')),memory=metric(memory.get('workingSetBytes'),quantity(capacity.get('memory')),memory.get('time')),disk=metric(disk.get('usedBytes'),disk.get('capacityBytes'),disk.get('time')))
        except (RuntimeError,ValueError,KeyError,subprocess.TimeoutExpired):return dict(name=name,allocation=budgets.get(name),error='Нет свежих метрик kubelet')
    with ThreadPoolExecutor(max_workers=4) as pool:return list(pool.map(one,nodes))

def links():
    if not config()['nodes']:
        return {}
    # Render configurable Jinja hostnames with Ansible, just like deployment does.
    output = capture(['ansible', 'server', '--limit', config()['nodes'][0]['name'], '-m', 'ansible.builtin.debug', '-a',
                      json.dumps({'msg': 'RANCHER_URL=https://{{ rancher_hostname }} TRAEFIK_URL=https://{{ traefik_dashboard_hostname }}/dashboard/'})], 20)
    import re
    return {key: re.search(label + r'=(https://[^\s"\\]+)', output).group(1)
            for key, label in [('rancher', 'RANCHER_URL'), ('traefik', 'TRAEFIK_URL')]}


def credentials(service):
    namespace, secret = {'rancher': ('cattle-system', 'bootstrap-secret'),
                         'traefik': ('kube-system', 'traefik-dashboard-auth')}[service]
    try:
        data = json.loads(capture(['./kubectl.sh', '-n', namespace, 'get', 'secret', secret,
                                   '-o', 'json', '--request-timeout=5s'], 8))['data']
        password = base64.b64decode(data['bootstrapPassword' if service == 'rancher' else 'password'], validate=True).decode()
        username = 'admin' if service == 'rancher' else base64.b64decode(data['username'], validate=True).decode()
        if not password:
            raise ValueError('empty password')
        return {'username': username, 'password': password}
    except Exception:
        raise RuntimeError('Не удалось получить пароль. Проверьте доступность кластера и наличие Secret сервиса.') from None


def timing_key(payload):
    # Network addresses and names do not affect the amount of deployment work.
    params = {k: str(v) for k, v in payload.get('params', {}).items()
              if k not in ('network', 'network_mode', 'name', 'ip', 'confirmation')}
    return json.dumps([payload['action'], params], sort_keys=True)

def timing_history():
    try:
        data = json.loads((ROOT / '.cache/durations.json').read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def timing_samples(key):
    values = timing_history().get(key, [])
    return [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v > 0][-5:] if isinstance(values, list) else []

def record_duration(key, seconds):
    history = timing_history()
    history[key] = (timing_samples(key) + [seconds])[-5:]
    folder = ROOT / '.cache'
    folder.mkdir(exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='duration-', dir=folder)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(history, output)
        os.replace(temporary, folder / 'durations.json')
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def execute(job, payload):
    try:
        key = timing_key(payload)
        samples = timing_samples(key)
        with LOCK:
            job['estimated_seconds'] = statistics.median(samples) if samples else None
            job['estimate_samples'] = len(samples)
        name = job.get('cluster', 'default')
        root = cluster_root(name)
        CONTEXT.root = root
        if payload['action'] == 'create' and payload.get('params', {}).get('network_mode') == 'new':
            proposed = ipaddress.ip_network(payload['params']['network'], strict=True)
            check_cluster_network(proposed, exclude=name)
        command = [sys.executable, str(ROOT / 'web/lab_action.py'), str(root)] if payload['action'] in LAB_ACTIONS else ['ruby', 'scripts/web-action.rb']
        p = subprocess.Popen(command, cwd=root, env=cluster_env(root), stdin=subprocess.PIPE,
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
        if payload['action']=='verify' and 'root' in locals():
            try:
                folder=root/'.cache';folder.mkdir(exist_ok=True)
                data=dict(state=job['state'],finished=job['finished'],duration=round(job['finished']-job['started']),stamp=verify_stamp(root))
                fd,temp=tempfile.mkstemp(dir=folder,prefix='cluster-check-')
                with os.fdopen(fd,'w') as out:json.dump(data,out)
                os.replace(temp,folder/'cluster-check.json')
            except OSError:pass
        if job['state'] == 'success':
            try:
                record_duration(key, job['finished'] - job['started'])
            except OSError:
                pass  # Optional timing history must not fail a completed deployment.


STOPPING = False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, code, data, content_type='application/json; charset=utf-8', download=None):
        body = json.dumps(data, ensure_ascii=False).encode() if not isinstance(data, bytes) else data
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="' + download + '"')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
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
        try:
            CONTEXT.root = cluster_root(self.headers.get('X-Lab-Cluster', 'default'))
        except ValueError as e:
            self.reply(400, {'error': str(e)})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/', '/app.js', '/style.css', '/vendor/xterm.js', '/vendor/xterm.css', '/vendor/addon-fit.js', '/graph.js', '/apps.js'):
            if self.headers.get('Host') != '127.0.0.1:' + str(self.server.server_port):
                return self.reply(403, {'error': 'Недопустимый Host'})
            file, mime = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css'), '/vendor/xterm.js': ('vendor/xterm.js', 'text/javascript'), '/vendor/xterm.css': ('vendor/xterm.css', 'text/css'), '/vendor/addon-fit.js': ('vendor/addon-fit.js', 'text/javascript'), '/graph.js': ('graph.js', 'text/javascript'), '/apps.js': ('apps.js', 'text/javascript')}[path]
            return self.reply(200, (ROOT / 'web' / file).read_bytes(), mime + '; charset=utf-8')
        if not self.allowed():
            return
        try:
            if path == '/api/kubeconfig':
                file = active_root() / 'kubeconfig'
                if file.is_symlink():
                    return self.reply(409, {'error': 'Файл подключения недоступен для скачивания.'})
                try:
                    content = file.read_bytes()
                except FileNotFoundError:
                    content = b''
                if not content:
                    return self.reply(409, {'error': 'Доступ к кластеру пока не готов. Kubeconfig появится после настройки кластера. Дождитесь завершения развёртывания.'})
                name = self.headers.get('X-Lab-Cluster', 'default')
                filename = ('k8s-cluster1' if name == 'default' else name) + '-kubeconfig.yaml'
                return self.reply(200, content, 'application/yaml', download=filename)
            if path == '/api/clusters':
                return self.reply(200, visible_clusters())
            if path in ('/api/credentials/rancher', '/api/credentials/traefik'):
                return self.reply(200, credentials(path.rsplit('/', 1)[1]))
            if path == '/api/secret-info':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).secret_info())
            if path == '/api/node-utilization':
                return self.reply(200, node_utilization())
            if path == '/api/pvcs':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).pvcs())
            if path == '/api/resources':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).resources())
            if path == '/api/apps':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).listing())
            if path == '/api/templates':
                return self.reply(200, lab_apps.templates())
            if path == '/api/topology':
                if not (active_root() / 'kubeconfig').is_file():
                    return self.reply(409, {'error':'Карта появится после настройки кластера.'})
                data = json.loads(capture(['./kubectl.sh', 'get', 'nodes,pods,services,ingresses.networking.k8s.io,endpointslices.discovery.k8s.io,replicasets.apps,deployments.apps,daemonsets.apps,statefulsets.apps,jobs.batch,cronjobs.batch', '-A', '-o', 'json', '--request-timeout=10s'], 15))
                warning = None
                try:
                    extra = json.loads(capture(['./kubectl.sh', 'get', 'ingressroutes.traefik.io', '-A', '-o', 'json', '--request-timeout=5s'], 8))
                    data['items'].extend(extra.get('items', []))
                except Exception:
                    warning = 'IngressRoute Traefik недоступны; показаны стандартные Ingress.'
                result = topology.build(data['items'])
                result.update(updated=time.time(), warning=warning)
                return self.reply(200, result)
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
        global JOB, STOPPING
        if not self.allowed():
            return
        if self.path not in ('/api/action', '/api/clusters', '/api/kubectl', '/api/terminal', '/api/shutdown', '/api/templates', '/api/pod', '/api/pods', '/api/app-access', '/api/resource-yaml', '/api/yaml-preview', '/api/yaml-apply'):
            return self.reply(404, {'error': 'Не найдено'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= (2097152 if self.path=='/api/yaml-preview' else 32768):
                raise ValueError('Некорректный размер запроса')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Некорректный запрос')
            if self.path == '/api/shutdown':
                with LOCK:
                    if JOB and JOB['state'] == 'running':
                        return self.reply(409, {'error':'Сейчас выполняется операция с кластером. Дождитесь её завершения перед остановкой веб-сервера.'})
                    STOPPING = True
                self.reply(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if STOPPING:
                return self.reply(409, {'error':'Веб-сервер завершает работу.'})
            if self.path == '/api/templates':
                with LOCK:
                    operation=data.get('operation','save')
                    if operation=='delete':return self.reply(200, lab_apps.delete_template(data))
                    if operation=='update':return self.reply(200, lab_apps.update_template(data))
                    if operation=='from_apps':return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).template_from_apps(data))
                    if operation!='save':raise ValueError('Неизвестная операция с шаблоном')
                    return self.reply(200, lab_apps.save_template(data))
            if self.path in ('/api/yaml-preview','/api/yaml-apply'):
                with LOCK:
                    if JOB and JOB['state']=='running':return self.reply(409,{'error':'Дождитесь завершения текущей операции.'})
                    root=active_root();apps=lab_apps.Apps(root,cluster_env(root))
                    for key in list(YAML_PREVIEWS):
                        if YAML_PREVIEWS[key]['expires']<time.time():del YAML_PREVIEWS[key]
                    if self.path=='/api/yaml-preview':
                        candidate,diff=apps.yaml_preview(data)
                        token=secrets.token_urlsafe(32)
                        if len(YAML_PREVIEWS)>=32:YAML_PREVIEWS.pop(next(iter(YAML_PREVIEWS)))
                        YAML_PREVIEWS[token]=dict(root=str(root),candidate=candidate,expires=time.time()+300)
                        return self.reply(200,dict(token=token,diff=diff,changed=bool(diff)))
                    if data.get('confirmed') is not True:raise ValueError('Подтвердите применение изменений')
                    preview=YAML_PREVIEWS.get(data.get('token',''))
                    if not preview or preview['root']!=str(root):raise ValueError('Просмотр изменений устарел. Проверьте YAML повторно.')
                    result=apps.yaml_apply(preview['candidate'])
                    del YAML_PREVIEWS[data['token']]
                    return self.reply(200,result)
            if self.path == '/api/resource-yaml':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).resource_yaml(data))
            if self.path == '/api/app-access':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).access(data))
            if self.path == '/api/pods':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).workload_pods(data))
            if self.path == '/api/pod':
                return self.reply(200, lab_apps.Apps(active_root(),cluster_env(active_root())).diagnostics(data))
            if self.path == '/api/terminal':
                data.pop('_command',None)
                if data.get('operation')=='open' and data.get('pod'):
                    ns=lab_apps.namespace(data.get('namespace'));name=lab_apps.resource_name(data['pod'])
                    pod=lab_apps.Apps(active_root(),cluster_env(active_root())).get('pod',ns,name)
                    container=data.get('container');spec=pod['spec']
                    if container not in [c['name'] for c in spec.get('containers',[])+spec.get('initContainers',[])+spec.get('ephemeralContainers',[])]:raise ValueError('Контейнер не найден в Pod')
                    mode=data.get('mode','shell')
                    if mode=='logs':args=['logs','-f','--tail=200','--timestamps','-n',ns,name,'-c',container]
                    elif mode=='shell':
                        shell=data.get('shell','sh')
                        if shell not in ('sh','bash'):raise ValueError('Выберите sh или bash')
                        args=['exec','-it','-n',ns,name,'-c',container,'--',shell]
                    else:raise ValueError('Неизвестный режим дебага')
                    data['_command']=[str(active_root()/'kubectl.sh')]+args
                env = cluster_env(active_root())
                env['PATH'] = str(ROOT / '.tools') + ':' + env['PATH']
                return self.reply(200, terminal_sessions.handle(data, active_root(), env))
            if self.path == '/api/kubectl':
                return self.reply(200, run_kubectl(data.get('command')))
            if self.path == '/api/clusters':
                if data.get('confirmed') is not True or not isinstance(data.get('params'), dict):
                    raise ValueError('Подтвердите создание кластера с выбранными параметрами')
                with LOCK:
                    if STOPPING or (JOB and JOB['state'] == 'running'):
                        return self.reply(409, {'error':'Дождитесь текущей операции'})
                    result = new_cluster(data.get('name', ''), data.get('network', ''), data['params'])
                    payload = {'action':'create', 'confirmed':True, 'params':dict(data['params'], network_mode='existing')}
                    JOB = dict(cluster=result['name'], id=secrets.token_hex(8), action='create', state='running', log='', started=time.time())
                    threading.Thread(target=execute, args=(JOB, payload), daemon=True).start()
                    return self.reply(201, result)
            action = data.get('action')
            if action not in ACTIONS or data.get('confirmed') is not True:
                raise ValueError('Неизвестная операция или нет подтверждения')
            if action in DESTRUCTIVE and data.get('confirmation') != 'УДАЛИТЬ':
                raise ValueError('Для удаления данных введите УДАЛИТЬ')
            if not isinstance(data.get('params', {}), dict):
                raise ValueError('Некорректные параметры')
            with LOCK:
                if STOPPING or (JOB and JOB['state'] == 'running'):
                    return self.reply(409, {'error': 'Дождитесь завершения текущей операции'})
                JOB = dict(cluster=self.headers.get('X-Lab-Cluster', 'default'), id=secrets.token_hex(8), action=action, state='running', log='', started=time.time())
                threading.Thread(target=execute, args=(JOB, data), daemon=True).start()
            self.reply(202, {'ok': True})
        except (ValueError, TypeError, OSError, subprocess.TimeoutExpired) as e:
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
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        terminal_sessions.cleanup()
        server.server_close()
