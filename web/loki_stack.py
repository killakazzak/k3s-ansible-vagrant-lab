"""Single-node Loki, Grafana and namespace-scoped Alloy log collection."""
import json
IMAGE='grafana/loki:3.7.7'
ALLOY_IMAGE='grafana/alloy:v1.19.2'
GRAFANA_IMAGE='grafana/grafana:13.2.2'
def configure(c,host,pod,main,obj):
 name,ns=c['name'],c['namespace'];secret=c['storage_secret'] or name+'-auth'
 def resources(cpu,mem):return {'requests':{'cpu':str(cpu)+'m','memory':str(mem)+'Mi'},'limits':{'cpu':str(cpu*2)+'m','memory':str(mem*2)+'Mi'}}
 def password(n):return {'name':n,'valueFrom':{'secretKeyRef':{'name':secret,'key':'password'}}}
 def mount(n,p,sub=None):
  x={'name':n,'mountPath':p}
  if sub:x['subPath']=sub
  return x
 config={'auth_enabled':False,'server':{'http_listen_port':3100},'common':{'instance_addr':'127.0.0.1','path_prefix':'/loki','storage':{'filesystem':{'chunks_directory':'/loki/chunks','rules_directory':'/loki/rules'}},'replication_factor':1,'ring':{'kvstore':{'store':'inmemory'}}},'schema_config':{'configs':[{'from':'2024-01-01','store':'tsdb','object_store':'filesystem','schema':'v13','index':{'prefix':'index_','period':'24h'}}]},'compactor':{'working_directory':'/loki/compactor','retention_enabled':True,'delete_request_store':'filesystem'},'limits_config':{'retention_period':'168h'},'analytics':{'reporting_enabled':False}}
 alloy='''discovery.kubernetes "pods" {
 role = "pod"
 namespaces { names = ["NAMESPACE"] }
}
discovery.relabel "pods" {
 targets = discovery.kubernetes.pods.targets
 rule {
  source_labels = ["__meta_kubernetes_namespace"]
  target_label = "namespace"
 }
 rule {
  source_labels = ["__meta_kubernetes_pod_name"]
  target_label = "pod"
 }
 rule {
  source_labels = ["__meta_kubernetes_pod_container_name"]
  target_label = "container"
 }
 rule {
  source_labels = ["__meta_kubernetes_pod_container_name"]
  regex = "alloy"
  action = "drop"
 }
}
loki.source.kubernetes "pods" {
 targets = discovery.relabel.pods.output
 forward_to = [loki.write.local.receiver]
}
loki.write "local" {
 endpoint { url = "http://127.0.0.1:3100/loki/api/v1/push" }
}
'''.replace('NAMESPACE',ns)
 datasource={'apiVersion':1,'datasources':[{'name':'Loki','uid':'loki','type':'loki','access':'proxy','url':'http://127.0.0.1:3100','isDefault':True,'editable':False}]}
 pod['securityContext']={'fsGroup':10001,'fsGroupChangePolicy':'OnRootMismatch'}
 pod['serviceAccountName']=name+'-logs';pod['automountServiceAccountToken']=True
 pod.setdefault('volumes',[]).append({'name':'config','configMap':{'name':name+'-config'}})
 # Mount separate directories through environment paths; no privileged init container.
 main['args']=['-config.file=/etc/loki/config.json']
 main['volumeMounts']=[mount('data','/loki'),mount('config','/etc/loki/config.json','loki.json')]
 main['readinessProbe']={'httpGet':{'path':'/ready','port':'app'},'periodSeconds':5,'timeoutSeconds':3}
 grafana={'name':'grafana','image':GRAFANA_IMAGE,'ports':[{'name':'grafana','containerPort':3000}],'resources':resources(100,256),'env':[{'name':'GF_PATHS_DATA','value':'/data/grafana'},{'name':'GF_SECURITY_ADMIN_USER','value':'admin'},password('GF_SECURITY_ADMIN_PASSWORD'),password('GF_SECURITY_SECRET_KEY'),{'name':'GF_SERVER_ROOT_URL','value':'http://'+host+'/'}],'volumeMounts':[mount('data','/data'),mount('config','/etc/grafana/provisioning/datasources/loki.yaml','datasources.json')],'readinessProbe':{'httpGet':{'path':'/api/health','port':'grafana'},'periodSeconds':5}}
 agent={'name':'alloy','image':ALLOY_IMAGE,'args':['run','--storage.path=/data/alloy','/etc/alloy/config.alloy'],'resources':resources(100,256),'volumeMounts':[mount('data','/data'),mount('config','/etc/alloy/config.alloy','config.alloy')],'readinessProbe':{'httpGet':{'path':'/-/ready','port':12345},'periodSeconds':5},'securityContext':{'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True}}
 agent['args'].insert(1,'--server.http.listen-addr=0.0.0.0:12345')
 for container in (grafana,agent):container['startupProbe']=dict(container['readinessProbe'],failureThreshold=60)
 pod['containers'].extend([grafana,agent])
 return [obj('v1','ConfigMap',name+'-config',data={'loki.json':json.dumps(config),'datasources.json':json.dumps(datasource),'config.alloy':alloy}),obj('v1','ServiceAccount',name+'-logs'),obj('rbac.authorization.k8s.io/v1','Role',name+'-logs',rules=[{'apiGroups':[''],'resources':['pods','pods/log'],'verbs':['get','list','watch']}]),obj('rbac.authorization.k8s.io/v1','RoleBinding',name+'-logs',roleRef={'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':name+'-logs'},subjects=[{'kind':'ServiceAccount','name':name+'-logs','namespace':ns}])]
