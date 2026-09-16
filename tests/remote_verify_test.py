import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import remote_clusters as remote
class RemoteVerifyTests(unittest.TestCase):
 def check(self,replies):
  with patch.object(Path,'is_file',return_value=True),patch.object(remote,'binary',return_value='kubectl'),patch.object(remote.subprocess,'run',side_effect=replies) as run:
   result=remote.verify(Path('/repo'),{},Path('/profile'))
   for call in run.call_args_list:
    self.assertEqual(call.args[0][3],'get');self.assertEqual(call.kwargs['timeout'],8)
   return result
 def reply(self,value,code=0):return SimpleNamespace(returncode=code,stdout=json.dumps(value) if not isinstance(value,str) else value,stderr='Forbidden' if code else '')
 def test_healthy(self):
  node={'metadata':{'name':'node'},'status':{'conditions':[{'type':'Ready','status':'True'}]}}
  pod={'metadata':{'name':'dns'},'status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}]}}
  r=self.check([self.reply({'gitVersion':'v1.test'}),self.reply('ok'),self.reply({'items':[node]}),self.reply({'items':[pod]}),self.reply({'items':[{}]})]);self.assertEqual(r['state'],'success');self.assertEqual(len(r['checks']),5)
 def test_forbidden_not_healthy(self):
  r=self.check([self.reply('',1)]);self.assertEqual(r['state'],'warning');self.assertIn('RBAC',r['checks'][0]['message'])
 def test_timeout(self):
  r=self.check([remote.subprocess.TimeoutExpired('kubectl',8)]);self.assertEqual(r['state'],'failed');self.assertEqual(len(r['checks']),1)
