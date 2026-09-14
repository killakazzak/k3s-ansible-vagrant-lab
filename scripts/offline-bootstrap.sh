#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$ROOT/vendor/offline"
export PATH="$PATH:/opt/vagrant/bin:/usr/local/bin:/opt/homebrew/bin"
[[ "$(uname -s)/$(uname -m)" == Darwin/arm64 ]] || { echo "Offline bundle requires macOS ARM64."; exit 1; }
[[ -f "$BUNDLE/manifest.json" ]] || { echo 'Offline bundle is incomplete: manifest.json missing'; exit 1; }
PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
if [[ ! -x "$PYTHON" ]]; then
  (cd "$BUNDLE"; shasum -a 256 -c SHA256SUMS) >/dev/null
  sudo installer -pkg "$BUNDLE/host/python-3.13.7-macos11.pkg" -target /
fi
"$PYTHON" "$ROOT/scripts/offline-verify.py" "$BUNDLE"
"$PYTHON" -m venv "$ROOT/.offline-venv"
"$ROOT/.offline-venv/bin/python" -m pip install --no-index --find-links="$BUNDLE/host/wheels" ansible-core==2.21.3
"$ROOT/.offline-venv/bin/python" - "$ROOT" <<'PYCHECK'
import json,sys,yaml
from pathlib import Path
root=Path(sys.argv[1]);m=json.loads((root/'vendor/offline/manifest.json').read_text());c=yaml.safe_load((root/'ansible/group_vars/all.yml').read_text())
for key in ('k3s_version','rancher_version','cert_manager_version'):
 if c.get(key)!=m[key]:raise SystemExit('Offline bundle: configuration mismatch for '+key)
for key,value in [('vm_provider','virtualbox'),('vm_box','k8s-lab/ubuntu-24.04-25gb'),('vm_architecture','arm64')]:
 if c.get(key)!=value:raise SystemExit('Offline bundle requires '+key+'='+value)
if str(c.get('vm_box_version')) != '0':raise SystemExit('Offline box version must be 0')
PYCHECK
command -v vagrant >/dev/null || "$ROOT/scripts/install-vagrant.sh"
if ! command -v VBoxManage >/dev/null; then
  MOUNT="$(mktemp -d)"
  hdiutil attach "$BUNDLE/host/VirtualBox.dmg" -mountpoint "$MOUNT" -nobrowse -quiet
  trap 'hdiutil detach "$MOUNT" -quiet; rmdir "$MOUNT"' EXIT
  sudo installer -pkg "$MOUNT/VirtualBox.pkg" -target /
fi
mkdir -p "$ROOT/.tools"
cp "$BUNDLE/kubectl" "$ROOT/.tools/kubectl"
chmod +x "$ROOT/.tools/kubectl"
echo v1.36.4 > "$ROOT/.tools/kubectl.version"
if ! vagrant box list | grep -F 'k8s-lab/ubuntu-24.04-25gb (virtualbox, 0, (arm64))' >/dev/null; then
  echo 'Ubuntu box is not included. First deploy will build it with internet access, or import your existing box into Vagrant beforehand.'
fi
echo 'Offline tools are ready. Ubuntu is supplied separately.'
