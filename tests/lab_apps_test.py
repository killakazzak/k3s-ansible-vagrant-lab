import sys, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
class LabTests(unittest.TestCase):
 def test_manifest_and_validation(self):
  app=lab.Apps('/tmp')
  c,k,objects,h=app.plan(dict(type='postgres',name='db',namespace='dev'))
  self.assertEqual(k,'StatefulSet')
  workload=next(o for o in objects if o['kind']==k)
  self.assertEqual(workload['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage'],'2Gi')
  env=workload['spec']['template']['spec']['containers'][0]['env']
  self.assertEqual(env[0]['valueFrom']['secretKeyRef']['name'],'db-auth')
  for config in [dict(type='postgres',replicas=2),dict(namespace='kube-system'),dict(image='nginx:latest'),dict(type='postgres',image='postgres:18'),dict(name='a;rm')]:
   with self.assertRaises(ValueError):lab.validate(dict({'name':'a','namespace':'dev'},**config))
 def test_existing_resources_are_not_overwritten(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'find',return_value={'kind':'Deployment'}),patch.object(app,'apply') as apply:
   with self.assertRaises(ValueError):app.preflight({'name':'a','namespace':'dev'})
   apply.assert_not_called()
 def test_template_roundtrip_filters_unexpected_fields(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(lab,'ROOT',Path(folder)):
   lab.save_template({'name':'bundle','apps':[{'name':'web','namespace':'dev','password':'not-saved'}]})
   saved=lab.templates();self.assertEqual(saved[0]['apps'][0]['name'],'web');self.assertNotIn('password',saved[0]['apps'][0])
 def test_namespace_scoped_commands(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'kubectl',return_value='{}') as call:
   app.get('pod','dev','one');self.assertIn('dev',call.call_args[0][0]);self.assertIn('one',call.call_args[0][0])
 def test_only_existing_vms_are_stopped(self):
  import lab_action, io
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'.vagrant/machines/master/virtualbox';path.mkdir(parents=True);(path/'id').write_text('fixture')
   with patch.object(sys,'argv',['lab_action.py',str(root),'stand_stop']),patch.object(lab_action.subprocess,'run') as run:
    lab_action.main()
    self.assertEqual(run.call_args[0][0],['vagrant','halt','master'])
 def test_diagnostics_excludes_container_environment(self):
  app=lab.Apps('/tmp')
  pod={'metadata':{'uid':'123'},'spec':{'containers':[{'name':'web','env':[{'name':'PASSWORD','value':'hidden'}]}]},'status':{'phase':'Pending','containerStatuses':[{'name':'web','restartCount':3,'state':{'waiting':{'reason':'CrashLoopBackOff'}}}]}}
  with patch.object(app,'get',return_value=pod),patch.object(app,'kubectl',side_effect=['log text','{"items":[]}']):
   data=app.diagnostics({'name':'web','namespace':'dev'})
   self.assertEqual(data['statuses'][0]['restarts'],3)
   self.assertNotIn('hidden',str(data))
