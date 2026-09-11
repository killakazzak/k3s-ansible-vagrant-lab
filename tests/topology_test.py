import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
from topology import build
class TopologyTests(unittest.TestCase):
 def test_namespace_and_endpoint_links(self):
  result=build([
   {'kind':'Ingress','metadata':{'name':'site','namespace':'a'},'spec':{'rules':[{'host':'example.test','http':{'paths':[{'path':'/','backend':{'service':{'name':'web','port':{'number':80}}}}]}}]}},
   {'kind':'EndpointSlice','metadata':{'namespace':'a','labels':{'kubernetes.io/service-name':'web'}},'endpoints':[{'targetRef':{'kind':'Pod','name':'pod'},'conditions':{'ready':False},'addresses':['10.0.0.1']}]},
   {'kind':'Pod','metadata':{'name':'pod','namespace':'a'},'spec':{'nodeName':'worker','containers':[{'env':[{'value':'never-return-secret'}]}]}},
   {'kind':'Node','metadata':{'name':'worker'}},
   {'kind':'Node','metadata':{'name':'master','labels':{'node-role.kubernetes.io/control-plane':''}}}
  ])
  self.assertEqual(result['routes'][0]['service'],'a/web')
  self.assertEqual(result['endpoints'][0]['pod'],'a/pod')
  self.assertFalse(result['endpoints'][0]['ready'])
  self.assertEqual(result['pods'][0]['node'],'worker')
  self.assertEqual([n['role'] for n in result['nodes']],['Worker','Master'])
  self.assertNotIn('never-return-secret',str(result))
 def test_internal_traefik_is_not_service(self):
  r=build([{'kind':'IngressRoute','metadata':{'name':'dashboard'},'spec':{'routes':[{'match':'Host(`test`)','services':[{'name':'api@internal','kind':'TraefikService'}]}]}}])['routes'][0]
  self.assertIsNone(r['service']);self.assertEqual(r['internal'],'api@internal')
