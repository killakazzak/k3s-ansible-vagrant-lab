import pathlib,subprocess,json,concurrent.futures,shlex,hashlib
r=pathlib.Path(__file__).resolve().parents[1];out=r/'vendor/offline'
def download(url,path):
 path=out/path;path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():subprocess.run(['curl','-fsSL','--retry','3','--connect-timeout','20',url,'-o',str(path)+'.part'],check=True);path.with_name(path.name+'.part').rename(path)
 print('Cached',path.name,flush=True)
jobs=[('https://www.python.org/ftp/python/3.13.7/python-3.13.7-macos11.pkg','host/python-3.13.7-macos11.pkg'),('https://download.virtualbox.org/virtualbox/7.2.16/SHA256SUMS','host/VirtualBox-SHA256SUMS'),('https://download.virtualbox.org/virtualbox/7.2.16/VirtualBox-7.2.16-174877-macOSArm64.dmg','host/VirtualBox.dmg'),('https://github.com/k3s-io/k3s/releases/download/v1.36.4%2Bk3s1/k3s-airgap-images-arm64.tar.zst','images/k3s-airgap-images-arm64.tar.zst'),('https://github.com/k3s-io/k3s/releases/download/v1.36.4%2Bk3s1/sha256sum-arm64.txt','k3s/sha256sum-arm64.txt'),('https://releases.rancher.com/server-charts/stable/rancher-2.15.1.tgz','charts/rancher.tgz'),('https://charts.jetstack.io/charts/cert-manager-v1.21.1.tgz','charts/cert-manager.tgz')]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for future in [pool.submit(download,*j) for j in jobs]:future.result()

# Resolve binary wheels for the bundled Python, regardless of the builder Python.
import sys
subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:',
 '--python-version','3.13','--platform','macosx_11_0_arm64',
 '--platform','macosx_10_9_universal2','--dest',str(out/'host/wheels'),
 'ansible-core==2.21.3'],check=True)
