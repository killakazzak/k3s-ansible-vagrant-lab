# k3s: один master и два worker на Mac

Локальная лаборатория Kubernetes на Ubuntu 24.04: Vagrant создаёт три VM в VirtualBox, Ansible устанавливает k3s. Traefik и ServiceLB включены. Один сервер использует встроенную SQLite; это лаборатория без отказоустойчивости control plane.

## Одна команда

После клонирования репозитория и установки Homebrew и VirtualBox:

```bash
./cluster.sh up --verify   # создать кластер и проверить DNS, сеть и Traefik
./cluster.sh destroy       # удалить VM и данные кластера без подтверждения
```

Повторный `up` применяет настройки к существующему кластеру. Для быстрого запуска без дополнительных сетевых тестов: `./cluster.sh up`. Состояние VM: `./cluster.sh status`. Отдельная проверка: `./cluster.sh verify`.

`destroy` действует на VM этого каталога, после успешного удаления убирает локальный kubeconfig и сохраняет кэш загрузок. Данные на дисках VM теряются. Сохранённые отдельно VM Parallels от предыдущего переноса эта команда не удаляет. Удаление и создание можно повторять; для последующего запуска используйте ту же команду `up`.

## Развёртывание с нуля

Нужен Mac **Apple Silicon**, Homebrew и установленный **VirtualBox 7.2 или новее для Apple Silicon** с доступным `VBoxManage`. Для VM выделяется суммарно 4 ГБ RAM и 4 vCPU; оставьте ресурсы macOS и приложениям. Нужны интернет и свободное место для трёх дисков Ubuntu. Intel Mac этим проектом не поддерживается.

1. Установите Homebrew по https://brew.sh и VirtualBox для Apple Silicon с https://www.virtualbox.org/wiki/Downloads. При запросе macOS разрешите работу сетевых компонентов VirtualBox.
2. Клонируйте репозиторий (для приватного репозитория нужна авторизация GitHub):

```bash
git clone https://github.com/killakazzak/k3s-ansible-vagrant-lab.git
cd k3s-ansible-vagrant-lab
./deploy.sh --verify
```

Скрипт устанавливает отсутствующие Vagrant и Ansible, скачивает совместимый kubectl, создаёт VM, настраивает кластер и сохраняет `kubeconfig` с правами 0600. Homebrew может запросить пароль администратора. Без `--verify` выполняются только проверки готовности узлов, CoreDNS и Traefik.

```bash
./kubectl.sh get nodes -o wide
./kubectl.sh get pods -A
./kubectl.sh -n kube-system get svc traefik
```

Первый запуск требует загрузки Ubuntu box, k3s и контейнерных образов. Для ускорения загрузка k3s идёт одновременно с их запуском, бинарник скачивается один раз на Mac с проверкой SHA256 и копируется на узлы. Повторные запуски используют кэш `.cache/`, `.tools/` и Vagrant box. Фиксированное время первого запуска не гарантируется: оно зависит от сети.

## Настройки

Все основные параметры находятся в `ansible/group_vars/all.yml`; список узлов и IP — в `ansible/inventory.yml`. Vagrant читает эти же файлы.

| Параметр | Назначение |
|---|---|
| `k3s_version` | Точная версия k3s, по умолчанию `v1.36.4+k3s1` |
| `vm_box`, `vm_box_version` | Образ Ubuntu и его версия |
| `vm_cpus`, `vm_memory_mb` | CPU/RAM для server и workers |
| `vm_name_prefix` | Префикс имён VM в VirtualBox |
| `private_network_prefix` | Маска сети VM |
| `pod_subnet`, `service_subnet`, `cluster_dns` | Сети Kubernetes и адрес DNS |
| `disabled_components` | Отключён только metrics-server; Traefik и ServiceLB сохранены |
| `server_taints` | По умолчанию приложения запускаются на workers |
| `dns_servers`, `dns_over_tls` | Внешние DNS и DNS-over-TLS |
| `node_ready_timeout`, `rollout_timeout` | Таймауты готовности |

По умолчанию master: `192.168.58.11`, workers: `192.168.58.21` и `.22`, API: `https://192.168.58.11:6443`. На другом Mac проверьте, что подсеть не пересекается с VPN, LAN и другими VM. При конфликте измените IP всех узлов до первого запуска. Не меняйте сети существующего кластера без пересоздания.

Можно переопределить `vm_cpus` и `vm_memory_mb` для конкретного узла прямо в inventory. Параметры CPU/RAM существующей VM применяйте через `vagrant reload`, затем `./deploy.sh`.

DNS узлов использует systemd-resolved и отдельный listener на private IP. CoreDNS пересылает внешние запросы этому resolver. DNS-over-TLS включён для обхода проблем DNS NAT при VPN; сеть должна пропускать TCP 853. Если это не подходит вашей сети, задайте доступные DNS и `dns_over_tls: false`.

