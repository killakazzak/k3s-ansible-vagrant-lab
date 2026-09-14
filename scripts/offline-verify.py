#!/usr/bin/env python3
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();manifest=json.loads((root/'manifest.json').read_text())
for name,expected in manifest['sha256'].items():
 path=(root/name).resolve()
 if not path.is_relative_to(root):raise SystemExit('Invalid bundle path')
 digest=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
 if digest.hexdigest()!=expected:raise SystemExit('Checksum mismatch: '+name)
print('Offline bundle verified: '+str(len(manifest['sha256']))+' files')
