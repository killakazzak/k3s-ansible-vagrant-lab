import unittest, tempfile, shutil, os, subprocess, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class DestroyTests(unittest.TestCase):
    def test_success_failure_and_recreate(self):
        for code in [1,0]:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                shutil.copytree(ROOT/'scripts',root/'scripts')
                shutil.copytree(ROOT/'ansible',root/'ansible')
                (root/'bin').mkdir()
                fake=root/'bin/vagrant';fake.write_text('#!/bin/sh\nexit '+str(code)+'\n');fake.chmod(0o755)
                inv=root/'ansible/inventory.yml';original=inv.read_bytes()
                result=subprocess.run(['ruby','scripts/destroy-cluster.rb'],cwd=root,env=dict(os.environ,PATH=str(root/'bin')+':'+os.environ['PATH']),capture_output=True)
                if code:
                    self.assertNotEqual(result.returncode,0)
                    self.assertEqual(inv.read_bytes(),original)
                else:
                    self.assertEqual(result.returncode,0,result.stderr)
                    text=subprocess.check_output(['ruby','-ryaml','-rjson','-e',"puts JSON.generate(YAML.load_file('ansible/inventory.yml'))"],cwd=root,text=True)
                    self.assertTrue(all(not v['hosts'] for v in json.loads(text)['all']['children'].values()))
                    backups=list((root/'.cache/deleted-clusters').glob('*/inventory.yml'))
                    self.assertEqual(backups[0].read_bytes(),original)
                    check="""require './scripts/menu'; m=ClusterMenu.new(Dir.pwd); c=m.settings;p={'masters'=>1,'workers'=>2,'network_mode'=>'existing'};%w[server workers].each{|r|p[r+'_cpu']=2;p[r+'_ram']=4096;p[r+'_disk']=64}; data,changes=m.creation_plan(p);raise unless data['all']['children']['server']['hosts'].size==1 && data['all']['children']['workers']['hosts'].size==2"""
                    subprocess.run(['ruby','-e',check],cwd=root,check=True)
if __name__=='__main__': unittest.main()
