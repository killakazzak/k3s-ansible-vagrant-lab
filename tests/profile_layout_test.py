import tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import profile_layout as layout

class ProfileLayoutTests(unittest.TestCase):
 def fixture(self,root):
  (root/'ansible/group_vars').mkdir(parents=True)
  (root/'ansible/group_vars/all.yml').write_text('rancher_enabled: false\n')
  (root/'ansible/inventory.yml').write_text('inventory')
  (root/'ansible/site.yml').write_text('shared v1')
  for name in ('scripts','web','vendor'):(root/name).mkdir()
  for name in layout.TOP_FILES:(root/name).write_text('code')
 def test_new_profile_shares_code_and_keeps_configuration(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root);profile=root/'.clusters/test';profile.mkdir(parents=True)
   layout.initialize(root,profile)
   (root/'ansible/site.yml').write_text('shared v2')
   self.assertEqual((profile/'ansible/site.yml').read_text(),'shared v2')
   (profile/'ansible/group_vars/all.yml').write_text('private settings')
   self.assertNotEqual((profile/'ansible/group_vars/all.yml').read_text(),(root/'ansible/group_vars/all.yml').read_text())
   self.assertTrue((profile/'scripts').is_symlink())
 def test_migration_preserves_data_and_backs_up_old_code(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.fixture(root);profile=root/'.clusters/test';(profile/'ansible/group_vars').mkdir(parents=True)
   protected=['ansible/inventory.yml','ansible/group_vars/all.yml','kubeconfig','.vagrant/machines/node/virtualbox/id']
   for name in protected:
    p=profile/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('private '+name)
   (profile/'deploy.sh').write_text('custom deploy')
   layout.migrate(root,profile)
   for name in protected:self.assertEqual((profile/name).read_text(),'private '+name)
   self.assertEqual(next((root/'.cache/profile-code-backups').glob('*/test/deploy.sh')).read_text(),'custom deploy')
   self.assertEqual(layout.migrate(root,profile),[])
