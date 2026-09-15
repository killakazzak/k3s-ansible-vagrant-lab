# Установщики Vagrant для macOS и Ubuntu

Оригинальный, неизменённый установщик HashiCorp Vagrant **2.4.9**, macOS ARM64.

- Файл: `vagrant_2.4.9_darwin_arm64.dmg` (около 54 МБ).
- Источник: https://releases.hashicorp.com/vagrant/2.4.9/vagrant_2.4.9_darwin_arm64.dmg
- Официальные контрольные суммы: https://releases.hashicorp.com/vagrant/2.4.9/vagrant_2.4.9_SHA256SUMS
- SHA256: `8de08bd435ef8ae0fc5fbd6acefa9c68e62fb898c5ae0fbdacd26853bea9d4d6`.
- Подписант PKG: `Hashicorp, Inc. (D38WU7D763)`; при проверке macOS подтвердила нотариальное заверение Apple.
- Лицензия поставщика сохранена в `LICENSE`; источник: https://github.com/hashicorp/vagrant/blob/v2.4.9/LICENSE.

Установщик включён в Git: `vendor/vagrant/vagrant_2.4.9_darwin_arm64.dmg`. Копия опубликована в [GitHub Release vagrant-2.4.9](https://github.com/killakazzak/k3s-ansible-vagrant-lab/releases/tag/vagrant-2.4.9).
`scripts/install-vagrant.sh` при отсутствии Vagrant использует локальный DMG из `vendor/vagrant`, сохраняя копию в `.cache/installers`. Загрузка из Release нужна только если локального файла нет.
`--check` проверяет SHA256 и подпись без установки. DMG доступен после clone/pull; отдельно скачивать Vagrant не требуется.

При смене версии замените DMG в Git и исключение в `.gitignore`, опубликуйте оригинальный DMG в release `vagrant-<версия>` и обновите `vagrant_version`, `vagrant_installer_sha256` и официальный SHA256SUMS в Git.

## Ubuntu 22.04 x86_64

Официальный пакет HashiCorp **Vagrant 2.4.9**: `vagrant_2.4.9-1_amd64.deb`, около **86 МиБ**.

- Источник: https://releases.hashicorp.com/vagrant/2.4.9/vagrant_2.4.9-1_amd64.deb
- SHA256: `42d830d05e6e9e647f8a5c854d9f5295e319dac74edd37d54b97b4f29cbbd70d`.
- Включён в Git по пути `vendor/vagrant/vagrant_2.4.9-1_amd64.deb`; доступен сразу после clone/pull. Копия также опубликована в GitHub Release `vagrant-2.4.9`.

При запуске на Ubuntu установщик выбирает DEB автоматически. Использует локальный `.cache/installers`, затем `vendor/vagrant`, иначе скачивает пакет из GitHub Release. Контрольная сумма берётся из сохранённого официального `vagrant_2.4.9_SHA256SUMS`; для проверки кеша интернет не нужен. Повреждённый пакет не устанавливается.

Для проверки локального DEB после клонирования выполните `./scripts/install-vagrant.sh --check` на Ubuntu. Проверка не устанавливает пакет. Зависимости apt должны быть доступны отдельно; этот DEB не заменяет полный офлайн-набор платформы.
