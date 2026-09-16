"""GitLab Kubernetes integrations; credentials only through existing Secrets."""
import json,re,base64
from urllib.parse import urlsplit
TYPES=('gitlab-runner','gitlab-agent')
CATALOG={
 'gitlab-runner':dict(image='registry.gitlab.com/gitlab-org/gitlab-runner:alpine-v19.3.2',port=9252,memory=256,cpu=100),
 'gitlab-agent':dict(image='registry.gitlab.com/gitlab-org/cluster-integration/gitlab-agent/agentk:v19.3.1',port=8080,memory=128,cpu=100),
}
def settings(config,dns,number):
 kind=config['type'];url=config.get('gitlab_url','https://gitlab.com').strip();kas=config.get('kas_address','grpcs://kas.gitlab.com').strip()
 for value,schemes in [(url,('https',)),(kas,('wss','grpcs'))]:
  try:p=urlsplit(value);valid=p.scheme in schemes and p.hostname and not p.username and not p.password and not p.query and not p.fragment and not any(x.isspace() for x in value);p.port
  except ValueError:valid=False
  if not valid:raise ValueError('Укажите HTTPS URL GitLab и защищённый адрес KAS (grpcs:// или wss://), без логина и токена в URL')
 if config.get('host'):raise ValueError('Runner и Agent используют исходящее соединение; Ingress не требуется')
 if config.get('storage_mode','none')!='none':raise ValueError('Runner и Agent не требуют PVC')
 return dict(gitlab_url=url.rstrip('/'),kas_address=kas,gitlab_secret=dns(config.get('gitlab_secret',''),'Secret с токеном GitLab'),concurrent=number(config.get('concurrent',1),1,10,'Одновременные CI jobs'))
def key(kind):return 'runner-token' if kind=='gitlab-runner' else 'token'
def check_secret(app,c):
 secret=app.find('secret',c['namespace'],c['gitlab_secret'])
 try:token=base64.b64decode((secret or {}).get('data',{}).get(key(c['type']),''),validate=True).decode().strip()
 except Exception:token=''
 if not token or (c['type']=='gitlab-runner' and not token.startswith('glrt-')):raise ValueError('Secret отсутствует или не содержит корректный '+key(c['type'])+(' (токен glrt-)' if c['type']=='gitlab-runner' else ''))
def save_secret(app,data,dns,namespace):
 kind=data.get('type');ns=namespace(data.get('namespace'),True);name=dns(data.get('name'),'имя Secret');token=data.get('token','')
 if kind not in TYPES or not isinstance(token,str) or not 8<=len(token)<=4096 or any(c.isspace() for c in token):raise ValueError('Укажите корректный токен GitLab')
 if kind=='gitlab-runner' and not token.startswith('glrt-'):raise ValueError('Нужен authentication token glrt-, а не старый registration token')
 if app.find('secret',ns,name):raise ValueError('Secret уже существует. Выберите другое имя или используйте существующий Secret.')
 if not app.find('namespace',None,ns):app.apply([{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns}}])
 try:app.kubectl(['create','-f','-'],{'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':ns},'type':'Opaque','stringData':{key(kind):token}})
 except Exception:raise ValueError('Не удалось создать Secret GitLab; проверьте доступ и namespace') from None
 return {'ok':True,'name':name}
