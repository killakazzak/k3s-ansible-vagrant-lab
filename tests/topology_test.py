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

class OwnershipTests(unittest.TestCase):
 def test_owner_chains_and_service_types(self):
  def obj(kind,name,uid,owner=None):
   meta={'name':name,'namespace':'demo','uid':uid}
   if owner:meta['ownerReferences']=[dict(kind=owner[0],name=owner[1],uid=owner[2],controller=True)]
   return {'kind':kind,'metadata':meta}
  items=[obj('Deployment','web','d'),obj('ReplicaSet','web-123','r',('Deployment','web','d')),obj('Pod','web-pod','p',('ReplicaSet','web-123','r')),
   obj('DaemonSet','agent','ds'),obj('Pod','agent-pod','p2',('DaemonSet','agent','ds')),
   obj('CronJob','backup','cj'),obj('Job','backup-1','j',('CronJob','backup','cj')),obj('Pod','backup-pod','p3',('Job','backup-1','j')),obj('Pod','manual','p4'),
   {'kind':'Service','metadata':{'name':'headless'},'spec':{'type':'ClusterIP','clusterIP':'None'}},
   {'kind':'Service','metadata':{'name':'lb'},'spec':{'type':'LoadBalancer'}}]
  data=build(items)
  self.assertEqual([p['workload']['kind'] for p in data['pods']],['Deployment','DaemonSet','CronJob','Pod'])
  self.assertEqual([c['kind'] for c in data['pods'][0]['workload']['chain']],['ReplicaSet','Deployment'])
  self.assertTrue(data['services'][0]['headless'])
  self.assertEqual(data['services'][1]['type'],'LoadBalancer')

class MultiControllerTests(unittest.TestCase):
 def test_standard_classes_and_nodeport(self):
  for controller in ['nginx.org/ingress-controller','haproxy.org/ingress-controller','traefik.io/ingress-controller','example.org/controller']:
   items=[{'kind':'IngressClass','metadata':{'name':'my-class','annotations':{'meta.helm.sh/release-name':'edge','meta.helm.sh/release-namespace':'edge'}},'spec':{'controller':controller}}, {'kind':'Service','metadata':{'name':'edge','namespace':'edge','labels':{'app.kubernetes.io/instance':'edge'}},'spec':{'type':'NodePort','ports':[{'port':80,'nodePort':30226}]}}, {'kind':'Ingress','metadata':{'name':'web','namespace':'dev'},'spec':{'ingressClassName':'my-class','rules':[{'host':'web.test','http':{'paths':[{'path':'/','backend':{'service':{'name':'web','port':{'number':80}}}}]}}]}}]
   route=build(items)['routes'][0];self.assertIn(controller,route['controller']);self.assertEqual(route['entryPort'],30226);self.assertEqual(route['service'],'dev/web')
 def test_controller_without_routes(self):
  result=build([{'kind':'IngressClass','metadata':{'name':'lab-nginx'},'spec':{'controller':'nginx.org/ingress-controller'}}])
  self.assertTrue(result['routes'][0]['controllerOnly']);self.assertIsNone(result['routes'][0]['service'])
 def test_nginx_virtualserver(self):
  result=build([{'kind':'VirtualServer','metadata':{'name':'web','namespace':'dev'},'spec':{'host':'web.test','upstreams':[{'name':'backend','service':'web','port':80}],'routes':[{'path':'/','action':{'pass':'backend'}}]}}])
  self.assertEqual(result['routes'][0]['service'],'dev/web')
 def test_traefik_tcp_udp(self):
  for kind,protocol in [('IngressRouteTCP','TCP'),('IngressRouteUDP','UDP')]:
   result=build([{'kind':kind,'metadata':{'name':'db','namespace':'dev'},'spec':{'routes':[{'services':[{'name':'db','port':5432}]}]}}])
   self.assertEqual(result['routes'][0]['protocol'],protocol);self.assertEqual(result['routes'][0]['service'],'dev/db')
