import sys, unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
import template_storage as storage

class TemplateStorageTests(unittest.TestCase):
 def setUp(self):
  self.template={'name':'stand','apps':[lab.validate(dict(name='postgres',type='postgres',storage_mode='existing',pvc='old',storage_secret='old-auth'))]}
  p=patch.object(storage,'templates',return_value=[self.template]);p.start();self.addCleanup(p.stop)
 def test_default_is_new_and_template_is_unchanged(self):
  c=storage.configs(dict(template='stand',namespace='dev'))[0]
  self.assertEqual(c['storage_mode'],'new');self.assertEqual(c['pvc'],'');self.assertEqual(c['storage_secret'],'')
  self.assertEqual(self.template['apps'][0]['pvc'],'old')
 def test_explicit_restore(self):
  c=storage.configs(dict(template='stand',namespace='test',storage={'postgres':dict(name='restored',storage_mode='existing',pvc='saved',storage_secret='saved-auth')}))[0]
  self.assertEqual((c['name'],c['namespace'],c['pvc'],c['storage_secret']),('restored','test','saved','saved-auth'))
 def test_options_skip_retained_names_and_exclude_occupied_claim(self):
  app=Mock()
  pvc=lambda name:dict(kind='PersistentVolumeClaim',metadata=dict(name=name),status=dict(phase='Bound',capacity=dict(storage='2Gi')),spec={})
  app.get.side_effect=[{'items':[pvc('data-postgres-0'),pvc('busy'),dict(kind='Secret',metadata=dict(name='postgres-auth'),data=dict(password='DO-NOT-EXPOSE'))]}, {'items':[dict(spec=dict(volumes=[dict(persistentVolumeClaim=dict(claimName='busy'))]))]}]
  result=storage.options(app,dict(template='stand',namespace='dev'))
  self.assertEqual(result['names']['postgres'],'postgres-2');self.assertTrue(result['pvcs'][0]['available']);self.assertFalse(result['pvcs'][1]['available'])
  self.assertNotIn('DO-NOT-EXPOSE',str(result));app.apply.assert_not_called()
 def test_preview_is_read_only(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'find',return_value=None),patch.object(app,'get',return_value={'items':[]}),patch.object(app,'host',return_value=''),patch.object(app,'check_capacity'),patch.object(app,'apply') as apply:
   result=storage.preview(app,dict(template='stand',namespace='dev'))
  self.assertTrue(result['ok']);self.assertEqual(result['apps'][0]['pvc'],'data-postgres-0');apply.assert_not_called()
 def test_existing_password_is_required_and_busy_pvc_rejected(self):
  app=lab.Apps('/tmp');c=dict(name='pg',type='postgres',storage_mode='existing',pvc='saved',storage_secret='old-auth')
  pvc=dict(metadata={},spec={},status=dict(phase='Bound'))
  with patch.object(app,'host',return_value=''),patch.object(app,'find',side_effect=lambda kind,ns,name:pvc if kind=='pvc' else None),patch.object(app,'get',return_value={'items':[]}):
   with self.assertRaisesRegex(ValueError,'password'):app.preflight(c)
  with patch.object(app,'host',return_value=''),patch.object(app,'find',return_value=pvc),patch.object(app,'get',return_value={'items':[dict(spec=dict(volumes=[dict(persistentVolumeClaim=dict(claimName='saved'))]))]}):
   with self.assertRaisesRegex(ValueError,'используется'):app.preflight(c)
 def test_new_secret_uses_create_never_apply(self):
  app=lab.Apps('/tmp');c=lab.validate(dict(name='db',type='postgres'))
  with patch.object(app,'find',return_value={'kind':'Namespace'}),patch.object(app,'kubectl',side_effect=ValueError('AlreadyExists')) as kube,patch.object(app,'apply') as apply:
   with self.assertRaisesRegex(ValueError,'AlreadyExists'):app.deploy(c,(c,'StatefulSet',[],''))
   self.assertEqual(kube.call_args.args[0],['create','-f','-']);apply.assert_not_called()

 def test_stopped_workload_reserves_its_pvc(self):
  workload=dict(kind='StatefulSet',metadata=dict(name='db'),spec=dict(replicas=0,volumeClaimTemplates=[dict(metadata=dict(name='data'))]))
  self.assertTrue(lab.claim_referenced('data-db-0',[workload]))
  self.assertFalse(lab.claim_referenced('data-db-2-other',[workload]))

 def test_storage_check_reports_new_pvc_collision_without_mutation(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'find',return_value={'kind':'PersistentVolumeClaim'}),patch.object(app,'apply') as apply:
   with self.assertRaisesRegex(ValueError,'PVC dev/data-postgres-0 уже существует'):app.check_storage(dict(type='postgres',name='postgres'))
   apply.assert_not_called()
 def test_no_storage_check_needs_no_cluster_access(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'kubectl') as kube:
   self.assertEqual(app.check_storage(dict(name='web'))['message'],'PVC не требуется.');kube.assert_not_called()

 def test_free_name_skips_apps_pvc_and_secret(self):
  self.assertEqual(storage.free_name('postgres',{'postgres-1','data-postgres-2-0','postgres-3-auth'}),'postgres-4')
  self.assertEqual(storage.free_name('redis',set()),'redis-1')
 def test_suggestion_respects_namespace_and_draft(self):
  app=Mock();app.get.return_value={'items':[{'metadata':{'name':'data-postgres-1-0'}}]}
  self.assertEqual(storage.suggest_name(app,dict(base='postgres',namespace='dev',reserved=['postgres-2']))['name'],'postgres-3')
  self.assertEqual(app.get.call_args.args[1],'dev');app.apply.assert_not_called()

 def test_editor_pvc_choices_and_secret_hint(self):
  app=Mock();app.get.return_value={'items':[
   dict(kind='PersistentVolumeClaim',metadata=dict(name='data-db-0'),spec={},status=dict(phase='Bound',capacity=dict(storage='2Gi'))),
   dict(kind='PersistentVolumeClaim',metadata=dict(name='busy'),spec={},status=dict(phase='Bound')),
   dict(kind='Pod',spec=dict(volumes=[dict(persistentVolumeClaim=dict(claimName='busy'))])),
   dict(kind='Secret',metadata=dict(name='db-auth'),data=dict(password='PRIVATE'))]}
  result=storage.editor_storage(app,dict(namespace='dev'));claims={p['name']:p for p in result['pvcs']}
  self.assertTrue(claims['data-db-0']['available']);self.assertEqual(claims['data-db-0']['secret'],'db-auth')
  self.assertFalse(claims['busy']['available']);self.assertNotIn('PRIVATE',str(result));app.apply.assert_not_called()

 def test_numbered_hostname_does_not_overlap_sslip_address(self):
  app=lab.Apps('/tmp');nodes={'items':[dict(metadata=dict(labels={'node-role.kubernetes.io/control-plane':'true'}),status=dict(addresses=[dict(type='InternalIP',address='192.168.60.11')]))]}
  with patch.object(app,'get',return_value=nodes):
   self.assertEqual(app.host({'host':'web-1'}),'web-1.app.192.168.60.11.sslip.io')
   self.assertEqual(app.host({'host':'web'}),'web.192.168.60.11.sslip.io')
   self.assertEqual(app.host({'host':'custom.example.com'}),'custom.example.com')
