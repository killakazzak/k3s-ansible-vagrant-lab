#!/bin/bash
set -euo pipefail
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
if command -v ansible-playbook >/dev/null && command -v ansible >/dev/null; then
  echo "Ansible уже установлен: $(ansible-playbook --version | sed -n '1p')"
  exit 0
fi
command -v brew >/dev/null || {
  echo 'Для установки Ansible установите Homebrew: https://brew.sh' >&2
  exit 1
}
echo 'Устанавливаю Ansible через Homebrew…'
brew install ansible
hash -r
command -v ansible-playbook >/dev/null && command -v ansible >/dev/null || {
  echo 'Ansible не найден после установки. Проверьте Homebrew и PATH.' >&2
  exit 1
}
ansible-playbook --version
