import os,sys,tempfile,subprocess,unittest,json
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/download.sh'
class DownloadTests(unittest.TestCase):
 def run_download(self,failures):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);curl=root/'curl';state=root/'calls.json';dest=root/'file';dest.write_text('previous verified cache')
   curl.write_text('#!'+sys.executable+'\n'+'''import os,sys,json
from pathlib import Path
p=Path(os.environ['CALLS']);calls=json.loads(p.read_text()) if p.exists() else [];calls.append(sys.argv[1:]);p.write_text(json.dumps(calls))
Path(sys.argv[sys.argv.index('-o')+1]).write_text('partial' if len(calls)<=int(os.environ['FAILURES']) else 'complete')
sys.exit(28 if len(calls)<=int(os.environ['FAILURES']) else 0)
''');curl.chmod(0o755)
   env=dict(os.environ,PATH=str(root)+':'+os.environ['PATH'],CALLS=str(state),FAILURES=str(failures),K3S_DOWNLOAD_RETRY_DELAY='0')
   result=subprocess.run(['bash',str(SCRIPT),'kubectl checksum','https://example.test/kubectl.sha256',str(dest)],env=env,capture_output=True,text=True)
   calls=json.loads(state.read_text());content=dest.read_text();partials=list(root.glob('file.part.*'))
   for args in calls:
    self.assertEqual(args[args.index('--connect-timeout')+1],'10')
    self.assertEqual(args[args.index('--speed-time')+1],'20')
   self.assertFalse(partials)
   return result,calls,content
 def test_timeout_retries_and_logs_file_source(self):
  result,calls,content=self.run_download(2)
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(len(calls),3);self.assertEqual(content,'complete')
  for text in ('kubectl checksum','https://example.test/kubectl.sha256','Попытка 3/4','[Готово]'):self.assertIn(text,result.stdout)
 def test_failed_download_preserves_previous_cache(self):
  result,calls,content=self.run_download(9)
  self.assertEqual(result.returncode,28);self.assertEqual(len(calls),4);self.assertEqual(content,'previous verified cache')
  self.assertIn('после 4 попыток',result.stderr)
