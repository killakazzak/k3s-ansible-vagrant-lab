#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/.offline-venv/bin:$PATH:/opt/homebrew/bin:/opt/vagrant/bin:/usr/local/bin"
lab_base="$ROOT"
if [[ "$(basename "$(dirname "$ROOT")")" == .clusters ]]; then lab_base="$(dirname "$(dirname "$ROOT")")"; fi
export K3S_LAB_CACHE_ROOT="${K3S_LAB_CACHE_ROOT:-$HOME/.cache/k3s-lab}"
export ANSIBLE_FORKS="${ANSIBLE_FORKS:-8}"
[[ -f kubeconfig ]] || { echo 'Сначала создайте и запустите кластер.'; exit 1; }
./scripts/install-ansible.sh
ansible-playbook ansible/components.yml -e '{"rancher_enabled":true}'
ruby -r ./scripts/menu.rb -e 'ClusterMenu.new(Dir.pwd).set_values("rancher_enabled"=>true)'
echo 'Rancher установлен. Ссылка доступна в веб-консоли.'

python3 "$ROOT/scripts/image-cache.py" capture --cluster "$ROOT" || echo "[Кеш] Не удалось сохранить образы; кластер продолжает работать."
