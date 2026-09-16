"""Authenticated, persistent ELK development bundle; one shared lifecycle."""
VERSION='9.5.4'
def images(version=VERSION):
 return {k:'docker.elastic.co/'+k+'/'+k+':'+version for k in ('elasticsearch','kibana','logstash')}
def configure(c,host,pod,main,obj):
 secret=c['storage_secret'] or c['name']+'-auth';version=c['image'].rsplit(':',1)[1];bundle=images(version)
 def env(n,v):return {'name':n,'value':v}
 def password(n):return {'name':n,'valueFrom':{'secretKeyRef':{'name':secret,'key':'password'}}}
 def mount(n,p,sub=None):
  x={'name':n,'mountPath':p}
  if sub:x['subPath']=sub
  return x
 def resources(cpu,mem):return {'requests':{'cpu':str(cpu)+'m','memory':str(mem)+'Mi'},'limits':{'cpu':str(cpu*2)+'m','memory':str(mem*2)+'Mi'}}
 pod['securityContext']={'runAsUser':1000,'runAsGroup':1000,'fsGroup':1000,'fsGroupChangePolicy':'OnRootMismatch'}
 pod.setdefault('volumes',[]).extend([{'name':'es-config','emptyDir':{}},{'name':'config','configMap':{'name':c['name']+'-config'}}])
 setup='''cp -R /usr/share/elasticsearch/config/. /work-config/
cp /bootstrap/roles.yml /work-config/roles.yml
mkdir -p /data/elasticsearch /data/kibana /data/logstash
export ES_PATH_CONF=/work-config
bin/elasticsearch-users useradd admin -p "$STACK_PASSWORD" -r superuser
bin/elasticsearch-users useradd lab_kibana -p "$STACK_PASSWORD" -r kibana_system
bin/elasticsearch-users useradd lab_logstash -p "$STACK_PASSWORD" -r lab_writer
'''
 pod['initContainers']=[{'name':'elk-setup','image':bundle['elasticsearch'],'command':['bash','-ec',setup],'env':[password('STACK_PASSWORD'),env('CLI_JAVA_OPTS','-Xms64m -Xmx128m')],'resources':resources(100,256),'volumeMounts':[mount('es-config','/work-config'),mount('config','/bootstrap'),mount('data','/data')]}]
 main['env']=[env('discovery.type','single-node'),env('xpack.security.enabled','true'),env('xpack.security.http.ssl.enabled','false'),env('xpack.security.transport.ssl.enabled','false'),env('xpack.security.enrollment.enabled','false'),env('node.store.allow_mmap','false'),env('ES_JAVA_OPTS','-Xms1g -Xmx1g'),password('ADMIN_PASSWORD')]
 main['volumeMounts']=[mount('es-config','/usr/share/elasticsearch/config'),mount('data','/usr/share/elasticsearch/data','elasticsearch')]
 main['readinessProbe']={'exec':{'command':['bash','-ec','curl -fsS -u "admin:$ADMIN_PASSWORD" "http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=1s" >/dev/null']},'periodSeconds':5,'timeoutSeconds':3}
 kibana={'name':'kibana','image':bundle['kibana'],'ports':[{'name':'kibana','containerPort':5601}],'resources':resources(250,1024),'env':[env('SERVER_HOST','0.0.0.0'),env('SERVER_PUBLICBASEURL','http://'+host),env('ELASTICSEARCH_HOSTS','["http://127.0.0.1:9200"]'),env('ELASTICSEARCH_USERNAME','lab_kibana'),password('ELASTICSEARCH_PASSWORD'),password('XPACK_SECURITY_ENCRYPTIONKEY'),password('XPACK_ENCRYPTEDSAVEDOBJECTS_ENCRYPTIONKEY'),password('XPACK_REPORTING_ENCRYPTIONKEY')],'volumeMounts':[mount('data','/usr/share/kibana/data','kibana')],'readinessProbe':{'httpGet':{'path':'/login','port':'kibana'},'periodSeconds':5,'timeoutSeconds':3}}
 pipeline='''input {
  http { port => 8080 codec => json user => "lab_ingest" password => "${STACK_PASSWORD}" }
}
output {
  elasticsearch {
    hosts => ["http://127.0.0.1:9200"]
    user => "lab_logstash"
    password => "${STACK_PASSWORD}"
    index => "lab-logs-%{+yyyy.MM.dd}"
    ilm_enabled => false
    data_stream => false
    manage_template => false
  }
}
'''
 logstash={'name':'logstash','image':bundle['logstash'],'ports':[{'name':'ingest','containerPort':8080}],'resources':resources(250,1024),'env':[password('STACK_PASSWORD'),env('LS_JAVA_OPTS','-Xms512m -Xmx512m')],'volumeMounts':[mount('data','/usr/share/logstash/data','logstash'),mount('config','/usr/share/logstash/pipeline/logstash.conf','pipeline.conf'),mount('config','/usr/share/logstash/config/logstash.yml','logstash.yml')],'readinessProbe':{'tcpSocket':{'port':'ingest'},'periodSeconds':5,'timeoutSeconds':3}}
 for sidecar in (kibana,logstash):sidecar['startupProbe']=dict(sidecar['readinessProbe'],failureThreshold=120)
 pod['containers'].extend([kibana,logstash])
 return obj('v1','ConfigMap',c['name']+'-config',data={'roles.yml':'lab_writer:\n  cluster: [monitor]\n  indices:\n    - names: ["lab-logs-*"]\n      privileges: [write, create_index, auto_configure]\n','pipeline.conf':pipeline,'logstash.yml':'api.http.host: "0.0.0.0"\npath.data: /usr/share/logstash/data\npipeline.workers: 1\nqueue.type: persisted\nqueue.max_bytes: 256mb\nxpack.monitoring.enabled: false\n'})

CHECK_SCRIPT='''import os,sys,json,time,uuid,base64,urllib.request,urllib.error
h=sys.argv[1];password=os.environ['STACK_PASSWORD']
def request(port,path,user='admin',data=None):
 auth=base64.b64encode((user+':'+password).encode()).decode()
 req=urllib.request.Request('http://'+h+':'+str(port)+path,data=data,headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=5) as r:return r.read()
request(9200,'/_cluster/health');request(5601,'/login')
marker=uuid.uuid4().hex
request(8080,'/','lab_ingest',json.dumps({'lab_probe':marker}).encode())
for attempt in range(25):
 try:
  result=json.loads(request(9200,'/lab-logs-*/_search',data=json.dumps({'query':{'match':{'lab_probe':marker}}}).encode()))
  if result['hits']['hits']:break
 except urllib.error.HTTPError as e:
  if e.code!=404:raise
 time.sleep(2)
else:raise RuntimeError('Logstash did not deliver the test event to Elasticsearch')
print('Elasticsearch, Kibana and Logstash pipeline OK')
'''
