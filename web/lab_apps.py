"""Application catalogue, repeatable templates and scoped Kubernetes diagnostics."""
import json, os, re, secrets, subprocess, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MANAGER = 'k3s-lab-catalog'
CATALOG = {'nginx': {'image':'nginx:1.30.4-alpine','port':80}, 'postgres':{'image':'postgres:18.6-alpine','port':5432}, 'redis':{'image':'redis:8.10.1-alpine','port':6379}, 'kafka':{'image':'apache/kafka:4.3.1','port':9092}, 'rabbitmq':{'image':'rabbitmq:4.3.5-management','port':5672}, 'custom':{'image':'','port':8080}}
STATEFUL = ('postgres','redis','kafka','rabbitmq')
PROTECTED = {'kube-system','kube-public','kube-node-lease','cattle-system','cert-manager','default'}

def dns(value, label='имя'):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',value):
        raise ValueError('Некорректное '+label)
    return value

def namespace(value, mutate=False):
    dns(value,'namespace')
    if mutate and (value in PROTECTED or value.startswith(('kube-','cattle-'))):
        raise ValueError('Для приложений используйте отдельный namespace, не системный.')
    return value

def number(value, low, high, label):
    try: result=int(value)
    except (TypeError,ValueError): raise ValueError('Некорректное значение: '+label)
    if not low<=result<=high: raise ValueError(f'{label}: от {low} до {high}')
    return result

def validate(config):
    if not isinstance(config,dict):raise ValueError('Некорректная конфигурация приложения')
    kind=config.get('type','nginx')
    if kind not in CATALOG: raise ValueError('Неизвестный тип приложения')
    image=config.get('image',CATALOG[kind]['image'])
    if not isinstance(image,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,250}',image):raise ValueError('Укажите корректный образ с тегом или digest')
    if ':' not in image.rsplit('/',1)[-1] or image.endswith(':latest'):raise ValueError('Укажите версию образа вместо latest')
    if kind=='postgres' and not re.fullmatch(r'(?:docker.io/library/)?postgres:(?:17|18)(?:[.\w-]*)',image):raise ValueError('Каталог PostgreSQL поддерживает ветки 17 и 18. Смена major требует отдельной миграции данных.')
    if kind=='redis' and not re.fullmatch(r'(?:docker.io/library/)?redis:(?:7|8)(?:[.\w-]*)',image):raise ValueError('Каталог Redis поддерживает ветки 7 и 8.')
    if kind=='kafka' and not re.fullmatch(r'(?:docker.io/)?apache/kafka:4\.(?:0|3)\.\d+',image):raise ValueError('Kafka: используйте apache/kafka:4.3.x')
    if kind=='rabbitmq' and not re.fullmatch(r'(?:docker.io/library/)?rabbitmq:4\.(?:1|3)(?:\.\d+)?-management',image):raise ValueError('RabbitMQ: используйте rabbitmq:4.3.5-management')
    if kind in ('kafka','rabbitmq') and int(config.get('port',CATALOG[kind]['port']))!=CATALOG[kind]['port']:raise ValueError('Для брокеров используется стандартный порт')
    host=config.get('host','').strip()
    if host and not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host):raise ValueError('URL: укажите hostname без http:// и пути')
    if host and ('..' in host or len(host)>253 or any(len(part)>63 for part in host.split('.'))):raise ValueError('Некорректный hostname')
    if kind in ('postgres','redis','kafka') and host:raise ValueError('HTTP Ingress не применяется к PostgreSQL/Redis/Kafka')
    return dict(type=kind,name=dns(config.get('name',''),'имя приложения'),namespace=namespace(config.get('namespace','dev'),True),image=image,
                replicas=number(config.get('replicas',1),1,1 if kind in STATEFUL else 10,'реплики'),
                cpu=number(config.get('cpu',100),25,8000,'CPU, millicores'),memory=number(config.get('memory',1024 if kind=='kafka' else 512 if kind=='rabbitmq' else 256),768 if kind=='kafka' else 256 if kind=='rabbitmq' else 32,16384,'RAM, MiB'),
                storage=number(config.get('storage',2),1,100,'диск, GiB'),port=number(config.get('port',CATALOG[kind]['port']),1,65535,'порт'),host=host)

