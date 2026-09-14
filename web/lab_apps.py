"""Application catalogue, repeatable templates and scoped Kubernetes diagnostics."""
import json, os, re, secrets, subprocess, tempfile, time, base64
import app_panels
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
    mode=config.get('storage_mode','new' if kind in STATEFUL else 'none')
    if mode not in ('none','new','existing') or (kind in STATEFUL and mode=='none'):raise ValueError('Выберите новый или существующий PVC')
    claim=dns(config.get('pvc',''),'PVC') if mode=='existing' else ''
    mount=config.get('mount_path','/data')
    if not isinstance(mount,str) or not mount.startswith('/') or mount=='/' or '..' in mount.split('/'):raise ValueError('Укажите абсолютный путь монтирования')
    credential=dns(config.get('storage_secret',''),'Secret с паролем') if mode=='existing' and kind in ('postgres','rabbitmq') else ''
    shovel=config.get('shovel',False)
    if shovel not in (True,False,'true','false'):raise ValueError('Некорректная настройка Shovel')
    return dict(shovel=shovel in (True,'true'),storage_mode=mode,pvc=claim,mount_path=mount,storage_secret=credential,type=kind,name=dns(config.get('name',''),'имя приложения'),namespace=namespace(config.get('namespace','dev'),True),image=image,
                replicas=number(config.get('replicas',1),1,1 if kind in STATEFUL else 10,'реплики'),
                cpu=number(config.get('cpu',100),25,8000,'CPU, millicores'),memory=number(config.get('memory',1024 if kind=='kafka' else 512 if kind=='rabbitmq' else 256),768 if kind=='kafka' else 256 if kind=='rabbitmq' else 32,16384,'RAM, MiB'),
                storage=number(config.get('storage',2),1,100,'диск, GiB'),port=number(config.get('port',CATALOG[kind]['port']),1,65535,'порт'),host=host)

def claim_referenced(name,objects):
    for obj in objects:
        spec=obj.get('spec',{})
        if obj.get('kind')=='CronJob':spec=spec.get('jobTemplate',{}).get('spec',{})
        pod=spec.get('template',{}).get('spec',spec)
        if any(v.get('persistentVolumeClaim',{}).get('claimName')==name for v in pod.get('volumes',[])):return True
        if obj.get('kind')=='StatefulSet':
            for claim in spec.get('volumeClaimTemplates',[]):
                prefix=claim['metadata']['name']+'-'+obj['metadata']['name']+'-'
                if name.startswith(prefix) and name[len(prefix):].isdigit():return True
    return False

def templates():
    path=ROOT/'.cache/app-templates.json'
    if not path.exists():return []
    data=json.loads(path.read_text())
    return data if isinstance(data,list) else []

def template_value(data):
    name=dns(data.get('name',''),'имя шаблона');items=data.get('apps')
    if not isinstance(items,list) or not 1<=len(items)<=10:raise ValueError('В шаблоне должно быть от 1 до 10 приложений')
    apps=[validate(c) for c in items]
    if len({(a['namespace'],a['name']) for a in apps})!=len(apps):raise ValueError('Имена приложений в namespace должны отличаться')
    return dict(name=name,apps=apps)

def save_template(data):
    value=template_value(data)
    return write_templates([v for v in templates() if v['name']!=value['name']]+[value])

def update_template(data):
    original=dns(data.get('original_name',''),'исходное имя шаблона')
    values=templates()
    current=next((v for v in values if v['name']==original),None)
    if current is None:raise ValueError('Шаблон удалён. Обновите список шаблонов.')
    if data.get('expected')!=current:raise ValueError('Шаблон уже изменён. Закройте редактор и откройте его заново.')
    value=template_value(data)
    if value['name']!=original and any(v['name']==value['name'] for v in values):raise ValueError('Шаблон с таким именем уже существует')
    return write_templates([value if v['name']==original else v for v in values])

def delete_template(data):
    name=dns(data.get('name',''),'имя шаблона')
    return write_templates([v for v in templates() if v['name']!=name])

def write_templates(values):
    folder=ROOT/'.cache';folder.mkdir(exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=folder,prefix='templates-')
    try:
        with os.fdopen(fd,'w') as out:json.dump(values,out,ensure_ascii=False,indent=2)
        os.replace(temp,folder/'app-templates.json')
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return {'ok':True}

def storage_location(pv,nodes):
    spec=pv.get('spec',{});local=spec.get('local') or spec.get('hostPath')
    if spec.get('nfs'):return dict(kind='NFS',server=spec['nfs'].get('server',''),path=spec['nfs'].get('path',''),nodes=[],note='Путь на NFS-сервере, не на VM Kubernetes.')
    if not local:return dict(kind=spec.get('csi',{}).get('driver','Не определено'),nodes=[],path='',note='Физический сервер и путь не раскрыты в PV.' if pv else 'PV ещё не назначен.')
    terms=spec.get('nodeAffinity',{}).get('required',{}).get('nodeSelectorTerms',[])
    def matches(node,term):
        expressions=term.get('matchExpressions',[]);fields=term.get('matchFields',[])
        if not expressions and not fields:return False
        for e,is_field in [(e,False) for e in expressions]+[(e,True) for e in fields]:
            labels={'metadata.name':node['metadata']['name']} if is_field else node['metadata'].get('labels',{})
            value=labels.get(e['key']);op=e['operator'];values=e.get('values',[])
            if op=='In' and value not in values:return False
            if op=='NotIn' and value in values:return False
            if op=='Exists' and value is None:return False
            if op=='DoesNotExist' and value is not None:return False
            if op not in ('In','NotIn','Exists','DoesNotExist'):return False
        return True
    candidates=[dict(name=n['metadata']['name'],ip=next((a['address'] for a in n.get('status',{}).get('addresses',[]) if a['type']=='InternalIP'),'')) for n in nodes if any(matches(n,t) for t in terms)]
    return dict(kind='Локальный диск VM',nodes=candidates,path=local.get('path',''),note='Путь внутри VM, а не на Mac.' if len(candidates)==1 else 'PV не определяет единственный узел хранения; показаны ограничения размещения.')

