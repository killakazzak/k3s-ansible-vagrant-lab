import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
import remote_clusters as remote
class RemoteAppsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'connection.json').write_text('{}');self.apps=lab.Apps(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_install_allowed_but_vm_operations_denied(self):
  for action in ('app_deploy','template_deploy'):remote.permit('/api/action',{'action':action})
  for action in ('destroy','stand_start','add_worker','app_rollback'):
   with self.assertRaises(ValueError):remote.permit('/api/action',{'action':action})
 def test_dotted_storage_class(self):
  self.assertEqual(lab.validate({'name':'db','storage_class':'fast2.ru-6'})['storage_class'],'fast2.ru-6')
 def test_no_vm_cache(self):
  with patch.object(lab.subprocess,'run') as run:self.apps.image_cache('restore');self.apps.image_cache('capture');run.assert_not_called()
 def test_internal_database_does_not_require_traefik(self):
  _,_,objects,host=self.apps.plan({'type':'postgres','name':'db','namespace':'dev','host':''})
  self.assertEqual(host,'');self.assertFalse(any(x['kind'] in ('Ingress','Middleware') for x in objects))
  self.assertTrue(any(x['kind']=='Service' for x in objects))
 def test_explicit_ingress_and_storage(self):
  with patch.object(self.apps,'find',return_value={'metadata':{'name':'lab-nginx'}}):
   c,_,objects,_=self.apps.plan({'type':'grafana','name':'dash','namespace':'dev','host':'dash.example.org','ingress_class':'lab-nginx','storage_class':'fast'})
  route=next(x for x in objects if x['kind']=='Ingress');self.assertEqual(route['spec']['ingressClassName'],'lab-nginx');self.assertFalse(route['metadata']['annotations'])
  workload=next(x for x in objects if x['kind']=='StatefulSet');self.assertEqual(workload['spec']['volumeClaimTemplates'][0]['spec']['storageClassName'],'fast')
 def test_no_default_storage_fails_before_creation(self):
  with patch.object(self.apps,'get',return_value={'items':[]}),patch.object(self.apps,'apply') as apply:
   with self.assertRaisesRegex(ValueError,'StorageClass'):self.apps.check_storage({'type':'postgres','name':'db','namespace':'dev'})
   apply.assert_not_called()

class PublicationTests(unittest.TestCase):
 def test_explicit_internal_clears_hostname(self):
  c=lab.validate({'name':'web','host':'web.example.org','publication':'internal'})
  self.assertEqual(c['host'],'')
 def test_ingress_requires_hostname(self):
  with self.assertRaises(ValueError):lab.validate({'name':'web','publication':'ingress'})
 def test_nodeport_discovery(self):
  apps=lab.Apps('/tmp')
  classes=[{'metadata':{'name':'lab-nginx','annotations':{'meta.helm.sh/release-name':'lab-nginx','meta.helm.sh/release-namespace':'lab-ingress-nginx'}}}]
  services=[{'metadata':{'namespace':'lab-ingress-nginx','labels':{'app.kubernetes.io/instance':'lab-nginx'}},'spec':{'type':'NodePort','ports':[{'port':80,'nodePort':30226}]}}]
  nodes=[{'status':{'addresses':[{'type':'InternalIP','address':'10.0.0.1'}]}}]
  with patch.object(apps,'get',side_effect=lambda key:{'items':{'ingressclasses':classes,'services':services,'nodes':nodes}[key]}):
   result=apps.publication_endpoints()['lab-nginx'];self.assertEqual(result['port'],30226);self.assertIn('10.0.0.1',result['hint'])

class RemoteDeleteTests(unittest.TestCase):
 def test_unmanaged_remote_workload_cannot_be_deleted(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'connection.json').write_text('{}');apps=lab.Apps(root)
   with patch.object(apps,'get',return_value={'metadata':{'labels':{}},'spec':{}}),patch.object(apps,'kubectl') as command:
    with self.assertRaises(ValueError):apps.delete({'kind':'Deployment','namespace':'dev','name':'other'})
    command.assert_not_called()
 def test_retention_and_owned_resources(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'connection.json').write_text('{}');apps=lab.Apps(root)
   labels={'app.kubernetes.io/managed-by':lab.MANAGER,'app.kubernetes.io/name':'db'}
   workload={'kind':'StatefulSet','metadata':{'name':'db','labels':labels},'spec':{'persistentVolumeClaimRetentionPolicy':{'whenDeleted':'Delete'},'template':{'spec':{'containers':[]}}}}
   objects=[{'kind':'Secret','metadata':{'name':'db-auth','labels':labels}},{'kind':'Service','metadata':{'name':'db','labels':labels}},{'kind':'Service','metadata':{'name':'other','labels':{'app.kubernetes.io/name':'other'}}}]
   with patch.object(apps,'get',side_effect=[workload,{'items':objects}]),patch.object(apps,'kubectl') as command:
    apps.delete({'kind':'StatefulSet','namespace':'dev','name':'db'})
    calls=[c.args[0] for c in command.call_args_list]
    self.assertEqual(calls[0][0],'patch');self.assertIn('Retain',calls[0][-1]);self.assertFalse(any('pvc' in c or 'db-auth' in c or 'other' in c for c in calls));self.assertTrue(any(c[:3]==['delete','Service','db'] for c in calls))

class ControllerAddressTests(unittest.TestCase):
 def test_distinct_load_balancer_addresses_and_pending(self):
  apps=lab.Apps('/tmp');classes=[];services=[]
  for kind,ip in [('nginx','135.106.157.33'),('traefik','135.106.146.140'),('haproxy',None)]:
   release='lab-'+kind;ns='lab-ingress-'+kind;owner={'meta.helm.sh/release-name':release,'meta.helm.sh/release-namespace':ns}
   classes.append({'metadata':{'name':release,'annotations':owner}})
   services.append({'metadata':{'namespace':ns,'annotations':owner,'labels':{'app.kubernetes.io/instance':release+'-'+ns}},'spec':{'type':'LoadBalancer','ports':[{'port':80}]},'status':{'loadBalancer':{'ingress':[{'ip':ip}] if ip else []}}})
  with patch.object(apps,'get',side_effect=lambda key:{'items':{'ingressclasses':classes,'services':services}[key]}):
   result=apps.publication_endpoints()
  self.assertEqual(result['lab-nginx']['ip'],'135.106.157.33')
  self.assertEqual(result['lab-traefik']['ip'],'135.106.146.140')
  self.assertEqual(result['lab-haproxy']['ip'],'')
  self.assertEqual(result['lab-traefik']['port'],80)
