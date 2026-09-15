#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/host-platform.sh"
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: ./scripts/install-virtualbox.sh'
  echo 'Installs missing VirtualBox after interactive confirmation (macOS ARM64 / Ubuntu 22.04 AMD64).'
  exit 0
fi
[[ $# -eq 0 ]] || { echo 'Unknown option.' >&2; exit 2; }
export PATH="$PATH:/Applications/VirtualBox.app/Contents/MacOS"
if command -v VBoxManage >/dev/null; then
  version=$(VBoxManage --version)
  if ruby -e 'exit(Gem::Version.new(ARGV[0].split("r")[0]) >= Gem::Version.new("7.2") ? 0 : 1)' "$version"; then exit 0; fi
  echo "VirtualBox $version: требуется версия 7.2 или новее."
fi
echo "VirtualBox требуется для VM на $LAB_HOST_LABEL ($LAB_ARCH_LABEL)."
echo 'Установить VirtualBox из официального источника Oracle? Потребуются права администратора.'
if [[ ! -t 0 ]]; then
  echo 'Для подтверждения запустите ./scripts/install-virtualbox.sh в терминале.' >&2
  exit 1
fi
read -r -p '1 — установить, 0 / Enter — отмена: ' answer
[[ "$answer" == 1 ]] || { echo 'Установка VirtualBox отменена.'; exit 1; }
if [[ "$LAB_HOST_OS" == darwin ]]; then
  version=7.2.16
  package="VirtualBox-${version}-174877-macOSArm64.dmg"
  lab_base="$ROOT"
  if [[ "$(basename "$(dirname "$ROOT")")" == .clusters ]]; then lab_base="$(dirname "$(dirname "$ROOT")")"; fi
  cache="${K3S_LAB_INSTALLER_CACHE:-$lab_base/.cache/installers}"
  mkdir -p "$cache"
  tmp=$(mktemp -d)
  mounted=0
  cleanup() { if [[ "$mounted" == 1 ]]; then hdiutil detach "$tmp/mount" >/dev/null || true; fi; rm -rf "$tmp"; }
  trap cleanup EXIT
  "$ROOT/scripts/download.sh" 'VirtualBox SHA256' "https://download.virtualbox.org/virtualbox/$version/SHA256SUMS" "$tmp/sums"
  expected=$(awk -v name="$package" '$2 == name || $2 == "*"name {print $1}' "$tmp/sums")
  [[ "$expected" =~ ^[a-f0-9]{64}$ ]] || { echo 'Не найдена SHA256 установщика VirtualBox.' >&2; exit 1; }
  if [[ ! -f "$cache/$package" ]]; then
    "$ROOT/scripts/download.sh" "VirtualBox $version macOS ARM64" "https://download.virtualbox.org/virtualbox/$version/$package" "$tmp/installer.dmg"
    actual=$(shasum -a 256 "$tmp/installer.dmg" | awk '{print $1}')
    [[ "$actual" == "$expected" ]] || { echo 'Ошибка SHA256 VirtualBox.' >&2; exit 1; }
    mv "$tmp/installer.dmg" "$cache/$package"
  fi
  actual=$(shasum -a 256 "$cache/$package" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || { echo 'Ошибка SHA256 кеша VirtualBox. Удалите повреждённый DMG и повторите.' >&2; exit 1; }
  mkdir "$tmp/mount"
  hdiutil attach "$cache/$package" -mountpoint "$tmp/mount" -nobrowse -readonly >/dev/null
  mounted=1
  pkg="$tmp/mount/VirtualBox.pkg"
  [[ -f "$pkg" ]] || { echo 'VirtualBox.pkg не найден.' >&2; exit 1; }
  pkgutil --check-signature "$pkg"
  spctl --assess --type install "$pkg"
  lab_sudo /usr/sbin/installer -pkg "$pkg" -target /
  VBoxManage --version
  echo 'VirtualBox установлен. Если macOS запросит разрешение или перезагрузку, завершите их перед созданием VM.'
  exit 0
fi
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
