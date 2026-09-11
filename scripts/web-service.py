#!/usr/bin/env python3
"""Start and stop this project's console without managing unrelated processes."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
if ROOT.parent.name == '.clusters':
    ROOT = ROOT.parent.parent

def running_url():
    path = ROOT / '.cache/web.lock'
    try:
        with path.open() as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return None
            except BlockingIOError:
                data = json.load(stream)
    except (FileNotFoundError, ValueError):
        return None
    url = data.get('url', '')
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password:
        raise ValueError('Некорректный адрес веб-сервера')
    return url

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    url = running_url()
    if args.action == 'start':
        if not url:
            cache = ROOT / '.cache'
            cache.mkdir(exist_ok=True)
            log = cache / 'web-server.log'
            fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.chmod(log, 0o600)
            with os.fdopen(fd, 'a') as output:
                process = subprocess.Popen([sys.executable, str(ROOT / 'web/server.py'), '--port', str(args.port)], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
            for _ in range(100):
                url = running_url()
                if url: break
                if process.poll() is not None: raise ValueError('Не удалось запустить веб-сервер. Журнал: ' + str(log))
                time.sleep(.1)
            if not url: raise ValueError('Веб-сервер не успел запуститься. Проверьте ' + str(log))
        print('Веб-сервер работает в фоне. Закрытие меню не останавливает его.')
        print(url)
    elif args.action == 'stop':
        if not url:
            print('Веб-сервер уже остановлен.')
            return
        parsed = urlsplit(url)
        token = parse_qs(parsed.fragment).get('token', [''])[0]
        request = Request('http://' + parsed.netloc + '/api/shutdown', data=b'{}', headers={'X-Lab-Token': token, 'Content-Type':'application/json'})
        try:
            with urlopen(request, timeout=5) as response: response.read()
        except HTTPError as error:
            if error.code == 404: raise ValueError('Запущена старая версия веб-сервера. Перезапустите её для управления через меню.')
            raise ValueError(json.load(error).get('error', 'Ошибка остановки'))
        for _ in range(100):
            if not running_url():
                print('Веб-сервер остановлен. Кластеры и VM продолжают работать.')
                return
            time.sleep(.1)
        raise ValueError('Сервер ещё завершает работу. Повторите проверку состояния.')
    else:
        print('Веб-сервер остановлен.' if not url else 'Веб-сервер работает:\n' + url)

if __name__ == '__main__':
    try: main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
