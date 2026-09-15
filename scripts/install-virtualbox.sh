#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/host-platform.sh"
if command -v VBoxManage >/dev/null; then
  version=$(VBoxManage --version)
  if ruby -e 'exit(Gem::Version.new(ARGV[0].split("r")[0]) >= Gem::Version.new("7.2") ? 0 : 1)' "$version"; then exit 0; fi
  echo "VirtualBox $version: требуется версия 7.2 или новее."
fi
[[ "$LAB_HOST_OS" == linux ]] || { echo 'Установите VirtualBox 7.2 для macOS ARM64: https://www.virtualbox.org/wiki/Downloads'; exit 1; }
echo 'Установка VirtualBox 7.2 из официального репозитория Oracle…'
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
"$ROOT/scripts/download.sh" 'Ключ Oracle VirtualBox' https://www.virtualbox.org/download/oracle_vbox_2016.asc "$tmp/key.asc"
gpg --batch --yes --dearmor -o "$tmp/key.gpg" "$tmp/key.asc"
lab_sudo install -m 0644 "$tmp/key.gpg" /usr/share/keyrings/k3s-lab-virtualbox.gpg
printf '%s\n' 'deb [arch=amd64 signed-by=/usr/share/keyrings/k3s-lab-virtualbox.gpg] https://download.virtualbox.org/virtualbox/debian jammy contrib' > "$tmp/repo"
lab_sudo install -m 0644 "$tmp/repo" /etc/apt/sources.list.d/k3s-lab-virtualbox.list
lab_sudo apt-get update
lab_sudo apt-get install -y "linux-headers-$(uname -r)" dkms virtualbox-7.2
VBoxManage --version
echo 'Если Secure Boot блокирует vboxdrv, завершите регистрацию ключа MOK и перезагрузите Ubuntu.'
