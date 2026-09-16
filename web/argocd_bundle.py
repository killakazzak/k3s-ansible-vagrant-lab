"""Pinned upstream Argo CD installation with a single catalogue entry."""
import json,copy
from pathlib import Path
VERSION='3.5.3'
IMAGE='quay.io/argoproj/argocd:v'+VERSION
CLUSTER_KINDS={'CustomResourceDefinition','ClusterRole','ClusterRoleBinding'}
def upstream():return json.loads((Path(__file__).parent/'manifests/argocd-3.5.3.json').read_text())
def images():return {c['image'] for o in upstream() if o['kind'] in ('Deployment','StatefulSet') for c in o['spec']['template']['spec'].get('containers',[])+o['spec']['template']['spec'].get('initContainers',[])}
def build(c,host,manager):
 ns,name=c['namespace'],c['name'];items=upstream();alias=None
 for o in items:
  m=o['metadata'];original=m['name'];kind=o['kind']
  m.setdefault('labels',{}).update({'app.kubernetes.io/managed-by':manager,'lab.k3s/bundle':name,'lab.k3s/bundle-namespace':ns})
  if kind not in CLUSTER_KINDS:m['namespace']=ns
  for subject in o.get('subjects',[]):
   if subject.get('kind')=='ServiceAccount':subject['namespace']=ns
  if kind in ('Deployment','StatefulSet'):
   m['labels'].update({'lab.k3s/type':'argocd','lab.k3s/panel-for':name})
   if original=='argocd-server':
    m['name']=name;m['labels'].pop('lab.k3s/panel-for');m['labels']['lab.k3s/type']='argocd'
   o['spec']['replicas']=1;pod=o['spec']['template']['spec']
   for container in pod.get('containers',[])+pod.get('initContainers',[]):
    cpu,mem=(c['cpu'],c['memory']) if original=='argocd-server' else (250,512) if original in ('argocd-repo-server','argocd-application-controller') else (100,128)
    container['resources']={'requests':{'cpu':str(cpu)+'m','memory':str(mem)+'Mi'},'limits':{'cpu':str(cpu*2)+'m','memory':str(mem*2)+'Mi'}}
    container['imagePullPolicy']='IfNotPresent'
  if original=='argocd-cmd-params-cm':o.setdefault('data',{})['server.insecure']='true'
  if original=='argocd-cm':o.setdefault('data',{})['url']='http://'+host
  if kind=='Service' and original=='argocd-server':
   alias=copy.deepcopy(o);alias['spec']['ports']=[{'name':'http','port':8080,'targetPort':8080}]
   if name=='argocd-server':o['spec']['ports']=alias['spec']['ports']
 if name!='argocd-server':
  alias['metadata']['name']=name;items.append(alias)
 items.append({'apiVersion':'networking.k8s.io/v1','kind':'Ingress','metadata':{'name':name,'namespace':ns,'labels':{'app.kubernetes.io/managed-by':manager,'lab.k3s/bundle':name,'lab.k3s/bundle-namespace':ns}},'spec':{'ingressClassName':'traefik','rules':[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':name,'port':{'number':8080}}}}]}}]}})
 return c,'Deployment',items,host

def owned(o,c,manager):
 labels=o.get('metadata',{}).get('labels',{})
 return labels.get('app.kubernetes.io/managed-by')==manager and labels.get('lab.k3s/bundle')==c['name'] and labels.get('lab.k3s/bundle-namespace')==c['namespace']
def preflight(app,plan,manager):
 c,_,items,host=plan
 if any(rule.get('host')==host for ingress in app.get('ingress')['items'] for rule in ingress.get('spec',{}).get('rules',[])):raise ValueError('Hostname уже используется: '+host)
 # Fixed upstream names require one Argo CD instance and an exclusive namespace.
 for o in items:
  old=app.find(o['kind'],None if o['kind'] in CLUSTER_KINDS else c['namespace'],o['metadata']['name'])
  if old and not (owned(old,c,manager) and o['kind'] in CLUSTER_KINDS|{'ConfigMap','Secret','ServiceAccount','Role','RoleBinding','NetworkPolicy'}):raise ValueError('Argo CD: ресурс уже существует: '+o['kind']+'/'+o['metadata']['name'])
 return plan

def workloads(app,ns,name):
 return [o for o in app.get('deployments,statefulsets',ns)['items'] if o['metadata'].get('labels',{}).get('lab.k3s/bundle')==name and o['metadata'].get('labels',{}).get('lab.k3s/bundle-namespace')==ns]
def ready(app,ns,name):
 for o in workloads(app,ns,name):print(app.wait_rollout(o['kind'],o['metadata']['name'],ns,600),flush=True)
def deploy(app,plan):
 c,_,items,host=plan;ns=c['namespace']
 if not app.find('namespace',None,ns):app.apply([{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns}}])
 app.image_cache('restore',sorted(images()))
 crds=[o for o in items if o['kind']=='CustomResourceDefinition'];app.apply(crds)
 for o in crds:app.kubectl(['wait','--for=condition=Established','crd/'+o['metadata']['name'],'--timeout=90s'],timeout=100)
 # Keep credentials and settings when reinstalling a stopped/uninstalled controller.
 rest=[o for o in items if o['kind']!='CustomResourceDefinition' and not (o['kind'] in ('Secret','ConfigMap') and app.find(o['kind'],ns,o['metadata']['name']))]
 app.apply(rest);ready(app,ns,c['name']);app.check(c,'Deployment',host);app.image_cache('capture')
 print('Argo CD готов: http://'+host+'/. Начальный пароль в карточке приложения.',flush=True)
def lifecycle(app,ns,name,action):
 objects=workloads(app,ns,name)
 # Scale all dependencies first; waiting for the API before Redis starts would deadlock.
 for o in objects:
  target=o['kind'].lower()+'/'+o['metadata']['name']
  if action=='app_stop':app.kubectl(['scale',target,'-n',ns,'--replicas=0'])
  elif action=='app_start' or o['spec'].get('replicas',1)==0:app.kubectl(['scale',target,'-n',ns,'--replicas=1'])
  else:app.kubectl(['rollout','restart',target,'-n',ns])
 if action!='app_stop':ready(app,ns,name)
def delete(app,ns,name):
 # Never cascade-delete Applications, CRDs or credentials: workloads managed through Git survive.
 for o in workloads(app,ns,name):app.kubectl(['delete',o['kind'],o['metadata']['name'],'-n',ns,'--ignore-not-found','--wait=false'])
 for resource in ('services','ingresses'):
  for o in app.get(resource,ns)['items']:
   if o['metadata'].get('labels',{}).get('lab.k3s/bundle')==name:app.kubectl(['delete',o['kind'],o['metadata']['name'],'-n',ns,'--ignore-not-found','--wait=false'])
 print('Компоненты Argo CD удалены. Applications, Git-настройки, CRD и Secrets сохранены для переустановки; развёрнутые через Git приложения не удалены.',flush=True)
