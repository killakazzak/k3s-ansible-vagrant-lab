#!/bin/bash
# Run from any directory. Dependencies are installed only when missing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export VAGRANT_CWD="$ROOT"
export VAGRANT_DOTFILE_PATH="$ROOT/.vagrant"
export PATH="$ROOT/.offline-venv/bin:$PATH"
export PATH="$PATH:/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin"
started_at=$SECONDS
lab_base="$ROOT"
if [[ "$(basename "$(dirname "$ROOT")")" == .clusters ]]; then lab_base="$(dirname "$(dirname "$ROOT")")"; fi
export K3S_LAB_CACHE_ROOT="${K3S_LAB_CACHE_ROOT:-$lab_base/.cache/assets}"
export ANSIBLE_FORKS="${ANSIBLE_FORKS:-8}"
[[ "$ANSIBLE_FORKS" =~ ^[1-9][0-9]*$ ]] && (( ANSIBLE_FORKS <= 32 )) || { echo 'ANSIBLE_FORKS must be 1–32'; exit 2; }
if [[ "${1:-}" == "--help" ]]; then
  echo 'Usage: ./deploy.sh [--verify]'
  echo 'Requires Apple Silicon, Homebrew and VirtualBox 7.2 or newer.'
  echo 'Installs missing tools, creates VMs, applies Ansible; --verify adds network tests.'
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--verify" ) ]]; then
  echo 'Unknown option; use --help.' >&2; exit 2
fi
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo 'This configuration requires an Apple Silicon Mac.' >&2; exit 1;
}
if [[ -d "$ROOT/vendor/offline" ]]; then
  "$ROOT/scripts/offline-bootstrap.sh"
  export PATH="$ROOT/.offline-venv/bin:$PATH"
else
  command -v brew >/dev/null || { echo 'Install Homebrew first: https://brew.sh' >&2; exit 1; }
fi
setting() { ruby -ryaml -e 'puts YAML.load_file(ARGV[0]).fetch(ARGV[1])' "$ROOT/ansible/group_vars/all.yml" "$1"; }
command -v vagrant >/dev/null || "$ROOT/scripts/install-vagrant.sh"
"$ROOT/scripts/install-ansible.sh"
case "$(setting vm_provider)" in
  virtualbox)
    command -v VBoxManage >/dev/null || { echo 'Install VirtualBox for Apple Silicon: https://www.virtualbox.org/wiki/Downloads' >&2; exit 1; }
    ;;
  parallels)
    command -v prlctl >/dev/null || { echo 'Install and activate Parallels Pro/Business/Enterprise.' >&2; exit 1; }
    plugin_version="$(setting vagrant_parallels_version)"
    if ! vagrant plugin list | grep -F "vagrant-parallels ($plugin_version," >/dev/null; then
      vagrant plugin install vagrant-parallels --plugin-version "$plugin_version"
    fi
    ;;
  *) echo 'Supported providers: virtualbox, parallels.' >&2; exit 1 ;;
esac
if [[ "$(setting vm_box)" == 'k8s-lab/ubuntu-24.04-25gb' ]]; then
  [[ "$(setting vm_provider)" == virtualbox ]] || { echo 'The 25 GiB base box requires VirtualBox.' >&2; exit 1; }
  "$ROOT/scripts/build-box-25.sh"
fi
# Keep kubectl compatible with the configured API instead of Homebrew's latest minor.
kubernetes_version="$(setting k3s_version)"
kubernetes_version="${kubernetes_version%%+*}"
mkdir -p .tools
if [[ ! -x .tools/kubectl || ! -f .tools/kubectl.version || "$(cat .tools/kubectl.version)" != "$kubernetes_version" ]]; then
  base_url="https://dl.k8s.io/release/$kubernetes_version/bin/darwin/arm64"
  curl --fail --location --retry 3 "$base_url/kubectl" -o .tools/kubectl.download
  curl --fail --location --retry 3 "$base_url/kubectl.sha256" -o .tools/kubectl.sha256
  expected="$(tr -d '[:space:]' < .tools/kubectl.sha256)"
  actual="$(shasum -a 256 .tools/kubectl.download | awk '{print $1}')"
  [[ "$expected" == "$actual" ]] || { echo 'kubectl checksum mismatch.' >&2; exit 1; }
  chmod 755 .tools/kubectl.download
  mv .tools/kubectl.download .tools/kubectl
  printf '%s\n' "$kubernetes_version" > .tools/kubectl.version
fi
vagrant validate
ansible-playbook --syntax-check ansible/site.yml
mkdir -p .cache
# Overlap downloading k3s with starting the VMs.
ansible-playbook ansible/assets.yml > .cache/assets.log 2>&1 &
assets_pid=$!
trap 'kill "$assets_pid" 2>/dev/null || true' EXIT
if [[ "$(setting vm_provider)" == virtualbox ]]; then
  echo "VirtualBox создаёт VM последовательно; Ansible подготавливает до $ANSIBLE_FORKS узлов одновременно."
fi
vagrant up --provider="$(setting vm_provider)" --no-provision --parallel
if ! wait "$assets_pid"; then
  cat .cache/assets.log >&2
  exit 1
fi
trap - EXIT
ansible all -m ping
ansible-playbook ansible/site.yml
if [[ "${1:-}" == "--verify" ]]; then
  ansible-playbook ansible/verify.yml
fi
"$ROOT/kubectl.sh" get nodes -o wide
echo 'Cluster is ready. Use ./kubectl.sh or export KUBECONFIG="$PWD/kubeconfig".'

ansible-playbook ansible/access.yml

printf "Completed in %s seconds.\n" "$((SECONDS-started_at))"
