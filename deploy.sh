#!/bin/bash
# Run from any directory. Dependencies are installed only when missing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
source "$ROOT/scripts/host-platform.sh"
[[ "${1:-}" == --help ]] || lab_host_prepare
export VAGRANT_CWD="$ROOT"
export VAGRANT_DOTFILE_PATH="$ROOT/.vagrant"
export PATH="$ROOT/.offline-venv/bin:$PATH"
export PATH="$PATH:/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin"
started_at=$SECONDS
lab_base="$ROOT"
if [[ "$(basename "$(dirname "$ROOT")")" == .clusters ]]; then lab_base="$(dirname "$(dirname "$ROOT")")"; fi
export K3S_LAB_CACHE_ROOT="${K3S_LAB_CACHE_ROOT:-$HOME/.cache/k3s-lab}"
export ANSIBLE_FORKS="${ANSIBLE_FORKS:-8}"
[[ "$ANSIBLE_FORKS" =~ ^[1-9][0-9]*$ ]] && (( ANSIBLE_FORKS <= 32 )) || { echo 'ANSIBLE_FORKS must be 1–32'; exit 2; }
if [[ "${1:-}" == "--help" ]]; then
  echo 'Usage: ./deploy.sh [--verify]'
  echo 'Supports macOS ARM64 and Ubuntu 22.04 x86_64 with VirtualBox 7.2.'
  echo 'Installs missing tools, creates VMs, applies Ansible; --verify adds network tests.'
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--verify" ) ]]; then
  echo 'Unknown option; use --help.' >&2; exit 2
fi
if ruby -ryaml -e 'g=YAML.load_file("ansible/inventory.yml").fetch("all").fetch("children"); exit(g.values.all? { |v| v.fetch("hosts").empty? } ? 0 : 1)'; then
  echo 'Кластер ещё не создан. Выполните ./cluster.sh: пункт 1 — создать кластер, пункт 12 — открыть веб-интерфейс и выбрать «Новый кластер».'
  exit 1
fi
if [[ "$LAB_HOST_OS" == darwin && -d "$ROOT/vendor/offline" ]]; then
  "$ROOT/scripts/offline-bootstrap.sh"
fi
setting() { ruby -ryaml -e 'puts YAML.load_file(ARGV[0]).fetch(ARGV[1])' "$ROOT/ansible/group_vars/all.yml" "$1"; }
command -v vagrant >/dev/null || "$ROOT/scripts/install-vagrant.sh"
"$ROOT/scripts/install-ansible.sh"
case "$(setting vm_provider)" in
  virtualbox)
    "$ROOT/scripts/install-virtualbox.sh"
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
if [[ ! -x .tools/kubectl || ! -f .tools/kubectl.version || "$(cat .tools/kubectl.version)" != "$kubernetes_version-$LAB_HOST_OS-$LAB_HOST_ARCH" ]]; then
  base_url="https://dl.k8s.io/release/$kubernetes_version/bin/$LAB_HOST_OS/$LAB_HOST_ARCH"
  "$ROOT/scripts/download.sh" "kubectl $kubernetes_version ($LAB_HOST_OS $LAB_HOST_ARCH)" "$base_url/kubectl" .tools/kubectl.download
  "$ROOT/scripts/download.sh" "SHA256 для kubectl $kubernetes_version" "$base_url/kubectl.sha256" .tools/kubectl.sha256
  expected="$(tr -d '[:space:]' < .tools/kubectl.sha256)"
  actual="$(shasum -a 256 .tools/kubectl.download | awk '{print $1}')"
  [[ "$expected" == "$actual" ]] || { echo 'kubectl checksum mismatch.' >&2; exit 1; }
  chmod 755 .tools/kubectl.download
  mv .tools/kubectl.download .tools/kubectl
  printf '%s\n' "$kubernetes_version-$LAB_HOST_OS-$LAB_HOST_ARCH" > .tools/kubectl.version
fi
vagrant validate
ansible-playbook --syntax-check ansible/site.yml
mkdir -p .cache
# Overlap downloading k3s with starting the VMs.
echo "[Этап] Загрузка k3s и контейнеров в кеш одновременно с запуском VM"
PYTHONUNBUFFERED=1 ansible-playbook ansible/assets.yml > >(tee .cache/assets.log) 2>&1 &
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
echo "[Этап] Проверка SSH и настройка узлов через Ansible"
ansible all -m ping
ansible-playbook ansible/site.yml
if [[ "${1:-}" == "--verify" ]]; then
  ansible-playbook ansible/verify.yml
fi
"$ROOT/kubectl.sh" get nodes -o wide
echo 'Cluster is ready. Use ./kubectl.sh or export KUBECONFIG="$PWD/kubeconfig".'

ansible-playbook ansible/access.yml

printf "Completed in %s seconds.\n" "$((SECONDS-started_at))"

python3 "$ROOT/scripts/image-cache.py" capture --cluster "$ROOT" || echo "[Кеш] Не удалось сохранить образы; кластер продолжает работать."
