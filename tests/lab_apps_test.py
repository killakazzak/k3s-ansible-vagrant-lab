import sys, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
class LabTests(unittest.TestCase):
 def setUp(self):
  host=patch.object(lab.Apps,'host',side_effect=lambda c: c['host']+'.example.test' if c['host'] else '');host.start();self.addCleanup(host.stop)
 def test_manifest_and_validation(self):
  app=lab.Apps('/tmp')
  c,k,objects,h=app.plan(dict(type='postgres',name='db',namespace='dev'))
  self.assertEqual(k,'StatefulSet')
  self.assertEqual(c['image'],'postgres:18.6-alpine')
  workload=next(o for o in objects if o['kind']==k)
  self.assertEqual(workload['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage'],'2Gi')
  env=workload['spec']['template']['spec']['containers'][0]['env']
  self.assertEqual(workload['spec']['template']['spec']['containers'][0]['volumeMounts'][0]['mountPath'],'/var/lib/postgresql')
  self.assertEqual(next(v['value'] for v in env if v['name']=='PGDATA'),'/var/lib/postgresql/18/docker')
  self.assertEqual(env[0]['valueFrom']['secretKeyRef']['name'],'db-auth')
  for config in [dict(type='postgres',replicas=2),dict(namespace='kube-system'),dict(image='nginx:latest'),dict(type='postgres',image='postgres:19'),dict(name='a;rm')]:
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

 def test_selected_vm_scope(self):
  import lab_action, io, json
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   for name in ('master','worker'):
    path=root/'.vagrant/machines'/name/'virtualbox';path.mkdir(parents=True);(path/'id').write_text('fixture')
   for action,verb in [('stand_stop','halt'),('stand_start','up')]:
    with patch.object(sys,'argv',['lab_action.py',str(root)]),patch.object(sys,'stdin',io.StringIO(json.dumps({'action':action,'params':{'nodes':['worker']}}))),patch.object(lab_action.subprocess,'run') as run:
     lab_action.main();self.assertEqual(run.call_args[0][0],['vagrant',verb]+(['--no-provision'] if verb=='up' else [])+['worker'])
   for selected in ([],['unknown'],['--help'],'worker'):
    with patch.object(sys,'argv',['lab_action.py',str(root)]),patch.object(sys,'stdin',io.StringIO(json.dumps({'action':'stand_stop','params':{'nodes':selected}}))),patch.object(lab_action.subprocess,'run') as run:
     with self.assertRaises(ValueError):lab_action.main()
     run.assert_not_called()
 def test_broker_manifests(self):
  app=lab.Apps('/tmp')
  for broker in ('kafka','rabbitmq'):
   with patch.object(app,'host',return_value='mq.example.test' if broker=='rabbitmq' else ''):
    c,k,objects,host=app.plan({'name':broker,'type':broker,'namespace':'dev'})
   self.assertEqual(k,'StatefulSet');w=next(o for o in objects if o['kind']==k);container=w['spec']['template']['spec']['containers'][0]
   self.assertTrue(w['spec']['volumeClaimTemplates'])
   if broker=='kafka':
    env={v['name']:v.get('value') for v in container['env']};self.assertIn('kafka.dev.svc.cluster.local',env['KAFKA_ADVERTISED_LISTENERS']);self.assertEqual(env['KAFKA_PROCESS_ROLES'],'broker,controller')
   else:
    ingress=next(o for o in objects if o['kind']=='Ingress');self.assertEqual(ingress['spec']['rules'][0]['http']['paths'][0]['backend']['service']['port']['number'],15672)
    self.assertEqual(container['env'][1]['valueFrom']['secretKeyRef']['name'],'rabbitmq-auth')
   with self.assertRaises(ValueError):lab.validate({'name':'mq','type':broker,'replicas':2})
 def test_default_versions_and_major_upgrade_guard(self):
  expected={'postgres':'postgres:18.6-alpine','redis':'redis:8.10.1-alpine','rabbitmq':'rabbitmq:4.3.5-management','kafka':'apache/kafka:4.3.1','nginx':'nginx:1.30.4-alpine'}
  for kind,image in expected.items():self.assertEqual(lab.validate({'name':'app','type':kind})['image'],image)
  for kind,old in [('postgres','postgres:17-alpine'),('redis','redis:7.4-alpine')]:
   app=lab.Apps('/tmp');obj={'metadata':{'labels':{'lab.k3s/type':kind}},'spec':{'template':{'spec':{'containers':[{'name':kind,'image':old}]}}}}
   with patch.object(app,'get',return_value=obj),patch.object(app,'kubectl') as cmd:
    with self.assertRaises(ValueError):app.change({'name':'app','namespace':'dev','kind':'StatefulSet','container':kind,'image':expected[kind]},'app_update')
    cmd.assert_not_called()
 def test_panel_auth_and_connection(self):
  for kind in ('postgres','redis','kafka'):
   c,k,objects,h=lab.Apps('/tmp').plan({'name':'sample','namespace':'dev','type':kind})
   auth=next(o for o in objects if o['kind']=='Secret' and o['metadata']['name']=='sample-ui-auth')
   self.assertGreater(len(auth['stringData']['password']),20)
   self.assertNotIn(auth['stringData']['password'],str([o for o in objects if o['kind']!='Secret']))
   ui=next(o for o in objects if o['kind']=='Deployment' and o['metadata']['name']=='sample-ui')
   self.assertIn('sample.dev.svc.cluster.local',str(objects))
   if kind!='postgres':self.assertTrue(any(o['kind']=='Middleware' for o in objects))
