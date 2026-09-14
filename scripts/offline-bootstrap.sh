#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$ROOT/vendor/offline"
export PATH="$PATH:/opt/vagrant/bin:/usr/local/bin:/opt/homebrew/bin"
[[ "$(uname -s)/$(uname -m)" == Darwin/arm64 ]] || { echo "Offline bundle requires macOS ARM64."; exit 1; }
[[ -f "$BUNDLE/manifest.json" ]] || { echo 'Offline bundle is incomplete: manifest.json missing'; exit 1; }
require_admin() {
  if [[ $EUID -ne 0 && ! -t 0 ]] && ! sudo -n true 2>/dev/null; then
    echo 'Нужна первоначальная установка системных зависимостей. Веб-консоль не может запросить пароль администратора.' >&2
    printf 'Откройте обычный терминал и выполните: cd %q && ./scripts/offline-bootstrap.sh\n' "$ROOT" >&2
    echo 'Затем повторите создание кластера в веб-интерфейсе.' >&2
    exit 1
  fi
}
# Reuse working tools: enabling a bundle must not force a system Python install.
PYTHON="$(command -v python3 || true)"
if command -v ansible >/dev/null && command -v ansible-playbook >/dev/null &&
   ansible-playbook --version >/dev/null 2>&1 && [[ -n "$PYTHON" ]] &&
   "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  echo "Использую установленный Ansible: $(ansible-playbook --version | sed -n '1p')"
  "$PYTHON" "$ROOT/scripts/offline-verify.py" "$BUNDLE"
else
  PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
  if [[ ! -x "$PYTHON" ]]; then
    require_admin
    (cd "$BUNDLE"; shasum -a 256 -c SHA256SUMS) >/dev/null
    sudo installer -pkg "$BUNDLE/host/python-3.13.7-macos11.pkg" -target /
  fi
  "$PYTHON" "$ROOT/scripts/offline-verify.py" "$BUNDLE"
  "$PYTHON" -m venv "$ROOT/.offline-venv"
  "$ROOT/.offline-venv/bin/python" -m pip install --no-index --find-links="$BUNDLE/host/wheels" ansible-core==2.21.3
fi
ruby -rjson -ryaml - "$ROOT" <<'CONFIGCHECK'
root=ARGV.fetch(0)
manifest=JSON.parse(File.read(File.join(root,'vendor/offline/manifest.json')))
config=YAML.load_file(File.join(root,'ansible/group_vars/all.yml'))
%w[k3s_version rancher_version cert_manager_version].each do |key|
  abort("Offline bundle: configuration mismatch for #{key}") unless config[key]==manifest[key]
end
{'vm_provider'=>'virtualbox','vm_box'=>'k8s-lab/ubuntu-24.04-25gb','vm_architecture'=>'arm64','vm_box_version'=>'0'}.each do |key,value|
  abort("Offline bundle requires #{key}=#{value}") unless config[key].to_s==value
end
CONFIGCHECK
if ! command -v vagrant >/dev/null; then
  require_admin
  "$ROOT/scripts/install-vagrant.sh"
fi
if ! command -v VBoxManage >/dev/null; then
  require_admin
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
