"""Companion management UIs for catalogue workloads."""
import base64,hashlib,json,secrets
IMAGES={'postgres':('dpage/pgadmin4:9.17',80,'pgAdmin'),'redis':('redis/redisinsight:2.70.0',5540,'Redis Insight'),'kafka':('tchiotludo/akhq:0.25.1',8080,'AKHQ')}
def build(c,host,manager):
 kind=c['type']
 if kind not in IMAGES:return []
 name=c['name']+'-ui';ns=c['namespace'];image,port,title=IMAGES[kind];password=secrets.token_urlsafe(24);user='admin@example.com' if kind=='postgres' else 'admin'
 labels={'app.kubernetes.io/managed-by':manager,'lab.k3s/panel-for':c['name']}
 def obj(api,k,n=name,**extra):return dict(apiVersion=api,kind=k,metadata=dict(name=n,namespace=ns,labels=labels),**extra)
 credential=obj('v1','Secret',name+'-auth',type='Opaque',stringData={'username':user,'password':password,'url':'http://'+host+'/','title':title})
 env=[];volumes=[];mounts=[];dns=c['name']+'.'+ns+'.svc.cluster.local'
 if kind=='postgres':
  env=[{'name':'PGADMIN_DEFAULT_EMAIL','value':user},{'name':'PGADMIN_DEFAULT_PASSWORD','valueFrom':{'secretKeyRef':{'name':name+'-auth','key':'password'}}}]
  servers={'Servers':{'1':{'Name':c['name'],'Group':'Lab','Host':dns,'Port':5432,'MaintenanceDB':'app','Username':'app','SSLMode':'prefer'}}}
  config=obj('v1','ConfigMap',data={'servers.json':json.dumps(servers)})
  volumes=[{'name':'config','configMap':{'name':name}},{'name':'data','emptyDir':{}}];mounts=[{'name':'config','mountPath':'/pgadmin4/servers.json','subPath':'servers.json'},{'name':'data','mountPath':'/var/lib/pgadmin'}]
 elif kind=='redis':
  env=[{'name':'RI_REDIS_HOST','value':dns},{'name':'RI_REDIS_PORT','value':'6379'},{'name':'RI_REDIS_ALIAS','value':c['name']}];config=None
  volumes=[{'name':'data','emptyDir':{}}];mounts=[{'name':'data','mountPath':'/data'}]
 else:
  config=None;env=[{'name':'AKHQ_CONFIGURATION','value':json.dumps({'akhq':{'connections':{'lab':{'properties':{'bootstrap.servers':dns+':9092'}}}}})}]
 container=dict(name='ui',image=image,ports=[{'name':'http','containerPort':port}],env=env,volumeMounts=mounts,resources={'requests':{'cpu':'100m','memory':'256Mi'},'limits':{'cpu':'1000m','memory':'1Gi'}},readinessProbe={'tcpSocket':{'port':'http'},'periodSeconds':5})
 pod={'containers':[container],'volumes':volumes,'enableServiceLinks':False}
 if kind=='postgres':pod['securityContext']={'fsGroup':5050}
 if kind=='redis':pod['securityContext']={'fsGroup':1000}
 workload=obj('apps/v1','Deployment',spec={'replicas':1,'selector':{'matchLabels':{'lab.k3s/panel':name}},'template':{'metadata':{'labels':dict(labels,**{'lab.k3s/panel':name})},'spec':pod}})
 service=obj('v1','Service',spec={'selector':{'lab.k3s/panel':name},'ports':[{'port':port,'targetPort':'http'}]})
 ingress=obj('networking.k8s.io/v1','Ingress',spec={'ingressClassName':'traefik','rules':[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':name,'port':{'number':port}}}}]}}]})
 ingress['metadata']['annotations']={'traefik.ingress.kubernetes.io/router.entrypoints':'web'}
 result=[credential,workload,service,ingress]+([config] if config else [])
 if kind!='postgres':
  auth=user+':{SHA}'+base64.b64encode(hashlib.sha1(password.encode()).digest()).decode()
  result.extend([obj('v1','Secret',name+'-http-auth',type='Opaque',stringData={'users':auth}),obj('traefik.io/v1alpha1','Middleware',spec={'basicAuth':{'secret':name+'-http-auth'}})])
  ingress['metadata']['annotations']['traefik.ingress.kubernetes.io/router.middlewares']=ns+'-'+name+'@kubernetescrd'
 return result