## Traefik

Для Ingress используйте `ingressClassName: traefik`. ServiceLB публикует HTTP/HTTPS на портах 80/443 узлов, где запущены его Pod. Проверяйте адреса через `./kubectl.sh -n kube-system get svc traefik`.

Например, для Ingress с host `app.test`, после создания приложения и Service:

```bash
curl --resolve app.test:80:192.168.58.21 http://app.test/
```

DNS-запись или `/etc/hosts` на Mac должны указывать домен приложения на IP worker. TLS-сертификаты и приложения автоматически не создаются. `--verify` создаёт временный nginx на workers и проверяет Ingress, DNS, Service и доступ между Pod, затем удаляет тестовый namespace.

## Повторный запуск и управление

```bash
./deploy.sh                 # применить конфигурацию и проверить готовность
ansible-playbook ansible/verify.yml  # отдельная сетевая проверка
vagrant status
vagrant ssh k3s-master1
vagrant halt                # выключить VM этого проекта
./deploy.sh                 # включить и проверить
```

Добавление worker: добавьте узел с уникальным IP и `vagrant_id` в группу `workers`, затем выполните `./deploy.sh`. Для удаления сначала эвакуируйте приложения (учтите локальные данные):

```bash
./kubectl.sh drain k3s-worker2 --ignore-daemonsets --delete-emptydir-data
vagrant destroy -f k3s-worker2
./kubectl.sh delete node k3s-worker2
```

После этого удалите worker из inventory. Должен остаться хотя бы один worker. `--delete-emptydir-data` разрешает удаление временных данных Pod; перенос persistent volumes требует отдельного плана. Проект поддерживает ровно один master: добавление masters/HA не реализовано.

## Изменение версии

Для новой лаборатории измените `k3s_version` до первого запуска. Для существующего кластера обычный deploy блокирует смену версии, чтобы не выполнять неподготовленное параллельное обновление.

Самый простой вариант для одноразовой лаборатории — сохранить нужные данные, выполнить `vagrant destroy -f`, изменить версию и снова запустить `./deploy.sh --verify`. **Все данные VM при destroy удаляются.**

Обновление с сохранением данных выполняйте по официальной инструкции https://docs.k3s.io/upgrades/manual: резервная копия datastore и server token, последовательное обновление server, затем workers, с проверкой готовности и совместимости версий. `allow_version_change: true` отключает защиту, но не превращает deploy в безопасный rolling upgrade. Downgrade этим проектом не поддерживается.

## Полное удаление

Из каталога проекта:

```bash
./cluster.sh destroy
```

Команда удаляет VM и их данные. Кэш образов Vagrant и инструментов остаётся для следующего запуска. Другие Vagrant-проекты не затрагиваются.

## Диагностика и секреты

```bash
ansible all -m ping
vagrant ssh k3s-master1 -c 'sudo journalctl -u k3s -n 100 --no-pager'
vagrant ssh k3s-worker1 -c 'sudo journalctl -u k3s-agent -n 100 --no-pager'
./kubectl.sh get events -A --sort-by=.lastTimestamp
```

Лог фоновой загрузки: `.cache/assets.log`. При проблемах VPN проверьте маршруты к private IP, HTTPS к GitHub/реестрам контейнеров и DNS TCP 853. Увеличьте RAM worker при нехватке памяти приложений.

`kubeconfig`, `.vagrant/`, `.cache/`, `.tools/`, ключи и логи исключены из Git. Токен присоединения генерируется k3s и передаётся Ansible с `no_log`; его нельзя публиковать. Kubeconfig предоставляет административный доступ к кластеру.

## Проверка проекта

Проверено на Apple Silicon с VirtualBox 7.2.16, Vagrant 2.4.9 и Ansible 14.3.1: три узла `Ready` на k3s `v1.36.4+k3s1`, CoreDNS, Traefik и ServiceLB работают. Проверки `--verify` прошли: внутренний и внешний DNS, Service, HTTP через Traefik и прямой доступ к Pod на обоих workers. Это проверка на текущем Mac; отдельный чистый Mac ещё не проверялся.


## Провайдер виртуализации

По умолчанию `vm_provider: virtualbox`; отдельный Vagrant-плагин для него не нужен. VM видны в менеджере VirtualBox как `k3s-master1`, `k3s-worker1`, `k3s-worker2`.

Для нового окружения можно выбрать `vm_provider: parallels` при установленном и активированном Parallels Pro/Business/Enterprise. Не переключайте провайдер у существующих VM простой заменой переменной: Vagrant хранит привязку провайдера в `.vagrant/`. Используйте отдельный каталог клона и другую подсеть для второго окружения.
