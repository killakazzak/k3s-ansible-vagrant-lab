import sys,json,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab,gitlab_apps as gl
class Tests(unittest.TestCase):
 def test_rotate(self):
  app=lab.Apps('/tmp');_,_,items,_=app.plan(dict(type='gitlab-runner',name='runner',namespace='dev',gitlab_secret='old'))
  obj=next(x for x in items if x['kind']=='Deployment');obj['metadata']['resourceVersion']='1'
  data=dict(kind='Deployment',name='runner',namespace='dev',resource_version='1',token='glrt-test-only')
  with patch.object(app,'get',return_value=obj),patch.object(app,'kubectl',return_value='ok') as k:
   result=gl.rotate_runner_token(app,data);self.assertTrue(result['ok']);self.assertEqual(k.call_count,4)
   secret=k.call_args_list[2].args[1];self.assertNotEqual(secret['metadata']['name'],'old')
   payload=json.loads(k.call_args.args[0][-1]);env=payload[-1]['value'];self.assertIn('CI_SERVER_TOKEN',[e['name'] for e in env]);self.assertNotIn('glrt-test-only',json.dumps(payload))
   k.reset_mock()
   with self.assertRaises(ValueError):gl.rotate_runner_token(app,dict(data,resource_version='old'))
   k.assert_not_called()
   with self.assertRaises(ValueError):gl.rotate_runner_token(app,dict(data,token='bad'))
   k.assert_not_called()
if __name__=='__main__':unittest.main()
