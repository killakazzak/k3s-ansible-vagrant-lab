import sys,unittest,copy,json
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import workload_types as w,lab_apps as lab
class WorkloadTests(unittest.TestCase):
 def plan(self,kind):return lab.Apps('/tmp').plan(dict(type='nginx',name='web',namespace='dev',workload_type=kind))
 def test_change_kind_allowed_in_remote_and_local_dispatch(self):
  import remote_clusters,server
  remote_clusters.permit('/api/action',{'action':'app_change_kind'})
  self.assertIn('app_change_kind',server.LAB_ACTIONS)
 def test_creation_types(self):
  for kind in w.KINDS:
   c,result,objects,_=self.plan(kind);obj=next(o for o in objects if o['kind']==kind)
   self.assertEqual(result,kind);self.assertEqual('replicas' in obj['spec'],kind!='DaemonSet')
   if kind=='StatefulSet':self.assertTrue(any(o['kind']=='Service' and o['spec'].get('clusterIP')=='None' for o in objects))
 def test_data_and_bundle_rejected(self):
  for config in [dict(type='postgres'),dict(type='nginx',storage_mode='new'),dict(type='gitlab-runner')]:
   with self.assertRaises(ValueError):lab.validate(dict(config,name='test',workload_type='DaemonSet'))
 def fixture(self):
  _,_,objects,_=self.plan('Deployment');old=next(o for o in objects if o['kind']=='Deployment');old['metadata'].update(uid='old-id',resourceVersion='1')
  app=Mock();app.find.return_value=None
  new=copy.deepcopy(old);new['kind']='DaemonSet';new['metadata']['uid']='new-id'
  route={'metadata':{'name':'web','resourceVersion':'2','ownerReferences':[{'uid':'old-id','kind':'Deployment','name':'web','apiVersion':'apps/v1'}]}}
  app.get.side_effect=lambda kind,*args:copy.deepcopy(old if kind=='Deployment' else new if kind=='DaemonSet' else {'items':[route]} if kind=='ingresses' else {'items':[]})
  data=dict(kind='Deployment',target_kind='DaemonSet',name='web',namespace='dev',confirmation='web',resource_version='1',replicas=1)
  return app,data
 def test_ready_before_delete_and_owner_transfer(self):
  app,data=self.fixture();w.migrate(app,data)
  calls=app.method_calls;wait=next(i for i,c in enumerate(calls) if c[0]=='wait_rollout');delete=next(i for i,c in enumerate(calls) if c[0]=='kubectl' and c[1][0][0]=='delete' and '--dry-run=server' not in c[1][0])
  self.assertLess(wait,delete)
  payload=next(c[1][1] for c in calls if c[0]=='kubectl' and c[1][0][0]=='delete' and '--dry-run=server' not in c[1][0]);self.assertEqual(payload['preconditions']['uid'],'old-id')
  patchcall=next(c for c in calls if c[0]=='kubectl' and c[1][0][0]=='patch');self.assertIn('new-id',patchcall[1][0][-1])
 def test_failed_rollout_keeps_old(self):
  app,data=self.fixture();app.wait_rollout.side_effect=ValueError('quota')
  with self.assertRaisesRegex(ValueError,'Старый ресурс сохранён'):w.migrate(app,data)
  self.assertFalse(any(c.args[0][0]=='delete' and '--dry-run=server' not in c.args[0] for c in app.kubectl.call_args_list))
 def test_stale_and_unconfirmed_do_not_mutate(self):
  for change in [dict(confirmation='wrong'),dict(resource_version='stale')]:
   app,data=self.fixture()
   with self.assertRaises(ValueError):w.migrate(app,dict(data,**change))
   app.kubectl.assert_not_called()
