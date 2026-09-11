import sys, os, tempfile, time, unittest, base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import terminal_sessions as terminal
class TerminalTests(unittest.TestCase):
    def test_shell_completion_resize_scope_and_control_c(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'kubeconfig').write_text('fixture')
            (root/'unique-tab-completion').touch()
            env=dict(os.environ)
            session=terminal.handle({'operation':'open'},root,env)['id']
            offset=0
            def call(operation,**kwargs):return terminal.handle(dict(operation=operation,id=session,**kwargs),root,env)
            def until(marker):
                nonlocal offset
                text=''
                end=time.monotonic()+10
                while time.monotonic()<end:
                    data=call('poll',offset=offset);offset=data['offset'];text+=base64.b64decode(data['output']).decode(errors='replace')
                    if marker in text:return text
                self.fail('Expected marker missing: '+repr(marker)+' in '+repr(text))
            try:
                until('Ctrl+C')
                call('input',input='print READY_$((17+23))\r')
                until('READY_40')
                call('input',input='print $KUBECONFIG\r')
                until(str(root/'kubeconfig'))
                call('input',input='echo unique-tab-\t')
                until('completion')
                call('input',input='\x03')
                call('resize',cols=80,rows=30)
                call('input',input='stty size\r')
                until('30 80')
                call('input',input='sleep 30\r')
                time.sleep(.2)
                call('input',input='\x03')
                call('input',input='print INTERRUPTED_$((1+1))\r')
                until('INTERRUPTED_2')
                with self.assertRaises(ValueError):terminal.handle({'operation':'poll','id':session},root/'other',env)
            finally:call('close')
            self.assertNotIn(session,terminal.SESSIONS)
