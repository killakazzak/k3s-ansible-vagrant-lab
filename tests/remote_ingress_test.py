import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import remote_ingress as ingress
import remote_clusters
class RemoteIngressTests(unittest.TestCase):
 def test_scope(self):
  remote_clusters.permit('/api/action',{'action':'remote_ingress_install'})
  with self.assertRaises(ValueError):remote_clusters.permit('/api/action',{'action':'stand_stop'})
  with patch.object(remote_clusters,'external',return_value=False):
   with self.assertRaises(ValueError):ingress.preview(Path('/repo'),{},Path('/local'),{'controller':'nginx'})
 def test_local_client_uses_local_kubeconfig(self):
  with patch.object(Path,'is_file',return_value=True),patch.object(remote_clusters,'binary',return_value='kubectl'):
   self.assertIn('--kubeconfig=/local/kubeconfig',ingress.client(Path('/repo'),{},Path('/local')))
 def test_validate(self):
  for data in [{'controller':'unknown'},{'controller':'nginx','service':'HostPort'},{'controller':'nginx','version':'--debug'}]:
   with self.assertRaises(ValueError):ingress.validate(data)
 def test_isolation(self):
  for kind in ingress.CATALOG:
   c=ingress.validate({'controller':kind});v=ingress.values(c)
   self.assertEqual(c['name'],'lab-'+kind)
   if kind=='traefik':self.assertFalse(v['ingressClass']['isDefaultClass']);self.assertEqual(v['service']['spec']['type'],'NodePort')
   elif kind=='nginx':self.assertFalse(v['controller']['ingressClass']['setAsDefaultIngress']);self.assertFalse(v['controller']['enableCustomResources'])
   else:self.assertFalse(v['controller']['ingressClassResource']['default'])
 def test_conflict_prevents_download_or_mutation(self):
  with patch.object(Path,'is_file',return_value=True),patch.object(remote_clusters,'binary',return_value='kubectl'),patch.object(ingress,'helm',return_value='helm'),patch.object(ingress,'run',return_value=json.dumps({'items':[{'metadata':{'name':'lab-nginx'}}]})) as run:
   with self.assertRaisesRegex(ValueError,'уже существует'):ingress.preview(Path('/repo'),{},Path('/remote'),{'controller':'nginx'})
   self.assertEqual(run.call_count,1)
 def test_install_requires_pinned_version(self):
  with self.assertRaises(ValueError):ingress.install(Path('/repo'),{},Path('/remote'),{'controller':'nginx'})

class ControllerManagementTests(unittest.TestCase):
 def test_validation(self):
  for data in [dict(controller='nginx',service='LoadBalancer',policy='Local',replicas=0),dict(controller='nginx',service='HostPort',policy='Local',replicas=1),dict(controller='nginx',service='NodePort',policy='bad',replicas=1)]:
   with self.assertRaises(ValueError):ingress.validate_management(data)
  with self.assertRaises(ValueError):ingress.validate_management({'controller':'nginx'},True)
  self.assertEqual(ingress.validate_management({'controller':'nginx','confirmation':'УДАЛИТЬ'},True),'nginx')
 def test_inventory_association(self):
  meta={'name':'lab-nginx','uid':'uid','annotations':{'meta.helm.sh/release-name':'lab-nginx','meta.helm.sh/release-namespace':'lab-ingress-nginx'}}
  labels={'app.kubernetes.io/instance':'lab-nginx'}
  resources=[{'items':[{'metadata':meta,'spec':{'controller':'nginx.org/ingress-controller'}},{'metadata':{'name':'other','uid':'other'},'spec':{'controller':'other'}}]}, {'items':[{'metadata':{'name':'nginx','namespace':'lab-ingress-nginx','labels':labels},'spec':{'type':'LoadBalancer','ports':[{'port':80}]},'status':{'loadBalancer':{'ingress':[{'ip':'1.2.3.4'}]}}}]}, {'items':[{'kind':'Deployment','metadata':{'name':'lab-nginx-controller','namespace':'lab-ingress-nginx','labels':labels},'spec':{'replicas':2},'status':{'readyReplicas':1}}]}, {'items':[{'metadata':{'namespace':'dev','name':'web'},'spec':{'ingressClassName':'lab-nginx'}}]}]
  with patch.object(ingress,'client',return_value=['kubectl']),patch.object(ingress,'run',side_effect=[json.dumps(r) for r in resources]):
   rows=ingress.inventory(Path('/repo'),{},Path('/root'))
  self.assertTrue(rows[0]['managed']);self.assertEqual(rows[0]['addresses'],['1.2.3.4']);self.assertEqual(rows[0]['routes'],['dev/web']);self.assertEqual(rows[0]['ready'],1);self.assertFalse(rows[1]['managed'])
 def test_stale_or_unmanaged_cannot_mutate(self):
  data={'controller':'nginx','confirmation':'УДАЛИТЬ','uid':'old'}
  for current in ({'name':'lab-nginx','managed':False},{'name':'lab-nginx','managed':True,'uid':'new'}):
   with patch.object(ingress,'inventory',return_value=[current]),patch.object(ingress.subprocess,'run') as execute:
    with self.assertRaises(ValueError):ingress.manage(Path('/repo'),{},Path('/root'),data,True)
    execute.assert_not_called()
 def test_update_preserves_chart_and_values(self):
  data={'controller':'nginx','uid':'same','service':'LoadBalancer','policy':'Cluster','replicas':2}
  current={'name':'lab-nginx','managed':True,'uid':'same','namespace':'lab-ingress-nginx','release':'lab-nginx'}
  def execute(command,**kwargs):
   if 'upgrade' in command:
    values=json.loads(Path(command[command.index('--values')+1]).read_text());self.assertEqual(values['controller']['replicaCount'],2);self.assertEqual(values['controller']['service']['type'],'LoadBalancer');self.assertIn('--reuse-values',command);self.assertEqual(command[command.index('--version')+1],'2.7.3')
   from types import SimpleNamespace
   return SimpleNamespace(returncode=0)
  with patch.object(ingress,'inventory',return_value=[current]),patch.object(ingress,'helm',return_value='helm'),patch.object(ingress,'run',return_value=json.dumps([{'name':'lab-nginx','chart':'nginx-ingress-2.7.3','status':'deployed'}])),patch.object(ingress.subprocess,'run',side_effect=execute) as run:
   ingress.manage(Path('/repo'),{},Path('/root'),data);self.assertEqual(run.call_count,1)
