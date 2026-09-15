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
