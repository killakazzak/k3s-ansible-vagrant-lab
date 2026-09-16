"""Install isolated ingress controllers in explicitly selected remote clusters."""
import hashlib,json,os,platform,re,shutil,subprocess,tarfile,tempfile,urllib.request
from pathlib import Path
import remote_clusters
CATALOG={
 'traefik':('Traefik','traefik','https://traefik.github.io/charts'),
 'nginx':('NGINX Ingress Controller (F5)','oci://ghcr.io/nginx/charts/nginx-ingress',''),
 'haproxy':('HAProxy','kubernetes-ingress','https://haproxytech.github.io/helm-charts')}
def validate(data):
 kind=data.get('controller');service=data.get('service','NodePort')
 if kind not in CATALOG or service not in ('NodePort','LoadBalancer'):raise ValueError('Выберите контроллер и тип Service')
 version=data.get('version','')
 if version and not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version):raise ValueError('Некорректная версия Helm chart')
 return dict(controller=kind,service=service,version=version,name='lab-'+kind,namespace='lab-ingress-'+kind)
def helm(repo):
 local=repo/'.tools/helm'
 if local.is_file():return str(local)
 found=shutil.which('helm')
 if found:return found
 raise ValueError('Для установки нужен Helm на этом ПК. Нажмите «Подготовить Helm» в форме ingress.')
def prepare_helm(repo):
 try:return {'message':'Helm доступен: '+helm(repo)}
 except ValueError:pass
 system={'Darwin':'darwin','Linux':'linux'}.get(platform.system());arch={'arm64':'arm64','aarch64':'arm64','x86_64':'amd64'}.get(platform.machine())
 if not system or not arch:raise ValueError('Установите Helm вручную для этой ОС/архитектуры')
 filename=f'helm-v3.19.0-{system}-{arch}.tar.gz';url='https://get.helm.sh/'+filename
 with tempfile.TemporaryDirectory() as tmp:
  archive=Path(tmp)/filename
  with urllib.request.urlopen(url,timeout=30) as response:archive.write_bytes(response.read(100*1024*1024))
  with urllib.request.urlopen(url+'.sha256sum',timeout=15) as response:checksum=response.read(4096).decode().split()[0]
  if hashlib.sha256(archive.read_bytes()).hexdigest()!=checksum:raise ValueError('Контрольная сумма Helm не совпала')
  with tarfile.open(archive) as tar:
   source=tar.extractfile(system+'-'+arch+'/helm')
   if source is None:raise ValueError('Helm отсутствует в архиве')
   target=repo/'.tools/helm';target.parent.mkdir(exist_ok=True)
   fd,name=tempfile.mkstemp(dir=target.parent,prefix='helm-')
   try:
    with os.fdopen(fd,'wb') as f:shutil.copyfileobj(source,f)
    os.chmod(name,0o755);os.replace(name,target)
   finally:
    if os.path.exists(name):os.unlink(name)
 return {'message':'Helm 3.19.0 установлен локально в .tools/helm'}
def values(c):
 name=c['name'];service={'type':c['service']}
 if c['controller']=='traefik':return {'deployment':{'replicas':1},'ingressClass':{'name':name,'isDefaultClass':False},'providers':{'kubernetesIngress':{'ingressClass':name},'kubernetesCRD':{'enabled':False},'kubernetesGateway':{'enabled':False}},'gateway':{'enabled':False},'service':{'spec':service},'resources':{'requests':{'cpu':'100m','memory':'128Mi'}},'ingressRoute':{'dashboard':{'enabled':False}}}
 if c['controller']=='nginx':return {'controller':{'replicaCount':1,'ingressClass':{'name':name,'create':True,'setAsDefaultIngress':False},'enableCustomResources':False,'service':service}}
 return {'controller':{'replicaCount':1,'ingressClass':name,'ingressClassResource':{'name':name,'default':False},'service':service}}
def run(command,timeout=30):
 p=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
 if p.returncode:raise ValueError((p.stderr or p.stdout or 'Команда завершилась с ошибкой')[-3000:])
 return p.stdout
