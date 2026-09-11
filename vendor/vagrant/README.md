# Vagrant для Apple Silicon

Оригинальный, неизменённый установщик HashiCorp Vagrant **2.4.9**, macOS ARM64.

- Файл: `vagrant_2.4.9_darwin_arm64.dmg` (около 54 МБ).
- Источник: https://releases.hashicorp.com/vagrant/2.4.9/vagrant_2.4.9_darwin_arm64.dmg
- Официальные контрольные суммы: https://releases.hashicorp.com/vagrant/2.4.9/vagrant_2.4.9_SHA256SUMS
- SHA256: `8de08bd435ef8ae0fc5fbd6acefa9c68e62fb898c5ae0fbdacd26853bea9d4d6`.
- Подписант PKG: `Hashicorp, Inc. (D38WU7D763)`; при проверке macOS подтвердила нотариальное заверение Apple.
- Лицензия поставщика сохранена в `LICENSE`; источник: https://github.com/hashicorp/vagrant/blob/v2.4.9/LICENSE.

Установщик хранится обычным файлом Git, без Git LFS и без отдельного GitHub Release. Он автоматически приходит вместе с клоном репозитория. `scripts/install-vagrant.sh` устанавливает его только при отсутствии Vagrant; `--check` проверяет SHA256 и подпись без установки.

Для замены версии одновременно обновите DMG, официальный файл SHA256SUMS и параметры `vagrant_version`, `vagrant_installer_sha256` в `ansible/group_vars/all.yml`. Не изменяйте содержимое официального DMG.
