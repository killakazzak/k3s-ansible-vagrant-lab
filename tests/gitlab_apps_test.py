import sys,json,base64,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
import gitlab_apps as gl
class GitlabTests(unittest.TestCase):
 def test_runner_authentication_token_environment(self):
  _,_,items,_=lab.Apps('/tmp').plan(self.config())
  container=next(o for o in items if o['kind']=='Deployment')['spec']['template']['spec']['containers'][0]
  env={v['name']:v for v in container['env']}
  self.assertNotIn('RUNNER_TOKEN',env)
  self.assertEqual(env['CI_SERVER_TOKEN']['valueFrom']['secretKeyRef'],{'name':'ci-token','key':'runner-token'})
 def config(self,kind='gitlab-runner',**kw):return dict(type=kind,name='ci',namespace='gitlab-ci',gitlab_secret='ci-token',**kw)
 def test_runner_isolated_jobs_and_no_token_in_templates(self):
  c,k,items,host=lab.Apps('/tmp').plan(self.config(concurrent=2));self.assertEqual(k,'Deployment');self.assertEqual(host,'')
  self.assertNotIn('Secret',[o['kind'] for o in items]);self.assertNotIn('ClusterRole',[o['kind'] for o in items])
  cm=next(o for o in items if o['kind']=='ConfigMap');self.assertIn('concurrent = 2',cm['data']['base.toml']);self.assertIn('privileged = false',cm['data']['config.template.toml']);self.assertIn('automount_service_account_token = false',cm['data']['config.template.toml'])
  job=next(o for o in items if o['kind']=='ServiceAccount' and o['metadata']['name']=='ci-job');self.assertFalse(job['automountServiceAccountToken'])
  w=next(o for o in items if o['kind']==k);self.assertEqual(w['spec']['strategy']['type'],'Recreate')
  v=lab.template_value({'name':'safe','apps':[dict(self.config(),gitlab_token='DO_NOT_STORE')]});self.assertNotIn('DO_NOT_STORE',json.dumps(v))
 def test_agent_outbound_secret_file_and_scoped_permissions(self):
  _,k,items,host=lab.Apps('/tmp').plan(self.config('gitlab-agent'));self.assertFalse(host)
  pod=next(o for o in items if o['kind']==k)['spec']['template']['spec'];self.assertIn('--token-file=/etc/agentk/token',pod['containers'][0]['args']);self.assertEqual(pod['volumes'][0]['secret']['secretName'],'ci-token')
  for role in [o for o in items if o['kind']=='Role']:
   self.assertTrue(all('impersonate' not in rule['verbs'] and '*' not in rule['resources'] for rule in role['rules']))
 def test_secret_save_and_missing_token(self):
  app=Mock();app.find.return_value=None
  gl.save_secret(app,dict(type='gitlab-runner',namespace='gitlab-ci',name='ci-token',token='glrt-test-token'),lab.dns,lab.namespace)
  self.assertEqual(app.kubectl.call_args.args[1]['stringData'],{'runner-token':'glrt-test-token'})
  with self.assertRaises(ValueError):gl.check_secret(app,lab.validate(self.config()))
  app.find.return_value={'data':{'runner-token':base64.b64encode(b'glrt-test-token').decode()}}
  gl.check_secret(app,lab.validate(self.config()))
 def test_capacity_includes_jobs(self):
  plan=lab.Apps('/tmp').plan(self.config());app=lab.Apps('/tmp');node={'metadata':{'name':'worker'},'status':{'allocatable':{'cpu':'2','memory':'500Mi'},'conditions':[{'type':'Ready','status':'True'}]}}
  with patch.object(app,'get',side_effect=[{'items':[node]},{'items':[]}]):
   with self.assertRaisesRegex(ValueError,'Проверка ресурсов'):app.check_capacity([plan])
 def test_invalid_settings(self):
  for kw in [dict(gitlab_url='https://user:token@gitlab.com'),dict(kas_address='ws://insecure'),dict(concurrent=0),dict(host='public'),dict(storage_mode='new'),dict(replicas=2)]:
   with self.assertRaises(ValueError):lab.validate(self.config(**kw))
 def test_installed_template_roundtrip(self):
  _,k,items,_=lab.Apps('/tmp').plan(self.config());w=next(o for o in items if o['kind']==k);app=lab.Apps('/tmp')
  with patch.object(app,'get',side_effect=[w,{'items':[]}]),patch.object(lab,'save_template') as save:app.template_from_apps({'name':'ci','selected':[{'name':'ci','namespace':'gitlab-ci','kind':k}]})
  saved=save.call_args.args[0]['apps'][0];self.assertEqual(saved['gitlab_secret'],'ci-token');self.assertEqual(saved['gitlab_url'],'https://gitlab.com')
if __name__=='__main__':unittest.main()
