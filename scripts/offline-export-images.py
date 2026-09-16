import pathlib,subprocess,json,shlex,sys,tarfile,shutil
r=pathlib.Path(__file__).resolve().parents[1];out=r/'vendor/offline';sys.path.insert(0,str(r/'web'));import lab_apps
import argparse,tempfile,atexit
parser=argparse.ArgumentParser();parser.add_argument('--cluster',required=True);parser.add_argument('--master',required=True);args=parser.parse_args()
root=pathlib.Path(args.cluster).resolve()
config=tempfile.NamedTemporaryFile(prefix='offline-ssh-',delete=False);config.close();atexit.register(lambda:pathlib.Path(config.name).unlink(missing_ok=True))
with open(config.name,'w') as f:subprocess.run(['vagrant','ssh-config'],cwd=root,stdout=f,check=True)
ssh=['ssh','-F',config.name,'-T',args.master]
pods=json.loads(subprocess.check_output([str(root/'kubectl.sh'),'get','pods','-A','-o','json']))['items']
images={c['image'] for p in pods for c in p['spec'].get('containers',[])+p['spec'].get('initContainers',[])}
images.update(v['image'] for v in lab_apps.CATALOG.values() if v['image'])
images.add(lab_apps.catalog_services.DATABASE_IMAGE)
images.update(lab_apps.elk_stack.images().values())
images.update(lab_apps.argocd_bundle.images())
images.add(lab_apps.catalog_services.loki_stack.ALLOY_IMAGE)
images.update(['alpine:3.22','registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:x86_64-v19.3.2','registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:arm64-v19.3.2'])
images.add('zabbix/zabbix-web-nginx-pgsql:'+lab_apps.CATALOG['zabbix']['image'].rsplit(':',1)[1])
# Fixed panel and verification images used by the catalogue.
images.update(['dpage/pgadmin4:9.17','redis/redisinsight:2.70.0','tchiotludo/akhq:0.25.1','python:3.13-alpine','nginx:1.28-alpine','busybox:1.37'])
def canonical(image):
 if '/' not in image:return 'docker.io/library/'+image
 if '.' not in image.split('/')[0] and ':' not in image.split('/')[0]:return 'docker.io/'+image
 return image
images={canonical(i) for i in images}
images.update(['quay.io/jetstack/cert-manager-startupapicheck:v1.21.1','docker.io/rancher/kuberlr-kubectl:v8.1.1'])
previous=(out/'images/list.txt').read_text().splitlines() if (out/'images/list.txt').exists() else []
images=previous+sorted(images-set(previous))
cached={}
for line in pathlib.Path(config.name).read_text().splitlines():
 if not line.startswith('Host '):continue
 node=line.split()[1]
 try:
  names=subprocess.check_output(['ssh','-F',config.name,'-o','ConnectTimeout=5','-T',node,'sudo k3s ctr images list -q'],text=True,timeout=15).splitlines()
  cached.update({name:node for name in names})
 except subprocess.SubprocessError:pass
(out/'images/list.txt').write_text('\n'.join(images)+'\n')
def export_one(pair):
 i,image=pair
 path=out/'images'/('catalog-%03d.tar'%i)
 if path.exists():return
 target=['ssh','-F',config.name,'-T',cached.get(image,args.master)]
 print('Image',i+1,'/',len(images),image,flush=True)
 if image not in cached:subprocess.run(target+['sudo timeout 600 k3s ctr images pull --platform linux/arm64 '+shlex.quote(image)],check=True,stdout=subprocess.DEVNULL,timeout=620)
 with path.with_suffix('.part').open('wb') as f:subprocess.run(target+['sudo k3s ctr images export --platform linux/arm64 - '+shlex.quote(image)],check=True,stdout=f)
 path.with_suffix('.part').rename(path)
import concurrent.futures
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 for result in pool.map(export_one,sorted(enumerate(images),key=lambda pair:pair[1] not in cached)):pass
for name in ['k3s-arm64','install.sh']:shutil.copy2(r/'.cache/v1.36.4+k3s1'/name,out/'k3s'/name)
shutil.copy2(r/'.tools/kubectl',out/'kubectl');shutil.copy2(r/'.tools/kubectl.sha256',out/'kubectl.sha256');print('Export complete',flush=True)
