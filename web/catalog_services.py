"""Persistent single-replica development services with pinned official images."""
import json
import elk_stack
import loki_stack
import argocd_bundle
import gitlab_apps
CATALOG={
 'loki':dict(image=loki_stack.IMAGE,port=3100,memory=512,cpu=250,storage=10),
 'argocd':dict(image=argocd_bundle.IMAGE,port=8080,memory=256,cpu=100),
 'elk':dict(image=elk_stack.images()['elasticsearch'],port=9200,memory=2048,cpu=1000,storage=10),
 'grafana':dict(image='grafana/grafana:13.2.2',port=3000,memory=256,cpu=100),
 'prometheus':dict(image='prom/prometheus:v3.14.0',port=9090,memory=512,cpu=250),
 'zabbix':dict(image='zabbix/zabbix-server-pgsql:alpine-7.4.14',port=10051,memory=512,cpu=250),
 'keycloak':dict(image='quay.io/keycloak/keycloak:26.7.3',port=8080,memory=1024,cpu=500),
}
CATALOG.update(gitlab_apps.CATALOG)
AUTH_TYPES=('loki','elk','grafana','zabbix','keycloak')
DATABASE_IMAGE='postgres:18.6-alpine'

def build(c,host,manager):
 if c['type'] in gitlab_apps.TYPES:return gitlab_apps.build(c,manager)
 if c['type']=='argocd':return argocd_bundle.build(c,host,manager)
 name,ns,kind=c['name'],c['namespace'],c['type'];secret=c['storage_secret'] or name+'-auth'
 labels={'app.kubernetes.io/managed-by':manager,'app.kubernetes.io/name':name,'lab.k3s/type':kind}
 selector={'lab.k3s/app':name}
 def obj(api,k,n=None,**kw):return dict(apiVersion=api,kind=k,metadata=dict(name=n or name,namespace=ns,labels=labels.copy()),**kw)
 def env(key,value):return dict(name=key,value=value)
 def password(key):return dict(name=key,valueFrom={'secretKeyRef':{'name':secret,'key':'password'}})
 def resources(cpu,memory):return {'requests':{'cpu':str(cpu)+'m','memory':str(memory)+'Mi'},'limits':{'cpu':str(cpu*2)+'m','memory':str(memory*2)+'Mi'}}
 def http(path,port):return {'httpGet':{'path':path,'port':port},'periodSeconds':5,'timeoutSeconds':3}
 main=dict(name=kind,image=c['image'],ports=[dict(name='app',containerPort=c['port'])],resources=resources(c['cpu'],c['memory']))
 pod={'containers':[main],'enableServiceLinks':False,'automountServiceAccountToken':False,'terminationGracePeriodSeconds':60}
 workload=obj('apps/v1','StatefulSet',spec={'serviceName':name+'-headless','replicas':1,'selector':{'matchLabels':selector},'template':{'metadata':{'labels':dict(labels,**selector)},'spec':pod}})
 if c['storage_mode']=='existing':
  pod['volumes']=[{'name':'data','persistentVolumeClaim':{'claimName':c['pvc']}}]
  workload['metadata']['annotations']={'lab.k3s/external-pvc':c['pvc']}
 else:workload['spec']['volumeClaimTemplates']=[{'metadata':{'name':'data'},'spec':{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':str(c['storage'])+'Gi'}}}}]
 objects=[workload]
 if kind in ('grafana','prometheus'):
  path='/var/lib/grafana' if kind=='grafana' else '/prometheus'
  main['volumeMounts']=[{'name':'data','mountPath':path}]
  pod['securityContext']={'fsGroup':472 if kind=='grafana' else 65534,'fsGroupChangePolicy':'OnRootMismatch'}
 if kind=='grafana':
  main['env']=[env('GF_SECURITY_ADMIN_USER','admin'),password('GF_SECURITY_ADMIN_PASSWORD'),password('GF_SECURITY_SECRET_KEY'),env('GF_USERS_ALLOW_SIGN_UP','false')]
  if host:main['env'].append(env('GF_SERVER_ROOT_URL','http://'+host+'/'))
  main['readinessProbe']=http('/api/health','app')
 if kind=='prometheus':
  config={'global':{'scrape_interval':'15s'},'scrape_configs':[{'job_name':'prometheus','static_configs':[{'targets':['localhost:9090']}]}]}
  objects.append(obj('v1','ConfigMap',name+'-config',data={'prometheus.yml':json.dumps(config)}))
  pod.setdefault('volumes',[]).append({'name':'config','configMap':{'name':name+'-config'}})
  main['volumeMounts'].append({'name':'config','mountPath':'/etc/prometheus','readOnly':True})
  main['args']=['--config.file=/etc/prometheus/prometheus.yml','--storage.tsdb.path=/prometheus','--storage.tsdb.retention.time=7d','--storage.tsdb.retention.size='+str(max(1,int(c['storage'])*700))+'MB']
  main['readinessProbe']=http('/-/ready','app')
 if kind in ('keycloak','zabbix'):
  db=dict(name='database',image=DATABASE_IMAGE,env=[env('POSTGRES_USER','app'),env('POSTGRES_DB','app'),password('POSTGRES_PASSWORD'),env('PGDATA','/var/lib/postgresql/18/docker')],volumeMounts=[{'name':'data','mountPath':'/var/lib/postgresql'}],resources=resources(100,256),readinessProbe={'exec':{'command':['pg_isready','-U','app','-d','app']},'periodSeconds':5})
  pod['containers'].append(db)
 if kind=='keycloak':
  main['args']=['start-dev','--http-enabled=true','--proxy-headers=xforwarded','--health-enabled=true','--cache=local']
  main['env']=[env('KC_DB','postgres'),env('KC_DB_URL','jdbc:postgresql://127.0.0.1:5432/app'),env('KC_DB_USERNAME','app'),password('KC_DB_PASSWORD'),env('KC_BOOTSTRAP_ADMIN_USERNAME','admin'),password('KC_BOOTSTRAP_ADMIN_PASSWORD'),env('KC_HOSTNAME','http://'+host)]
  main['ports'].append({'name':'health','containerPort':9000})
  main['readinessProbe']=http('/health/ready','health')
 if kind=='zabbix':
  db_env=[env('DB_SERVER_HOST','127.0.0.1'),env('POSTGRES_USER','app'),env('POSTGRES_DB','app'),password('POSTGRES_PASSWORD')]
  main['env']=db_env;main['readinessProbe']={'tcpSocket':{'port':'app'},'periodSeconds':5}
  tag=c['image'].rsplit(':',1)[1]
  web=dict(name='web',image='zabbix/zabbix-web-nginx-pgsql:'+tag,ports=[{'name':'web','containerPort':8080}],env=db_env+[env('ZBX_SERVER_HOST','127.0.0.1'),env('PHP_TZ','UTC')],resources=resources(100,256),readinessProbe=http('/','web'))
  pod['containers'].append(web)
 if kind=='loki':objects.extend(loki_stack.configure(c,host,pod,main,obj))
 if kind=='elk':objects.append(elk_stack.configure(c,host,pod,main,obj))
 main['startupProbe']=dict(main['readinessProbe'],failureThreshold=120)
 ports=[{'name':'app','port':c['port'],'targetPort':'app'}]
 if kind=='loki':ports.append({'name':'grafana','port':3000,'targetPort':'grafana'})
 if kind=='elk':ports.extend([{'name':'kibana','port':5601,'targetPort':'kibana'},{'name':'ingest','port':8080,'targetPort':'ingest'}])
 if kind=='zabbix':ports.append({'name':'web','port':8080,'targetPort':'web'})
 objects.extend([obj('v1','Service',spec={'selector':selector,'ports':ports}),obj('v1','Service',name+'-headless',spec={'clusterIP':'None','selector':selector,'ports':ports})])
 if host:
  ingress=obj('networking.k8s.io/v1','Ingress',spec={'ingressClassName':'traefik','rules':[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':name,'port':{'number':3000 if kind=='loki' else 5601 if kind=='elk' else 8080 if kind=='zabbix' else c['port']}}}}]}}]})
  ingress['metadata']['annotations']={'traefik.ingress.kubernetes.io/router.entrypoints':'web'};objects.append(ingress)
 return c,'StatefulSet',objects,host
