"""Explicit, previewed Rancher installation in an existing cluster."""
import json,re,subprocess,tempfile
from pathlib import Path
import remote_ingress as ingress
import lab_apps
RANCHER_REPO='https://releases.rancher.com/server-charts/stable'
CERT_REPO='https://charts.jetstack.io'

def validate(data):
 host=data.get('host','')
 if not isinstance(host,str):raise ValueError('Hostname must be a string')
 host=host.strip().lower()
 if not isinstance(host,str) or '.' not in host or len(host)>253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in host.split('.')):raise ValueError('Укажите полный hostname Rancher без http:// и пути')
 cls=lab_apps.resource_class(data.get('ingress_class',''))
 if not cls:raise ValueError('Выберите Ingress-контроллер')
 replicas=int(data.get('replicas',1))
 if not 1<=replicas<=3:raise ValueError('Допустимо от 1 до 3 реплик')
 return dict(host=host,ingress_class=cls,replicas=replicas)

def version(h,chart,repo):
 metadata=ingress.run([h,'show','chart',chart,'--repo',repo],60)
 match=re.search(r'^version:\s*[\"\']?(v?\d+\.\d+\.\d+(?:[-+][\w.-]+)?)',metadata,re.M)
 if not match:raise ValueError('Не удалось определить версию '+chart)
 return match[1]

def status(repo,env,root):
 k=ingress.client(repo,env,root)
 def find(kind,name,ns):
  out=ingress.run(k+['get',kind,name,'-n',ns,'--ignore-not-found','-o','json'],20)
  return json.loads(out) if out.strip() else {}
 deploy=find('deployment','rancher','cattle-system');route=find('ingress','rancher','cattle-system')
 host=next((r.get('host') for r in route.get('spec',{}).get('rules',[]) if r.get('host')),None)
 return dict(installed=bool(deploy),ready=deploy.get('status',{}).get('readyReplicas',0),replicas=deploy.get('spec',{}).get('replicas',0),url='https://'+host+'/' if host else None)

def preview(repo,env,root,data):
 c=validate(data);k=ingress.client(repo,env,root);h=ingress.helm(repo)
 releases=json.loads(ingress.run([h,'list','--all','--all-namespaces','--kubeconfig',str(root/'kubeconfig'),'-o','json']))
 if any(r['name']=='rancher' and r['namespace']=='cattle-system' for r in releases) or status(repo,env,root)['installed']:raise ValueError('Rancher уже установлен или существует незавершённый Helm release. Повторная установка отменена.')
 ingress.run(k+['get','ingressclass',c['ingress_class'],'-o','name'])
 endpoint=lab_apps.Apps(root,env).publication_endpoints().get(c['ingress_class'],{})
 if endpoint.get('type')!='LoadBalancer' or not endpoint.get('addresses'):raise ValueError('Rancher requires an ingress LoadBalancer with an assigned external address')
 cert=json.loads(ingress.run(k+['get','deployments','--all-namespaces','-o','json']))['items']
 existing=next((d for d in cert if d['metadata']['name']=='cert-manager' and d['metadata'].get('labels',{}).get('app.kubernetes.io/name')=='cert-manager'),None)
 cert_release=any(r['name']=='cert-manager' for r in releases)
 if existing:
  if existing.get('status',{}).get('availableReplicas',0)<1:raise ValueError('Существующий cert-manager не готов')
  ingress.run(k+['get','crd','certificates.cert-manager.io','issuers.cert-manager.io','-o','name'])
 elif cert_release:raise ValueError('Существует Helm release cert-manager, но готовый Deployment не найден')
 c.update(version=version(h,'rancher',RANCHER_REPO),cert_version=None if existing else version(h,'cert-manager',CERT_REPO),install_cert=not bool(existing))
 return c

def install(repo,env,root,data):
 # Recheck immediately before mutation; never silently change reviewed versions.
 plan=preview(repo,env,root,data)
 if any(plan.get(key)!=data.get(key) for key in ('version','cert_version','install_cert')):raise ValueError('Версии или состояние cert-manager изменились. Повторите предварительную проверку.')
 h=ingress.helm(repo);scope=['--kubeconfig',str(root/'kubeconfig')]
 def execute(args):
  result=subprocess.run([h]+args+scope,timeout=660)
  if result.returncode:raise ValueError('Установка не завершена. Ресурсы сохранены; проверьте журнал и Pods.')
 if plan['install_cert']:
  print('Установка cert-manager '+plan['cert_version']+' из '+CERT_REPO,flush=True)
  execute(['install','cert-manager','cert-manager','--repo',CERT_REPO,'--version',plan['cert_version'],'--namespace','cert-manager','--create-namespace','--set','crds.enabled=true','--wait','--timeout','10m'])
 values=dict(hostname=plan['host'],replicas=plan['replicas'],ingress=dict(ingressClassName=plan['ingress_class'],tls=dict(source='rancher')),agentTLSMode='strict',resources=dict(requests=dict(cpu='500m',memory='1Gi'),limits=dict(memory='2Gi')))
 print('Установка Rancher '+plan['version']+' из '+RANCHER_REPO,flush=True)
 with tempfile.TemporaryDirectory() as tmp:
  path=Path(tmp)/'values.json';path.write_text(json.dumps(values))
  execute(['install','rancher','rancher','--repo',RANCHER_REPO,'--version',plan['version'],'--namespace','cattle-system','--create-namespace','--values',str(path),'--wait','--timeout','10m'])
 k=ingress.client(repo,env,root)
 ingress.run(k+['wait','-n','cattle-system','--for=condition=Ready','certificate/tls-rancher-ingress','--timeout=120s'],135)
 print('Rancher установлен: https://'+plan['host']+'/ · начальный пароль доступен по кнопке в интерфейсе.',flush=True)