def build(c,manager):
 name,ns,kind=c['name'],c['namespace'],c['type'];labels={'app.kubernetes.io/managed-by':manager,'app.kubernetes.io/name':name,'lab.k3s/type':kind};selector={'lab.k3s/app':name}
 def obj(api,k,n=None,**kw):return dict(apiVersion=api,kind=k,metadata=dict(name=n or name,namespace=ns,labels=labels.copy()),**kw)
 container={'name':kind,'image':c['image'],'resources':{'requests':{'cpu':str(c['cpu'])+'m','memory':str(c['memory'])+'Mi'},'limits':{'cpu':str(c['cpu']*2)+'m','memory':str(c['memory']*2)+'Mi'}},'ports':[{'name':'app','containerPort':c['port']}]}
 pod={'serviceAccountName':name,'containers':[container],'terminationGracePeriodSeconds':60}
 rules=[];objects=[]
 if kind=='gitlab-runner':
  config='''concurrent = CONCURRENT
check_interval = 3
listen_address = ":9252"
[[runners]]
  [runners.kubernetes]
    namespace = NAMESPACE
    image = "alpine:3.22"
    privileged = false
    service_account = JOB_ACCOUNT
    automount_service_account_token = false
    cpu_request = "250m"
    cpu_limit = "1000m"
    memory_request = "256Mi"
    memory_limit = "1Gi"
    helper_cpu_request = "100m"
    helper_cpu_limit = "500m"
    helper_memory_request = "128Mi"
    helper_memory_limit = "256Mi"
    service_cpu_request = "100m"
    service_cpu_limit = "500m"
    service_memory_request = "128Mi"
    service_memory_limit = "256Mi"
'''.replace('CONCURRENT',str(c['concurrent'])).replace('NAMESPACE',json.dumps(ns)).replace('JOB_ACCOUNT',json.dumps(name+'-job'))
  objects.append(obj('v1','ConfigMap',data={'config.template.toml':config,'base.toml':config.split('[[runners]]')[0]}))
  pod['volumes']=[{'name':'config','configMap':{'name':name}},{'name':'runtime','emptyDir':{}}]
  container['env']=[{'name':'CI_SERVER_URL','value':c['gitlab_url']},{'name':'CI_SERVER_TOKEN','valueFrom':{'secretKeyRef':{'name':c['gitlab_secret'],'key':'runner-token'}}},{'name':'RUNNER_EXECUTOR','value':'kubernetes'}]
  container['command']=['/bin/sh','-ec','cp /config/base.toml /runtime/config.toml; gitlab-runner register --non-interactive --config /runtime/config.toml --template-config /config/config.template.toml; exec gitlab-runner run --config /runtime/config.toml --working-directory /runtime']
  container['volumeMounts']=[{'name':'config','mountPath':'/config','readOnly':True},{'name':'runtime','mountPath':'/runtime'}]
  container['readinessProbe']={'httpGet':{'path':'/metrics','port':'app'},'periodSeconds':10}
  rules=[{'apiGroups':[''],'resources':['pods'],'verbs':['create','delete','get','list','watch']},{'apiGroups':[''],'resources':['pods/attach','pods/exec'],'verbs':['create','delete','get','patch']},{'apiGroups':[''],'resources':['pods/log','events'],'verbs':['get','list','watch']},{'apiGroups':[''],'resources':['secrets'],'verbs':['create','delete','get','update']},{'apiGroups':[''],'resources':['services'],'verbs':['create','delete','get']},{'apiGroups':[''],'resources':['serviceaccounts'],'verbs':['get']}]
  objects.append(obj('v1','ServiceAccount',name+'-job',automountServiceAccountToken=False))
 else:
  container['args']=['--kas-address='+c['kas_address'],'--token-file=/etc/agentk/token']
  container['env']=[{'name':n,'valueFrom':{'fieldRef':{'fieldPath':p}}} for n,p in [('POD_NAMESPACE','metadata.namespace'),('POD_NAME','metadata.name'),('POD_IP','status.podIP'),('SERVICE_ACCOUNT_NAME','spec.serviceAccountName')]]
  container['volumeMounts']=[{'name':'token','mountPath':'/etc/agentk','readOnly':True}]
  pod['volumes']=[{'name':'token','secret':{'secretName':c['gitlab_secret'],'items':[{'key':'token','path':'token'}]}}]
  container['readinessProbe']={'httpGet':{'path':'/readiness','port':'app'},'periodSeconds':10}
  container['livenessProbe']={'httpGet':{'path':'/liveness','port':'app'},'initialDelaySeconds':15,'periodSeconds':20}
  rules=[{'apiGroups':[''],'resources':['pods','pods/log','services','configmaps','secrets','persistentvolumeclaims'],'verbs':['get','list','watch','create','update','patch','delete']},{'apiGroups':['apps'],'resources':['deployments','statefulsets','daemonsets','replicasets'],'verbs':['get','list','watch','create','update','patch','delete']},{'apiGroups':['batch'],'resources':['jobs','cronjobs'],'verbs':['get','list','watch','create','update','patch','delete']},{'apiGroups':['networking.k8s.io'],'resources':['ingresses','networkpolicies'],'verbs':['get','list','watch','create','update','patch','delete']}]
 container['startupProbe']=dict(container['readinessProbe'],failureThreshold=60)
 annotations={'lab.k3s/gitlab-config':json.dumps({k:c[k] for k in ('gitlab_url','kas_address','gitlab_secret','concurrent')})}
 workload=obj('apps/v1','Deployment',spec={'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':selector},'template':{'metadata':{'labels':dict(labels,**selector)},'spec':pod}});workload['metadata']['annotations']=annotations
 objects.extend([obj('v1','ServiceAccount'),obj('rbac.authorization.k8s.io/v1','Role',rules=rules),obj('rbac.authorization.k8s.io/v1','RoleBinding',roleRef={'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':name},subjects=[{'kind':'ServiceAccount','name':name,'namespace':ns}]),workload,obj('v1','Service',spec={'selector':selector,'ports':[{'name':'app','port':c['port'],'targetPort':'app'}]})])
 return c,'Deployment',objects,''

