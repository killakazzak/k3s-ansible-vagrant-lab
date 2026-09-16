import copy, json, os, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import remote_clusters as remote
import server

CONFIG={'apiVersion':'v1','kind':'Config','clusters':[{'name':'c','cluster':{'server':'https://cluster.example:6443'}}],'users':[{'name':'u','user':{'token':'test-token'}}],'contexts':[{'name':'ctx','context':{'cluster':'c','user':'u'}}],'current-context':'ctx'}
class RemoteTests(unittest.TestCase):
 def test_publication_address_validation_and_isolation(self):
  with tempfile.TemporaryDirectory() as d:
   first=Path(d)/'first';second=Path(d)/'second'
   for root in (first,second):
    root.mkdir();(root/'connection.json').write_text(json.dumps({'name':root.name,'context':'kept'}))
   self.assertEqual(remote.publication_ip(first),'')
   self.assertEqual(remote.publication_ip(first,'135.106.145.26'),'135.106.145.26')
   self.assertEqual(remote.publication_ip(first),'135.106.145.26')
   self.assertEqual(remote.publication_ip(second),'')
   self.assertEqual(json.loads((first/'connection.json').read_text())['context'],'kept')
   for invalid in ('999.1.1.1','example.org','http://1.2.3.4','1.2.3.4:80',''):
    with self.assertRaises(ValueError):remote.publication_ip(first,invalid)
   self.assertEqual(remote.publication_ip(first),'135.106.145.26')
 def test_safe_selection(self):
  c=copy.deepcopy(CONFIG);c['users'].append({'name':'other','user':{'token':'unrelated'}})
  result=remote.select(c,'ctx');self.assertEqual(len(result['users']),1);self.assertNotIn('unrelated',json.dumps(result))
  for field in ('exec','auth-provider','tokenFile','client-key','client-certificate'):
   c=copy.deepcopy(CONFIG);c['users'][0]['user'][field]={}
   with self.assertRaises(ValueError):remote.select(c,'ctx')
  for field,value in [('insecure-skip-tls-verify',True),('certificate-authority','/tmp/key'),('server','http://example.com')]:
   c=copy.deepcopy(CONFIG);c['clusters'][0]['cluster'][field]=value
   with self.assertRaises(ValueError):remote.select(c,'ctx')
 def test_import_and_disconnect(self):
  with tempfile.TemporaryDirectory() as d:
   repo=Path(d);(repo/'kubectl.sh').write_text('');(repo/'.tools').mkdir()
   binary=repo/'.tools/kubectl'
   binary.write_text('#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\np=Path(sys.argv[1].split("=",1)[1])\nif "view" in sys.argv:print(p.read_text())\nelse:print("node/test")\n');binary.chmod(0o700)
   data=dict(name='test',context='ctx',kubeconfig=json.dumps(CONFIG))
   self.assertEqual(remote.connect(repo,dict(os.environ),data),{'name':'remote-test'})
   root=repo/'.connections/remote-test';self.assertEqual((root/'kubeconfig').stat().st_mode&0o777,0o600)
   with self.assertRaises(ValueError):remote.connect(repo,dict(os.environ),data)
   with patch.object(remote.subprocess,'run',side_effect=AssertionError('No cluster commands on disconnect')):
    remote.disconnect(repo,root)
   self.assertFalse(root.exists());self.assertTrue(binary.exists())
 def test_failed_probe_does_not_save(self):
  with tempfile.TemporaryDirectory() as d,patch.object(remote,'parse',return_value=CONFIG),patch.object(remote,'binary',return_value='kubectl'),patch.object(remote.subprocess,'run') as run:
   run.return_value.returncode=1
   with self.assertRaises(ValueError):remote.connect(Path(d),{},dict(name='test',context='ctx'))
   self.assertEqual(list((Path(d)/'.connections').iterdir()),[])
 def test_http_mutations_are_denied(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);profile=root/'.connections/remote-test';profile.mkdir(parents=True);(profile/'connection.json').write_text('{}')
   with patch.object(server,'ROOT',root):
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
     cases=[('/api/action',dict(action='destroy',confirmed=True,confirmation='УДАЛИТЬ')),('/api/action',dict(action='stand_stop',confirmed=True)),('/api/yaml-apply',{}),('/api/yaml-preview',{}),('/api/kubectl',dict(command='delete nodes --all')),('/api/terminal',dict(operation='open')),('/api/terminal',dict(operation='open',pod='test',mode='shell'))]
     for path,data in cases:
      req=Request('http://127.0.0.1:'+str(http.server_port)+path,data=json.dumps(data).encode(),headers={'X-Lab-Token':server.TOKEN,'X-Lab-Cluster':'remote-test','Content-Type':'application/json'})
      with self.assertRaises(HTTPError) as error:urlopen(req)
      self.assertEqual(error.exception.code,400)
      expected={'/api/yaml-apply':'Подтвердите применение','/api/yaml-preview':'YAML должен'}.get(path,'режиме просмотра')
      self.assertIn(expected,json.loads(error.exception.read())['error'])
    finally:http.shutdown();http.server_close();thread.join()
 def test_remote_nodes_do_not_use_vm_tools(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'connection.json').write_text('{}');previous=server.active_root();server.CONTEXT.root=root
   node={'metadata':{'name':'worker','labels':{}},'status':{'capacity':{'cpu':'4','memory':'4Gi'},'conditions':[{'type':'Ready','status':'True'}],'addresses':[{'type':'InternalIP','address':'10.0.0.1'}]}}
   try:
    with patch.object(server,'capture',return_value=json.dumps({'items':[node]})) as capture:
     result=server.status();self.assertTrue(result['reachable']);self.assertEqual(result['nodes'][0]['ram'],4096);self.assertEqual(capture.call_count,1);self.assertEqual(capture.call_args.args[0][0],'./kubectl.sh')
   finally:server.CONTEXT.root=previous
 def test_read_operations(self):
  for path,data in [('/api/pod',{}),('/api/resource-yaml',{}),('/api/terminal',dict(operation='open',pod='test',mode='logs')),('/api/terminal',dict(operation='poll'))]:remote.permit(path,data)

if __name__=='__main__':unittest.main()
