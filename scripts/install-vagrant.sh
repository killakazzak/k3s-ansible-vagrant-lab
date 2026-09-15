#!/bin/bash
# Install the pinned official Vagrant package downloaded into the local cache.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$PATH:/opt/vagrant/bin:/usr/local/bin"
if [[ "${1:-}" == --help ]]; then
  echo 'Usage: ./scripts/install-vagrant.sh [--check]'
  echo 'Download and install Vagrant if absent. --check verifies the DMG/package without installing.'
  exit 0
fi
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --check ) ]] || { echo 'Unknown option; use --help.' >&2; exit 2; }
source "$ROOT/scripts/host-platform.sh"
if [[ "${1:-}" != --check ]] && command -v vagrant >/dev/null; then
  echo "Vagrant already installed: $(vagrant --version). Keeping it."
  exit 0
fi
setting() { ruby -ryaml -e 'puts YAML.load_file(ARGV[0]).fetch(ARGV[1])' "$ROOT/ansible/group_vars/all.yml" "$1"; }
version="$(setting vagrant_version)"
if [[ "$LAB_HOST_OS" == linux ]]; then
  lab_base="$ROOT"
  if [[ "$(basename "$(dirname "$ROOT")")" == .clusters ]]; then lab_base="$(dirname "$(dirname "$ROOT")")"; fi
  cache="${K3S_LAB_INSTALLER_CACHE:-$lab_base/.cache/installers}"
  mkdir -p "$cache"
  package="vagrant_${version}-1_amd64.deb"
  sums="$lab_base/vendor/vagrant/vagrant_${version}_SHA256SUMS"
  expected=$(awk -v name="$package" '$2 == name {print $1}' "$sums")
  [[ "$expected" =~ ^[a-f0-9]{64}$ ]] || { echo 'Нет закреплённой SHA256 для Vagrant Ubuntu.' >&2; exit 1; }
  if [[ ! -f "$cache/$package" ]]; then
    if [[ -f "$lab_base/vendor/vagrant/$package" ]]; then
      cp "$lab_base/vendor/vagrant/$package" "$cache/$package"
    else
      url="https://github.com/killakazzak/k3s-ansible-vagrant-lab/releases/download/vagrant-${version}/$package"
      "$ROOT/scripts/download.sh" "Vagrant $version Ubuntu amd64" "$url" "$cache/$package"
    fi
  fi
  actual=$(shasum -a 256 "$cache/$package" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || { echo 'Vagrant Ubuntu: SHA256 не совпадает; установка запрещена.' >&2; exit 1; }
  echo "Vagrant $version Ubuntu amd64: SHA256 проверена."
  [[ "${1:-}" == --check ]] && exit 0
  lab_sudo apt-get install -y "$cache/$package"
  vagrant --version
  exit 0
fi
expected="$(setting vagrant_installer_sha256)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$expected" =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid installer version or SHA256 setting.' >&2; exit 1; }
lab_base="$ROOT"
if [[ "$(basename "$(dirname "$ROOT")")" == .clusters ]]; then lab_base="$(dirname "$(dirname "$ROOT")")"; fi
cache="${K3S_LAB_INSTALLER_CACHE:-$lab_base/.cache/installers}"
mkdir -p "$cache"
dmg="$cache/vagrant_${version}_darwin_arm64.dmg"
if [[ ! -f "$dmg" ]]; then
  legacy="$lab_base/vendor/vagrant/vagrant_${version}_darwin_arm64.dmg"
  if [[ -f "$legacy" ]]; then
    cp "$legacy" "$dmg"
  else
    url="https://github.com/killakazzak/k3s-ansible-vagrant-lab/releases/download/vagrant-${version}/vagrant_${version}_darwin_arm64.dmg"
    temporary="$(mktemp "$cache/.vagrant-download.XXXXXX")"
    trap 'rm -f "$temporary"' EXIT
    "$ROOT/scripts/download.sh" "Vagrant $version (macOS ARM64)" "$url" "$temporary"
    actual="$(shasum -a 256 "$temporary" | awk '{print $1}')"
    [[ "$actual" == "$expected" ]] || { echo 'Downloaded Vagrant checksum mismatch.' >&2; exit 1; }
    mv "$temporary" "$dmg"
    trap - EXIT
  fi
fi
actual="$(shasum -a 256 "$dmg" | awk '{print $1}')"
[[ "$actual" == "$expected" ]] || { echo 'Vagrant installer checksum mismatch; installation refused.' >&2; exit 1; }
mount_dir="$(mktemp -d "${TMPDIR:-/tmp}/k3s-vagrant.XXXXXX")"
cleanup() {
  if mountpoint_output="$(hdiutil detach "$mount_dir" 2>&1)"; then
    rmdir "$mount_dir"
  else
    # Do not remove a directory that might still be mounted.
    rmdir "$mount_dir" 2>/dev/null || echo "Could not unmount $mount_dir; eject it manually." >&2
  fi
}
trap cleanup EXIT
hdiutil attach -readonly -nobrowse -quiet -mountpoint "$mount_dir" "$dmg"
pkg="$mount_dir/vagrant.pkg"
[[ -f "$pkg" ]] || { echo 'vagrant.pkg not found inside the official DMG.' >&2; exit 1; }
signature="$(pkgutil --check-signature "$pkg")"
printf '%s\n' "$signature"
[[ "$signature" == *'Hashicorp, Inc. (D38WU7D763)'* ]] || { echo 'Unexpected package signer; installation refused.' >&2; exit 1; }
if [[ "${1:-}" == --check ]]; then
  echo "Vagrant $version: SHA256 and package signature verified; nothing installed."
  exit 0
fi
echo "Installing Vagrant $version from the verified local cache. macOS may request your administrator password."
if [[ $EUID -eq 0 ]]; then
  /usr/sbin/installer -pkg "$pkg" -target /
else
  sudo /usr/sbin/installer -pkg "$pkg" -target /
fi
hash -r
command -v vagrant >/dev/null || { echo 'Installation completed but vagrant is not in PATH.' >&2; exit 1; }
[[ "$(vagrant --version)" == "Vagrant $version" ]] || { echo 'Unexpected Vagrant version after installation; check PATH.' >&2; exit 1; }
vagrant --version
