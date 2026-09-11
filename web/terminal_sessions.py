"""Private PTY sessions for the loopback console."""
import json, atexit, base64, fcntl, os, pty, secrets, signal, struct, subprocess, sys, tempfile, termios, threading, time
from pathlib import Path
SESSIONS = {}
LOCK = threading.Lock()
class Session:
    def __init__(self, root, env, command=None):
        self.root = root
        self.condition = threading.Condition()
        self.buffer = bytearray()
        self.offset = 0
        self.finished = False
        self.touched = time.monotonic()
        self.settings = tempfile.TemporaryDirectory(prefix='k3s-shell-')
        (Path(self.settings.name) / '.zshrc').write_text('''autoload -Uz compinit
compinit -D
bindkey -e
bindkey '^I' expand-or-complete
HISTSIZE=2000
SAVEHIST=0
PROMPT='[%F{green}${LAB_CLUSTER}%f] %~ %# '
setopt PROMPT_SUBST
if (( $+commands[kubectl] )); then
 source <(kubectl completion zsh)
 alias k=kubectl
 compdef k=kubectl
fi
print 'Tab — дополнение · ↑/↓ — история · Ctrl+C — остановить'
''')
        env = dict(env, ZDOTDIR=self.settings.name, TERM='xterm-256color', KUBECONFIG=str(root/'kubeconfig'), LAB_CLUSTER=root.name, PATH=str(root/'.tools')+':'+env['PATH'])
        if command:env["LAB_PTY_COMMAND"]=json.dumps(command)
        else:env.pop("LAB_PTY_COMMAND",None)
        self.master, slave = pty.openpty()
        self.resize(100,24)
        try:
            self.process = subprocess.Popen([sys.executable,str(Path(__file__).with_name('terminal_child.py'))], stdin=slave,stdout=slave,stderr=slave,cwd=root,env=env,close_fds=True)
        except Exception:
            os.close(self.master)
            self.settings.cleanup()
            raise
        finally:
            os.close(slave)
        threading.Thread(target=self.read,daemon=True).start()
    def resize(self, cols, rows):
        cols, rows = int(cols), int(rows)
        if not 20 <= cols <= 400 or not 5 <= rows <= 150:
            raise ValueError('Некорректный размер терминала')
        fcntl.ioctl(self.master,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0))
    def read(self):
        try:
            while True:
                chunk=os.read(self.master,8192)
                if not chunk: break
                with self.condition:
                    self.buffer.extend(chunk)
                    self.offset+=len(chunk)
                    if len(self.buffer)>262144: del self.buffer[:-262144]
                    self.condition.notify_all()
        except OSError: pass
        finally:
            with self.condition:
                self.finished=True
                self.condition.notify_all()
    def poll(self, offset):
        with self.condition:
            if offset==self.offset and not self.finished: self.condition.wait(1)
            start=max(0,self.offset-len(self.buffer))
            if offset<0 or offset>self.offset: raise ValueError('Некорректная позиция вывода')
            return dict(output=base64.b64encode(bytes(self.buffer[max(offset-start,0):])).decode(),offset=self.offset,truncated=offset<start,finished=self.finished)
    def close(self):
        try:
            fg=os.tcgetpgrp(self.master)
            if fg>0 and fg!=os.getpgrp(): os.killpg(fg,signal.SIGHUP)
        except OSError: pass
        if self.process.poll() is None:
            try: os.killpg(self.process.pid,signal.SIGHUP)
            except ProcessLookupError: pass
            except PermissionError:
                if self.process.poll() is None:self.process.terminate()
        os.close(self.master)
        try: self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.settings.cleanup()
def handle(data,root,env):
    action=data.get('operation')
    with LOCK:
        if action=='open':
            if len(SESSIONS)>=8: raise ValueError('Закройте неиспользуемые терминалы (максимум 8).')
            file=root/'kubeconfig'
            if file.is_symlink() or not file.is_file() or not file.stat().st_size: raise ValueError('Подключение пока не готово. Дождитесь настройки кластера.')
            session=Session(root,env,data.get("_command"))
            key=secrets.token_hex(24)
            SESSIONS[key]=session
            return {'id':key}
        key=data.get('id')
        session=SESSIONS.get(key)
        if not session or session.root!=root: raise ValueError('Сессия завершена. Откройте терминал заново.')
        session.touched=time.monotonic()
        if action=='close':
            del SESSIONS[key]
            session.close()
            return {'ok':True}
        if action=='resize':
            session.resize(data.get('cols'),data.get('rows'))
            return {'ok':True}
        if action=='input':
            text=data.get('input')
            if not isinstance(text,str) or len(text.encode())>4096: raise ValueError('Слишком большой ввод')
            if session.finished: raise ValueError('Оболочка завершена. Закройте сессию и откройте заново.')
            payload=text.encode()
            while payload:
                count=os.write(session.master,payload)
                payload=payload[count:]
            return {'ok':True}
        if action!='poll': raise ValueError('Неизвестная операция терминала')
    return session.poll(int(data.get('offset',0)))
def cleanup():
    with LOCK:
        for session in list(SESSIONS.values()): session.close()
        SESSIONS.clear()
def reap():
    while True:
        time.sleep(30)
        with LOCK:
            for key,session in list(SESSIONS.items()):
                if time.monotonic()-session.touched>1800: SESSIONS.pop(key).close()
atexit.register(cleanup)
threading.Thread(target=reap,daemon=True).start()
