import subprocess,sys,tempfile
from pathlib import Path
script=Path(__file__).resolve().parents[1]/'scripts/prepare-box-25.py'
for controller in ['"IDE Controller"','"IDE"','(var.os_arch == "aarch64" ? "IDE" : "IDE Controller")']:
 with tempfile.TemporaryDirectory() as d:
  root=Path(d)/'packer_templates';(root/'scripts/_common').mkdir(parents=True)
  (root/'pkr-plugins.pkr.hcl').write_text('')
  (root/'pkr-builder.pkr.hcl').write_text('')
  source=root/'pkr-sources.pkr.hcl';source.write_text('["storagectl", "{{.Name}}", "--name", '+controller+', "--remove"]\n["storagectl", "{{.Name}}", "--name", "SATA", "--portcount", "2"]')
  subprocess.run([sys.executable,str(script),d],check=True)
  first=source.read_text()
  assert '--remove' not in first
  assert '"SATA", "--portcount", "2"' in first
  subprocess.run([sys.executable,str(script),d],check=True)
  assert source.read_text()==first
print('IDE cleanup removed from pristine and cached templates; SATA preserved; repeatability passed')
