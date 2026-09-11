import importlib.util
import json
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('console', Path(__file__).resolve().parents[1] / 'web/server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class ConsoleTests(unittest.TestCase):
    def setUp(self):
        app.JOB = None
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
    def request(self, path='/api/job', payload=None, token=True, headers=None):
        hdr = {'X-Lab-Token': app.TOKEN} if token else {}
        hdr.update(headers or {})
        req = Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps(payload).encode() if payload is not None else None, headers=hdr)
        try:
            with urlopen(req) as response: return response.status, response.read()
        except HTTPError as e: return e.code, e.read()
    def test_requires_token(self):
        self.assertEqual(self.request(token=False)[0], 401)
    def test_rejects_foreign_origin_and_host(self):
        self.assertEqual(self.request(headers={'Origin':'https://example.com'})[0],403)
        self.assertEqual(self.request(headers={'Host':'attacker.test'})[0],403)
    def test_destructive_confirmation_and_allowlist(self):
        for payload in [{'action':'destroy','confirmed':True},{'action':'shell','confirmed':True},{'action':'verify','confirmed':False}]:
            self.assertEqual(self.request('/api/action',payload)[0],400)
        self.assertIsNone(app.JOB)
    def test_one_job_at_a_time(self):
        app.JOB={'state':'running'}
        self.assertEqual(self.request('/api/action',{'action':'verify','confirmed':True})[0],409)
    def test_dispatches_allowed_job_without_real_mutation(self):
        called=threading.Event()
        def fake(job,payload): called.set()
        with patch.object(app,'execute',side_effect=fake):
            self.assertEqual(self.request('/api/action',{'action':'verify','confirmed':True})[0],202)
            self.assertTrue(called.wait(2))
        self.assertEqual(app.JOB['action'],'verify')
    def test_static_no_path_traversal(self):
        self.assertEqual(self.request('/../ansible/inventory.yml')[0],404)

class RepeatedLaunchTests(unittest.TestCase):
    def test_reuses_existing_server_and_keeps_private_url(self):
        import tempfile, shutil, subprocess, sys, os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'web').mkdir()
            shutil.copy(Path(app.__file__), root / 'web/server.py')
            command = [sys.executable, str(root / 'web/server.py'), '--port', '0']
            first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(first.stdout.readline().strip(), '')
                initial = first.stdout.readline().strip().split(' → ')[1]
                again = subprocess.run(command, capture_output=True, text=True, timeout=5)
                self.assertEqual(again.returncode, 0)
                self.assertIn(initial, again.stdout)
                self.assertEqual(os.stat(root / '.cache/web.lock').st_mode & 0o777, 0o600)
            finally:
                first.terminate()
                first.communicate(timeout=5)

if __name__ == '__main__': unittest.main()