def templates():
    path=ROOT/'.cache/app-templates.json'
    if not path.exists():return []
    data=json.loads(path.read_text())
    return data if isinstance(data,list) else []

def save_template(data):
    name=dns(data.get('name',''),'имя шаблона');items=data.get('apps')
    if not isinstance(items,list) or not 1<=len(items)<=10:raise ValueError('В шаблоне должно быть от 1 до 10 приложений')
    apps=[validate(c) for c in items]
    if len({(a['namespace'],a['name']) for a in apps})!=len(apps):raise ValueError('Имена приложений в namespace должны отличаться')
    values=[v for v in templates() if v['name']!=name]+[dict(name=name,apps=apps)]
    folder=ROOT/'.cache';folder.mkdir(exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=folder,prefix='templates-')
    try:
        with os.fdopen(fd,'w') as out:json.dump(values,out,ensure_ascii=False,indent=2)
        os.replace(temp,folder/'app-templates.json')
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return {'ok':True}

class Apps:
    def __init__(self,root,env=None):self.root=Path(root);self.env=env or os.environ.copy()
    def kubectl(self,args,body=None,timeout=30):
        p=subprocess.run([str(self.root/'kubectl.sh')]+args,cwd=self.root,env=self.env,input=json.dumps(body) if body is not None else None,capture_output=True,text=True,timeout=timeout)
        if p.returncode:raise ValueError(p.stderr.strip()[-3000:] or 'kubectl завершился с ошибкой')
        return p.stdout
    def get(self,resource,ns=None,name=None):
        args=['get',resource]+([name] if name else [])+(['-n',ns] if ns else ['-A'])+['-o','json','--request-timeout=10s']
        return json.loads(self.kubectl(args))
    def find(self,resource,ns,name):
        return json.loads(self.kubectl(['get',resource,name]+(['-n',ns] if ns else [])+['--ignore-not-found','-o','json','--request-timeout=10s']) or 'null')
    def apply(self,objects):
        self.kubectl(['apply','--server-side','--field-manager='+MANAGER,'-f','-'],{'apiVersion':'v1','kind':'List','items':objects})
    def listing(self):
        items=self.get('deployments.apps,statefulsets.apps')['items'];out=[]
        for obj in items:
            m=obj['metadata'];ns=m.get('namespace','default')
            if ns in PROTECTED or ns.startswith(('kube-','cattle-')):continue
            containers=obj['spec']['template']['spec']['containers']
            out.append(dict(name=m['name'],namespace=ns,kind=obj['kind'],replicas=obj['spec'].get('replicas',1),ready=obj.get('status',{}).get('readyReplicas',0),containers=[dict(name=c['name'],image=c['image']) for c in containers],managed=m.get('labels',{}).get('app.kubernetes.io/managed-by')==MANAGER,type=m.get('labels',{}).get('lab.k3s/type','custom')))
        return out
    def workload_pods(self,data):
        ns=namespace(data.get('namespace'));name=dns(data.get('name'));kind=data.get('kind')
        if kind not in ('Deployment','StatefulSet'):raise ValueError('Неизвестный тип workload')
        obj=self.get(kind,ns,name);selector=obj['spec']['selector']
        def matches(labels):
            if any(labels.get(k)!=v for k,v in selector.get('matchLabels',{}).items()):return False
            for expr in selector.get('matchExpressions',[]):
                key,op=expr['key'],expr['operator'];values=expr.get('values',[])
                if op=='In' and labels.get(key) not in values:return False
                if op=='NotIn' and labels.get(key) in values:return False
                if op=='Exists' and key not in labels:return False
                if op=='DoesNotExist' and key in labels:return False
            return True
        return [dict(name=p['metadata']['name'],namespace=ns,phase=p.get('status',{}).get('phase','Unknown')) for p in self.get('pods',ns)['items'] if matches(p['metadata'].get('labels',{}))]
    def diagnostics(self,data):
        ns=namespace(data.get('namespace'));name=dns(data.get('name'),'Pod')
        pod=self.get('pod',ns,name);spec=pod['spec'];status=pod.get('status',{})
        containers=[c['name'] for c in spec.get('containers',[])]+[c['name'] for c in spec.get('initContainers',[])]
        container=data.get('container') or containers[0]
        if container not in containers:raise ValueError('Контейнер не найден')
        try:logs=self.kubectl(['logs',name,'-n',ns,'-c',container,'--tail=150','--limit-bytes=30000']+(['--previous'] if data.get('previous') else []),timeout=15)
        except (ValueError,subprocess.TimeoutExpired) as e:logs=str(e)
        events=json.loads(self.kubectl(['get','events','-n',ns,'--field-selector=involvedObject.uid='+pod['metadata']['uid'],'-o','json']))['items']
        statuses=status.get('containerStatuses',[])+status.get('initContainerStatuses',[])
        return dict(name=name,namespace=ns,container=container,containers=containers,phase=status.get('phase','Unknown'),node=spec.get('nodeName'),conditions=[dict(type=c['type'],status=c['status'],reason=c.get('reason',''),message=c.get('message','')) for c in status.get('conditions',[])],statuses=[dict(name=c['name'],ready=c.get('ready',False),restarts=c.get('restartCount',0),state=c.get('state',{}),lastState=c.get('lastState',{})) for c in statuses],events=[dict(reason=e.get('reason',''),message=e.get('message',''),count=e.get('count',1),time=e.get('lastTimestamp',e.get('eventTime',''))) for e in events][-40:],logs=logs)
    def host(self,config):
        if not config['host']:return ''
        if '.' in config['host']:return config['host']
        nodes=self.get('nodes')['items']
        master=next((n for n in nodes if 'node-role.kubernetes.io/control-plane' in n['metadata'].get('labels',{})),nodes[0])
        ip=next(a['address'] for a in master['status']['addresses'] if a['type']=='InternalIP')
        return config['host']+'.'+ip+'.sslip.io'
    def plan(self,config):
        c=validate(config);ns=c['namespace'];name=c['name'];kind='StatefulSet' if c['type'] in STATEFUL else 'Deployment'
        labels={'app.kubernetes.io/managed-by':MANAGER,'app.kubernetes.io/name':name,'lab.k3s/type':c['type']}
        selector={'lab.k3s/app':name}
        def resource(api,kind,n=name):return dict(apiVersion=api,kind=kind,metadata=dict(name=n,namespace=ns,labels=labels.copy()))
        objects=[]
        workload=resource('apps/v1',kind)
        container=dict(name=c['type'] if c['type']!='custom' else 'app',image=c['image'],ports=[dict(name='app',containerPort=c['port'])],resources={'requests':{'cpu':str(c['cpu'])+'m','memory':str(c['memory'])+'Mi'},'limits':{'cpu':str(c['cpu']*2)+'m','memory':str(c['memory']*2)+'Mi'}},readinessProbe={'tcpSocket':{'port':'app'},'initialDelaySeconds':3,'periodSeconds':5})
        pod=dict(containers=[container]);workload['spec']=dict(replicas=c['replicas'],selector={'matchLabels':selector},template={'metadata':{'labels':dict(labels,**selector)},'spec':pod},revisionHistoryLimit=5)
        if kind=='StatefulSet':
            workload['spec']['serviceName']=name+'-headless'
            workload['spec']['volumeClaimTemplates']=[dict(metadata={'name':'data'},spec={'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':str(c['storage'])+'Gi'}}})]
            container['volumeMounts']=[dict(name='data',mountPath={'postgres':('/var/lib/postgresql' if ':18' in c['image'] else '/var/lib/postgresql/data'),'redis':'/data','kafka':'/var/lib/kafka/data','rabbitmq':'/var/lib/rabbitmq'}[c['type']])]
            headless=resource('v1','Service',name+'-headless');headless['spec']=dict(clusterIP='None',selector=selector,ports=[dict(port=c['port'],targetPort='app')]);objects.append(headless)
        if c['type']=='postgres':
            container['env']=[dict(name='POSTGRES_PASSWORD',valueFrom={'secretKeyRef':{'name':name+'-auth','key':'password'}}),dict(name='POSTGRES_USER',value='app'),dict(name='POSTGRES_DB',value='app'),dict(name='PGDATA',value='/var/lib/postgresql/18/docker' if ':18' in c['image'] else '/var/lib/postgresql/data/pgdata')]
        if c['type']=='redis':container['args']=['redis-server','--appendonly','yes']
        if c['type']=='kafka':
            pod['securityContext']={'fsGroup':1000}
            values={'KAFKA_NODE_ID':'1','KAFKA_PROCESS_ROLES':'broker,controller','KAFKA_LISTENERS':'PLAINTEXT://:9092,CONTROLLER://:9093','KAFKA_ADVERTISED_LISTENERS':'PLAINTEXT://'+name+'.'+ns+'.svc.cluster.local:9092','KAFKA_LISTENER_SECURITY_PROTOCOL_MAP':'CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT','KAFKA_CONTROLLER_LISTENER_NAMES':'CONTROLLER','KAFKA_CONTROLLER_QUORUM_VOTERS':'1@localhost:9093','KAFKA_INTER_BROKER_LISTENER_NAME':'PLAINTEXT','KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR':'1','KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR':'1','KAFKA_TRANSACTION_STATE_LOG_MIN_ISR':'1','KAFKA_LOG_DIRS':'/var/lib/kafka/data/logs','KAFKA_HEAP_OPTS':'-Xms256m -Xmx512m','CLUSTER_ID':'MkU3OEVBNTcwNTJENDM2Qk'}
            container['env']=[dict(name=k,value=v) for k,v in values.items()]
        if c['type']=='rabbitmq':
            container['env']=[dict(name='RABBITMQ_DEFAULT_USER',value='app'),dict(name='RABBITMQ_DEFAULT_PASS',valueFrom={'secretKeyRef':{'name':name+'-auth','key':'password'}})]
            container['ports'].append(dict(name='management',containerPort=15672))
        objects.append(workload)
        service=resource('v1','Service');service['spec']=dict(type='ClusterIP',selector=selector,ports=[dict(name='app',port=c['port'],targetPort='app')]);objects.append(service)
        if c['type']=='rabbitmq':service['spec']['ports'].append(dict(name='management',port=15672,targetPort='management'))
        host=self.host(c)
        if host:
            ingress=resource('networking.k8s.io/v1','Ingress');ingress['metadata']['annotations']={'traefik.ingress.kubernetes.io/router.entrypoints':'web'}
            ingress['spec']=dict(ingressClassName='traefik',rules=[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':name,'port':{'number':15672 if c['type']=='rabbitmq' else c['port']}}}}]}}]);objects.append(ingress)
        return c,kind,objects,host
    def preflight(self,config):
        c,kind,objects,host=self.plan(config)
        for obj in objects:
            existing=self.find(obj['kind'],c['namespace'],obj['metadata']['name'])
            if existing:raise ValueError(f"{obj['kind']} {c['namespace']}/{obj['metadata']['name']} уже существует. Используйте изменение версии/реплик.")
        for other in ('Deployment','StatefulSet'):
            if self.find(other,c['namespace'],c['name']):raise ValueError('Приложение с таким именем уже существует')
        if host and any(r.get('host')==host for i in self.get('ingress')['items'] for r in i.get('spec',{}).get('rules',[])):raise ValueError('Этот hostname уже используется Ingress')
        if c['type'] in ('postgres','rabbitmq') and self.find('secret',c['namespace'],c['name']+'-auth'):raise ValueError('Secret для базы уже существует; используйте другое имя')
        if kind=='StatefulSet' and self.find('pvc',c['namespace'],'data-'+c['name']+'-0'):raise ValueError('Сохранённый PVC уже существует. Используйте другое имя или восстановите приложение вручную.')
        return c,kind,objects,host
    def deploy(self,config,prepared=None):
        c,kind,objects,host=prepared or self.preflight(config);ns=c['namespace'];name=c['name']
        print('TASK [Создать '+ns+'/'+name+']',flush=True)
        if not self.find('namespace',None,ns):self.apply([{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns}}])
        if c['type'] in ('postgres','rabbitmq'):
            self.apply([dict(apiVersion='v1',kind='Secret',metadata=dict(name=name+'-auth',namespace=ns),type='Opaque',stringData={'password':secrets.token_urlsafe(32)})])
        self.apply(objects)
        print(self.kubectl(['rollout','status',kind.lower()+'/'+name,'-n',ns,'--timeout=240s'],timeout=250),flush=True)
        self.check(c,kind,host)
        print('Готово: '+(host and 'http://'+host+'/' or name+'.'+ns+'.svc.cluster.local:'+str(c['port'])),flush=True)
        if c['type']=='rabbitmq':print('RabbitMQ: пользователь app, пароль в Secret '+ns+'/'+name+'-auth (ключ password).',flush=True)
        if c['type']=='postgres':print('PostgreSQL: пользователь app, база app, пароль в Secret '+ns+'/'+name+'-auth (ключ password).',flush=True)
    def check(self,c,kind,host=''):
        ns=c['namespace'];name=c['name'];target=kind.lower()+'/'+name
        print('TASK [Проверки: готовность, DNS, сеть и приложение]',flush=True)
        print(self.kubectl(['rollout','status',target,'-n',ns,'--timeout=180s'],timeout=190),flush=True)
        probe='lab-check-'+secrets.token_hex(4)
        dnsname=name+'.'+ns+'.svc.cluster.local'
        script='import socket,sys; h,p=sys.argv[1],int(sys.argv[2]); socket.getaddrinfo(h,p); c=socket.create_connection((h,p),10); c.close(); print("DNS/TCP OK")'
        if c['type']=='nginx' or host:
            script+='; import urllib.request; r=urllib.request.urlopen("http://"+h+":"+str(p)+"/",timeout=10); print("HTTP",r.status); r.close()'
        command=['python','-c',script,dnsname,str(15672 if c['type']=='rabbitmq' and host else c['port'])]
        manifest={'apiVersion':'v1','kind':'Pod','metadata':{'name':probe,'namespace':ns},'spec':{'restartPolicy':'Never','activeDeadlineSeconds':90,'containers':[{'name':'check','image':'python:3.13-alpine','command':command,'resources':{'requests':{'cpu':'10m','memory':'16Mi'},'limits':{'cpu':'100m','memory':'64Mi'}}}]}}
        try:
            self.apply([manifest]);end=time.monotonic()+110
            while time.monotonic()<end:
                phase=self.get('pod',ns,probe).get('status',{}).get('phase')
                if phase in ('Succeeded','Failed'):break
                time.sleep(2)
            if phase!='Succeeded':
                try:print(self.kubectl(['logs',probe,'-n',ns]),flush=True)
                except ValueError:pass
                raise ValueError('Проверка DNS/сети не прошла; приложение сохранено для диагностики.')
        finally:self.kubectl(['delete','pod',probe,'-n',ns,'--ignore-not-found','--wait=false'])
        if c['type']=='postgres':
            self.kubectl(['exec','-n',ns,target,'--','sh','-ec','PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$1" -U app -d app -v ON_ERROR_STOP=1 -c "SELECT 1"','check',dnsname])
            print('PostgreSQL SELECT 1 через Service: OK',flush=True)
        elif c['type']=='redis':
            result=self.kubectl(['exec','-n',ns,target,'--','redis-cli','-h',dnsname,'PING'])
            if 'PONG' not in result:raise ValueError('Redis PING не прошёл')
            print('Redis PING через Service: OK',flush=True)
        if c['type']=='kafka':
            self.kubectl(['exec','-n',ns,target,'--','/opt/kafka/bin/kafka-topics.sh','--bootstrap-server',dnsname+':9092','--list'],timeout=60)
            print('Kafka broker metadata: OK',flush=True)
        elif c['type']=='rabbitmq':
            self.kubectl(['exec','-n',ns,target,'--','rabbitmq-diagnostics','-q','check_running'],timeout=60)
            print('RabbitMQ check_running: OK',flush=True)
        if host:
            subprocess.run(['curl','--noproxy','*','--fail','--silent','--show-error','--max-time','10','--retry','5','--retry-delay','2','--retry-all-errors','--output',os.devnull,'http://'+host+'/'],check=True,timeout=90)
            print('URL http://'+host+'/: OK',flush=True)
        print('DNS и соединение с Service: OK',flush=True)
    def change(self,data,action):
        ns=namespace(data.get('namespace'),True);name=dns(data.get('name'));kind=data.get('kind')
        if kind not in ('Deployment','StatefulSet'):raise ValueError('Поддерживаются Deployment и StatefulSet')
        obj=self.get(kind,ns,name);target=kind.lower()+'/'+name
        containers=obj['spec']['template']['spec']['containers'];ctype=obj['metadata'].get('labels',{}).get('lab.k3s/type','custom')
        if action=='app_update':
            image=data.get('image','');container=data.get('container')
            if container not in [c['name'] for c in containers]:raise ValueError('Выберите контейнер')
            validate(dict(type=ctype,image=image,name=name,namespace=ns))
            if ctype in ('postgres','redis'):
                old=next(c['image'] for c in containers if c['name']==container)
                if old.rsplit(':',1)[-1].split('.')[0].split('-')[0]!=image.rsplit(':',1)[-1].split('.')[0].split('-')[0]:raise ValueError('Смена major базы требует миграции данных. Создайте новую базу и перенесите данные.')
            replicas=number(data.get('replicas',1),0,1 if ctype in STATEFUL else 10,'реплики')
            patch={'spec':{'replicas':replicas,'template':{'spec':{'containers':[{'name':container,'image':image}]}}}}
            self.kubectl(['patch',target,'-n',ns,'--type=strategic','-p',json.dumps(patch)])
        elif action=='app_rollback':
            if ctype in STATEFUL:raise ValueError('Откат образа базы может быть несовместим с данными. Восстановление базы выполняйте отдельно.')
            self.kubectl(['rollout','undo',target,'-n',ns])
            if kind=='StatefulSet':
                restored=self.get(kind,ns,name)
                images={c['name']:c['image'] for c in restored['spec']['template']['spec']['containers']}
                for pod in self.get('pods',ns)['items']:
                    owned=any(o.get('uid')==restored['metadata']['uid'] and o.get('controller') for o in pod['metadata'].get('ownerReferences',[]))
                    ready=any(c.get('type')=='Ready' and c.get('status')=='True' for c in pod.get('status',{}).get('conditions',[]))
                    differs=any(images.get(c['name'])!=c['image'] for c in pod['spec']['containers'])
                    if owned and not ready and differs:
                        self.kubectl(['delete','pod',pod['metadata']['name'],'-n',ns,'--wait=true','--timeout=60s'],timeout=70)

        print(self.kubectl(['rollout','status',target,'-n',ns,'--timeout=180s'],timeout=190),flush=True)
        if action=='app_check':
            service=self.get('service',ns,name)
            host=next((r.get('host','') for i in self.get('ingress',ns)['items'] for r in i.get('spec',{}).get('rules',[]) if any(p.get('backend',{}).get('service',{}).get('name')==name for p in r.get('http',{}).get('paths',[]))),'')
            self.check(dict(name=name,namespace=ns,type=ctype,port=service['spec']['ports'][0]['port']),kind,host)
