import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps
class LocalParityTests(unittest.TestCase):
 def test_local_plan_honors_selected_ingress_and_storage(self):
  with tempfile.TemporaryDirectory() as root:
   app=lab_apps.Apps(root)
   with patch.object(app,'find',return_value={'metadata':{'name':'lab-nginx'}}):
    _,_,objects,_=app.plan(dict(type='nginx',name='web',namespace='dev',host='web.example.org',publication='ingress',ingress_class='lab-nginx',storage_class='fast'))
   route=next(o for o in objects if o['kind']=='Ingress')
   self.assertEqual(route['spec']['ingressClassName'],'lab-nginx')
   self.assertFalse(any(k.startswith('traefik.') for k in route['metadata'].get('annotations',{})))
 def test_local_storage_without_publication(self):
  with tempfile.TemporaryDirectory() as root:
   app=lab_apps.Apps(root)
   with patch.object(app,'host',return_value='db.example.org'):
    _,_,objects,_=app.plan(dict(type='postgres',name='db',namespace='dev',publication='internal',storage_class='fast'))
   sts=next(o for o in objects if o['kind']=='StatefulSet')
   self.assertEqual(sts['spec']['volumeClaimTemplates'][0]['spec']['storageClassName'],'fast')
   self.assertFalse(any(o['kind']=='Ingress' for o in objects))
