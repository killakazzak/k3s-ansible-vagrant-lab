"""Local connections to existing clusters. No provisioning or cluster mutations."""
import json, os, re, shutil, subprocess, tempfile
from pathlib import Path
from urllib.parse import urlsplit

def external(root):
    return (root/'connection.json').is_file()

def binary(repo, env):
    local=repo/'.tools/kubectl'
    found=str(local) if local.is_file() else shutil.which('kubectl',path=env.get('PATH'))
    if not found: raise ValueError('Для подключения нужен kubectl. Установите его через проверку окружения или добавьте в PATH.')
    return found

def parse(repo, env, content):
    if not isinstance(content,str) or not 0<len(content.encode())<=1048576:
        raise ValueError('Выберите kubeconfig размером до 1 МБ')
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'config'
        path.write_text(content);path.chmod(0o600)
        # config view only parses; it does not run credential plugins or contact the API.
        p=subprocess.run([binary(repo,env),'--kubeconfig='+str(path),'config','view','--raw','-o','json'],capture_output=True,text=True,timeout=10,env=env)
        if p.returncode:raise ValueError('Не удалось прочитать kubeconfig. Проверьте формат файла.')
        try: result=json.loads(p.stdout)
        except ValueError:raise ValueError('Некорректный kubeconfig')
    if not result.get('contexts'):raise ValueError('В kubeconfig нет контекстов')
    return result

def select(config, context):
    def entry(key,name,body):
        values=[x[body] for x in config.get(key,[]) if x.get('name')==name]
        if len(values)!=1:raise ValueError('Контекст, кластер или пользователь не найден либо неоднозначен')
        return values[0]
    ctx=entry('contexts',context,'context')
    cluster=entry('clusters',ctx.get('cluster'),'cluster')
    user=entry('users',ctx.get('user'),'user')
    if any(k in user for k in ('exec','auth-provider','tokenFile','client-key','client-certificate')) or 'certificate-authority' in cluster:
        raise ValueError('Нужен автономный kubeconfig: встроенные сертификаты и token, без exec, auth-provider и ссылок на локальные файлы.')
    url=urlsplit(cluster.get('server',''))
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Адрес Kubernetes API должен быть HTTPS без пароля и параметров URL')
    if cluster.get('insecure-skip-tls-verify'):
        raise ValueError('Включите проверку TLS: добавьте certificate-authority-data вместо insecure-skip-tls-verify.')
    # Reconstruct a minimal document, excluding extensions and unrelated credentials.
    c={k:v for k,v in cluster.items() if k in ('server','certificate-authority-data','tls-server-name')}
    u={k:v for k,v in user.items() if k in ('token','client-certificate-data','client-key-data','username','password')}
    if not u:raise ValueError('В выбранном контексте нет поддерживаемых учётных данных')
    return dict(apiVersion='v1',kind='Config',clusters=[dict(name='remote',cluster=c)],users=[dict(name='remote',user=u)],contexts=[dict(name=context,context=dict(cluster='remote',user='remote',**({'namespace':ctx['namespace']} if ctx.get('namespace') else {})))],**{'current-context':context})

def connect(repo,env,data):
    name=data.get('name','').strip()
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,23}',name):raise ValueError('Имя: латинские строчные буквы, цифры и дефисы, до 24 символов')
    config=select(parse(repo,env,data.get('kubeconfig')),data.get('context'))
    key='remote-'+name
    folder=repo/'.connections';folder.mkdir(mode=0o700,exist_ok=True)
    dest=folder/key
    if dest.exists() or (repo/'.clusters'/key).exists():raise ValueError('Такое имя подключения уже занято')
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        root=Path(tmp)
        path=root/'kubeconfig';path.write_text(json.dumps(config));path.chmod(0o600)
        (root/'connection.json').write_text(json.dumps(dict(name=name,context=data['context'])))
        (root/'kubectl.sh').symlink_to(repo/'kubectl.sh')
        (root/'.tools').symlink_to(repo/'.tools',target_is_directory=True)
        # A bounded read verifies both connectivity and permission to list nodes.
        p=subprocess.run([binary(repo,env),'--kubeconfig='+str(path),'get','nodes','-o','name','--request-timeout=8s'],capture_output=True,text=True,timeout=12,env=env)
        if p.returncode:raise ValueError('Не удалось подключиться: проверьте доступность API, VPN, сертификаты и право list nodes. Подключение не сохранено.')
        os.rename(root,dest)
    return {'name':key}

def disconnect(repo, root):
    if root.parent!=repo/'.connections' or root.is_symlink() or not external(root):raise ValueError('Это не внешнее подключение')
    shutil.rmtree(root)
    return {'ok':True}

def permit(path,data):
    if path in ('/api/connections','/api/clusters','/api/pod','/api/pods','/api/resource-yaml','/api/shutdown'):return
    if path=='/api/terminal':
        op=data.get('operation')
        if op in ('poll','close','resize'):return
        if op=='open' and data.get('pod') and data.get('mode')=='logs':return
    raise ValueError('Внешнее подключение работает в режиме просмотра. Изменение кластера и shell отключены.')
