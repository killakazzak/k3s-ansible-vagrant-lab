# Лепим дома — лендинг про пельмени

Адрес: http://pelmeni.192.168.59.11.sslip.io/
Кластер: k8s-cluster1; namespace: pelmeni.
Deployment Nginx → Service ClusterIP → Ingress Traefik.
Доступен с Mac и устройств с маршрутом к сети VM, не из публичного интернета.

## Развёртывание

Из корня репозитория:

```bash
.clusters/k8s-cluster1/kubectl.sh apply --server-side -k examples/pelmeni
.clusters/k8s-cluster1/kubectl.sh -n pelmeni rollout status deployment/pelmeni
```

HTML и фотография лежат в `site/`. Kustomize создаёт ConfigMap с хешем,
поэтому изменения контента автоматически обновляют Deployment при применении.
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
