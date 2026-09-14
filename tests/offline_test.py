"""Bundle integrity checks run without network or host installation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

VERIFY = Path(__file__).resolve().parents[1] / 'scripts/offline-verify.py'


class OfflineIntegrityTests(unittest.TestCase):
    def test_integrity_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / 'asset'
            asset.write_bytes(b'original')
            (root / 'manifest.json').write_text(json.dumps({
                'sha256': {'asset': hashlib.sha256(b'original').hexdigest()}
            }))
            def check():
                return subprocess.run([sys.executable, str(VERIFY), directory], capture_output=True).returncode
            self.assertEqual(check(), 0)
            asset.write_bytes(b'changed')
            self.assertNotEqual(check(), 0)
            asset.unlink()
            self.assertNotEqual(check(), 0)

    def test_manifest_cannot_read_outside_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_text(json.dumps({'sha256': {'../outside': '0' * 64}}))
            result = subprocess.run([sys.executable, str(VERIFY), directory], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Invalid bundle path', result.stderr)
