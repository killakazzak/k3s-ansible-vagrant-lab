#!/bin/bash
# Install the pinned Packer binary exclusively from this checkout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/host-platform.sh"
[[ $# -eq 0 ]] || { echo 'Usage: ./scripts/install-packer.sh'; exit 2; }
lab_base="$ROOT"
if [[ "$(basename "$(dirname "$ROOT")")" == .clusters ]]; then lab_base="$(dirname "$(dirname "$ROOT")")"; fi
version=1.14.2
name="packer_${version}_${LAB_HOST_OS}_${LAB_HOST_ARCH}.zip"
archive="$lab_base/vendor/packer/$name"
sums="$lab_base/vendor/packer/packer_${version}_SHA256SUMS"
[[ -f "$archive" && -f "$sums" ]] || { echo "Нет локального архива Packer: $archive. Обновите репозиторий." >&2; exit 1; }
expected=$(awk -v name="$name" '$2 == name {print $1}' "$sums")
[[ "$expected" =~ ^[a-f0-9]{64}$ ]] || { echo 'Нет SHA256 для Packer.' >&2; exit 1; }
actual=$(shasum -a 256 "$archive" | awk '{print $1}')
[[ "$actual" == "$expected" ]] || { echo 'SHA256 Packer не совпадает. Установка отменена.' >&2; exit 1; }
mkdir -p "$ROOT/.tools"
tmp=$(mktemp -d "$ROOT/.tools/.packer-install.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
unzip -q "$archive" packer -d "$tmp"
chmod 755 "$tmp/packer"
if ! cmp -s "$tmp/packer" "$ROOT/.tools/packer"; then
  mv "$tmp/packer" "$ROOT/.tools/packer"
fi
chmod 755 "$ROOT/.tools/packer"
CHECKPOINT_DISABLE=1 "$ROOT/.tools/packer" version
echo "Packer установлен локально: $ROOT/.tools/packer (SHA256 проверена)."
