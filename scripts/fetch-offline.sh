#!/bin/bash
# Fetch once on an online Mac, or unpack files delivered on a USB drive.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE=offline-macos-arm64-20260915
CHECKSUMS="$ROOT/offline/RELEASE-SHA256SUMS"
[[ -f "$CHECKSUMS" ]] || { echo 'Release checksums are missing; bundle has not been published.'; exit 1; }
CACHE="${1:-$ROOT/.cache/offline-download}"
mkdir -p "$CACHE"
while read -r checksum name; do
  [[ "$name" == offline-macos-arm64.tar.part-* && "$name" != */* ]] || exit 1
  if [[ ! -f "$CACHE/$name" ]]; then
    [[ $# -eq 0 ]] || { echo "Missing local archive: $name"; exit 1; }
    curl -fL --retry 3 --connect-timeout 20 "https://github.com/killakazzak/k3s-ansible-vagrant-lab/releases/download/$RELEASE/$name" -o "$CACHE/$name.part"
    mv "$CACHE/$name.part" "$CACHE/$name"
  fi
done < "$CHECKSUMS"
(cd "$CACHE"; shasum -a 256 -c "$CHECKSUMS")
mkdir -p "$ROOT/vendor"
# Read only the parts listed in the committed checksum file, in that order.
while read -r checksum name; do cat "$CACHE/$name"; done < "$CHECKSUMS" | tar -xf - -C "$ROOT/vendor"
echo 'Offline bundle unpacked. Run ./cluster.sh or ./deploy.sh.'