def rotate_runner_token(app,data):
 import app_editor,secrets
 ns,name,kind,workload=app_editor.load(app,data)
 if kind!='Deployment' or workload['metadata']['labels'].get('lab.k3s/type')!='gitlab-runner':raise ValueError('Выберите GitLab Runner из каталога')
 token=data.get('token','')
 if not isinstance(token,str) or not token.startswith('glrt-') or not 8<=len(token)<=4096 or any(c.isspace() for c in token):raise ValueError('Введите новый authentication token glrt- из GitLab')
 if data.get('resource_version')!=workload['metadata']['resourceVersion']:raise ValueError('Runner изменился. Откройте редактирование заново.')
 secret_name=name[:40]+'-token-'+secrets.token_hex(4)
 config=json.loads(workload['metadata'].get('annotations',{}).get('lab.k3s/gitlab-config','{}'));config['gitlab_secret']=secret_name
 containers=workload['spec']['template']['spec']['containers']
 container=next((c for c in containers if c['name']=='gitlab-runner'),None)
 if not container:raise ValueError('Контейнер Runner не найден')
 env=[e for e in container.get('env',[]) if e['name'] not in ('RUNNER_TOKEN','CI_SERVER_TOKEN')]
 env.append({'name':'CI_SERVER_TOKEN','valueFrom':{'secretKeyRef':{'name':secret_name,'key':'runner-token'}}})
 secret=dict(apiVersion='v1',kind='Secret',metadata=dict(name=secret_name,namespace=ns),type='Opaque',stringData={'runner-token':token})
 patch=[{'op':'test','path':'/metadata/resourceVersion','value':data['resource_version']},{'op':'add','path':'/metadata/annotations','value':dict(workload['metadata'].get('annotations',{}),**{'lab.k3s/gitlab-config':json.dumps(config)})},{'op':'add','path':'/spec/template/spec/containers/'+str(containers.index(container))+'/env','value':env}]
 command=['patch','deployment',name,'-n',ns,'--type=json','-p',json.dumps(patch)]
 try:
  app.kubectl(['create','--dry-run=server','-f','-','-o','name'],secret)
  app.kubectl(command+['--dry-run=server','-o','name'])
  app.kubectl(['create','-f','-','-o','name'],secret)
 except Exception:raise ValueError('Не удалось сохранить новый токен. Проверьте права на создание Secrets и изменение Deployment.') from None
 try:app.kubectl(command)
 except Exception:raise ValueError('Новый токен сохранён в Secret '+secret_name+', но Runner не обновлён. Откройте редактирование заново и повторите операцию.') from None
 return {'ok':True,'message':'Новый токен сохранён. Конфигурация Runner обновлена; при запуске Pod выполнится повторная регистрация. Проверьте статус Online в GitLab.'}
