import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import remote_rancher as r
class RancherTests(unittest.TestCase):
 def test_validate(self):
  c=r.validate({'host':'rancher.example.org','ingress_class':'lab-nginx','replicas':1});self.assertEqual(c['host'],'rancher.example.org')
  for h in ('http://example.org','a..b','localhost','x/y.com',None):
   with self.assertRaises(ValueError):r.validate({'host':h,'ingress_class':'lab-nginx'})
 def test_reviewed_versions_cannot_change(self):
  with patch.object(r,'preview',return_value={'version':'2.14.2','cert_version':None,'install_cert':False}),patch.object(r.subprocess,'run') as run:
   with self.assertRaisesRegex(ValueError,'cert-manager'):r.install(Path('/repo'),{},Path('/root'),{'version':'2.14.1'})
   run.assert_not_called()
 def test_empty_status(self):
  with patch.object(r.ingress,'client',return_value=['kubectl']),patch.object(r.ingress,'run',return_value=''):
   self.assertFalse(r.status(Path('/repo'),{},Path('/root'))['installed'])
 def test_stable_chart_version_parser(self):
  with patch.object(r.ingress,'run',return_value='version: 2.14.2\n'):
   self.assertEqual(r.version('helm','rancher',r.RANCHER_REPO),'2.14.2')
if __name__=='__main__':unittest.main()
