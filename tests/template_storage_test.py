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
