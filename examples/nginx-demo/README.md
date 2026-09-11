# Тестовый сайт Nginx через Ingress

Адрес текущего развёртывания: http://nginx.192.168.59.11.sslip.io/
Кластер: `k8s-cluster1`. Namespace: `nginx-demo`.
Сайт доступен с Mac и других устройств, имеющих маршрут к сети VM; публичного доступа из интернета это не создаёт.

Манифест содержит Namespace, ConfigMap с HTML, Deployment Nginx, Service и Ingress класса `traefik`. Используется HTTP entrypoint `web`.

Из корня репозитория:

```bash
.clusters/k8s-cluster1/kubectl.sh apply -f examples/nginx-demo/site.yaml
.clusters/k8s-cluster1/kubectl.sh -n nginx-demo rollout status deployment/nginx-demo
curl --noproxy '*' http://nginx.192.168.59.11.sslip.io/
```

Для другого кластера укажите его путь к `kubectl.sh` и замените `spec.rules[0].host` в Ingress на `nginx.<IP-master>.sslip.io`. Traefik должен быть включён.

Удаление только тестового сайта и его namespace:

```bash
.clusters/k8s-cluster1/kubectl.sh delete -f examples/nginx-demo/site.yaml
```
