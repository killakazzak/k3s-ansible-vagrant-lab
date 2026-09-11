#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$ROOT/kubeconfig" ]] || { echo 'Доступ к кластеру пока не готов. Если развёртывание уже запущено, дождитесь его завершения. Иначе создайте кластер через меню или веб-интерфейс.' >&2; exit 1; }
if [[ -x "$ROOT/.tools/kubectl" ]]; then
  exec "$ROOT/.tools/kubectl" --kubeconfig="$ROOT/kubeconfig" "$@"
fi
command -v kubectl >/dev/null || { echo 'Run ./deploy.sh to install kubectl.' >&2; exit 1; }
exec kubectl --kubeconfig="$ROOT/kubeconfig" "$@"
