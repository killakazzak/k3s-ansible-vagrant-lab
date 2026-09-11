import sys, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
class LabTests(unittest.TestCase):
 def setUp(self):
  host=patch.object(lab.Apps,'host',side_effect=lambda c: c['host']+'.example.test' if c['host'] else '');host.start();self.addCleanup(host.stop)
 def test_rollout_explains_scheduler_failure(self):
  app=lab.Apps('/tmp')
  pod={'status':{'conditions':[{'type':'PodScheduled','status':'False','message':'0/2 nodes: 1 Insufficient memory, 1 untolerated taint'}]}}
  with patch.object(app,'kubectl',side_effect=ValueError('timed out')),patch.object(app,'workload_pods',return_value=[{'name':'rabbitmq-0'}]),patch.object(app,'get',return_value=pod):
   with self.assertRaisesRegex(ValueError,'Недостаточно свободной памяти по requests') as result:app.wait_rollout('StatefulSet','rabbitmq','dev')
   self.assertIn('taints',str(result.exception))
   self.assertIn('Ресурсы сохранены',str(result.exception))
 def test_rollout_preserves_error_when_diagnostics_unavailable(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'kubectl',side_effect=ValueError('original failure')),patch.object(app,'workload_pods',side_effect=ValueError('API unavailable')):
   with self.assertRaisesRegex(ValueError,'original failure'):app.wait_rollout('Deployment','web','dev')

 def test_delete_template_preserves_other_templates(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(lab,'ROOT',Path(folder)):
   for name in ('one','two'):lab.save_template({'name':name,'apps':[{'name':'web','namespace':'dev'}]})
   lab.delete_template({'name':'one'})
   self.assertEqual([t['name'] for t in lab.templates()],['two'])
 def test_capture_template_copies_config_without_secrets_or_data(self):
  app=lab.Apps('/tmp');c,k,objects,h=app.plan({'type':'postgres','name':'db','namespace':'dev','memory':512,'cpu':200})
  obj=next(o for o in objects if o['kind']==k)
  with patch.object(app,'get',side_effect=[obj,{'items':[]}]),patch.object(lab,'save_template') as save:
   app.template_from_apps({'name':'stand','selected':[{'kind':k,'name':'db','namespace':'dev'}]})
   config=save.call_args.args[0]['apps'][0]
   self.assertEqual(config['memory'],512);self.assertEqual(config['cpu'],200)
   self.assertEqual(config['storage_mode'],'new');self.assertEqual(config['storage_secret'],'')
   self.assertNotIn('env',config);self.assertEqual(config['image'],'postgres:18.6-alpine')
 def test_capture_rejects_unmanaged_workload(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'get',return_value={'metadata':{'labels':{}}}),patch.object(lab,'save_template') as save:
   with self.assertRaises(ValueError):app.template_from_apps({'name':'stand','selected':[{'kind':'Deployment','name':'web','namespace':'dev'}]})
   save.assert_not_called()

 def test_bulk_delete_validates_all_before_deleting(self):
  import lab_action,io,json
  targets=[dict(kind='Deployment',namespace='dev',name=n) for n in ('one','two')]
  payload={'action':'app_delete','params':{'apps':targets}}
  with patch.object(sys,'argv',['lab_action.py','/tmp']),patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),patch.object(lab.Apps,'get',side_effect=[{},ValueError('missing')]),patch.object(lab.Apps,'delete') as delete:
   with self.assertRaises(ValueError):lab_action.main()
   delete.assert_not_called()
  with patch.object(sys,'argv',['lab_action.py','/tmp']),patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),patch.object(lab.Apps,'get',return_value={}),patch.object(lab.Apps,'delete') as delete:
   lab_action.main()
   self.assertEqual([c.args[0] for c in delete.call_args_list],[dict(t,delete_data=False) for t in targets])

 def test_bulk_stop_and_restart_restore_stopped_apps(self):
  import lab_action,io,json
  for action,replicas in [('app_stop',1),('app_restart',0),('app_restart',1)]:
   payload={'action':action,'params':{'apps':[dict(kind='Deployment',namespace='dev',name='web')]}}
   with patch.object(sys,'argv',['lab_action.py','/tmp']),patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),patch.object(lab.Apps,'get',return_value={'metadata':{},'spec':{'replicas':replicas}}),patch.object(lab.Apps,'kubectl',return_value='OK') as cmd,patch.object(lab.Apps,'wait_rollout',return_value='Ready'):
    lab_action.main()
    if action=='app_stop':self.assertEqual(cmd.call_args.args[0],['scale','deployment/web','-n','dev','--replicas=0'])
    elif replicas==0:self.assertEqual(cmd.call_args.args[0],['scale','deployment/web','-n','dev','--replicas=1'])
    else:self.assertEqual(cmd.call_args.args[0],['rollout','restart','deployment/web','-n','dev'])

 def test_resource_yaml_is_scoped_and_rejects_unknown_types(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'kubectl',return_value='kind: Deployment\n') as cmd:
   result=app.resource_yaml(dict(type='deployments',namespace='dev',name='web'))
   self.assertEqual(result['filename'],'dev_deployments_web.yaml')
   self.assertEqual(cmd.call_args.args[0],['get','deployments.apps','web','-n','dev','-o','yaml','--show-managed-fields=false','--request-timeout=10s'])
  with patch.object(app,'kubectl') as cmd:
   for data in [dict(type='nodes',namespace='dev',name='one'),dict(type='pods',namespace='dev',name='--all')]:
    with self.assertRaises(ValueError):app.resource_yaml(data)
   cmd.assert_not_called()

 def test_capacity_includes_panel_and_ignores_completed_pods(self):
  app=lab.Apps('/tmp');plan=app.plan({'type':'postgres','name':'db','namespace':'dev','memory':256})
  node={'metadata':{'name':'worker'},'status':{'allocatable':{'cpu':'2','memory':'400Mi'},'conditions':[{'type':'Ready','status':'True'}]}}
  with patch.object(app,'get',side_effect=[{'items':[node]},{'items':[]}]),patch.object(app,'apply') as apply:
   with self.assertRaisesRegex(ValueError,'Проверка ресурсов'):app.check_capacity([plan])
   apply.assert_not_called()
  pod={'spec':{'nodeName':'worker','containers':[{'resources':{'requests':{'memory':'300Mi'}}}]},'status':{'phase':'Succeeded'}}
  self.assertEqual(lab.allocation([node],[pod])['worker']['requests']['memory'],0)
 def test_pod_budget_includes_init_sidecars(self):
  spec={'containers':[{'resources':{'requests':{'memory':'100Mi'}}}], 'initContainers':[{'restartPolicy':'Always','resources':{'requests':{'memory':'50Mi'}}},{'resources':{'requests':{'memory':'200Mi'}}}]}
  self.assertEqual(lab.pod_budget(spec)['memory'],250*1024**2)

 def test_shovel_is_persisted_in_pod_startup(self):
  app=lab.Apps('/tmp')
  for enabled in (True,False):
   c,k,objects,h=app.plan(dict(type='rabbitmq',name='mq',namespace='dev',shovel=enabled))
   obj=next(o for o in objects if o['kind']=='StatefulSet')
   self.assertEqual(obj['metadata']['annotations']['lab.k3s/shovel'],str(enabled).lower())
   self.assertIn('--offline '+('enable' if enabled else 'disable'),obj['spec']['template']['spec']['containers'][0]['command'][2])
 def test_shovel_update_keeps_stopped_broker_stopped(self):
  app=lab.Apps('/tmp');obj={'metadata':{'labels':{'app.kubernetes.io/managed-by':lab.MANAGER,'lab.k3s/type':'rabbitmq'}},'spec':{'replicas':0,'template':{'spec':{'containers':[{'name':'rabbitmq'}]}}}}
  with patch.object(app,'get',return_value=obj),patch.object(app,'kubectl') as cmd,patch.object(app,'wait_rollout') as wait:
   app.rabbit_plugins(dict(namespace='dev',name='mq',enabled=True))
   self.assertEqual(cmd.call_args.args[0][0],'patch');self.assertNotIn('replicas',cmd.call_args.args[0][-1]);wait.assert_not_called()

 def test_yaml_preview_validates_identity_and_only_dry_runs(self):
  import json
  app=lab.Apps('/tmp');obj={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'settings','namespace':'dev','uid':'id','resourceVersion':'10'},'data':{'key':'old'}}
  changed=json.loads(json.dumps(obj));changed['data']['key']='new'
  with patch.object(app,'yaml_edit_object',return_value=obj),patch.object(app,'kubectl',return_value=json.dumps(changed)) as cmd:
   candidate,diff=app.yaml_preview(dict(type='configmaps',name='settings',namespace='dev',yaml=json.dumps(changed)))
   self.assertIn('--dry-run=server',cmd.call_args.args[0]);self.assertIn('+',diff);self.assertEqual(candidate['data']['key'],'new')
   changed['metadata']['resourceVersion']='9'
   with self.assertRaisesRegex(ValueError,'свежий YAML'):app.yaml_preview(dict(yaml=json.dumps(changed)))
  with self.assertRaises(ValueError):app.yaml_preview(dict(yaml='kind: ConfigMap\n---\nkind: Secret'))

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
 def test_check_state_persists_and_invalidates(self):
  with tempfile.TemporaryDirectory() as folder:
   app=lab.Apps(folder);obj={'metadata':{'uid':'one','generation':1}}
   app.record_check(obj,'success');self.assertEqual(lab.Apps(folder).check_result(obj)['state'],'success')
   obj['metadata']['generation']=2;self.assertIsNone(app.check_result(obj))
   app.record_check(obj,'failed');self.assertEqual(app.check_result(obj)['state'],'failed')
 def test_delete_scope_and_preserve_data(self):
  app=lab.Apps('/tmp');labels={'app.kubernetes.io/managed-by':lab.MANAGER,'app.kubernetes.io/name':'db'}
  workload={'kind':'StatefulSet','metadata':{'name':'db','labels':labels},'spec':{'template':{'spec':{'containers':[]}},'volumeClaimTemplates':[{'metadata':{'name':'data'}}]}}
  own={'kind':'Service','metadata':{'name':'db','labels':labels}};other={'kind':'Service','metadata':{'name':'other','labels':{'app.kubernetes.io/managed-by':lab.MANAGER,'app.kubernetes.io/name':'other'}}}
  for remove in (False,True):
   responses=[workload,{'items':[workload,own,other]},{'items':[]}]+([{'items':[{'metadata':{'name':'data-db-0'}},{'metadata':{'name':'data-other-0'}}]}] if remove else [])
   with patch.object(app,'get',side_effect=responses),patch.object(app,'kubectl') as cmd:
    app.delete({'kind':'StatefulSet','name':'db','namespace':'dev','delete_data':remove})
    calls=[c.args[0] for c in cmd.call_args_list];self.assertTrue(any(c[:3]==['delete','Service','db'] for c in calls));self.assertFalse(any('other' in c or 'data-other-0' in c for c in calls));self.assertEqual(any('pvc' in c for c in calls),remove)
 def test_failed_check_is_red(self):
  with tempfile.TemporaryDirectory() as folder:
   app=lab.Apps(folder);obj={'metadata':{'uid':'one','generation':1}}
   with patch.object(app,'get',return_value=obj),patch.object(app,'_check',side_effect=ValueError('failure')):
    with self.assertRaises(ValueError):app.check({'name':'web','namespace':'dev'},'Deployment')
   self.assertEqual(app.check_result(obj)['state'],'failed')

 def test_existing_pvc_manifest_is_not_recreated(self):
  c,k,objects,h=lab.Apps('/tmp').plan({'name':'db','namespace':'dev','type':'postgres','storage_mode':'existing','pvc':'saved','storage_secret':'saved-auth'})
  w=next(o for o in objects if o['kind']=='StatefulSet');self.assertNotIn('volumeClaimTemplates',w['spec']);self.assertEqual(w['spec']['template']['spec']['volumes'][0]['persistentVolumeClaim']['claimName'],'saved');self.assertFalse(any(o['kind']=='PersistentVolumeClaim' for o in objects));self.assertIn('saved-auth',str(w))
 def test_new_pvc_for_custom_application(self):
  c,k,objects,h=lab.Apps('/tmp').plan({'name':'web','namespace':'dev','type':'custom','image':'nginx:1.30.4-alpine','storage_mode':'new','mount_path':'/content'})
  self.assertTrue(any(o['kind']=='PersistentVolumeClaim' for o in objects));w=next(o for o in objects if o['kind']=='Deployment');self.assertEqual(w['spec']['template']['spec']['containers'][0]['volumeMounts'][0]['mountPath'],'/content')
 def test_busy_pvc_rejected_before_apply(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'find',return_value={'metadata':{},'spec':{},'status':{'phase':'Bound'}}),patch.object(app,'get',return_value={'items':[{'spec':{'volumes':[{'persistentVolumeClaim':{'claimName':'saved'}}]}}]}),patch.object(app,'apply') as apply:
   with self.assertRaises(ValueError):app.preflight({'name':'cache','type':'redis','namespace':'dev','storage_mode':'existing','pvc':'saved'})
   apply.assert_not_called()
 def test_storage_location_comes_from_pv_not_pod(self):
  nodes=[{'metadata':{'name':'worker1','labels':{'kubernetes.io/hostname':'worker1'}},'status':{'addresses':[{'type':'InternalIP','address':'192.168.59.21'}]}}]
  pv={'spec':{'hostPath':{'path':'/var/lib/rancher/k3s/storage/claim'},'nodeAffinity':{'required':{'nodeSelectorTerms':[{'matchExpressions':[{'key':'kubernetes.io/hostname','operator':'In','values':['worker1']}]}]}}}}
  location=lab.storage_location(pv,nodes);self.assertEqual(location['nodes'][0]['name'],'worker1');self.assertEqual(location['path'],'/var/lib/rancher/k3s/storage/claim')
  self.assertEqual(lab.storage_location({'spec':{'hostPath':{'path':'/data'}}},nodes)['nodes'],[])
  self.assertEqual(lab.storage_location({'spec':{'nfs':{'server':'nas','path':'/export'}}},nodes)['server'],'nas')
 def test_secret_info_never_returns_values(self):
  app=lab.Apps('/tmp')
  with patch.object(app,'get',return_value={'items':[{'metadata':{'name':'db-auth','namespace':'dev'},'data':{'password':'sensitive-base64'}}]}):
   info=app.secret_info();self.assertTrue(info[0]['hasPassword']);self.assertEqual(info[0]['keys'],['password']);self.assertNotIn('sensitive-base64',str(info))
