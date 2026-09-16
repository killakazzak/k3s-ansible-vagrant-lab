import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
import catalog_services as services
class CatalogServicesTests(unittest.TestCase):
 def plan(self,kind,**values):
  return lab.Apps('/tmp').plan(dict(type=kind,name=kind,namespace='dev',host=kind+'.example.test',**values))
 def test_all_persistent_and_credential_references(self):
  for kind in (k for k in services.CATALOG if k not in ('argocd','gitlab-runner','gitlab-agent')):
   with self.subTest(kind=kind):
    c,k,objects,host=self.plan(kind);self.assertEqual(k,'StatefulSet')
    workload=next(o for o in objects if o['kind']==k);spec=workload['spec'];pod=spec['template']['spec']
    self.assertEqual(spec['replicas'],1);self.assertEqual(spec['volumeClaimTemplates'][0]['metadata']['name'],'data')
    self.assertEqual(len(pod['containers']),{'grafana':1,'prometheus':1,'keycloak':2,'zabbix':3,'elk':3,'loki':3}[kind])
    for container in pod['containers']:
     self.assertIn('readinessProbe',container);self.assertIn('requests',container['resources'])
     for env in container.get('env',[]):
      if env['name'].endswith('PASSWORD'):self.assertEqual(env['valueFrom']['secretKeyRef']['name'],kind+'-auth')
    if kind in ('zabbix','keycloak'):
     database=next(c for c in pod['containers'] if c['name']=='database');self.assertEqual(database['image'],services.DATABASE_IMAGE);self.assertEqual(database['volumeMounts'][0]['name'],'data')
    ingress=next(o for o in objects if o['kind']=='Ingress');port=ingress['spec']['rules'][0]['http']['paths'][0]['backend']['service']['port']['number']
    self.assertEqual(port,3000 if kind=='loki' else 5601 if kind=='elk' else 8080 if kind=='zabbix' else services.CATALOG[kind]['port'])
    service=next(o for o in objects if o['kind']=='Service' and o['metadata']['name']==kind);self.assertIn(port,[p['port'] for p in service['spec']['ports']])
 def test_existing_storage_uses_original_secret_without_claim_creation(self):
  for kind in (k for k in services.CATALOG if k not in ('argocd','gitlab-runner','gitlab-agent')):
   args=dict(storage_mode='existing',pvc='saved-data')
   if kind in services.AUTH_TYPES:args['storage_secret']='saved-auth'
   c,k,objects,_=self.plan(kind,**args);workload=next(o for o in objects if o['kind']==k);pod=workload['spec']['template']['spec']
   self.assertNotIn('volumeClaimTemplates',workload['spec']);self.assertFalse(any(o['kind']=='PersistentVolumeClaim' for o in objects))
   self.assertEqual(next(v for v in pod['volumes'] if v['name']=='data')['persistentVolumeClaim']['claimName'],'saved-data')
   for container in pod['containers']:
    for env in container.get('env',[]):
     if 'valueFrom' in env:self.assertEqual(env['valueFrom']['secretKeyRef']['name'],'saved-auth')
 def test_resource_budget_includes_database_and_web(self):
  for kind,expected in [('keycloak',1280),('zabbix',1024),('elk',4096),('loki',1024)]:
   plan=self.plan(kind);workload=next(o for o in plan[2] if o['kind']=='StatefulSet')
   self.assertEqual(lab.pod_budget(workload['spec']['template']['spec'])['memory'],expected*1024**2)
   app=lab.Apps('/tmp');node={'metadata':{'name':'worker'},'status':{'allocatable':{'cpu':'4','memory':str(expected-1)+'Mi'},'conditions':[{'type':'Ready','status':'True'}]}}
   with patch.object(app,'get',side_effect=[{'items':[node]},{'items':[]}]):
    with self.assertRaisesRegex(ValueError,'Проверка ресурсов'):app.check_capacity([plan])
 def test_template_round_trip_suites(self):
  for kind in ('keycloak','zabbix','elk'):
   c,k,objects,_=self.plan(kind);workload=next(o for o in objects if o['kind']==k);app=lab.Apps('/tmp')
   with patch.object(app,'get',side_effect=[workload,{'items':[]}]),patch.object(lab,'save_template') as save:
    app.template_from_apps({'name':'test','selected':[{'kind':k,'namespace':'dev','name':kind}]})
   captured=save.call_args.args[0]['apps'][0];self.assertEqual(captured['storage_mode'],'new');self.assertEqual(captured['storage_secret'],'');self.assertNotIn('env',captured)
   captured['host']=kind+'.example.test';new_plan=app.plan(captured);new_workload=next(o for o in new_plan[2] if o['kind']==k)
   self.assertEqual(len(new_workload['spec']['template']['spec']['containers']),len(workload['spec']['template']['spec']['containers']))
 def test_zabbix_upgrade_keeps_web_version_matched(self):
  _,_,objects,_=self.plan('zabbix');workload=next(o for o in objects if o['kind']=='StatefulSet');app=lab.Apps('/tmp')
  with patch.object(app,'get',return_value=workload),patch.object(app,'kubectl') as cmd,patch.object(app,'wait_rollout',return_value='Ready'):
   app.change(dict(namespace='dev',name='zabbix',kind='StatefulSet',container='zabbix',image='zabbix/zabbix-server-pgsql:alpine-7.4.14',replicas=1),'app_update')
   containers=json.loads(cmd.call_args.args[0][-1])['spec']['template']['spec']['containers'];self.assertEqual(containers[1]['image'],'zabbix/zabbix-web-nginx-pgsql:alpine-7.4.14')
 def test_reject_ephemeral_and_multiple_replicas_and_floating_images(self):
  for kind in (k for k in services.CATALOG if k not in ('argocd','gitlab-runner','gitlab-agent')):
   for changes in [dict(storage_mode='none'),dict(replicas=2),dict(image=services.CATALOG[kind]['image'].rsplit(':',1)[0]+':latest')]:
    with self.assertRaises(ValueError):self.plan(kind,**changes)
 def test_prometheus_configuration_and_retention(self):
  _,_,objects,_=self.plan('prometheus');config=next(o for o in objects if o['kind']=='ConfigMap');parsed=json.loads(config['data']['prometheus.yml'])
  self.assertEqual(parsed['scrape_configs'][0]['static_configs'][0]['targets'],['localhost:9090'])
  main=next(o for o in objects if o['kind']=='StatefulSet')['spec']['template']['spec']['containers'][0];self.assertIn('--storage.tsdb.retention.time=7d',main['args'])
if __name__=='__main__':unittest.main()
