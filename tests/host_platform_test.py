import os, subprocess, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class HostPlatformTests(unittest.TestCase):
    def run_platform(self, system, machine, release='ID=ubuntu\nVERSION_ID=22.04\n', prepare=False, existing=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binpath = root/'bin'; binpath.mkdir()
            for name, body in {'uname': 'case "$1" in -s) echo '+system+';; -m) echo '+machine+';; esac', 'dpkg-query': 'echo "install ok installed"', 'shasum': 'exit 0', 'gpg': 'exit 0', 'rsync': 'exit 0'}.items():
                path = binpath/name; path.write_text('#!/bin/bash\n'+body+'\n'); path.chmod(0o755)
            releasepath=root/'os-release'; releasepath.write_text(release)
            script=root/'platform.sh'; script.write_text((ROOT/'scripts/host-platform.sh').read_text().replace('/etc/os-release',str(releasepath)))
            config=root/'ansible/group_vars/all.yml'; config.parent.mkdir(parents=True); config.write_text('vm_architecture: arm64\n')
            if existing:
                state=root/'.vagrant/machines/node/virtualbox/id'; state.parent.mkdir(parents=True);state.write_text('existing-vm')
            command='set -e; ROOT="$1"; source "$ROOT/platform.sh"; '
            if prepare: command+='lab_host_prepare; '
            command+='echo "$LAB_HOST_OS/$LAB_HOST_ARCH"'
            result=subprocess.run(['bash','-c',command,'test',str(root)],env=dict(os.environ,PATH=str(binpath)+':'+os.environ['PATH']),text=True,capture_output=True)
            return result,config.read_text()
    def test_mac_unchanged(self):
        result,_=self.run_platform('Darwin','arm64'); self.assertEqual(result.returncode,0);self.assertIn('darwin/arm64',result.stdout)
    def test_ubuntu_detection(self):
        result,_=self.run_platform('Linux','x86_64');self.assertEqual(result.returncode,0);self.assertIn('linux/amd64',result.stdout)
    def test_unsupported_linux_rejected(self):
        result,_=self.run_platform('Linux','x86_64','ID=rocky\nVERSION_ID=9\n');self.assertNotEqual(result.returncode,0)
    def test_ubuntu_arm_rejected(self):
        result,_=self.run_platform('Linux','aarch64');self.assertNotEqual(result.returncode,0)
    def test_fresh_ubuntu_selects_amd64(self):
        result,config=self.run_platform('Linux','x86_64',prepare=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('vm_architecture: amd64',config)
    def test_existing_vm_blocks_architecture_change(self):
        result,config=self.run_platform('Linux','x86_64',prepare=True,existing=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('нельзя переносить',result.stderr);self.assertIn('vm_architecture: arm64',config)
