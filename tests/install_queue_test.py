import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
from install_queue import InstallQueue
import server
class QueueTests(unittest.TestCase):
 def job(self,n,state='queued'):return dict(id=n,cluster='c',action='app_deploy',state=state,title=n,queued_at=0,targets=[('dev',n)])
 def test_fifo_frozen_parameters_and_cancel(self):
  q=InstallQueue();payload={'apps':[{'name':'one'}]};q.add(self.job('one'),payload,None);payload['apps'][0]['name']='changed';q.add(self.job('two'),{},None)
  self.assertEqual(q.pop()[1]['apps'][0]['name'],'one');self.assertEqual(q.cancel('two')['id'],'two');self.assertFalse(q.items)
 def test_conflicts_and_cluster_changes(self):
  q=InstallQueue();active=self.job('one','running')
  with self.assertRaises(ValueError):q.add(self.job('one'),{},active)
  active['action']='create'
  with self.assertRaises(ValueError):q.add(self.job('two'),{},active)
  q.add(self.job('two'),{},None)
  with self.assertRaises(ValueError):q.add(self.job('two'),{},None)
 def test_failed_install_advances(self):
  q=InstallQueue();first=self.job('one','running');first['dispatching']=True;q.add(self.job('two'),{'action':'app_deploy'},first)
  def execute(job,payload):job['state']='failed'
  with patch.object(server,'INSTALL_QUEUE',q),patch.object(server,'JOB',first),patch.object(server,'execute',side_effect=execute),patch.object(server.threading,'Thread') as thread:
   server.execute_queued(first,{})
   self.assertEqual(server.JOB['id'],'two');self.assertEqual(server.JOB['state'],'running');self.assertTrue(server.JOB['dispatching']);thread.return_value.start.assert_called_once();self.assertNotIn('dispatching',first)
 def test_capacity(self):
  q=InstallQueue()
  for n in range(20):q.add(self.job(str(n)),{},None)
  with self.assertRaises(ValueError):q.add(self.job('overflow'),{},None)
if __name__=='__main__':unittest.main()