def preview(repo,env,root,data):
 if not (root/'kubeconfig').is_file():raise ValueError('Доступ к Kubernetes ещё не настроен')
 c=validate(data);h=helm(repo);k=[remote_clusters.binary(repo,env),'--kubeconfig='+str(root/'kubeconfig'),'--request-timeout=5s']
 classes=json.loads(run(k+['get','ingressclasses','-o','json']))['items']
 if any(x['metadata']['name']==c['name'] for x in classes):raise ValueError('IngressClass '+c['name']+' уже существует. Повторная установка запрещена.')
 releases=json.loads(run([h,'list','--all','--all-namespaces','--kubeconfig',str(root/'kubeconfig'),'-o','json']))
 if any(x['name']==c['name'] for x in releases):raise ValueError('Helm release '+c['name']+' уже существует')
 for verb,resource in [('create','namespaces'),('create','deployments.apps'),('create','services'),('create','secrets'),('create','serviceaccounts'),('create','clusterroles.rbac.authorization.k8s.io'),('bind','clusterroles.rbac.authorization.k8s.io'),('create','clusterrolebindings.rbac.authorization.k8s.io'),('create','ingressclasses.networking.k8s.io')]:
  if run(k+['auth','can-i',verb,resource,'--all-namespaces']).strip()!='yes':raise ValueError('Недостаточно прав: '+verb+' '+resource)
 _,chart,repo_url=CATALOG[c['controller']];source=[chart]+(['--repo',repo_url] if repo_url else [])
 metadata=run([h,'show','chart']+source+(['--version',c['version']] if c['version'] else []),60)
 match=re.search(r'^version:\s*[\"\']?([^\s\"\']+)',metadata,re.M)
 if not match:raise ValueError('Не удалось определить версию chart')
 c['version']=match[1];validate(c)
 return dict(params=c,classes=[x['metadata']['name'] for x in classes],title=CATALOG[c['controller']][0],values=values(c))
def install(repo,env,root,data):
 if not data.get('version'):raise ValueError('Сначала выполните предварительную проверку')
 plan=preview(repo,env,root,data);c=plan['params'];h=helm(repo);_,chart,url=CATALOG[c['controller']]
 print('Установка '+plan['title']+' · chart '+c['version']+' · '+c['namespace'],flush=True)
 print('Источник: '+(url or chart),flush=True)
 with tempfile.TemporaryDirectory() as tmp:
  file=Path(tmp)/'values.json';file.write_text(json.dumps(plan['values']))
  command=[h,'install',c['name'],chart]+(['--repo',url] if url else [])+['--version',c['version'],'--kubeconfig',str(root/'kubeconfig'),'--namespace',c['namespace'],'--create-namespace','--skip-crds','--values',str(file),'--wait','--timeout','5m']
  # Keep failed releases for diagnosis; never delete existing resources automatically.
  result=subprocess.run(command,timeout=420)
  if result.returncode:raise ValueError('Установка не завершена. Проверьте Pods и события namespace '+c['namespace']+'. Ресурсы сохранены для диагностики.')
 print('Контроллер готов. В Ingress укажите spec.ingressClassName: '+c['name'],flush=True)
 k=[remote_clusters.binary(repo,env),'--kubeconfig='+str(root/'kubeconfig'),'--request-timeout=5s']
 print(run(k+['get','services','-n',c['namespace'],'-o','wide']),flush=True)


def client(repo,env,root):
 if not (root/'kubeconfig').is_file():raise ValueError('Доступ к Kubernetes ещё не настроен')
 return [remote_clusters.binary(repo,env),'--kubeconfig='+str(root/'kubeconfig'),'--request-timeout=8s']

def inventory(repo,env,root):
 k=client(repo,env,root)
 def items(resource):return json.loads(run(k+['get',resource,'--all-namespaces','-o','json'],20)).get('items',[])
 classes=items('ingressclasses');services=items('services');workloads=items('deployments,daemonsets');routes=items('ingresses')
 result=[]
 for cls in classes:
  meta=cls['metadata'];annotations=meta.get('annotations',{});name=meta['name'];release=annotations.get('meta.helm.sh/release-name','');ns=annotations.get('meta.helm.sh/release-namespace','')
  kind=next((kind for kind in CATALOG if name=='lab-'+kind and release=='lab-'+kind and ns=='lab-ingress-'+kind),'')
  def belongs(obj):
   m=obj['metadata'];a=m.get('annotations',{})
   return bool(ns and release and m.get('namespace')==ns and ((a.get('meta.helm.sh/release-name')==release and a.get('meta.helm.sh/release-namespace')==ns) or m.get('labels',{}).get('app.kubernetes.io/instance')==release))
  matched=[s for s in services if belongs(s) and s['spec'].get('type') in ('NodePort','LoadBalancer')]
  pods=[w for w in workloads if belongs(w)]
  service=matched[0] if len(matched)==1 else None
  uses=[r['metadata']['namespace']+'/'+r['metadata']['name'] for r in routes if (r.get('spec',{}).get('ingressClassName') or r['metadata'].get('annotations',{}).get('kubernetes.io/ingress.class') or (name if annotations.get('ingressclass.kubernetes.io/is-default-class')=='true' else ''))==name]
  desired=sum(w.get('spec',{}).get('replicas',w.get('status',{}).get('desiredNumberScheduled',0)) for w in pods)
  ready=sum(w.get('status',{}).get('readyReplicas',w.get('status',{}).get('numberReady',0)) for w in pods)
  result.append(dict(name=name,controller=cls.get('spec',{}).get('controller',''),kind=kind,namespace=ns,release=release,managed=bool(kind and service and len(pods)==1 and pods[0]['kind']=='Deployment'),service=(service or {}).get('spec',{}).get('type',''),policy=(service or {}).get('spec',{}).get('externalTrafficPolicy','Cluster'),addresses=[a.get('ip') or a.get('hostname') for a in (service or {}).get('status',{}).get('loadBalancer',{}).get('ingress',[])],ports=(service or {}).get('spec',{}).get('ports',[]),workload=dict(name=pods[0]['metadata']['name'],namespace=ns,kind=pods[0]['kind']) if len(pods)==1 else None,replicas=desired,ready=ready,routes=uses,uid=meta['uid'],dashboard=any(a in ('--api.insecure=true','--api.insecure') for w in pods for c in w.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[]) for a in c.get('args',[])),dashboard_url=next((w.get('spec',{}).get('template',{}).get('metadata',{}).get('annotations',{}).get('lab.k3s/dashboard-url') for w in pods if w.get('spec',{}).get('template',{}).get('metadata',{}).get('annotations',{}).get('lab.k3s/dashboard-url')),None),dashboard_port=next((p['containerPort'] for w in pods for c in w.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[]) for p in c.get('ports',[]) if p.get('name')=='traefik'),9000)))
 return result

