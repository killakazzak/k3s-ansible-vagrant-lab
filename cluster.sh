#!/bin/bash
# One entry point for this project's cluster lifecycle.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ "${1:-}" == "--cluster" ]]; then
  name="${2:-}"
  [[ "$name" =~ ^[a-z][a-z0-9-]{0,30}$ && -f "$ROOT/.clusters/$name/cluster.sh" ]] || { echo 'Unknown cluster'; exit 2; }
  shift 2
  exec "$ROOT/.clusters/$name/cluster.sh" "$@"
fi
# Keep lifecycle operations scoped to this checkout, even with Vagrant overrides.
export VAGRANT_CWD="$ROOT"
export VAGRANT_DOTFILE_PATH="$ROOT/.vagrant"
usage() {
  echo 'Usage: ./cluster.sh {menu|web [--port PORT]|web-start|web-stop|web-status|up [--verify]|destroy|status|verify}'
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
  web-start|web-stop|web-status)
    export PATH="$PATH:/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin"
    exec python3 "$ROOT/scripts/web-service.py" "${command_name#web-}" "$@"
    ;;
  up) exec "$ROOT/deploy.sh" "$@" ;;
  destroy|status|verify)
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    case "$command_name" in
      destroy)
        command -v vagrant >/dev/null || { echo 'Vagrant is required to delete the VMs.' >&2; exit 1; }
        ruby "$ROOT/scripts/destroy-cluster.rb"
        ;;
      status)
        if ruby -ryaml -e "exit(YAML.load_file('ansible/inventory.yml')['all']['children'].values.all? { |g| g['hosts'].empty? } ? 0 : 1)"; then
          echo 'Кластер пуст. В inventory нет узлов.'
        else
          exec vagrant status
        fi
        ;;
      verify) exec ansible-playbook ansible/verify.yml ;;
    esac
    ;;
  --help|-h) usage ;;
  *) usage >&2; exit 2 ;;
esac
