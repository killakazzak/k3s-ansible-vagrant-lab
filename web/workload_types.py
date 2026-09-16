"""Workload type selection and guarded migration of stateless catalog apps."""
import copy,json,secrets
KINDS=('Deployment','StatefulSet','DaemonSet')
def eligible(obj):
 spec=obj['spec'];pod=spec['template']['spec']
 return obj['metadata'].get('labels',{}).get('lab.k3s/type') in ('nginx','custom') and not spec.get('volumeClaimTemplates') and not any('persistentVolumeClaim' in v or 'hostPath' in v for v in pod.get('volumes',[]))
def convert(obj,target,replicas=1):
 if target not in KINDS:raise ValueError('Выберите Deployment, StatefulSet или DaemonSet')
 result=copy.deepcopy(obj);result['kind']=target;result.pop('status',None)
 result['metadata']={k:v for k,v in result['metadata'].items() if k in ('name','namespace','labels','annotations')}
 spec=result['spec'];result['spec']={k:spec[k] for k in ('selector','template','revisionHistoryLimit','minReadySeconds') if k in spec}
 if target!='DaemonSet':result['spec']['replicas']=replicas
 if target=='StatefulSet':result['spec']['serviceName']=result['metadata']['name']+'-headless'
 return result

def migrate(apps,data):
 import app_editor,lab_apps
 ns,name,kind,old=app_editor.load(apps,data);target=data.get('target_kind')
 if target==kind or target not in KINDS:raise ValueError('Выберите другой тип нагрузки')
 if not eligible(old):raise ValueError('Смена типа доступна для Nginx и своего образа без PVC и hostPath. Приложения с данными требуют отдельной миграции.')
 if data.get('confirmation')!=name:raise ValueError('Подтвердите смену типа именем приложения')
 if old['metadata']['resourceVersion']!=data.get('resource_version'):raise ValueError('Приложение изменилось. Откройте форму заново.')
 if apps.find(target,ns,name):raise ValueError('Целевой ресурс уже существует. Проверьте предыдущую миграцию в разделе ресурсов.')
 desired=convert(old,target,lab_apps.number(data.get('replicas',1),1,10,'Реплики'))
 label=secrets.token_hex(6);desired['spec']['selector'].setdefault('matchLabels',{})['lab.k3s/migration']=label;desired['spec']['template']['metadata'].setdefault('labels',{})['lab.k3s/migration']=label
 headless=None
 if target=='StatefulSet':
  service=apps.get('service',ns,name)
  existing=apps.find('service',ns,name+'-headless')
  if existing:
   if existing['spec'].get('clusterIP')!='None' or existing['spec'].get('selector')!=service['spec'].get('selector'):raise ValueError('Имя headless Service занято другой конфигурацией')
  else:
   service=apps.get('service',ns,name)
   headless=dict(apiVersion='v1',kind='Service',metadata=dict(name=name+'-headless',namespace=ns,labels=old['metadata'].get('labels',{})),spec=dict(clusterIP='None',selector=service['spec']['selector'],ports=service['spec']['ports']))
   for port in headless['spec']['ports']:port.pop('nodePort',None)
 apps.kubectl(['delete',kind.lower(),name,'-n',ns,'--dry-run=server'])
 if headless:apps.kubectl(['create','--dry-run=server','-f','-'],headless)
 apps.kubectl(['create','--dry-run=server','-f','-'],desired)
 if headless:apps.kubectl(['create','-f','-'],headless)
 apps.kubectl(['create','-f','-'],desired)
 print('Новый '+target+' создан. Ждём готовности; прежняя нагрузка пока сохранена.',flush=True)
 try:apps.wait_rollout(target,name,ns,300)
 except Exception:raise ValueError('Новая нагрузка не готова. Старый ресурс сохранён; проверьте оба ресурса и события Pod. Автоматическое удаление не выполнялось.') from None
 new=apps.get(target,ns,name)
 # Transfer ownership of publication resources before retiring the old controller.
 for resource in ('services','ingresses'):
  for obj in apps.get(resource,ns).get('items',[]):
   refs=obj['metadata'].get('ownerReferences',[])
   if not any(ref.get('uid')==old['metadata']['uid'] for ref in refs):continue
   for ref in refs:
    if ref.get('uid')==old['metadata']['uid']:ref.update(apiVersion='apps/v1',kind=target,name=name,uid=new['metadata']['uid'])
   apps.kubectl(['patch',resource,obj['metadata']['name'],'-n',ns,'--type=merge','-p',json.dumps({'metadata':{'resourceVersion':obj['metadata']['resourceVersion'],'ownerReferences':refs}})])
 latest=apps.get(kind,ns,name)
 if latest['metadata']['uid']!=old['metadata']['uid'] or latest['spec']!=old['spec']:raise ValueError('Старая нагрузка изменена во время миграции. Обе нагрузки сохранены; проверьте их перед удалением.')
 plural={'Deployment':'deployments','StatefulSet':'statefulsets','DaemonSet':'daemonsets'}[kind]
 apps.kubectl(['delete','--raw=/apis/apps/v1/namespaces/'+ns+'/'+plural+'/'+name,'-f','-'],dict(apiVersion='v1',kind='DeleteOptions',propagationPolicy='Foreground',preconditions={'uid':latest['metadata']['uid'],'resourceVersion':latest['metadata']['resourceVersion']}))
 print('Тип изменён: '+kind+' → '+target+'. Service и Ingress сохранены.',flush=True)