def resource_name(value):
    if not isinstance(value,str) or len(value)>253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',value) or '..' in value:raise ValueError('Некорректное имя ресурса')
    return value

def rabbit_startup(enabled):
    operation='enable' if enabled else 'disable'
    return ['sh','-ec','rabbitmq-plugins --offline '+operation+' rabbitmq_shovel_management rabbitmq_shovel; exec docker-entrypoint.sh rabbitmq-server']

def resource_quantity(value):
    from decimal import Decimal
    match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)([a-zA-Z]*)',str(value))
    if not match:raise ValueError('Неизвестная величина ресурсов: '+str(value))
    factors={'':1,'n':1e-9,'u':1e-6,'m':.001,'k':1000,'K':1000,'M':1e6,'G':1e9,'T':1e12,'Ki':1024,'Mi':1024**2,'Gi':1024**3,'Ti':1024**4,'Pi':1024**5,'Ei':1024**6}
    if match[2] not in factors:raise ValueError('Неизвестная единица ресурсов')
    return float(Decimal(match[1])*Decimal(str(factors[match[2]])))

def pod_budget(spec,field='requests'):
    def values(c):return {k:resource_quantity(c.get('resources',{}).get(field,{}).get(k,0)) for k in ('cpu','memory')}
    total={k:sum(values(c)[k] for c in spec.get('containers',[])) for k in ('cpu','memory')}
    sidecars=dict(cpu=0,memory=0);peak=dict(cpu=0,memory=0)
    for c in spec.get('initContainers',[]):
        v=values(c)
        if c.get('restartPolicy')=='Always':
            for k in total:sidecars[k]+=v[k]
            v=dict(cpu=0,memory=0)
        for k in total:peak[k]=max(peak[k],sidecars[k]+v[k])
    for k in total:total[k]=max(total[k]+sidecars[k],peak[k])+resource_quantity(spec.get('overhead',{}).get(k,0))
    return total

