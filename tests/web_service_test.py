import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, parse_qs
ROOT=Path(__file__).resolve().parents[1]
class WebServiceTests(unittest.TestCase):
    def test_background_start_repeat_stop_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shutil.copytree(ROOT/'web',root/'web')
            (root/'scripts').mkdir()
            shutil.copy(ROOT/'scripts/web-service.py',root/'scripts/web-service.py')
            command=[sys.executable,str(root/'scripts/web-service.py')]
            def run(*args):return subprocess.run(command+list(args),capture_output=True,text=True,timeout=15)
            try:
                self.assertEqual(run('start','--port','0').returncode,0)
                info=(root/'.cache/web.lock').read_text()
                self.assertEqual(run('start').returncode,0)
                self.assertEqual((root/'.cache/web.lock').read_text(),info)
                url=json.loads(info)['url'];parsed=urlsplit(url)
                token=parse_qs(parsed.fragment)['token'][0]
                self.assertIn('работает',run('status').stdout)
                self.assertEqual(os.stat(root/'.cache/web-server.log').st_mode & 0o777,0o600)
                self.assertEqual(run('stop').returncode,0)
                self.assertIn('остановлен',run('status').stdout)
                self.assertEqual(run('stop').returncode,0)
            finally:run('stop')
