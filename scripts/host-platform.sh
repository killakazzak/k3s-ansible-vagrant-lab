#!/bin/bash
# Source from entry points; no installation occurs just by sourcing.
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64) LAB_HOST_OS=darwin; LAB_HOST_ARCH=arm64; LAB_HOST_LABEL="macOS $(sw_vers -productVersion)"; LAB_ARCH_LABEL="ARM64 (Apple Silicon)" ;;
  Linux/x86_64)
    . /etc/os-release
    [[ "$ID" == ubuntu && "$VERSION_ID" == 22.04 ]] || { echo "Поддерживаются macOS ARM64 и Ubuntu 22.04 x86_64." >&2; return 1; }
    LAB_HOST_OS=linux; LAB_HOST_ARCH=amd64; LAB_HOST_LABEL="${PRETTY_NAME:-Ubuntu 22.04}"; LAB_ARCH_LABEL="x86_64 (AMD64, Intel/AMD)" ;;
  *) echo 'Поддерживаются macOS ARM64 и Ubuntu 22.04 x86_64.' >&2; return 1 ;;
esac
export LAB_HOST_OS LAB_HOST_ARCH LAB_HOST_LABEL LAB_ARCH_LABEL
export PATH="$ROOT/.offline-venv/bin:$PATH:/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin"
lab_sudo() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }
lab_host_prepare() {
  printf "\nK3s Lab · ОС: %s · архитектура: %s\n\n" "$LAB_HOST_LABEL" "$LAB_ARCH_LABEL"
  if [[ "$LAB_HOST_OS" == linux ]]; then
    local missing=0 tool
    for tool in ruby python3 curl unzip git zsh ssh rsync gpg shasum; do command -v "$tool" >/dev/null || missing=1; done
    python3 -c 'import venv' 2>/dev/null || missing=1
    dpkg-query -W -f='${Status}' python3-venv 2>/dev/null | grep -q 'install ok installed' || missing=1
    if (( missing )); then
      lab_sudo apt-get update
      lab_sudo apt-get install -y ruby python3 python3-venv curl unzip git zsh openssh-client rsync gnupg ca-certificates libdigest-sha-perl
    fi
  fi
  # Set architecture on a fresh checkout only. Never convert existing VM state.
  ruby -ryaml -e '
    p=ARGV[0]; arch=ARGV[1]; s=YAML.load_file(p)
    if s["vm_architecture"] != arch
      root=File.expand_path("../..", File.dirname(p))
      abort "Архитектура профиля отличается от хоста; существующие VM нельзя переносить между архитектурами." unless Dir.glob(root+"/.vagrant/machines/**/id").empty?
      text=File.read(p).sub(/^vm_architecture:.*$/, "vm_architecture: #{arch}")
      File.write(p,text)
    end
  ' "$ROOT/ansible/group_vars/all.yml" "$LAB_HOST_ARCH"
}
