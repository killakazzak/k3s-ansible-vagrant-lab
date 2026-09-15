#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.offline-venv/bin:$PATH:/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin"
[[ -f kubeconfig ]] || { echo 'Create the cluster first.'; exit 1; }
./scripts/install-ansible.sh
ruby -r ./scripts/menu.rb -e 'm=ClusterMenu.new(Dir.pwd);m.set_values("disabled_components"=>(m.settings["disabled_components"] || []).reject { |c| c == "metrics-server" })'
ansible-playbook ansible/metrics-enable.yml
