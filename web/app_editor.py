"""Conservative edits of catalog-managed workloads and their primary Ingress."""
import copy,json
import lab_apps as lab

def load(apps,data):
 ns=lab.namespace(data.get('namespace'),True);name=lab.dns(data.get('name'));kind=data.get('kind')
 if kind not in ('Deployment','StatefulSet','DaemonSet'):raise ValueError('Неподдерживаемый ресурс')
 obj=apps.get(kind,ns,name)
 if obj['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')!=lab.MANAGER or obj['metadata'].get('labels',{}).get('lab.k3s/panel-for'):raise ValueError('Редактировать можно приложения, установленные через каталог')
 return ns,name,kind,obj

def settings(apps,data):
 ns,name,kind,obj=load(apps,data);spec=obj['spec']['template']['spec'];containers=spec['containers'];c=containers[0];ctype=obj['metadata']['labels'].get('lab.k3s/type','custom')
 resources=c.get('resources',{});requests=resources.get('requests',{});limits=resources.get('limits',{})
 route=apps.find('ingress',ns,name);service=apps.get('service',ns,name)
 editable_route=not route or route['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')==lab.MANAGER
 classes=[x['metadata']['name'] for x in apps.get('ingressclasses')['items']]
 import workload_types
 return dict(can_change_kind=workload_types.eligible(obj),name=name,namespace=ns,kind=kind,resource_version=obj['metadata']['resourceVersion'],type=ctype,container=c['name'],image=c['image'],image_editable=len(containers)==1 and ctype not in ('argocd','gitlab-agent','gitlab-runner'),replicas=obj['spec'].get('replicas',1),replica_max=1 if kind=='StatefulSet' or any('persistentVolumeClaim' in v for v in spec.get('volumes',[])) or ctype in ('argocd','gitlab-agent','gitlab-runner') else 10,cpu=round(lab.resource_quantity(requests.get('cpu','100m'))*1000),memory=round(lab.resource_quantity(requests.get('memory','128Mi'))/1024**2),cpu_limit=round(lab.resource_quantity(limits.get('cpu','0'))*1000),memory_limit=round(lab.resource_quantity(limits.get('memory','0'))/1024**2),publication='ingress' if route else 'internal',host=(route or {}).get('spec',{}).get('rules',[{}])[0].get('host',''),ingress_class=(route or {}).get('spec',{}).get('ingressClassName',''),ingress_classes=classes,publication_editable=editable_route,service_ports=[p['port'] for p in service['spec']['ports']],service_port=next((p.get('backend',{}).get('service',{}).get('port',{}).get('number') for r in (route or {}).get('spec',{}).get('rules',[]) for p in r.get('http',{}).get('paths',[])),service['spec']['ports'][0]['port']))

