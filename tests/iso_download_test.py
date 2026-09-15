import hashlib,importlib.util,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('iso',Path(__file__).resolve().parents[1]/'scripts/prepare-iso.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as d:
 root=Path(d);data=b'test ISO';sha=hashlib.sha256(data).hexdigest();var=root/'vars.hcl';out=root/'local.json';cache=root/'cache'
 var.write_text('iso_url = "https://example.org/ubuntu.iso"\niso_checksum = "sha256:'+sha+'"\n')
 class Download:
  def __init__(self,args):
   Path(args[args.index('-o')+1]).write_bytes(data);self.returncode=0
  def poll(self):return self.returncode
 with patch.object(sys,'argv',['iso',str(var),str(cache),str(out)]),patch.object(m.subprocess,'Popen',Download):m.main()
 result=json.loads(out.read_text());assert Path(result['iso_url']).read_bytes()==data;assert result['iso_checksum']=='sha256:'+sha
 with patch.object(sys,'argv',['iso',str(var),str(cache),str(out)]),patch.object(m.subprocess,'Popen',side_effect=AssertionError('cached ISO must not download')):m.main()
 Path(result['iso_url']).unlink()
 data=b'corrupt'
 with patch.object(sys,'argv',['iso',str(var),str(cache),str(out)]),patch.object(m.subprocess,'Popen',Download):
  try:m.main();raise AssertionError('accepted corrupt image')
  except ValueError as e:assert 'checksum mismatch' in str(e)
 assert not Path(result['iso_url']).exists()
print('ISO download: local file, verified cache and corrupt image rejection passed')
with tempfile.TemporaryDirectory() as d:
 root=Path(d);project=root/'project';cache=root/'shared';data=b'cached Ubuntu';sha=hashlib.sha256(data).hexdigest();name='ubuntu.iso'
 old=project/'.clusters/k8s-cluster1/.cache/box25/iso'/sha[:16]/name;old.parent.mkdir(parents=True);old.write_bytes(data)
 m.migrate_legacy(cache,sha,name,project)
 target=cache/sha[:16]/name
 assert target.read_bytes()==data and not old.exists()
 import shutil
 shutil.rmtree(project)
 assert target.read_bytes()==data
 project.mkdir();old=project/'.cache/box25/iso'/sha[:16]/name;old.parent.mkdir(parents=True);old.write_bytes(b'bad')
 target.unlink();m.migrate_legacy(cache,sha,name,project)
 assert not target.exists() and old.exists()
 old.unlink();partial=old.with_name(name+'.part');partial.write_bytes(b'cached')
 m.migrate_legacy(cache,sha,name,project)
 assert target.with_name(name+'.part').read_bytes()==b'cached' and not partial.exists()
print('Shared cache migration: checksum, partial download and survival after project deletion passed')
