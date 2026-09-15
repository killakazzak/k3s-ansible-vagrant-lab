#!/usr/bin/env python3
"""Persistent host cache. Export only images already present on Vagrant nodes."""
import argparse, contextlib, hashlib, json, os, shlex, subprocess, tempfile
from pathlib import Path

def cache_root():
    return Path(os.environ.get('K3S_LAB_CACHE_ROOT',str(Path.home()/'.cache/k3s-lab'))).expanduser()

def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def entries(arch):
    result=[]
    for path in sorted((cache_root()/'images'/arch).glob('*.json')):
        try:
            data=json.loads(path.read_text());archive=path.with_suffix('.tar')
            if data['arch']!=arch or not isinstance(data['digest'],str) or not isinstance(data['refs'],list) or not archive.is_file() or checksum(archive)!=data['sha256']:continue
            result.append((archive,data))
        except (OSError,ValueError,KeyError):continue
    return result

def run(args,**kw):
    return subprocess.run(args,check=True,timeout=kw.pop('timeout',120),**kw)

@contextlib.contextmanager
def connections(root):
    with tempfile.TemporaryDirectory(prefix='k3s-image-cache-') as folder:
        config=Path(folder)/'ssh-config'
        env=dict(os.environ,VAGRANT_CWD=str(root),VAGRANT_DOTFILE_PATH=str(root/'.vagrant'))
        with config.open('w') as out:run(['vagrant','ssh-config'],cwd=root,env=env,stdout=out,stderr=subprocess.PIPE)
        nodes=[line.split()[1] for line in config.read_text().splitlines() if line.startswith('Host ')]
        yield lambda node:['ssh','-F',str(config),'-o','ConnectTimeout=5','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=3','-T',node],nodes

def node_arch(ssh):
    value=run(ssh+['uname -m'],capture_output=True,text=True,timeout=15).stdout.strip()
    if value not in ('aarch64','arm64','x86_64','amd64'):raise ValueError('Unsupported node architecture: '+value)
    return 'arm64' if value in ('aarch64','arm64') else 'amd64'

def capture(root):
    saved=0
    with connections(root) as (ssh,nodes):
        for node in nodes:
            try:
                arch=node_arch(ssh(node));known={d['digest'] for _,d in entries(arch)}
                listing=run(ssh(node)+['sudo k3s ctr images list'],capture_output=True,text=True,timeout=30).stdout
                groups={}
                for line in listing.splitlines()[1:]:
                    parts=line.split()
                    if len(parts)<3 or not parts[2].startswith('sha256:') or parts[0].startswith('sha256:'):continue
                    groups.setdefault(parts[2],[]).append(parts[0])
                for digest,refs in groups.items():
                    if digest in known:continue
                    folder=cache_root()/'images'/arch;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                    key=hashlib.sha256(digest.encode()).hexdigest();dest=folder/(key+'.tar')
                    print('[Кеш] Сохраняем с '+node+': '+', '.join(refs),flush=True)
                    fd,temp=tempfile.mkstemp(dir=folder,suffix='.part')
                    try:
                        with os.fdopen(fd,'wb') as out:run(ssh(node)+['sudo k3s ctr images export --skip-manifest-json --platform linux/'+arch+' - '+' '.join(shlex.quote(v) for v in refs)],stdout=out,stderr=subprocess.PIPE,timeout=300)
                        temp=Path(temp);sha=checksum(temp);os.replace(temp,dest)
                        metadata=dict(arch=arch,digest=digest,refs=refs,sha256=sha)
                        fd,record=tempfile.mkstemp(dir=folder,suffix='.part')
                        with os.fdopen(fd,'w') as out:json.dump(metadata,out)
                        os.replace(record,dest.with_suffix('.json'));known.add(digest);saved+=1
                    except (OSError,ValueError,subprocess.SubprocessError) as error:
                        detail=getattr(error,'stderr',b'') or b''
                        if isinstance(detail,bytes):detail=detail.decode(errors='replace')
                        print('[Кеш] Не сохранён '+refs[0]+': '+(detail.strip()[-500:] or type(error).__name__),flush=True)
                    finally:Path(temp).unlink(missing_ok=True)
            except (OSError,ValueError,subprocess.SubprocessError) as error:
                print('[Кеш] '+node+': не удалось сохранить все образы ('+type(error).__name__+'). Повторите capture, пока VM доступна.',flush=True)
    print('[Кеш] Сохранено архивов: '+str(saved)+'. Папка: '+str(cache_root()),flush=True)

def canonical(ref):
    if '/' not in ref:return 'docker.io/library/'+ref
    if '.' not in ref.split('/')[0] and ':' not in ref.split('/')[0] and ref.split('/')[0]!='localhost':return 'docker.io/'+ref
    return ref

def restore(root,images):
    wanted={canonical(v) for v in images}
    if not wanted:return
    with connections(root) as (ssh,nodes):
        for node in nodes:
            arch=node_arch(ssh(node))
            present=set(run(ssh(node)+['sudo k3s ctr images list -q'],capture_output=True,text=True,timeout=30).stdout.splitlines())
            for archive,data in entries(arch):
                refs=set(data['refs'])
                if not refs&wanted or refs&wanted<=present:continue
                print('[Кеш] Загружаем на '+node+': '+', '.join(sorted(refs&wanted)),flush=True)
                with archive.open('rb') as source:run(ssh(node)+['sudo k3s ctr images import --platform linux/'+arch+' -'],stdin=source,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=300)
                present.update(refs)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['capture','restore','restore-rancher','list']);parser.add_argument('--cluster',default=os.getcwd());parser.add_argument('--arch',choices=['arm64','amd64'],default='arm64');args=parser.parse_args()
    if args.operation=='list':print(json.dumps([str(p) for p,_ in entries(args.arch)]));return
    if os.environ.get('K3S_LAB_IMAGE_CACHE','1')=='0':return
    root=Path(args.cluster).absolute()
    if args.operation=='capture':capture(root)
    elif args.operation=='restore-rancher':
        refs=[ref for _,data in entries(args.arch) for ref in data['refs'] if ref.startswith(('docker.io/rancher/','quay.io/jetstack/'))]
        restore(root,refs)
    else:restore(root,json.load(__import__('sys').stdin))
if __name__=='__main__':main()
