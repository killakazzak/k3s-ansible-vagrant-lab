#!/bin/bash
# Build a fresh 25 GiB Ubuntu base disk; existing VM disks are never shrunk.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
[[ "$(uname -s)/$(uname -m)" == Darwin/arm64 ]] || { echo 'Apple Silicon Mac required'; exit 1; }
command -v VBoxManage >/dev/null
command -v vagrant >/dev/null
BOX_NAME='k8s-lab/ubuntu-24.04-25gb'
if vagrant box list | grep -F "$BOX_NAME (virtualbox, 0, (arm64))" >/dev/null; then exit 0; fi
CACHE="$ROOT/.cache/box25"
mkdir -p "$CACHE"
PACKER="$CACHE/packer"
if [[ ! -x "$PACKER" ]]; then
  curl -fL --retry 3 https://releases.hashicorp.com/packer/1.14.2/packer_1.14.2_darwin_arm64.zip -o "$CACHE/packer_1.14.2_darwin_arm64.zip"
  curl -fL --retry 3 https://releases.hashicorp.com/packer/1.14.2/packer_1.14.2_SHA256SUMS -o "$CACHE/SHA256SUMS"
  (cd "$CACHE"; grep ' packer_1.14.2_darwin_arm64.zip$' SHA256SUMS | shasum -a 256 -c -)
  unzip -o "$CACHE/packer_1.14.2_darwin_arm64.zip" packer -d "$CACHE"
fi
BENTO="$CACHE/bento"
if [[ ! -d "$BENTO/.git" ]]; then
  git clone https://github.com/chef/bento.git "$BENTO"
  git -C "$BENTO" checkout c884c077e041f54f56e4e07baddd916c49d31a0e
fi
/usr/bin/python3 "$ROOT/scripts/prepare-box-25.py" "$BENTO"
cd "$BENTO"
"$PACKER" init packer_templates
"$PACKER" build -only=virtualbox-iso.vm -var-file=os_pkrvars/ubuntu/ubuntu-24.04-aarch64.pkrvars.hcl -var 'sources_enabled=["source.virtualbox-iso.vm"]' -var disk_size=25600 -var cpus=2 -var memory=4096 -var headless=true packer_templates
vagrant box add --name "$BOX_NAME" --provider virtualbox --architecture arm64 builds/build_complete/ubuntu-24.04-aarch64.virtualbox.box
