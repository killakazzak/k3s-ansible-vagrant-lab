#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/host-platform.sh"
lab_host_prepare
if [[ "$LAB_HOST_OS" == darwin ]]; then
  for item in python3:python ruby:ruby git:git curl:curl unzip:unzip zsh:zsh rsync:rsync ssh:openssh; do
    tool=${item%%:*}; package=${item#*:}
    if ! command -v "$tool" >/dev/null; then
      command -v brew >/dev/null || { echo 'Для установки недостающих инструментов нужен Homebrew: https://brew.sh'; exit 1; }
      brew install "$package"
    fi
  done
fi
"$ROOT/scripts/install-vagrant.sh"
"$ROOT/scripts/install-ansible.sh"
"$ROOT/scripts/install-virtualbox.sh"
ruby "$ROOT/scripts/environment.rb"
