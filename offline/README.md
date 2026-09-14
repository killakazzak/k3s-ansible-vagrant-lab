# Офлайн-комплект для macOS ARM64

Комплект рассчитан на Mac Apple Silicon, VirtualBox и Ubuntu 24.04 ARM64
с базовым диском 25 GiB. **Образ Ubuntu исключён из комплекта.** Linux, Windows и Intel Mac этим комплектом не покрываются.

## Подготовить один раз

На компьютере с интернетом получите исходники репозитория и выполните:

```sh
./scripts/fetch-offline.sh
```

Скрипт получает архивы из GitHub Release `offline-macos-arm64-20260915`,
проверяет SHA256 по файлу из Git и распаковывает в `vendor/offline`.
Крупные архивы хранятся в Releases, чтобы не раздувать историю Git.
Обычный `git clone` сам по себе их не скачивает.

Для переноса на другой Mac скопируйте весь проект вместе с `vendor/`,
но без `.clusters`, `.vagrant`, `.cache`, `.offline-venv`, `kubeconfig` и секретов.
Можно также перенести части архива на USB и распаковать без сети:

```sh
./scripts/fetch-offline.sh /Volumes/USB/offline-files
```

## Установка без повторных загрузок

```sh
./scripts/offline-bootstrap.sh
./cluster.sh
```

Bootstrap проверяет комплект и устанавливает недостающие Python 3.13,
Ansible из локальных wheels, Vagrant и VirtualBox.
Для системных установщиков macOS запросит пароль администратора;
после установки VirtualBox может понадобиться разрешение в настройках macOS.
Локальное окружение Ansible находится в `.offline-venv` и создаётся заново на каждом Mac.
Homebrew для этого пути установки не требуется. Системные Bash, Ruby,
`curl`, `tar`, `shasum` и инструменты установки macOS должны быть доступны.

Создайте конфигурацию через меню. При `./deploy.sh` наличие `vendor/offline`
включает офлайн-путь автоматически. Неполный комплект останавливает установку.
При несовместимой версии k3s/Rancher/cert-manager или другом провайдере
будет ошибка с пояснением, а не автоматическое скачивание другой версии.

## Ubuntu — отдельно

Образ Ubuntu не входит в архивы Release. Если box уже есть в кэше Vagrant,
он будет использован повторно. Если его нет, первый `./deploy.sh` вызовет
`./scripts/build-box-25.sh`: этот этап требует интернета для Ubuntu ISO,
Packer и файлов сборки. Остальные компоненты берутся из комплекта.

Для полностью изолированного Mac заранее перенесите свой готовый box:

```sh
vagrant box add --name k8s-lab/ubuntu-24.04-25gb --provider virtualbox --architecture arm64 /путь/ubuntu-25gb.box
```

На исходном Mac сохранённый box находится в `.cache/offline-basebox/ubuntu-25gb.box`.
Он не публикуется в Release и не включён в Git.

## Что входит

- Vagrant 2.4.9 (уже в `vendor/vagrant`), VirtualBox 7.2.16.
- Python 3.13.7 и Ansible Core 2.21.3 со всеми Python-зависимостями.
- kubectl и k3s `v1.36.4+k3s1`, установочный скрипт и системные airgap-образы.
- Charts Rancher 2.15.1 и cert-manager v1.21.1.
- Образы текущего каталога: Nginx 1.30.4, PostgreSQL 18.6, Redis 8.10.1,
  RabbitMQ 4.3.5, Kafka 4.3.1; pgAdmin 9.17, RedisInsight 2.70.0 и AKHQ 0.25.1.
- Образы контроллеров текущей конфигурации Rancher, Traefik и проверок.

Точный список и хеши — `vendor/offline/manifest.json`.
Архивы образов копируются на каждый узел до запуска k3s;
Rancher использует charts из комплекта и встроенные системные charts.
Это соответствует механизмам [K3s airgap](https://docs.k3s.io/installation/airgap)
и [Rancher bundled charts](https://ranchermanager.docs.rancher.com/v2.14/getting-started/installation-and-upgrade/other-installation-methods/air-gapped-helm-cli-install/install-rancher-ha).

## Границы комплекта

Это комплект для перечисленных версий и приложений. Произвольный новый образ,
другая версия или дополнительные функции Rancher могут потребовать новых файлов.
`sslip.io` требует доступного DNS: в полностью изолированной сети настройте
локальный DNS или записи hosts для используемых доменов. Офлайн-пакеты не
заменяют сетевую связность Mac с ВМ. Ошибка `no route to host` требует
отдельной проверки сети и состояния ВМ.

Каждая ВМ хранит архивы и распакованные слои; оставляйте свободное место
сверх данных приложений. Полное развёртывание на чистом Mac с отключённой
сетью пока не проверено; проверка контрольных сумм не заменяет этот тест.

## Пересобрать комплект

На Mac с интернетом, установленным Python/pip и работающим эталонным кластером:

```sh
python3 scripts/offline-download.py
python3 scripts/offline-export-images.py --cluster "$PWD/.clusters/k8s-cluster1" --master k8s-cluster1-master1
python3 scripts/offline-finalize.py
python3 scripts/offline-verify.py vendor/offline
python3 scripts/offline-pack.py
```

Экспортёр сохраняет только контейнерные образы, а не диски ВМ,
Secret или kubeconfig. Ubuntu box намеренно не экспортируется.
Не меняйте версии, оставляя старые архивы: собирайте новый каталог комплекта.
