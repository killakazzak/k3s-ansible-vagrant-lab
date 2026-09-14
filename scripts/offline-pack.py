#!/usr/bin/env python3
"""Create release parts below GitHub's per-asset limit; never include cluster state."""
import hashlib
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'vendor/offline'
DEST = ROOT / '.cache/offline-release'
subprocess.run([sys.executable, str(ROOT / 'scripts/offline-finalize.py')], check=True)
DEST.mkdir(parents=True, exist_ok=True)


class Parts:
    limit = 1800 * 1024 * 1024

    def __init__(self):
        self.file = None
        self.size = 0
        self.rows = []

    def finish_part(self):
        if self.file:
            self.file.close()
            self.rows.append(self.digest.hexdigest() + '  ' + self.name)
            self.file = None

    def write(self, data):
        original = len(data)
        while data:
            if self.file is None:
                self.name = 'offline-macos-arm64.tar.part-%03d' % len(self.rows)
                self.file = (DEST / self.name).open('wb')
                self.size = 0
                self.digest = hashlib.sha256()
            piece = data[:self.limit - self.size]
            self.file.write(piece)
            self.digest.update(piece)
            self.size += len(piece)
            data = data[len(piece):]
            if self.size == self.limit:
                self.finish_part()
        return original


parts = Parts()
with tarfile.open(fileobj=parts, mode='w|') as archive:
    for path in sorted(BUNDLE.rglob('*')):
        if path.is_file():
            info = archive.gettarinfo(str(path), arcname='offline/' + str(path.relative_to(BUNDLE)))
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            with path.open('rb') as stream:
                archive.addfile(info, stream)
parts.finish_part()
(ROOT / 'offline/RELEASE-SHA256SUMS').write_text('\n'.join(parts.rows) + '\n')
shutil.copy2(BUNDLE / 'manifest.json', ROOT / 'offline/manifest-macos-arm64.json')
print('Release parts:', len(parts.rows), 'in', DEST)
