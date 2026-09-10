#!/bin/bash
# Run from any directory. Dependencies are installed only when missing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
started_at=$SECONDS
if [[ "${1:-}" == "--help" ]]; then
  echo 'Usage: ./deploy.sh [--verify]'
  echo 'Requires Apple Silicon, Homebrew and an activated Parallels Pro/Business/Enterprise.'
  echo 'Installs missing tools, creates VMs, applies Ansible; --verify adds network tests.'
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--verify" ) ]]; then
  echo 'Unknown option; use --help.' >&2; exit 2
fi
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo 'This configuration requires an Apple Silicon Mac.' >&2; exit 1;
}
command -v brew >/dev/null || { echo 'Install Homebrew first: https://brew.sh' >&2; exit 1; }
command -v prlctl >/dev/null || {
  echo 'Install and activate Parallels Desktop Pro/Business/Enterprise first.' >&2; exit 1;
}
setting() { ruby -ryaml -e 'puts YAML.load_file(ARGV[0]).fetch(ARGV[1])' "$ROOT/ansible/group_vars/all.yml" "$1"; }
command -v vagrant >/dev/null || brew install --cask vagrant
command -v ansible-playbook >/dev/null || brew install ansible
plugin_version="$(setting vagrant_parallels_version)"
if ! vagrant plugin list | grep -F "vagrant-parallels ($plugin_version," >/dev/null; then
  vagrant plugin install vagrant-parallels --plugin-version "$plugin_version"
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
vagrant up --provider="$(setting vm_provider)" --no-provision
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

printf "Completed in %s seconds.\n" "$((SECONDS-started_at))"