def allocation(nodes,pods):
    result={n['metadata']['name']:dict(allocatable={k:resource_quantity(n['status']['allocatable'].get(k,0)) for k in ('cpu','memory')},requests=dict(cpu=0,memory=0),limits=dict(cpu=0,memory=0),unlimited=dict(cpu=0,memory=0)) for n in nodes}
    for p in pods:
        if p.get('status',{}).get('phase') in ('Succeeded','Failed'):continue
        node=result.get(p.get('spec',{}).get('nodeName'))
        if not node:continue
        for field in ('requests','limits'):
            v=pod_budget(p['spec'],field)
            for k in v:node[field][k]+=v[k]
        for c in p['spec'].get('containers',[]):
            for k in ('cpu','memory'):
                if not c.get('resources',{}).get('limits',{}).get(k):node['unlimited'][k]+=1
    return result

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
    def template_from_apps(self,data):
        import math
        selected=data.get('selected',[])
        if not isinstance(selected,list) or not 1<=len(selected)<=10:raise ValueError('Выберите от 1 до 10 приложений')
        configs=[]
        def amount(value,unit):
            match=re.fullmatch(r'([0-9.]+)([a-zA-Z]*)',str(value))
            if not match:raise ValueError('Неподдерживаемый формат ресурсов: '+str(value))
            number,suffix=match.groups()
            factors={'':1,'m':.001,'Ki':1024,'Mi':1024**2,'Gi':1024**3,'Ti':1024**4,'K':1000,'M':1000**2,'G':1000**3}
            if suffix not in factors:raise ValueError('Неподдерживаемая единица ресурсов')
            return math.ceil(float(number)*factors[suffix]/unit)
        for item in selected:
            kind=item.get('kind');ns=namespace(item.get('namespace'),True);name=dns(item.get('name'))
            if kind not in ('Deployment','StatefulSet'):raise ValueError('Неподдерживаемая рабочая нагрузка')
            obj=self.get(kind,ns,name);labels=obj['metadata'].get('labels',{})
            if labels.get('app.kubernetes.io/managed-by')!=MANAGER or labels.get('lab.k3s/panel-for'):raise ValueError('В шаблон можно включить приложения, установленные через каталог')
            containers=obj['spec']['template']['spec']['containers']
            if len(containers)!=1:raise ValueError('Наборы с несколькими контейнерами пока не поддерживаются')
            c=containers[0];ctype=labels.get('lab.k3s/type','custom');requests=c.get('resources',{}).get('requests',{})
            config=dict(shovel=obj['metadata'].get('annotations',{}).get('lab.k3s/shovel')=='true',type=ctype,name=name,namespace=ns,image=c['image'],replicas=obj['spec'].get('replicas',1),cpu=amount(requests.get('cpu','100m'),.001),memory=amount(requests.get('memory','256Mi'),1024**2),port=c.get('ports',[{'containerPort':8080}])[0]['containerPort'],host='',storage_mode='none')
            claims=obj['spec'].get('volumeClaimTemplates',[])
            if claims:
                size=claims[0]['spec']['resources']['requests']['storage']
                config.update(storage_mode='new',storage=amount(size,1024**3))
            else:
                volumes=obj['spec']['template']['spec'].get('volumes',[])
                claims=[v for v in volumes if 'persistentVolumeClaim' in v]
                if len(claims)>1:raise ValueError('Шаблоны с несколькими PVC пока не поддерживаются')
                if claims:
                    claim=claims[0];pvc=self.get('pvc',ns,claim['persistentVolumeClaim']['claimName'])
                    config.update(storage_mode='new',storage=amount(pvc['spec']['resources']['requests']['storage'],1024**3))
                    mount=next((v['mountPath'] for v in c.get('volumeMounts',[]) if v['name']==claim['name']),'/data')
                    config['mount_path']=mount
            routes=self.get('ingress',ns)['items']
            if any(p.get('backend',{}).get('service',{}).get('name')==name for i in routes for rule in i.get('spec',{}).get('rules',[]) for p in rule.get('http',{}).get('paths',[])):config['host']=name
            configs.append(validate(config))
        return save_template(dict(name=data.get('name'),apps=configs))

    def rabbit_plugins(self,data):
        ns=namespace(data.get('namespace'),True);name=dns(data.get('name'));enabled=data.get('enabled')
        if not isinstance(enabled,bool):raise ValueError('Укажите состояние Shovel')
        obj=self.get('StatefulSet',ns,name)
        labels=obj['metadata'].get('labels',{})
        if labels.get('app.kubernetes.io/managed-by')!=MANAGER or labels.get('lab.k3s/type')!='rabbitmq':raise ValueError('Выберите RabbitMQ из каталога')
        containers=obj['spec']['template']['spec']['containers']
        if len(containers)!=1:raise ValueError('Поддерживается RabbitMQ с одним контейнером')
        patch={'metadata':{'annotations':{'lab.k3s/shovel':str(enabled).lower()}},'spec':{'template':{'spec':{'containers':[{'name':containers[0]['name'],'command':rabbit_startup(enabled),'args':None}]}}}}
        self.kubectl(['patch','statefulset/'+name,'-n',ns,'--type=strategic','-p',json.dumps(patch)])
        if obj['spec'].get('replicas',1)==0:
            print('Настройка сохранена. Shovel будет '+('включён' if enabled else 'выключен')+' при запуске RabbitMQ.',flush=True);return
        print(self.wait_rollout('StatefulSet',name,ns,300),flush=True)
        plugins=self.kubectl(['exec','-n',ns,'statefulset/'+name,'--','rabbitmq-plugins','list','-e','-m'])
        active=set(plugins.split())
        if enabled and not {'rabbitmq_shovel','rabbitmq_shovel_management'}<=active:raise ValueError('Shovel не подтвердил включение')
        if not enabled and {'rabbitmq_shovel','rabbitmq_shovel_management'}&active:raise ValueError('Shovel не подтвердил отключение')
        print('Shovel '+('включён. В RabbitMQ: Admin → Shovel Management.' if enabled else 'выключен.')+' Настройка сохранена в StatefulSet.',flush=True)

    def yaml_edit_object(self,data):
        resources={'pods':'pods','pvcs':'persistentvolumeclaims','secrets':'secrets','deployments':'deployments.apps','statefulsets':'statefulsets.apps','daemonsets':'daemonsets.apps','jobs':'jobs.batch','cronjobs':'cronjobs.batch','services':'services','ingresses':'ingresses.networking.k8s.io','configmaps':'configmaps'}
        resource=resources.get(data.get('type'))
        if not resource:raise ValueError('Неизвестный тип ресурса')
        ns=namespace(data.get('namespace'));name=resource_name(data.get('name'))
        return self.get(resource,ns,name)

    def yaml_preview(self,data):
        import difflib
        source=data.get('yaml')
        if not isinstance(source,str) or not 0<len(source.encode())<=1048576:raise ValueError('YAML должен быть не больше 1 MiB')
        # Safe YAML parser already available with the project's Ruby runtime.
        code="require 'yaml';require 'json';require 'date';source=STDIN.read;raise 'one object required' unless Psych.parse_stream(source).children.length==1;puts JSON.generate(YAML.safe_load(source, permitted_classes: [Date, Time], aliases: false))"
        parsed=subprocess.run(['ruby','-e',code],input=source,text=True,capture_output=True,timeout=10)
        if parsed.returncode:raise ValueError('Некорректный YAML: проверьте отступы и синтаксис. Разрешён один объект без YAML aliases.')
        candidate=json.loads(parsed.stdout);live=self.yaml_edit_object(data)
        if not isinstance(candidate,dict):raise ValueError('Ожидается один объект Kubernetes')
        meta=candidate.get('metadata',{});original=live['metadata']
        if not isinstance(meta,dict):raise ValueError('Некорректная metadata')
        if (candidate.get('apiVersion'),candidate.get('kind'),meta.get('name'),meta.get('namespace'))!=(live['apiVersion'],live['kind'],original['name'],original.get('namespace')):raise ValueError('Нельзя менять apiVersion, kind, имя или namespace в редакторе ресурса')
        if meta.get('resourceVersion')!=original.get('resourceVersion') or meta.get('uid')!=original.get('uid'):raise ValueError('Ресурс изменился или изменены uid/resourceVersion. Загрузите свежий YAML.')
        def clean(obj):
            obj=json.loads(json.dumps(obj));obj.pop('status',None);obj['metadata'].pop('managedFields',None);return obj
        before=clean(live);candidate=clean(candidate)
        # Server admission/defaulting and immutable field checks, without persistence.
        validated=json.loads(self.kubectl(['replace','--dry-run=server','-f','-','-o','json'],candidate))
        after=clean(validated)
        def yaml_dump(obj):
            return subprocess.run(['ruby','-rjson','-ryaml','-e','puts YAML.dump(JSON.parse(STDIN.read))'],input=json.dumps(obj),text=True,capture_output=True,check=True,timeout=10).stdout
        diff=''.join(difflib.unified_diff(yaml_dump(before).splitlines(True),yaml_dump(after).splitlines(True),fromfile='Текущая версия',tofile='После применения'))
        return candidate,diff

    def yaml_apply(self,candidate):
        # resourceVersion makes replacement atomic and rejects concurrent changes.
        result=json.loads(self.kubectl(['replace','-f','-','-o','json'],candidate))
        return dict(ok=True,name=result['metadata']['name'],resourceVersion=result['metadata']['resourceVersion'])

    def resource_yaml(self,data):
        resources={'pods':'pods','pvcs':'persistentvolumeclaims','secrets':'secrets','deployments':'deployments.apps','statefulsets':'statefulsets.apps','daemonsets':'daemonsets.apps','jobs':'jobs.batch','cronjobs':'cronjobs.batch','services':'services','ingresses':'ingresses.networking.k8s.io','configmaps':'configmaps'}
        resource=resources.get(data.get('type'))
        if not resource:raise ValueError('Неизвестный тип ресурса')
        ns=namespace(data.get('namespace'));name=resource_name(data.get('name'))
        output=self.kubectl(['get',resource,name,'-n',ns,'-o','yaml','--show-managed-fields=false','--request-timeout=10s'])
        return dict(yaml=output,filename=ns+'_'+data['type']+'_'+name+'.yaml')

    def resources(self):
        items=self.get('deployments.apps,statefulsets.apps,daemonsets.apps,jobs.batch,cronjobs.batch,services,ingresses.networking.k8s.io,configmaps')['items']
        result=[]
        for obj in items:
            m=obj['metadata'];spec=obj.get('spec',{});status=obj.get('status',{});kind=obj['kind']
            details={'Создан':m.get('creationTimestamp',''),'Метки':m.get('labels',{})}
            summary='';state='—'
            if kind in ('Deployment','StatefulSet','DaemonSet'):
                desired=spec.get('replicas',1) if kind!='DaemonSet' else status.get('desiredNumberScheduled',0)
                ready=status.get('readyReplicas',0) if kind!='DaemonSet' else status.get('numberReady',0)
                state=f'{ready}/{desired} Ready';summary=', '.join(c['image'] for c in spec.get('template',{}).get('spec',{}).get('containers',[]))
                details.update(Selector=spec.get('selector',{}),Образы=summary)
            elif kind=='Service':
                state=spec.get('type','ClusterIP');summary=spec.get('clusterIP','—');details.update(Порты=spec.get('ports',[]),Selector=spec.get('selector',{}),ExternalIP=status.get('loadBalancer',{}))
            elif kind=='Ingress':
                state=spec.get('ingressClassName','—');summary=', '.join(rule.get('host','*') for rule in spec.get('rules',[]));details.update(Маршруты=spec.get('rules',[]),TLS=spec.get('tls',[]))
            elif kind=='Job':
                state='Failed' if status.get('failed') else 'Complete' if any(c.get('type')=='Complete' and c.get('status')=='True' for c in status.get('conditions',[])) else 'Active' if status.get('active') else 'Pending';summary=str(status.get('succeeded',0))+'/'+str(spec.get('completions',1));details.update(Состояние=status)
            elif kind=='CronJob':
                state='Suspended' if spec.get('suspend') else 'Enabled';summary=spec.get('schedule','');details.update(Расписание=summary,Последний_запуск=status.get('lastScheduleTime','—'),Часовой_пояс=spec.get('timeZone','По умолчанию'))
            else:
                state='ConfigMap';summary=', '.join(sorted(set(obj.get('data',{}))|set(obj.get('binaryData',{}))));details['Ключи']=summary
            result.append(dict(name=m['name'],namespace=m.get('namespace',''),kind=kind,state=state,summary=summary,details=details))
        return result

    def listing(self):
        items=self.get('deployments.apps,statefulsets.apps')['items'];out=[]
        routes=self.get('ingress')['items']
        for obj in items:
            m=obj['metadata'];ns=m.get('namespace','default')
            if ns in PROTECTED or ns.startswith(('kube-','cattle-')):continue
            if m.get('labels',{}).get('lab.k3s/panel-for'):continue
            containers=obj['spec']['template']['spec']['containers']
            out.append(dict(name=m['name'],namespace=ns,kind=obj['kind'],replicas=obj['spec'].get('replicas',1),ready=obj.get('status',{}).get('readyReplicas',0),containers=[dict(name=c['name'],image=c['image']) for c in containers],managed=m.get('labels',{}).get('app.kubernetes.io/managed-by')==MANAGER,type=m.get('labels',{}).get('lab.k3s/type','custom'),shovel=m.get('annotations',{}).get('lab.k3s/shovel')=='true',check=self.check_result(obj)))
        for app in out:
            app['urls']=[{'title':i['metadata']['name'],'url':'http://'+r['host']+'/'} for i in routes if i['metadata'].get('namespace')==app['namespace'] for r in i.get('spec',{}).get('rules',[]) if r.get('host') and any(p.get('backend',{}).get('service',{}).get('name') in (app['name'],app['name']+'-ui') for p in r.get('http',{}).get('paths',[]))]
        return out
    def secret_info(self):
        result=[]
        for obj in self.get('secrets')['items']:
            m=obj['metadata'];ns=m.get('namespace','default')
            if ns in PROTECTED or ns.startswith(('kube-','cattle-')):continue
            keys=sorted(obj.get('data',{}))
            result.append(dict(name=m['name'],namespace=ns,type=obj.get('type','Opaque'),keys=keys,hasPassword=bool(obj.get('data',{}).get('password'))))
        return result
    def pvcs(self):
        pods=self.get('pods')['items'];result=[]
        volumes={v['metadata']['name']:v for v in self.get('pv')['items']}
        nodes=self.get('nodes')['items']
        for pvc in self.get('pvc')['items']:
            m=pvc['metadata'];spec=pvc['spec'];status=pvc.get('status',{})
            users=[p['metadata']['name'] for p in pods if p['metadata'].get('namespace')==m['namespace'] and any(v.get('persistentVolumeClaim',{}).get('claimName')==m['name'] for v in p.get('spec',{}).get('volumes',[]))]
            result.append(dict(name=m['name'],namespace=m['namespace'],phase=status.get('phase','Pending'),capacity=status.get('capacity',{}).get('storage',spec.get('resources',{}).get('requests',{}).get('storage','')),storageClass=spec.get('storageClassName',''),accessModes=spec.get('accessModes',[]),volume=spec.get('volumeName',''),pods=users,location=storage_location(volumes.get(spec.get('volumeName'),{}),nodes)))
        return result
    def check_result(self,obj):
        try:data=json.loads((self.root/'.cache/app-checks.json').read_text()).get(obj['metadata']['uid'])
        except (OSError,ValueError,KeyError):return None
        if not data or data.get('generation')!=obj['metadata'].get('generation'):return None
        if data['state']=='running' and time.time()-data['time']>900:return None
        return data
    def record_check(self,obj,state):
        folder=self.root/'.cache';folder.mkdir(exist_ok=True);path=folder/'app-checks.json'
        try:values=json.loads(path.read_text())
        except (OSError,ValueError):values={}
        values[obj['metadata']['uid']]={'state':state,'time':time.time(),'generation':obj['metadata'].get('generation')}
        fd,temp=tempfile.mkstemp(dir=folder,prefix='app-check-')
        try:
            with os.fdopen(fd,'w') as out:json.dump(values,out)
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def delete(self,data):
        ns=namespace(data.get('namespace'),True);name=dns(data.get('name'));kind=data.get('kind')
        if kind not in ('Deployment','StatefulSet'):raise ValueError('Неизвестный workload')
        workload=self.get(kind,ns,name)
        managed=workload['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')==MANAGER
        delete_data=data.get('delete_data',False)
        if not isinstance(delete_data,bool):raise ValueError('Некорректный выбор удаления данных')
        objects=self.get('deployments,statefulsets,services,ingresses,configmaps,secrets',ns)['items']
        try:objects+=self.get('middlewares.traefik.io',ns)['items']
        except ValueError as e:
            if "the server doesn't have a resource type" not in str(e):raise
        selected=[]
        for obj in objects:
            m=obj['metadata'];labels=m.get('labels',{})
            owned=managed and labels.get('app.kubernetes.io/managed-by')==MANAGER and (labels.get('app.kubernetes.io/name')==name or labels.get('lab.k3s/panel-for')==name)
            if owned:selected.append((obj['kind'],m['name']))
        # Older generated database Secrets have no ownership labels. Keep them with data.
        if delete_data:
            refs={e.get('valueFrom',{}).get('secretKeyRef',{}).get('name') for c in workload['spec']['template']['spec']['containers'] for e in c.get('env',[])}
            if managed and not workload['metadata'].get('annotations',{}).get('lab.k3s/external-pvc') and name+'-auth' in refs:selected.append(('Secret',name+'-auth'))
        else:selected=[o for o in selected if o!=('Secret',name+'-auth')]
        self.kubectl(['delete',kind,name,'-n',ns,'--wait=true','--timeout=90s'],timeout=100)
        for resource,n in selected:
            if (resource,n)==(kind,name):continue
            self.kubectl(['delete',resource,n,'-n',ns,'--ignore-not-found','--wait=false'])
        owned_pvc=workload['metadata'].get('annotations',{}).get('lab.k3s/owned-pvc')
        if delete_data and owned_pvc and managed:self.kubectl(['delete','pvc',owned_pvc,'-n',ns,'--ignore-not-found','--wait=false'])
        if delete_data and kind=='StatefulSet':
            claims=[v['metadata']['name'] for v in workload['spec'].get('volumeClaimTemplates',[])]
            for pvc in self.get('pvc',ns)['items']:
                n=pvc['metadata']['name']
                if any(re.fullmatch(re.escape(claim+'-'+name+'-')+r'\d+',n) for claim in claims):self.kubectl(['delete','pvc',n,'-n',ns,'--wait=false'])
        if workload['metadata'].get('annotations',{}).get('lab.k3s/external-pvc'):delete_data=False
        print(('Приложение и веб-панель удалены. ' if managed else 'Workload удалён; внешние Service/Ingress сохранены. ')+('PVC и пароль базы удалены.' if delete_data else 'PVC и пароль базы сохранены.'),flush=True)
    def access(self,data):
        ns=namespace(data.get('namespace'));name=resource_name(data.get('name'));kind=data.get('kind')
        if kind not in ('Deployment','StatefulSet'):raise ValueError('Неизвестный workload')
        workload=self.get(kind,ns,name)
        if workload['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')!=MANAGER:raise ValueError('Учётные данные доступны для приложений каталога')
        def secret(n):
            obj=self.find('secret',ns,n)
            return {k:base64.b64decode(v).decode() for k,v in (obj or {}).get('data',{}).items()}
        result={'connection':name+'.'+ns+'.svc.cluster.local','panels':[]}
        panel=secret(name+'-ui-auth')
        if panel:result['panels'].append({k:panel.get(k,'') for k in ('title','url','username','password')})
        ctype=workload['metadata']['labels'].get('lab.k3s/type')
        if ctype in ('postgres','rabbitmq'):
            env=workload['spec']['template']['spec']['containers'][0].get('env',[])
            secret_name=next((e.get('valueFrom',{}).get('secretKeyRef',{}).get('name') for e in env if e['name'] in ('POSTGRES_PASSWORD','RABBITMQ_DEFAULT_PASS')),name+'-auth')
            credentials=secret(secret_name);result['username']='app';result['password']=credentials.get('password','')
        else:result['note']='У приложения нет отдельного пароля подключения.'
        for ingress in self.get('ingress',ns)['items']:
            for rule in ingress.get('spec',{}).get('rules',[]):
                if any(p.get('backend',{}).get('service',{}).get('name')==name for p in rule.get('http',{}).get('paths',[])):
                    result['panels'].append(dict(title='RabbitMQ Management' if ctype=='rabbitmq' else 'Сайт приложения',url='http://'+rule['host']+'/',username=result.get('username',''),password=result.get('password','')))
        return result
    def workload_pods(self,data):
        ns=namespace(data.get('namespace'));name=resource_name(data.get('name'));kind=data.get('kind')
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
        if c['storage_mode']=='existing':
            workload['spec'].pop('volumeClaimTemplates',None)
            pod.setdefault('volumes',[]).append({'name':'data','persistentVolumeClaim':{'claimName':c['pvc']}})
            workload['metadata']['annotations']={'lab.k3s/external-pvc':c['pvc']}
        elif c['storage_mode']=='new' and kind=='Deployment':
            pvc=resource('v1','PersistentVolumeClaim',name+'-data');pvc['spec']={'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':str(c['storage'])+'Gi'}}};objects.append(pvc)
            pod.setdefault('volumes',[]).append({'name':'data','persistentVolumeClaim':{'claimName':name+'-data'}})
            workload['metadata']['annotations']={'lab.k3s/owned-pvc':name+'-data'}
        if kind=='Deployment' and c['storage_mode']!='none':
            if c['replicas']!=1:raise ValueError('Приложение с одним PVC поддерживает одну реплику')
            workload['spec']['strategy']={'type':'Recreate'}
            container['volumeMounts']=[{'name':'data','mountPath':c['mount_path']}]
        if c['type']=='postgres':
            container['env']=[dict(name='POSTGRES_PASSWORD',valueFrom={'secretKeyRef':{'name':c['storage_secret'] or name+'-auth','key':'password'}}),dict(name='POSTGRES_USER',value='app'),dict(name='POSTGRES_DB',value='app'),dict(name='PGDATA',value='/var/lib/postgresql/18/docker' if ':18' in c['image'] else '/var/lib/postgresql/data/pgdata')]
        if c['type']=='redis':container['args']=['redis-server','--appendonly','yes']
        if c['type']=='kafka':
            pod['securityContext']={'fsGroup':1000}
            values={'KAFKA_NODE_ID':'1','KAFKA_PROCESS_ROLES':'broker,controller','KAFKA_LISTENERS':'PLAINTEXT://:9092,CONTROLLER://:9093','KAFKA_ADVERTISED_LISTENERS':'PLAINTEXT://'+name+'.'+ns+'.svc.cluster.local:9092','KAFKA_LISTENER_SECURITY_PROTOCOL_MAP':'CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT','KAFKA_CONTROLLER_LISTENER_NAMES':'CONTROLLER','KAFKA_CONTROLLER_QUORUM_VOTERS':'1@localhost:9093','KAFKA_INTER_BROKER_LISTENER_NAME':'PLAINTEXT','KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR':'1','KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR':'1','KAFKA_TRANSACTION_STATE_LOG_MIN_ISR':'1','KAFKA_LOG_DIRS':'/var/lib/kafka/data/logs','KAFKA_HEAP_OPTS':'-Xms256m -Xmx512m','CLUSTER_ID':'MkU3OEVBNTcwNTJENDM2Qk'}
            container['env']=[dict(name=k,value=v) for k,v in values.items()]
        if c['type']=='rabbitmq':
            container['command']=rabbit_startup(c['shovel'])
            workload['metadata'].setdefault('annotations',{})['lab.k3s/shovel']=str(c['shovel']).lower()
            container['env']=[dict(name='RABBITMQ_DEFAULT_USER',value='app'),dict(name='RABBITMQ_DEFAULT_PASS',valueFrom={'secretKeyRef':{'name':c['storage_secret'] or name+'-auth','key':'password'}})]
            container['ports'].append(dict(name='management',containerPort=15672))
        objects.append(workload)
        service=resource('v1','Service');service['spec']=dict(type='ClusterIP',selector=selector,ports=[dict(name='app',port=c['port'],targetPort='app')]);objects.append(service)
        if c['type']=='rabbitmq':service['spec']['ports'].append(dict(name='management',port=15672,targetPort='management'))
        host=self.host(dict(c,host=c['host'] or (name+'-'+ns if c['type']=='rabbitmq' else '')))
        if host:
            ingress=resource('networking.k8s.io/v1','Ingress');ingress['metadata']['annotations']={'traefik.ingress.kubernetes.io/router.entrypoints':'web'}
            ingress['spec']=dict(ingressClassName='traefik',rules=[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':name,'port':{'number':15672 if c['type']=='rabbitmq' else c['port']}}}}]}}]);objects.append(ingress)
        if c['type'] in app_panels.IMAGES:
            panelhost=self.host(dict(c,host=c['name']+'-'+ns+'-ui'))
            objects.extend(app_panels.build(c,panelhost,MANAGER))
        return c,kind,objects,host
    def preflight(self,config):
        c,kind,objects,host=self.plan(config)
        if c['storage_mode']=='existing':
            pvc=self.find('pvc',c['namespace'],c['pvc'])
            if not pvc or pvc.get('metadata',{}).get('deletionTimestamp') or pvc.get('status',{}).get('phase')!='Bound' or pvc.get('spec',{}).get('volumeMode','Filesystem')!='Filesystem':raise ValueError('Нужен готовый Filesystem PVC в выбранном namespace')
            if any(v.get('persistentVolumeClaim',{}).get('claimName')==c['pvc'] for p in self.get('pods',c['namespace'])['items'] for v in p.get('spec',{}).get('volumes',[])):raise ValueError('PVC уже используется Pod. Сначала остановите использующее его приложение.')
            if claim_referenced(c['pvc'],self.get('deployments,statefulsets,daemonsets,jobs,cronjobs',c['namespace'])['items']):raise ValueError('PVC используется существующим приложением, даже если оно остановлено. Выберите другой PVC.')
            if c['storage_secret']:
                secret=self.find('secret',c['namespace'],c['storage_secret'])
                if not secret or not secret.get('data',{}).get('password'):raise ValueError('Secret должен содержать ключ password с прежним паролем базы (пользователь app)')
        for obj in objects:
            if obj['kind']=='Ingress':
                panelhost=obj['spec']['rules'][0]['host']
                if any(r.get('host')==panelhost for i in self.get('ingress')['items'] for r in i.get('spec',{}).get('rules',[])):raise ValueError('Hostname уже используется: '+panelhost)
            existing=self.find(obj['kind'],c['namespace'],obj['metadata']['name'])
            if existing:raise ValueError(f"{obj['kind']} {c['namespace']}/{obj['metadata']['name']} уже существует. Используйте изменение версии/реплик.")
        for other in ('Deployment','StatefulSet'):
            if self.find(other,c['namespace'],c['name']):raise ValueError('Приложение с таким именем уже существует')
        if host and any(r.get('host')==host for i in self.get('ingress')['items'] for r in i.get('spec',{}).get('rules',[])):raise ValueError('Этот hostname уже используется Ingress')
        if c['type'] in ('postgres','rabbitmq') and not c['storage_secret'] and self.find('secret',c['namespace'],c['name']+'-auth'):raise ValueError('Сохранённый Secret уже существует. Для новых данных выберите свободное имя приложения; для восстановления выберите существующий PVC и Secret.')
        if kind=='StatefulSet' and c['storage_mode']=='new' and self.find('pvc',c['namespace'],'data-'+c['name']+'-0'):raise ValueError('Сохранённый PVC уже существует. Выберите его в списке существующих PVC или задайте новое имя приложения для нового диска.')
        return c,kind,objects,host
    def wait_rollout(self,kind,name,ns,seconds=240):
        try:
            return self.kubectl(['rollout','status',kind.lower()+'/'+name,'-n',ns,'--timeout='+str(seconds)+'s'],timeout=seconds+10)
        except (ValueError,subprocess.TimeoutExpired) as error:
            details=[]
            try:
                for item in self.workload_pods(dict(kind=kind,name=name,namespace=ns)):
                    pod=self.get('pod',ns,item['name'])
                    for condition in pod.get('status',{}).get('conditions',[]):
                        if condition.get('type')=='PodScheduled' and condition.get('status')=='False':
                            message=condition.get('message','')
                            hints=[]
                            if 'Insufficient memory' in message:hints.append('Недостаточно свободной памяти по requests. Увеличьте RAM worker или добавьте worker; низкая текущая утилизация не означает наличие свободной квоты для размещения.')
                            if 'Insufficient cpu' in message:hints.append('Недостаточно CPU по requests. Увеличьте CPU worker или добавьте worker.')
                            if 'taint' in message:hints.append('Часть узлов исключена из размещения из-за taints.')
                            details.append(item['name']+': '+(' '.join(hints) or message))
                    for status in pod.get('status',{}).get('containerStatuses',[])+pod.get('status',{}).get('initContainerStatuses',[]):
                        waiting=status.get('state',{}).get('waiting',{})
                        if waiting.get('reason'):details.append(item['name']+'/'+status['name']+': '+waiting['reason'])
            except Exception:
                pass  # Diagnostics must not replace the original deployment failure.
            if details:
                raise ValueError('Приложение '+ns+'/'+name+' пока не готово. '+' '.join(dict.fromkeys(details))+' Ресурсы сохранены; после устранения причины выполните «Проверить».') from error
            raise

    def check_capacity(self,plans):
        nodes=self.get('nodes')['items'];pods=self.get('pods')['items'];budget=allocation(nodes,pods)
        candidates=[n for n in nodes if not n.get('spec',{}).get('unschedulable') and any(c.get('type')=='Ready' and c.get('status')=='True' for c in n.get('status',{}).get('conditions',[])) and not any(t.get('effect') in ('NoSchedule','NoExecute') for t in n.get('spec',{}).get('taints',[]))]
        demands=[]
        for c,kind,objects,host in plans:
            for obj in objects:
                if obj['kind'] not in ('Deployment','StatefulSet'):continue
                for _ in range(obj['spec'].get('replicas',1)):
                    demands.append((obj['metadata']['name'],pod_budget(obj['spec']['template']['spec'])))
        for name,need in sorted(demands,key=lambda v:v[1]['memory'],reverse=True):
            node=next((n for n in candidates if all(budget[n['metadata']['name']]['allocatable'][k]-budget[n['metadata']['name']]['requests'][k]>=need[k] for k in need)),None)
            if node is None:
                raise ValueError('Проверка ресурсов: для '+name+' требуется '+str(round(need['cpu']*1000))+'m CPU и '+str(round(need['memory']/1024**2))+' MiB RAM. По requests нет места на доступных узлах. Учтены приложения набора и веб-панели. Увеличьте ресурсы worker или добавьте worker. Развёртывание не начато.')
            for k in need:budget[node['metadata']['name']]['requests'][k]+=need[k]
        print('Проверка CPU/RAM пройдена (оценка по requests; PVC, affinity и ResourceQuota могут дополнительно ограничить размещение).',flush=True)

    def image_cache(self,operation,images=None):
        if self.env.get('K3S_LAB_IMAGE_CACHE','1')=='0':return
        import sys
        try:
            subprocess.run([sys.executable,str(ROOT/'scripts/image-cache.py'),operation,'--cluster',str(self.root)],env=self.env,input=json.dumps(images or []),text=True,check=True,timeout=1800)
        except (OSError,subprocess.SubprocessError):
            print('[Кеш] Операция с локальным кешем не завершена. При необходимости containerd скачает образ обычным способом.',flush=True)

    def deploy(self,config,prepared=None):
        c,kind,objects,host=prepared or self.preflight(config);ns=c['namespace'];name=c['name']
        print('TASK [Создать '+ns+'/'+name+']',flush=True)
        if not self.find('namespace',None,ns):self.apply([{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns}}])
        if c['type'] in ('postgres','rabbitmq') and not c['storage_secret']:
            self.kubectl(['create','-f','-'],dict(apiVersion='v1',kind='Secret',metadata=dict(name=name+'-auth',namespace=ns),type='Opaque',stringData={'password':secrets.token_urlsafe(32)}))
        images=[container['image'] for obj in objects if obj['kind'] in ('Deployment','StatefulSet') for container in obj['spec']['template']['spec'].get('containers',[])+obj['spec']['template']['spec'].get('initContainers',[])]
        self.image_cache('restore',images)
        self.apply(objects)
        print(self.wait_rollout(kind,name,ns),flush=True)
        self.check(c,kind,host)
        if c['type'] in app_panels.IMAGES:
            print(self.wait_rollout('Deployment',name+'-ui',ns,300),flush=True)
            print('Веб-панель: '+next(o['stringData']['url'] for o in objects if o['kind']=='Secret' and o['metadata']['name']==name+'-ui-auth')+' — учётные данные в карточке приложения.',flush=True)
        print('Готово: '+(host and 'http://'+host+'/' or name+'.'+ns+'.svc.cluster.local:'+str(c['port'])),flush=True)
        if c['type']=='rabbitmq':print('RabbitMQ: пользователь app, пароль в Secret '+ns+'/'+(c['storage_secret'] or name+'-auth')+' (ключ password).',flush=True)
        if c['type']=='postgres':print('PostgreSQL: пользователь app, база app, пароль в Secret '+ns+'/'+(c['storage_secret'] or name+'-auth')+' (ключ password).',flush=True)
        self.image_cache('capture')
    def check(self,c,kind,host=''):
        obj=self.get(kind,c['namespace'],c['name'])
        self.record_check(obj,'running')
        try:self._check(c,kind,host)
        except Exception:
            self.record_check(obj,'failed');raise
        else:self.record_check(obj,'success')
    def _check(self,c,kind,host=''):
        ns=c['namespace'];name=c['name'];target=kind.lower()+'/'+name
        print('TASK [Проверки: готовность, DNS, сеть и приложение]',flush=True)
        print(self.wait_rollout(kind,name,ns,180),flush=True)
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
            if replicas>1 and any(v.get('persistentVolumeClaim') for v in obj['spec']['template']['spec'].get('volumes',[])):raise ValueError('Для приложения с одним PVC разрешена только одна реплика')
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

        if action!='app_check':print(self.wait_rollout(kind,name,ns,180),flush=True)
        if action=='app_check':
            service=self.get('service',ns,name)
            host=next((r.get('host','') for i in self.get('ingress',ns)['items'] for r in i.get('spec',{}).get('rules',[]) if any(p.get('backend',{}).get('service',{}).get('name')==name for p in r.get('http',{}).get('paths',[]))),'')
            self.check(dict(name=name,namespace=ns,type=ctype,port=service['spec']['ports'][0]['port']),kind,host)