def validate_management(data,delete=False):
 kind=data.get('controller')
 if kind not in CATALOG:raise ValueError('Неподдерживаемый контроллер')
 if delete:
  if data.get('confirmation')!='УДАЛИТЬ':raise ValueError('Для удаления контроллера введите УДАЛИТЬ')
 else:
  if data.get('service') not in ('NodePort','LoadBalancer'):raise ValueError('Выберите NodePort или LoadBalancer')
  if data.get('policy') not in ('Local','Cluster'):raise ValueError('Выберите Local или Cluster')
  try:replicas=int(data.get('replicas',1))
  except (ValueError,TypeError):raise ValueError('Укажите число реплик от 1 до 10')
  if not 1<=replicas<=10:raise ValueError('Укажите число реплик от 1 до 10')
 return kind

def manage(repo,env,root,data,delete=False):
 kind=validate_management(data,delete)
 current=next((c for c in inventory(repo,env,root) if c['name']=='lab-'+kind),None)
 if not current or not current['managed']:raise ValueError('Изменять можно контроллеры, установленные платформой; проверьте Helm release и Service')
 if data.get('uid')!=current['uid']:raise ValueError('Контроллер изменился. Откройте список заново.')
 h=helm(repo);scope=['--kubeconfig',str(root/'kubeconfig'),'--namespace',current['namespace']]
 releases=json.loads(run([h,'list','--all','-o','json']+scope))
 release=next((r for r in releases if r['name']==current['release']),None)
 chart_name={'nginx':'nginx-ingress','traefik':'traefik','haproxy':'kubernetes-ingress'}[kind]
 match=re.fullmatch(re.escape(chart_name)+r'-(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)',(release or {}).get('chart',''))
 if not match:raise ValueError('Helm chart не соответствует контроллеру. Изменение отменено.')
 if delete:
  print('Удаляем '+current['release']+'. Ingress приложений сохраняются, но их адреса перестанут обслуживаться. Облачный LoadBalancer будет удалён.',flush=True)
  command=[h,'uninstall',current['release']]+scope+['--wait','--timeout','5m']
 else:
  if release.get('status')!='deployed':raise ValueError('Helm release не готов к обновлению: '+release.get('status','unknown'))
  _,chart,url=CATALOG[kind];settings={'service':{'spec':{'type':data['service'],'externalTrafficPolicy':data['policy']}},'deployment':{'replicas':int(data['replicas'])}} if kind=='traefik' else {'controller':{'replicaCount':int(data['replicas']),'service':{'type':data['service'],'externalTrafficPolicy':data['policy']}}}
  if kind=='traefik' and 'dashboard' in data:
   settings['api']={'dashboard':True,'insecure':data['dashboard'] is True}
   settings['ports']={'traefik':{'expose':{'default':False}}}
  print('Обновляем '+current['release']+' · '+data['service']+' · реплик '+str(data['replicas']),flush=True)
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'values.json';path.write_text(json.dumps(settings))
   command=[h,'upgrade',current['release'],chart]+(['--repo',url] if url else [])+scope+['--version',match[1],'--reuse-values','--values',str(path),'--wait','--timeout','5m']
   result=subprocess.run(command,timeout=360)
   if result.returncode:raise ValueError('Обновление не завершено. Проверьте состояние контроллера и журнал операции.')
  print('Настройки контроллера сохранены.',flush=True);return
 result=subprocess.run(command,timeout=360)
 if result.returncode:raise ValueError('Удаление не завершено. Проверьте состояние Helm release и облачного балансировщика.')
 print('Контроллер удалён. Приложения и их данные сохранены.',flush=True)
