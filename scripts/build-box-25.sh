#!/bin/bash
# Build a fresh 25 GiB Ubuntu base disk; existing VM disks are never shrunk.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
source "$ROOT/scripts/host-platform.sh"
guest_arch=x86_64
[[ "$LAB_HOST_ARCH" != arm64 ]] || guest_arch=aarch64
command -v VBoxManage >/dev/null
command -v vagrant >/dev/null
BOX_NAME='k8s-lab/ubuntu-24.04-25gb'
if vagrant box list | grep -F "$BOX_NAME (virtualbox, 0, ($LAB_HOST_ARCH))" >/dev/null; then exit 0; fi
CACHE="$ROOT/.cache/box25"
mkdir -p "$CACHE"
"$ROOT/scripts/install-packer.sh"
PACKER="$ROOT/.tools/packer"
BENTO="$CACHE/bento"
if [[ ! -d "$BENTO/.git" ]]; then
  git clone https://github.com/chef/bento.git "$BENTO"
  git -C "$BENTO" checkout c884c077e041f54f56e4e07baddd916c49d31a0e
fi
/usr/bin/python3 "$ROOT/scripts/prepare-box-25.py" "$BENTO"
echo '[Этап] Загрузка и проверка ISO Ubuntu до запуска Packer'
python3 "$ROOT/scripts/prepare-iso.py" "$BENTO/os_pkrvars/ubuntu/ubuntu-24.04-${guest_arch}.pkrvars.hcl" "$CACHE/iso" "$CACHE/local-iso.pkrvars.json"
cd "$BENTO"
"$PACKER" init packer_templates
"$PACKER" build -only=virtualbox-iso.vm -var-file=os_pkrvars/ubuntu/ubuntu-24.04-${guest_arch}.pkrvars.hcl -var-file="$CACHE/local-iso.pkrvars.json" -var 'sources_enabled=["source.virtualbox-iso.vm"]' -var disk_size=25600 -var cpus=2 -var memory=4096 -var headless=true packer_templates
vagrant box add --name "$BOX_NAME" --provider virtualbox --architecture "$LAB_HOST_ARCH" builds/build_complete/ubuntu-24.04-${guest_arch}.virtualbox.box
