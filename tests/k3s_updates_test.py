import sys, unittest, tempfile
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import k3s_updates as u

class Updates(unittest.TestCase):
 def test_latest_five_stable_versions(self):
  import io,json
  releases=[{'tag_name':'v1.36.%d+k3s1'%i} for i in (1,5,2,4,3,0)]
  releases += [{'tag_name':'v1.37.0+k3s1','prerelease':True},{'tag_name':'v1.38.0+k3s1','draft':True},{'tag_name':'v1.39.0-rc1+k3s1'},{'tag_name':'v1.36.5+k3s1'}]
  with patch.object(u,'urlopen',return_value=io.StringIO(json.dumps(releases))):
   self.assertEqual(u.stable_releases()['versions'],['v1.36.%d+k3s1'%i for i in (5,4,3,2,1)])
 def test_release_network_failure(self):
  with patch.object(u,'urlopen',side_effect=OSError()):
   with self.assertRaisesRegex(ValueError,'повторите'):u.stable_releases()
 def test_versions(self):
  self.assertLess(u.version('v1.36.4+k3s1'),u.version('v1.36.4+k3s2'))
  for value in ('v1.36.4-rc1+k3s1','; rm','v1.36.4'):
   with self.assertRaises(ValueError):u.version(value)
 def plan(self,tmp):
  nodes=[dict(name='master',vm='master',role='server',version='v1.36.3+k3s1',uid='m',cordoned=False),dict(name='worker',vm='worker',role='workers',version='v1.36.3+k3s1',uid='w',cordoned=True)]
  return dict(target='v1.36.4+k3s1',fingerprint='f',available=True,nodes=nodes)
 def test_order_and_preserved_cordon(self):
  with tempfile.TemporaryDirectory() as tmp:
   app=Mock(root=Path(tmp));path=app.root/'ansible/group_vars/all.yml';path.parent.mkdir(parents=True);path.write_text('k3s_version: v1.36.3+k3s1\nother: keep\n')
   plan=self.plan(tmp);events=[]
   app.get.return_value={'status':{'nodeInfo':{'kubeletVersion':plan['target']},'conditions':[{'type':'Ready','status':'True'}]}}
   with patch.object(u,'preview',return_value=plan),patch.object(u,'ssh',side_effect=lambda a,n,s,**kw:events.append((n['name'],s))):
    u.upgrade(app,dict(target=plan['target'],fingerprint='f'))
   self.assertIn('sha256sum',events[0][1]);self.assertIn('sha256sum',events[1][1]);self.assertIn('etcd-snapshot',events[2][1]);self.assertIn('systemctl restart k3s',events[3][1]);self.assertIn('systemctl restart k3s-agent',events[4][1])
   self.assertEqual([c.args[0] for c in app.kubectl.call_args_list],[['cordon','master'],['uncordon','master']]);self.assertIn('other: keep',path.read_text());self.assertIn(plan['target'],path.read_text())
 def test_stale_preview_never_mutates(self):
  plan=self.plan('/tmp')
  with patch.object(u,'preview',return_value=plan),patch.object(u,'ssh') as ssh:
   with self.assertRaises(ValueError):u.upgrade(Mock(),dict(target=plan['target'],fingerprint='old'))
   ssh.assert_not_called()
 def test_failed_download_never_restarts(self):
  with patch.object(u,'preview',return_value=self.plan('/tmp')),patch.object(u,'ssh',side_effect=RuntimeError('download')) as ssh:
   app=Mock()
   with self.assertRaises(RuntimeError):u.upgrade(app,dict(target='v1.36.4+k3s1',fingerprint='f'))
   app.kubectl.assert_not_called();self.assertEqual(ssh.call_count,1)
 def test_preview_rejects_remote(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'connection.json').write_text('{}')
   with self.assertRaisesRegex(ValueError,'провайдера'):u.preview(Mock(root=root))
 def test_preview_patch_channel_and_downgrade(self):
  with tempfile.TemporaryDirectory() as tmp:
   app=Mock(root=Path(tmp));app.get.return_value={'items':[{'metadata':{'name':'master','uid':'x'},'status':{'nodeInfo':{'kubeletVersion':'v1.36.4+k3s1'},'conditions':[{'type':'Ready','status':'True'}]}}]}
   cfg={'k3s_embedded_etcd':True};inv={'all':{'children':{'server':{'hosts':{'master':{'vagrant_id':'master'}}},'workers':{'hosts':{}}}}}
   response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
   for target,ok in [('v1.36.5+k3s1',True),('v1.36.3+k3s1',False),('v1.37.0+k3s1',False)]:
    response.geturl.return_value='https://github.com/k3s-io/k3s/releases/tag/'+target
    with patch.object(u,'yaml_file',side_effect=[cfg,inv]),patch.object(u,'urlopen',return_value=response):
     if ok:self.assertTrue(u.preview(app)['available'])
     else:
      with self.assertRaises(ValueError):u.preview(app)

 def fixture(self,root,server='v1.36.4+k3s1',worker='v1.36.4+k3s1'):
  app=Mock(root=Path(root));nodes=[]
  for name,v in [('master',server),('worker',worker)]:nodes.append({'metadata':{'name':name,'uid':name},'status':{'nodeInfo':{'kubeletVersion':v},'conditions':[{'type':'Ready','status':'True'}]}})
  app.get.return_value={'items':nodes}
  config={'k3s_embedded_etcd':True};inventory={'all':{'children':{'server':{'hosts':{'master':{}}},'workers':{'hosts':{'worker':{}}}}}}
  return app,config,inventory
 def channel(self,url,**kwargs):
  response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
  tag='v1.37.1+k3s1' if url.endswith('v1.37') else 'v1.36.4+k3s1'
  response.geturl.return_value='https://github.com/k3s-io/k3s/releases/tag/'+tag
  return response
 def test_next_minor_and_rejected_skip_or_downgrade(self):
  with tempfile.TemporaryDirectory() as tmp:
   app,cfg,inv=self.fixture(tmp)
   for target,valid in [('v1.37.1+k3s1',True),('v1.38.0+k3s1',False),('v1.35.1+k3s1',False)]:
    with patch.object(u,'yaml_file',side_effect=[cfg,inv]),patch.object(u,'urlopen',side_effect=self.channel):
     if valid:
      plan=u.preview(app,target);self.assertTrue(plan['minor_upgrade']);self.assertTrue(plan['available']);self.assertEqual(len(plan['choices']),2)
     else:
      with self.assertRaises(ValueError):u.preview(app,target)
 def test_resume_mixed_minor(self):
  with tempfile.TemporaryDirectory() as tmp:
   app,cfg,inv=self.fixture(tmp,server='v1.37.1+k3s1')
   with patch.object(u,'yaml_file',side_effect=[cfg,inv]),patch.object(u,'urlopen',side_effect=self.channel):
    plan=u.preview(app);self.assertTrue(plan['mixed']);self.assertEqual(plan['target'],'v1.37.1+k3s1');self.assertEqual(len(plan['choices']),1)
 def test_worker_ahead_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   app,cfg,inv=self.fixture(tmp,worker='v1.37.1+k3s1')
   with patch.object(u,'yaml_file',side_effect=[cfg,inv]),patch.object(u,'urlopen') as channel:
    with self.assertRaisesRegex(ValueError,'Worker новее'):u.preview(app)
    channel.assert_not_called()
 def test_minor_requires_explicit_acknowledgment(self):
  plan=self.plan('/tmp');plan['minor_upgrade']=True
  with patch.object(u,'preview',return_value=plan),patch.object(u,'ssh') as ssh:
   with self.assertRaisesRegex(ValueError,'совместимости'):u.upgrade(Mock(),dict(target=plan['target'],fingerprint='f'))
   ssh.assert_not_called()
