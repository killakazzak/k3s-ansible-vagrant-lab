import contextlib, importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock
spec=importlib.util.spec_from_file_location('image_cache',Path(__file__).resolve().parents[1]/'scripts/image-cache.py')
cache=importlib.util.module_from_spec(spec);spec.loader.exec_module(cache)

class HostCacheTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  p=patch.dict(os.environ,{'K3S_LAB_CACHE_ROOT':self.tmp.name});p.start();self.addCleanup(p.stop)
 def archive(self,arch='arm64'):
  folder=Path(self.tmp.name)/'images'/arch;folder.mkdir(parents=True,exist_ok=True)
  path=folder/'image.tar';path.write_bytes(b'archive')
  path.with_suffix('.json').write_text(json.dumps(dict(arch=arch,digest='sha256:abc',refs=['docker.io/library/nginx:1.30.4-alpine'],sha256=cache.checksum(path))))
  return path
 def test_integrity_and_architecture(self):
  path=self.archive();self.assertEqual(len(cache.entries('arm64')),1);self.assertEqual(cache.entries('amd64'),[])
  path.write_bytes(b'corrupted');self.assertEqual(cache.entries('arm64'),[])
 def test_incomplete_export_is_not_used(self):
  folder=Path(self.tmp.name)/'images/arm64';folder.mkdir(parents=True);(folder/'unfinished.part').write_bytes(b'partial')
  self.assertEqual(cache.entries('arm64'),[])
 def test_restore_uses_local_archive_and_skips_present_image(self):
  self.archive()
  @contextlib.contextmanager
  def connections(root):yield lambda node:['ssh',node],['master','worker']
  calls=[]
  def run(args,**kw):
   calls.append(args)
   if args[-1].endswith('list -q'):return Mock(stdout='' if args[1]=='master' else 'docker.io/library/nginx:1.30.4-alpine\n')
   self.assertEqual(kw['stdin'].read(),b'archive');return Mock()
  with patch.object(cache,'connections',connections),patch.object(cache,'node_arch',return_value='arm64'),patch.object(cache,'run',side_effect=run):
   cache.restore(Path('/tmp'),['nginx:1.30.4-alpine'])
  imports=[c for c in calls if 'images import' in c[-1]]
  self.assertEqual(len(imports),1);self.assertEqual(imports[0][1],'master');self.assertNotIn('pull',str(calls))
 def test_capture_deduplicates_digest_and_does_not_pull(self):
  self.archive()
  @contextlib.contextmanager
  def connections(root):yield lambda node:['ssh',node],['master']
  listing='REF TYPE DIGEST SIZE\ndocker.io/library/nginx:1.30.4-alpine index sha256:abc 10MiB\n'
  with patch.object(cache,'connections',connections),patch.object(cache,'node_arch',return_value='arm64'),patch.object(cache,'run',return_value=Mock(stdout=listing)) as run:
   cache.capture(Path('/tmp'))
  self.assertEqual(run.call_count,1)
