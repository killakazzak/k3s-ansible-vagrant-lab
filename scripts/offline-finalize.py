#!/usr/bin/env python3
import base64,hashlib,json,tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];bundle=root/'vendor/offline'
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
required=['ubuntu-25gb.box','kubectl','k3s/k3s-arm64','k3s/install.sh','images/k3s-airgap-images-arm64.tar.zst','host/VirtualBox.dmg','host/python-3.13.7-macos11.pkg','charts/rancher.tgz','charts/cert-manager.tgz']
if len(list((bundle/'host/wheels').glob('*.whl'))) < 9:raise SystemExit('Ansible wheelhouse is incomplete')
images=(bundle/'images/list.txt').read_text().splitlines()
required+=['images/catalog-%03d.tar'%i for i in range(len(images))]
for name in required:
 if not (bundle/name).is_file():raise SystemExit('Missing: '+name)
def canonical(name):
 if '/' not in name:return 'docker.io/library/'+name
 if '.' not in name.split('/')[0] and ':' not in name.split('/')[0]:return 'docker.io/'+name
 return name
for i,image in enumerate(images):
 with tarfile.open(bundle/('images/catalog-%03d.tar'%i)) as archive:
  archive.getmembers()  # Reject truncated streams before publishing checksums.
  manifests=json.load(archive.extractfile('manifest.json'))
  tags={canonical(tag) for entry in manifests for tag in entry.get('RepoTags',[]) or []}
  if image not in tags:raise SystemExit('Wrong image archive: '+image)
if list(bundle.rglob('*.part')):raise SystemExit('Partial download remains')
for p in (bundle/'charts').glob('*.tgz'):p.with_suffix('.b64').write_text(base64.b64encode(p.read_bytes()).decode())
for relative,source,name in [('images/k3s-airgap-images-arm64.tar.zst','k3s/sha256sum-arm64.txt','k3s-airgap-images-arm64.tar.zst'),('k3s/k3s-arm64','k3s/sha256sum-arm64.txt','k3s-arm64'),('host/VirtualBox.dmg','host/VirtualBox-SHA256SUMS','VirtualBox-7.2.16-174877-macOSArm64.dmg')]:
 expected=next(line.split()[0] for line in (bundle/source).read_text().splitlines() if line.split()[-1].lstrip('*')==name)
 if digest(bundle/relative)!=expected:raise SystemExit('Upstream checksum mismatch: '+relative)
if digest(bundle/'kubectl') != (bundle/'kubectl.sha256').read_text().strip():raise SystemExit('kubectl checksum mismatch')
hashes={}
for p in sorted(bundle.rglob('*')):
 if not p.is_file() or p.name in ('manifest.json','SHA256SUMS'):continue
 if p.is_symlink():raise SystemExit('Symlink forbidden: '+str(p))
 hashes[str(p.relative_to(bundle))]=digest(p)
manifest=dict(platform='darwin-arm64',python_version='3.13.7',ansible_version='2.21.3',virtualbox_version='7.2.16',vagrant_version='2.4.9',box='k8s-lab/ubuntu-24.04-25gb',k3s_version='v1.36.4+k3s1',rancher_version='2.15.1',cert_manager_version='v1.21.1',images=images,sha256=hashes)
(bundle/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
hashes['manifest.json']=hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()
(bundle/'SHA256SUMS').write_text(''.join(value+'  '+name+'\n' for name,value in hashes.items()))
print('Finalized',len(hashes),'files')
