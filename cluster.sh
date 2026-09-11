#!/bin/bash
# One entry point for this project's cluster lifecycle.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
# Keep lifecycle operations scoped to this checkout, even with Vagrant overrides.
export VAGRANT_CWD="$ROOT"
export VAGRANT_DOTFILE_PATH="$ROOT/.vagrant"
usage() {
  echo 'Usage: ./cluster.sh {menu|web [--port PORT]|up [--verify]|destroy|status|verify}'
  echo 'up       Create/start the cluster and apply Ansible.'
  echo 'destroy  Delete the VMs of this project and their data without a prompt.'
  echo '         Removes local kubeconfig after successful deletion; preserves download caches.'
  echo 'status   Show VM status.'
  echo 'verify   Run Kubernetes network and Traefik tests.'
}
command_name="${1:-menu}"
[[ $# -eq 0 ]] || shift
case "$command_name" in
  menu)
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    exec ruby "$ROOT/scripts/menu.rb"
    ;;
  web)
    export PATH="$PATH:/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin"
    "$ROOT/scripts/install-vagrant.sh"
    "$ROOT/scripts/install-ansible.sh"
    exec python3 "$ROOT/web/server.py" "$@"
    ;;
  up) exec "$ROOT/deploy.sh" "$@" ;;
  destroy|status|verify)
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    case "$command_name" in
      destroy)
        command -v vagrant >/dev/null || { echo 'Vagrant is required to delete the VMs.' >&2; exit 1; }
        vagrant destroy -f
        rm -f "$ROOT/kubeconfig"
        echo 'Cluster VMs deleted. Download caches retained.'
        ;;
      status) exec vagrant status ;;
      verify) exec ansible-playbook ansible/verify.yml ;;
    esac
    ;;
  --help|-h) usage ;;
  *) usage >&2; exit 2 ;;
esac
