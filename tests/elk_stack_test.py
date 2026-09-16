import sys,json,unittest,base64,io
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
import elk_stack
class ElkTests(unittest.TestCase):
 def plan(self):return lab.Apps('/tmp').plan(dict(type='elk',name='logs',namespace='dev',host='logs.example.test'))
 def test_versions_wiring_and_data(self):
  c,k,objects,_=self.plan();w=next(o for o in objects if o['kind']==k);p=w['spec']['template']['spec']
  self.assertEqual(c['storage'],10)
  self.assertTrue(all(x['image'].endswith(':9.5.4') for x in p['containers']+p['initContainers']))
  self.assertEqual({m['subPath'] for x in p['containers'] for m in x['volumeMounts'] if m['name']=='data'},{'elasticsearch','kibana','logstash'})
  self.assertIn('kibana_system',p['initContainers'][0]['command'][2]);self.assertNotIn('rm ',p['initContainers'][0]['command'][2])
  config=next(o for o in objects if o['kind']=='ConfigMap')['data']
  self.assertIn('127.0.0.1:9200',config['pipeline.conf']);self.assertIn('${STACK_PASSWORD}',config['pipeline.conf'])
 def test_coordinated_update_and_downgrade_block(self):
  _,k,objects,_=self.plan();w=next(o for o in objects if o['kind']==k);app=lab.Apps('/tmp')
  data=dict(namespace='dev',name='logs',kind=k,container='elk',image=elk_stack.images()['elasticsearch'],replicas=1)
  with patch.object(app,'get',return_value=w),patch.object(app,'kubectl') as cmd,patch.object(app,'wait_rollout',return_value='Ready'):
   app.change(data,'app_update');p=json.loads(cmd.call_args.args[0][-1])['spec']['template']['spec']
   self.assertEqual(len(p['containers']),3);self.assertEqual(p['initContainers'][0]['image'],data['image'])
   with self.assertRaises(ValueError):app.change(dict(data,container='kibana'),'app_update')
   with self.assertRaises(ValueError):app.change(dict(data,image='docker.elastic.co/elasticsearch/elasticsearch:9.5.3'),'app_update')
 def test_pipeline_probe_checks_delivery(self):
  calls=[];marker=[]
  def request(req,timeout):
   calls.append(req)
   if ':8080/' in req.full_url:marker.append(json.loads(req.data)['lab_probe'])
   result={'hits':{'hits':[{'_source':{'lab_probe':marker[0]}}]}} if '_search' in req.full_url else {}
   return io.BytesIO(json.dumps(result).encode())
  with patch('sys.argv',['check','logs.dev.svc']),patch.dict('os.environ',{'STACK_PASSWORD':'test-password'}),patch('urllib.request.urlopen',side_effect=request):exec(elk_stack.CHECK_SCRIPT,{})
  self.assertEqual(len(calls),4);self.assertIn('/_search',calls[-1].full_url)
  self.assertEqual(json.loads(calls[-1].data)['query']['match']['lab_probe'],marker[0])
  self.assertTrue(all(req.get_header('Authorization').startswith('Basic ') for req in calls))
if __name__=='__main__':unittest.main()
