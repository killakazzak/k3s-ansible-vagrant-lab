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
    if path=='/api/action' and data.get('action') in ('app_change_kind','remote_traefik_publish','remote_rancher_install','remote_ingress_update','remote_ingress_delete','remote_ingress_install','app_deploy','template_deploy','app_edit','app_delete'):return
    if path in ('/api/templates','/api/gitlab-secret','/api/app-access','/api/app-settings'):return
    if path in ('/api/connections','/api/clusters','/api/pod','/api/pods','/api/resource-yaml','/api/yaml-preview','/api/yaml-apply','/api/resource-delete','/api/shutdown'):return
    if path=='/api/terminal':
        op=data.get('operation')
        if op in ('poll','close','resize'):return
        if op=='open' and data.get('pod') and data.get('mode')=='logs':return
    raise ValueError('Внешнее подключение работает в режиме просмотра. Изменение кластера и shell отключены.')


def verify(repo, env, root):
    """Bounded, read-only checks; no diagnostic Pods or RBAC mutations."""
    import time
    if not (root/'kubeconfig').is_file():
        raise ValueError('Доступ к Kubernetes ещё не настроен')
    executable = binary(repo, env)
    checks = []
    def read(title, args, evaluate, optional=False):
        try:
            result = subprocess.run([executable, '--kubeconfig='+str(root/'kubeconfig'), '--request-timeout=5s']+args,
                                    capture_output=True, text=True, timeout=8, env=env)
            if result.returncode:
                error = result.stderr.lower()
                if 'forbidden' in error:
                    message = 'Недостаточно прав RBAC для этой проверки.'
                elif 'unauthorized' in error:
                    message = 'Учётные данные отклонены. Обновите kubeconfig.'
                elif 'x509' in error or 'certificate' in error:
                    message = 'Ошибка проверки сертификата TLS.'
                else:
                    message = 'API не ответил успешно: проверьте сеть, VPN и доступность ресурса.'
                checks.append(dict(title=title, state='warning' if optional or 'forbidden' in error else 'failed', message=message))
                return False
            state, message = evaluate(result.stdout)
            checks.append(dict(title=title, state=state, message=message))
            return True
        except (OSError, subprocess.TimeoutExpired):
            checks.append(dict(title=title, state='warning' if optional else 'failed', message='Превышено время ожидания или kubectl недоступен.'))
        except (ValueError, KeyError, TypeError):
            checks.append(dict(title=title, state='warning', message='Не удалось разобрать ответ API.'))
        return False
    reachable = read('Kubernetes API', ['get', '--raw=/version'], lambda text: ('success', json.loads(text).get('gitVersion', 'API доступен')))
    if reachable:
        read('Готовность API', ['get', '--raw=/readyz'], lambda text: ('success' if text.strip()=='ok' else 'failed', 'API готов' if text.strip()=='ok' else 'API сообщает о неготовности'))
        def nodes(text):
            items = json.loads(text)['items']; issues=[]
            for item in items:
                conditions=item.get('status',{}).get('conditions',[])
                if not any(c['type']=='Ready' and c['status']=='True' for c in conditions):issues.append(item['metadata']['name']+': NotReady')
                for c in conditions:
                    if c['type'] in ('MemoryPressure','DiskPressure','PIDPressure','NetworkUnavailable') and c['status']=='True':issues.append(item['metadata']['name']+': '+c['type'])
            return ('failed', '; '.join(issues)) if issues else ('success', str(len(items))+' узлов Ready') if items else ('warning', 'Узлы не найдены')
        read('Узлы и ресурсы', ['get','nodes','-o','json'], nodes)
        def pods(text):
            items=json.loads(text)['items']; bad=[]
            for item in items:
                status=item.get('status',{})
                if status.get('phase')=='Succeeded':continue
                if status.get('phase')!='Running' or not any(c.get('type')=='Ready' and c.get('status')=='True' for c in status.get('conditions',[])):bad.append(item['metadata']['name'])
            return ('warning', 'Не готовы: '+', '.join(bad[:15])) if bad else ('success', 'Системные Pods готовы: '+str(len(items))) if items else ('warning', 'В kube-system нет Pods')
        read('Системные компоненты · kube-system', ['get','pods','-n','kube-system','-o','json'], pods)
        read('Метрики узлов', ['get','--raw=/apis/metrics.k8s.io/v1beta1/nodes'], lambda text: ('success','Метрики доступны: '+str(len(json.loads(text)['items']))+' узлов') if json.loads(text)['items'] else ('warning','Метрики пока пусты'), optional=True)
    return dict(checks=checks, finished=time.time(), state='failed' if any(c['state']=='failed' for c in checks) else 'warning' if any(c['state']=='warning' for c in checks) else 'success')


def publication_ip(root, value=None):
    """Remember the explicitly supplied ingress address, never the API server IP."""
    if not external(root):
        if value is not None: raise ValueError('Выберите удалённый кластер')
        return ''
    path=root/'connection.json'
    profile=json.loads(path.read_text())
    if value is None: return profile.get('publication_ip','')
    import ipaddress
    try: value=str(ipaddress.IPv4Address(str(value).strip()))
    except ValueError: raise ValueError('Укажите корректный IPv4 адрес ingress-контроллера')
    profile['publication_ip']=value
    fd,temporary=tempfile.mkstemp(dir=root,prefix='.publication-')
    try:
        with os.fdopen(fd,'w') as stream: json.dump(profile,stream)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return value
