import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))
from network_access import valid_authority, local_ipv4

class NetworkAccessTest(unittest.TestCase):
    def test_local_address(self):
        self.assertTrue(valid_authority('127.0.0.1:8765', 8765))
        self.assertTrue(valid_authority('localhost:8765', 8765))

    def test_reject_foreign_or_malformed_authority(self):
        for host in ['foreign.invalid:8765', '0.0.0.0:8765', '127.0.0.1:1', '127.0.0.1:8765@foreign.invalid', '127.0.0.1:8765/path']:
            self.assertFalse(valid_authority(host, 8765), host)

    def test_discovery_includes_loopback(self):
        self.assertIn('127.0.0.1', local_ipv4())
