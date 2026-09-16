import sys,unittest,copy
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import app_editor as editor
import lab_apps as lab
class AppEditorTests(unittest.TestCase):
 def setUp(self):
  self.obj={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'web','namespace':'dev','uid':'app-uid','resourceVersion':'12','labels':{'app.kubernetes.io/managed-by':lab.MANAGER,'lab.k3s/type':'nginx'}},'spec':{'replicas':1,'template':{'spec':{'containers':[{'name':'nginx','image':'nginx:1.30.4-alpine','resources':{'requests':{'cpu':'100m','memory':'128Mi'},'limits':{'cpu':'200m','memory':'256Mi'}}}]}}}}
  self.apps=Mock();self.apps.find.return_value=None
  self.apps.get.side_effect=lambda resource,*args:copy.deepcopy(self.obj) if resource=='Deployment' else {'spec':{'ports':[{'port':80}]}} if resource=='service' else {'items':[{'metadata':{'name':'lab-nginx'}}]} if resource=='ingressclasses' else {'items':[]}
  self.data=dict(name='web',namespace='dev',kind='Deployment',resource_version='12',image='nginx:1.30.4-alpine',replicas=1,cpu=100,memory=128,cpu_limit=200,memory_limit=256,publication='ingress',host='web.example.org',ingress_class='lab-nginx',service_port=80)
 def test_new_publication_and_preserve_volume_spec(self):
  _,p,_,route=editor.prepare(self.apps,self.data)
  self.assertEqual(route['spec']['ingressClassName'],'lab-nginx');self.assertEqual(route['metadata']['ownerReferences'][0]['uid'],'app-uid');self.assertNotIn('volumes',p['spec']['template']['spec']);self.assertNotIn('volumeClaimTemplates',p['spec'])
 def test_foreign_workload_denied(self):
  self.obj['metadata']['labels']={}
  with self.assertRaises(ValueError):editor.prepare(self.apps,self.data)
  self.apps.kubectl.assert_not_called()
 def test_stale_resource_denied(self):
  self.data['resource_version']='11'
  with self.assertRaisesRegex(ValueError,'изменилось'):editor.prepare(self.apps,self.data)
 def test_foreign_ingress_denied(self):
  self.apps.find.return_value={'metadata':{'name':'web','labels':{}},'spec':{'rules':[{'host':'web.example.org'}]}}
  with self.assertRaises(ValueError):editor.prepare(self.apps,self.data)
 def test_bad_limits(self):
  self.data['cpu_limit']=50
  with self.assertRaises(ValueError):editor.prepare(self.apps,self.data)
 def test_admission_failure_does_not_apply(self):
  self.apps.kubectl.side_effect=ValueError('quota exceeded')
  with self.assertRaises(ValueError):editor.edit(self.apps,self.data)
  self.assertEqual(self.apps.kubectl.call_count,1);self.assertIn('--dry-run=server',self.apps.kubectl.call_args.args[0]);self.apps.apply.assert_not_called()
 def test_internal_removes_only_owned_ingress(self):
  self.data['publication']='internal';self.apps.find.return_value={'metadata':{'name':'web','uid':'ingress-uid','resourceVersion':'4','labels':{'app.kubernetes.io/managed-by':lab.MANAGER}},'spec':{'rules':[{'host':'web.example.org'}]}}
  editor.edit(self.apps,self.data)
  delete=[c for c in self.apps.kubectl.call_args_list if '--raw=' in ' '.join(c.args[0])][0]
  self.assertEqual(delete.args[1]['preconditions'],{'uid':'ingress-uid','resourceVersion':'4'})

 def test_existing_ingress_update_preserves_version_and_unrelated_fields(self):
  _,_,_,route=editor.prepare(self.apps,self.data)
  route['metadata'].update(uid='route-uid',resourceVersion='7',annotations={'custom.example/note':'keep'})
  route['metadata']['managedFields']=[{'manager':'kubectl-patch'}]
  route['spec']['rules'][0]['host']='old.example.org'
  self.apps.find.return_value=route
  editor.edit(self.apps,self.data)
  replacements=[c for c in self.apps.kubectl.call_args_list if c.args[0][0]=='replace']
  self.assertEqual(len(replacements),2)
  self.assertIn('--dry-run=server',replacements[0].args[0])
  desired=replacements[1].args[1]
  self.assertEqual(desired['metadata']['resourceVersion'],'7')
  self.assertEqual(desired['metadata']['annotations']['custom.example/note'],'keep')
  self.assertNotIn('managedFields',desired['metadata'])
  self.assertEqual(desired['spec']['rules'][0]['host'],'web.example.org')
  self.apps.apply.assert_not_called()
 def test_new_ingress_is_created_without_overwriting_existing(self):
  editor.edit(self.apps,self.data)
  commands=[c.args[0] for c in self.apps.kubectl.call_args_list if c.args[0][0]=='create']
  self.assertEqual(len(commands),2)
  self.assertIn('--dry-run=server',commands[0])
