import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import job_logs
class JobLogTests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name);self.job=dict(id='0123456789abcdef',cluster='test',action='create',state='running',started=100,log='')
 def test_full_log_survives_ui_tail_and_restart(self):
  job_logs.save(self.root,self.job,begin=True);full='START\n'+'x'*160000+'\nDONE\n';job_logs.save(self.root,self.job,line=full)
  self.job.update(log=full[-150000:],finished=566,state='success');job_logs.save(self.root,self.job)
  result=job_logs.export(self.root,self.job['id']);self.assertIn(full,result['text']);self.assertIn('466 с',result['text']);self.assertTrue(result['filename'].endswith('.log'))
  recovered=job_logs.latest(self.root);self.assertEqual(recovered['state'],'success');self.assertEqual(len(recovered['log']),150000)
 def test_running_snapshot_and_ansi(self):
  job_logs.save(self.root,self.job,begin=True);job_logs.save(self.root,self.job,line='\x1b[32mготово\x1b[0m\n');result=job_logs.export(self.root,self.job['id'],self.job)
  self.assertIn('готово',result['text']);self.assertNotIn('\x1b',result['text']);self.assertIn('running',result['text'])
 def test_traversal_rejected_and_buffer_fallback_labelled(self):
  with self.assertRaises(ValueError):job_logs.export(self.root,'../../secret')
  self.assertIn('могло быть обрезано',job_logs.export(self.root,self.job['id'],self.job)['text'])
 def test_interrupted_operation_is_not_reported_running(self):
  job_logs.save(self.root,self.job,begin=True);self.assertIn('итог операции неизвестен',job_logs.latest(self.root)['log'])
if __name__=='__main__':unittest.main()
