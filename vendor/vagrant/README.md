# Vagrant для Apple Silicon

Оригинальный, неизменённый установщик HashiCorp Vagrant **2.4.9**, macOS ARM64.

- Файл: `vagrant_2.4.9_darwin_arm64.dmg` (около 54 МБ).
- Источник: https://releases.hashicorp.com/vagrant/2.4.9/vagrant_2.4.9_darwin_arm64.dmg
- Официальные контрольные суммы: https://releases.hashicorp.com/vagrant/2.4.9/vagrant_2.4.9_SHA256SUMS
- SHA256: `8de08bd435ef8ae0fc5fbd6acefa9c68e62fb898c5ae0fbdacd26853bea9d4d6`.
- Подписант PKG: `Hashicorp, Inc. (D38WU7D763)`; при проверке macOS подтвердила нотариальное заверение Apple.
- Лицензия поставщика сохранена в `LICENSE`; источник: https://github.com/hashicorp/vagrant/blob/v2.4.9/LICENSE.

Установщик опубликован в [GitHub Release vagrant-2.4.9](https://github.com/killakazzak/k3s-ansible-vagrant-lab/releases/tag/vagrant-2.4.9), а не в текущем дереве Git.
`scripts/install-vagrant.sh` скачивает его только при отсутствии Vagrant и сохраняет в `.cache/installers` корневого проекта. Повторные установки используют кеш.
`--check` проверяет SHA256 и подпись без установки. Для полностью офлайн-установки заранее выполните эту команду или перенесите проверенный DMG в `.cache/installers`.

При смене версии опубликуйте оригинальный DMG в release `vagrant-<версия>` и обновите `vagrant_version`, `vagrant_installer_sha256` и официальный SHA256SUMS в Git.
