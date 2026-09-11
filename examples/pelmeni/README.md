# Лепим дома — лендинг про пельмени

Адрес: http://pelmeni.192.168.59.11.sslip.io/
Кластер: k8s-cluster1; namespace: pelmeni.
StatefulSet Nginx → Service ClusterIP → Ingress Traefik.
Доступен с Mac и устройств с маршрутом к сети VM, не из публичного интернета.

## Развёртывание

Из корня репозитория:

```bash
.clusters/k8s-cluster1/kubectl.sh apply --server-side -k examples/pelmeni
.clusters/k8s-cluster1/kubectl.sh -n pelmeni rollout status statefulset/pelmeni
```

HTML и фотография лежат в `site/`. Kustomize создаёт ConfigMap с хешем,
поэтому изменения контента автоматически обновляют StatefulSet при применении.
Server-side apply не сохраняет большую копию фото в last-applied annotation.
Для другого кластера поменяйте hostname Ingress в `resources.yaml` и путь к kubectl.sh.

Удаление только этого сайта:

```bash
.clusters/k8s-cluster1/kubectl.sh delete namespace pelmeni
```

## Фото

Bernd Hutschenreuther, 2006: https://commons.wikimedia.org/wiki/File:Pelmeni.jpg
Источник: https://upload.wikimedia.org/wikipedia/commons/4/49/Pelmeni.jpg
Лицензия CC BY-SA 3.0: https://creativecommons.org/licenses/by-sa/3.0/
Файл сохранён без изменений; в дизайне кадрируется через object-fit.

StatefulSet использует Pod `pelmeni-0` и Headless Service `pelmeni-headless`
для стабильного DNS: `pelmeni-0.pelmeni-headless.pelmeni.svc.cluster.local`.
Внешний трафик по-прежнему идёт через Ingress и ClusterIP Service `pelmeni`.
PVC не требуется: статический контент хранится в ConfigMap; сайт не записывает данные.

При переходе с прежней версии после готовности StatefulSet удалите старый Deployment:

```bash
.clusters/k8s-cluster1/kubectl.sh -n pelmeni delete deployment pelmeni --ignore-not-found
```