def prepare(apps,data):
 ns,name,kind,obj=load(apps,data);current=settings(apps,data)
 if data.get('resource_version')!=obj['metadata']['resourceVersion']:raise ValueError('Приложение изменилось. Откройте редактирование заново.')
 image=data.get('image',current['image']);ctype=current['type']
 if image!=current['image']:
  if not current['image_editable']:raise ValueError('Версия этого набора меняется отдельно; сохраните текущий образ')
  lab.validate(dict(type=ctype,name=name,namespace=ns,image=image))
  if ctype in ('postgres','redis') and image.rsplit(':',1)[-1].split('.')[0].split('-')[0]!=current['image'].rsplit(':',1)[-1].split('.')[0].split('-')[0]:raise ValueError('Смена major базы требует отдельной миграции')
 replicas=lab.number(data.get('replicas'),0,current['replica_max'],'Реплики')
 cpu=lab.number(data.get('cpu'),25,8000,'CPU');memory=lab.number(data.get('memory'),32,16384,'RAM')
 cpu_limit=lab.number(data.get('cpu_limit',0),0,32000,'Лимит CPU');memory_limit=lab.number(data.get('memory_limit',0),0,65536,'Лимит RAM')
 if (cpu_limit and cpu_limit<cpu) or (memory_limit and memory_limit<memory):raise ValueError('Лимиты должны быть не меньше requests; 0 означает без лимита')
 resources=copy.deepcopy(obj['spec']['template']['spec']['containers'][0].get('resources',{}));resources.setdefault('requests',{}).update(cpu=str(cpu)+'m',memory=str(memory)+'Mi');resources.setdefault('limits',{}).update(cpu=str(cpu_limit)+'m' if cpu_limit else None,memory=str(memory_limit)+'Mi' if memory_limit else None)
 patch={'metadata':{'resourceVersion':data['resource_version']},'spec':{'replicas':replicas,'template':{'spec':{'containers':[{'name':current['container'],'image':image,'resources':resources}]}}}}
 if kind=='DaemonSet':patch['spec'].pop('replicas',None)
 route=apps.find('ingress',ns,name);publication=data.get('publication');desired=None
 if publication not in ('internal','ingress'):raise ValueError('Выберите способ публикации')
 if route and any(p.get('backend',{}).get('service',{}).get('name')!=name for rule in route.get('spec',{}).get('rules',[]) for p in rule.get('http',{}).get('paths',[])):raise ValueError('Ingress содержит маршруты другого приложения; используйте редактор YAML')
 if route and not current['publication_editable']:raise ValueError('Ingress с этим именем не принадлежит каталогу; редактирование публикации запрещено')
 if publication=='ingress':
  if ctype in ('postgres','redis','kafka','gitlab-runner','gitlab-agent'):raise ValueError('Основной Service этого приложения не поддерживает HTTP Ingress')
  host=data.get('host','').strip();ingress_class=lab.resource_class(data.get('ingress_class',''));port=lab.number(data.get('service_port'),1,65535,'Порт Service')
  lab.validate(dict(type='custom',image='nginx:1.30.4-alpine',name=name,namespace=ns,host=host))
  if not host or '.' not in host:raise ValueError('Укажите полный hostname без http:// и порта')
  if ingress_class not in current['ingress_classes']:raise ValueError('IngressClass не существует')
  if port not in current['service_ports']:raise ValueError('Порт отсутствует в Service приложения')
  for other in apps.get('ingress')['items']:
   if other['metadata'].get('namespace')==ns and other['metadata']['name']==name:continue
   if any(rule.get('host')==host for rule in other.get('spec',{}).get('rules',[])):raise ValueError('Hostname уже занят другим Ingress')
  desired=copy.deepcopy(route) if route else dict(apiVersion='networking.k8s.io/v1',kind='Ingress',metadata=dict(name=name,namespace=ns,labels={'app.kubernetes.io/managed-by':lab.MANAGER},ownerReferences=[dict(apiVersion=obj['apiVersion'],kind=kind,name=name,uid=obj['metadata']['uid'],controller=False)]),spec={})
  desired.pop('status',None);desired['metadata'].pop('managedFields',None)
  if route and (len(route['spec'].get('rules',[]))!=1 or len(route['spec']['rules'][0].get('http',{}).get('paths',[]))!=1 or route['spec'].get('tls')):raise ValueError('Для Ingress с TLS или несколькими маршрутами используйте редактор YAML')
  desired['spec'].update(ingressClassName=ingress_class,rules=[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':name,'port':{'number':port}}}}]}}])
  # A class change cannot retain controller-specific annotations.
  if route and ingress_class!=route['spec'].get('ingressClassName'):
   desired['metadata']['annotations']={k:v for k,v in desired['metadata'].get('annotations',{}).items() if not k.startswith(('traefik.','nginx.','nginx.org/','haproxy.'))}
 return current,patch,route,desired

def edit(apps,data):
 current,patch,route,desired=prepare(apps,data);ns=current['namespace'];name=current['name'];target=current['kind'].lower()+'/'+name
 command=['patch',target,'-n',ns,'--type=strategic','-p',json.dumps(patch)]
 apps.kubectl(command+['--dry-run=server','-o','name'])
 # Existing routes retain resourceVersion and all unrelated fields. Replace
 # avoids SSA ownership conflicts while rejecting concurrent changes.
 route_command=['replace' if route else 'create','-f','-','-o','name']
 if desired:apps.kubectl(route_command+['--dry-run=server'],desired)
 elif route:apps.kubectl(['delete','ingress',name,'-n',ns,'--dry-run=server'])
 print('Проверка API пройдена. Сохраняем параметры '+ns+'/'+name,flush=True)
 apps.kubectl(command)
 if desired:apps.kubectl(route_command,desired)
 elif route:
  # UID/resourceVersion preconditions prevent deleting a concurrently replaced route.
  apps.kubectl(['delete','--raw=/apis/networking.k8s.io/v1/namespaces/'+ns+'/ingresses/'+name,'-f','-'],dict(apiVersion='v1',kind='DeleteOptions',preconditions={'uid':route['metadata']['uid'],'resourceVersion':route['metadata']['resourceVersion']}))
 if current['replicas'] or int(data['replicas']):print(apps.wait_rollout(current['kind'],name,ns,300),flush=True)
 print('Параметры сохранены. PVC и данные не изменялись.',flush=True)
