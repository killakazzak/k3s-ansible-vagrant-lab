"""Authenticated HTTPS dashboard, configured through the installed Helm release."""
import base64,copy,ipaddress,json,secrets,shutil,subprocess,tempfile,re
from pathlib import Path
import remote_ingress as ingress
SECRET='lab-dashboard-login'
def credentials(repo,env,root):
 k=ingress.client(repo,env,root)
 obj=json.loads(ingress.run(k+['get','secret',SECRET,'-n','lab-ingress-traefik','-o','json']))
 return {key:base64.b64decode(obj['data'][key]).decode() for key in ('username','password')}
def publish(repo,env,root,data):
 current=next((c for c in ingress.inventory(repo,env,root) if c['kind']=='traefik' and c['managed']),None)
 if not current or current['uid']!=data.get('uid'):raise ValueError('Обновите настройки Traefik перед публикацией')
 if current['service']!='LoadBalancer':raise ValueError('Для публичной панели требуется LoadBalancer')
 address=next((a for a in current['addresses'] if re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}',a)),None)
 if not address:raise ValueError('LoadBalancer ещё не получил IPv4')
 address=str(ipaddress.IPv4Address(address));host='traefik.'+address.replace('.','-')+'.sslip.io';url='https://'+host+'/dashboard/'
 h=ingress.helm(repo);k=ingress.client(repo,env,root);ns=current['namespace'];release=current['release'];scope=['--kubeconfig',str(root/'kubeconfig'),'-n',ns]
 releases=json.loads(ingress.run([h,'list','--all','-o','json']+scope));record=next((r for r in releases if r['name']==release),{})
 match=re.fullmatch(r'traefik-(\d+\.\d+\.\d+)',record.get('chart',''))
 if not match or record.get('status')!='deployed':raise ValueError('Helm release Traefik не готов')
 existing=ingress.run(k+['get','secret',SECRET,'-n',ns,'--ignore-not-found','-o','json'])
 if existing:
  obj=json.loads(existing)
  if obj['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')!='k3s-lab-dashboard':raise ValueError('Secret с таким именем уже занят')
  password=base64.b64decode(obj['data']['password']).decode();hashed=base64.b64decode(obj['data']['users']).decode()
 else:
  binary=shutil.which('htpasswd',path=env.get('PATH')) or shutil.which('htpasswd',path='/usr/sbin:/usr/bin')
  if not binary:raise ValueError('Для защиты панели установите htpasswd (apache2-utils в Ubuntu)')
  password=secrets.token_urlsafe(24)
  hashed=subprocess.run([binary,'-niB','admin'],input=password+'\n',capture_output=True,text=True,check=True).stdout.strip()
 current_values=json.loads(ingress.run([h,'get','values',release,'-o','json']+scope)) or {}
 content=copy.deepcopy(current_values.get('providers',{}).get('file',{}).get('content') or {})
 if not isinstance(content,dict):raise ValueError('Нестандартная конфигурация file provider: публикация отменена')
 http=content.setdefault('http',{});routers=http.setdefault('routers',{});middlewares=http.setdefault('middlewares',{})
 if not existing and ('labDashboard' in routers or 'labDashboardAuth' in middlewares):raise ValueError('Имена маршрутов панели уже заняты')
 routers['labDashboard']={'rule':'Host(`'+host+'`) && (PathPrefix(`/dashboard`) || PathPrefix(`/api`))','entryPoints':['websecure'],'service':'api@internal','middlewares':['labDashboardAuth'],'tls':{}}
 middlewares['labDashboardAuth']={'basicAuth':{'users':[hashed],'removeHeader':True}}
 values={'api':{'dashboard':True,'insecure':False},'providers':{'file':{'enabled':True,'content':content}},'ports':{'traefik':{'expose':{'default':False}}},'deployment':{'podAnnotations':{'lab.k3s/dashboard-url':url}}}
 # The password is stored only in a Kubernetes Secret, never in Helm values or logs.
 if not existing:
  secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':SECRET,'namespace':ns,'labels':{'app.kubernetes.io/managed-by':'k3s-lab-dashboard'}},'type':'Opaque','stringData':{'username':'admin','password':password,'users':hashed}}
  result=subprocess.run(k+['create','-f','-'],input=json.dumps(secret),capture_output=True,text=True)
  if result.returncode:raise ValueError('Не удалось сохранить пароль панели в Secret')
 with tempfile.TemporaryDirectory() as tmp:
  path=Path(tmp)/'values.json';path.write_text(json.dumps(values));path.chmod(0o600)
  result=subprocess.run([h,'upgrade',release,'traefik','--repo','https://traefik.github.io/charts','--version',match[1]]+scope+['--reuse-values','--values',str(path),'--wait','--timeout','5m'],timeout=360)
  if result.returncode:raise ValueError('Обновление Traefik не завершено; проверьте журнал и Pods')
 print('Публичная панель: '+url+' · логин и пароль доступны в интерфейсе платформы.',flush=True)
