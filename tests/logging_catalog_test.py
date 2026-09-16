import sys,json,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps as lab
import argocd_bundle as argo
class LoggingCatalogTests(unittest.TestCase):
 def plan(self,kind):return lab.Apps('/tmp').plan(dict(type=kind,name='test-'+kind,namespace='argocd-test' if kind=='argocd' else 'dev',host=kind+'.example.test'))
 def test_loki_collection_and_grafana(self):
  c,k,items,_=self.plan('loki');w=next(o for o in items if o['kind']==k);p=w['spec']['template']['spec']
  self.assertEqual(len(p['containers']),3);self.assertEqual(lab.pod_budget(p)['memory'],1024**3)
  config=next(o for o in items if o['kind']=='ConfigMap')['data'];ds=json.loads(config['datasources.json'])['datasources'][0]
  self.assertEqual(ds['url'],'http://127.0.0.1:3100');self.assertIn('names = ["dev"]',config['config.alloy'])
  self.assertEqual(json.loads(config['loki.json'])['limits_config']['retention_period'],'168h')
  self.assertFalse(any(o['kind']=='ClusterRole' for o in items));role=next(o for o in items if o['kind']=='Role');self.assertEqual(role['rules'][0]['verbs'],['get','list','watch'])
  self.assertEqual(next(o for o in items if o['kind']=='Ingress')['spec']['rules'][0]['http']['paths'][0]['backend']['service']['port']['number'],3000)
 def test_argocd_upstream_and_namespace_binding(self):
  c,k,items,_=self.plan('argocd');self.assertEqual(k,'Deployment')
  workloads=[o for o in items if o['kind'] in ('Deployment','StatefulSet')];self.assertEqual(len(workloads),7)
  visible=[o for o in workloads if not o['metadata']['labels'].get('lab.k3s/panel-for')];self.assertEqual([o['metadata']['name'] for o in visible],['test-argocd'])
  for o in items:
   if o['kind'] not in argo.CLUSTER_KINDS:self.assertEqual(o['metadata']['namespace'],'argocd-test')
   for s in o.get('subjects',[]):
    if s['kind']=='ServiceAccount':self.assertEqual(s['namespace'],'argocd-test')
  service=next(o for o in items if o['kind']=='Service' and o['metadata']['name']=='test-argocd');self.assertEqual(service['spec']['ports'][0]['port'],8080)
  self.assertEqual(len([o for o in items if o['kind']=='CustomResourceDefinition']),3)
  self.assertTrue(all('requests' in container['resources'] for o in workloads for container in o['spec']['template']['spec']['containers']))
 def test_argocd_validation(self):
  with self.assertRaises(ValueError):lab.validate(dict(type='argocd',name='cd',namespace='dev'))
  with self.assertRaises(ValueError):lab.validate(dict(type='argocd',name='cd',namespace='argocd',storage_mode='new'))
  with self.assertRaises(ValueError):lab.validate(dict(type='argocd',name='cd',namespace='argocd',image='quay.io/argoproj/argocd:v3.5.2'))
 def test_all_components_start_before_waiting(self):
  _,_,items,_=self.plan('argocd');workloads=[o for o in items if o['kind'] in ('Deployment','StatefulSet')];app=Mock();app.get.return_value={'items':workloads}
  argo.lifecycle(app,'argocd-test','test-argocd','app_start')
  calls=[c[0] for c in app.mock_calls];self.assertLess(max(i for i,n in enumerate(calls) if n=='kubectl'),min(i for i,n in enumerate(calls) if n=='wait_rollout'))
  self.assertEqual(app.kubectl.call_count,7)
 def test_delete_preserves_crds_and_applications(self):
  _,_,items,_=self.plan('argocd');app=Mock();app.get.side_effect=lambda kind,ns:{'items':[o for o in items if o['kind'] in (('Deployment','StatefulSet') if kind=='deployments,statefulsets' else ('Service',) if kind=='services' else ('Ingress',))]}
  argo.delete(app,'argocd-test','test-argocd')
  for call in app.kubectl.call_args_list:self.assertIn(call.args[0][1],['Deployment','StatefulSet','Service','Ingress'])
if __name__=='__main__':unittest.main()
