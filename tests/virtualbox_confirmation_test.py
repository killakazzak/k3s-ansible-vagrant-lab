from pathlib import Path
import tempfile, shutil, subprocess, os, pty, select, time
source=Path(__file__).resolve().parents[1]/'scripts/install-virtualbox.sh'
for platform in ['darwin','linux']:
 with tempfile.TemporaryDirectory() as folder:
  root=Path(folder);scripts=root/'scripts';scripts.mkdir()
  shutil.copy(source,scripts/'install-virtualbox.sh')
  (scripts/'host-platform.sh').write_text('LAB_HOST_OS='+platform+'\nLAB_HOST_LABEL=Test\nLAB_ARCH_LABEL=test\ncommand() { if [[ "$1" == -v && "$2" == VBoxManage ]]; then return 1; fi; builtin command "$@"; }\nlab_sudo() { echo UNEXPECTED_INSTALL; exit 90; }\n')
  (scripts/'download.sh').write_text('#!/bin/bash\necho DOWNLOAD_REACHED\nexit 99\n');(scripts/'download.sh').chmod(0o755)
  r=subprocess.run(['bash',str(scripts/'install-virtualbox.sh')],input='',capture_output=True,text=True)
  assert r.returncode==1 and 'DOWNLOAD_REACHED' not in r.stdout and 'UNEXPECTED_INSTALL' not in r.stdout
  for answer,expected in [('0',1),('',1),('1',99)]:
   master,slave=pty.openpty()
   p=subprocess.Popen(['bash',str(scripts/'install-virtualbox.sh')],stdin=slave,stdout=slave,stderr=slave);os.close(slave)
   output=b'';sent=False;deadline=time.time()+10
   while time.time()<deadline:
    if select.select([master],[],[],.1)[0]:
     try:part=os.read(master,8192)
     except OSError:break
     output+=part
     if b': ' in output and not sent:os.write(master,(answer+'\n').encode());sent=True
    if p.poll() is not None:break
   p.wait(timeout=2);os.close(master)
   assert p.returncode==expected,(platform,answer,p.returncode,output)
 print(platform+': no TTY, refusal, Enter cancellation and explicit approval passed')
