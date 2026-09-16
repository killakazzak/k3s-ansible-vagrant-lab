"""Build a routing map from Kubernetes objects; never return pod env or secrets."""
def build(items):
    nodes, services, pods, routes, endpoints = [], [], [], [], []
    by_uid = {o.get('metadata', {}).get('uid'): o for o in items if o.get('metadata', {}).get('uid')}
    def ownership(obj):
        chain, seen = [], set()
        current = obj
        while current:
            refs = current.get('metadata', {}).get('ownerReferences', [])
            owner = next((r for r in refs if r.get('controller') is True), None)
            if not owner:
                break
            uid = owner.get('uid')
            if uid in seen:
                break
            seen.add(uid)
            chain.append(dict(kind=owner.get('kind', 'Unknown'), name=owner.get('name', ''), resolved=uid in by_uid))
            current = by_uid.get(uid)
        if chain:
            return dict(kind=chain[-1]['kind'], name=chain[-1]['name'], chain=chain)
        static = 'kubernetes.io/config.mirror' in obj.get('metadata', {}).get('annotations', {})
        return dict(kind='StaticPod' if static else 'Pod', name=obj.get('metadata', {}).get('name', ''), chain=[])
    for obj in items:
        kind=obj.get('kind');meta=obj.get('metadata',{});spec=obj.get('spec',{});status=obj.get('status',{})
        name=meta.get('name','');ns=meta.get('namespace','default');key=ns+'/'+name
        if kind=='Node':
            master=any(k in meta.get('labels',{}) for k in ('node-role.kubernetes.io/control-plane','node-role.kubernetes.io/master'))
            nodes.append(dict(id=name,name=name,role='Master' if master else 'Worker',ready=any(c.get('type')=='Ready' and c.get('status')=='True' for c in status.get('conditions',[])),ip=next((a['address'] for a in status.get('addresses',[]) if a['type']=='InternalIP'),'')))
        elif kind=='Pod':
            pods.append(dict(id=key,name=name,namespace=ns,node=spec.get('nodeName'),workload=ownership(obj),created=meta.get('creationTimestamp',''),qos=status.get('qosClass',''),labels=meta.get('labels',{}),containers=[dict(name=c.get('name',''),image=c.get('image',''),resources=c.get('resources',{}),ports=c.get('ports',[])) for c in spec.get('containers',[])],statuses=[dict(name=c['name'],ready=c.get('ready'),restarts=c.get('restartCount',0),state=c.get('state',{})) for c in status.get('containerStatuses',[])],volumes=[dict(name=v['name'],claim=v.get('persistentVolumeClaim',{}).get('claimName')) for v in spec.get('volumes',[])],ip=status.get('podIP',''),phase=status.get('phase','Unknown'),ready=any(c.get('type')=='Ready' and c.get('status')=='True' for c in status.get('conditions',[]))))
        elif kind=='Service':
            services.append(dict(id=key,name=name,namespace=ns,type=spec.get('type','ClusterIP'),headless=spec.get('clusterIP')=='None',ip=spec.get('clusterIP',''),external=spec.get('externalName',''),ports=spec.get('ports',[])))
        elif kind=='EndpointSlice':
            service=meta.get('labels',{}).get('kubernetes.io/service-name')
            if not service:continue
            for endpoint in (obj.get('endpoints') or []):
                target=endpoint.get('targetRef',{})
                endpoints.append(dict(service=ns+'/'+service,pod=(target.get('namespace',ns)+'/'+target['name']) if target.get('kind')=='Pod' and target.get('name') else None,addresses=endpoint.get('addresses',[]),ready=endpoint.get('conditions',{}).get('ready'),node=endpoint.get('nodeName')))
        elif kind=='Ingress':
            for rule in spec.get('rules',[]):
                for path in rule.get('http',{}).get('paths',[]):
                    backend=path.get('backend',{}).get('service',{})
                    routes.append(dict(id=key+':'+str(len(routes)),name=name,namespace=ns,kind=kind,host=rule.get('host','*'),path=path.get('path','/'),pathType=path.get('pathType',''),controller=spec.get('ingressClassName',meta.get('annotations',{}).get('kubernetes.io/ingress.class','по умолчанию')),service=ns+'/'+backend['name'] if backend.get('name') else None,port=backend.get('port',{}).get('number',backend.get('port',{}).get('name','')),tls=any(rule.get('host') in t.get('hosts',[]) for t in spec.get('tls',[]))))
            backend=spec.get('defaultBackend',{}).get('service',{})
            if backend.get('name'):routes.append(dict(id=key+':default',name=name,namespace=ns,kind=kind,host='*',path='default backend',service=ns+'/'+backend['name'],port=backend.get('port',{}),controller=spec.get('ingressClassName','по умолчанию')))
        elif kind in ('IngressRoute','IngressRouteTCP','IngressRouteUDP'):
            for route in spec.get('routes',[]):
                for backend in route.get('services',[]):
                    routes.append(dict(id=key+':'+str(len(routes)),name=name,namespace=ns,kind=kind,host=route.get('match',', '.join(spec.get('entryPoints',[]))),path='',protocol='TCP' if kind.endswith('TCP') else 'UDP' if kind.endswith('UDP') else 'HTTP',controller='Traefik',service=(backend.get('namespace',ns)+'/'+backend['name']) if backend.get('kind','Service')=='Service' else None,internal=backend.get('name') if backend.get('kind')=='TraefikService' else None,port=backend.get('port',''),tls='tls' in spec))
        elif kind in ('VirtualServer','VirtualServerRoute','TransportServer'):
            upstreams={u.get('name'):u for u in spec.get('upstreams',[])}
            entries=spec.get('routes',spec.get('subroutes',[])) if kind!='TransportServer' else [{'action':spec.get('action',{})}]
            for entry in entries:
                targets=[entry.get('action',{}).get('pass')]+[split.get('action',{}).get('pass') for split in entry.get('splits',[])]
                for target in [t for t in targets if t] or [None]:
                    upstream=upstreams.get(target,{})
                    routes.append(dict(id=kind+':'+key+':'+str(len(routes)),name=name,namespace=ns,kind=kind,host=spec.get('host','*'),path=entry.get('path',''),controller=spec.get('ingressClassName','NGINX'),protocol=spec.get('listener',{}).get('protocol','HTTP'),service=ns+'/'+upstream['service'] if upstream.get('service') else None,port=upstream.get('port',''),tls=bool(spec.get('tls'))))
    classes=[o for o in items if o.get('kind')=='IngressClass']
    controllers=[]
    for cls in classes:
        meta=cls['metadata'];name=meta['name'];identifier=cls.get('spec',{}).get('controller','');annotations=meta.get('annotations',{})
        release=annotations.get('meta.helm.sh/release-name');namespace=annotations.get('meta.helm.sh/release-namespace')
        services_for_class=[o for o in items if o.get('kind')=='Service' and release and namespace and o['metadata'].get('namespace')==namespace and o['metadata'].get('labels',{}).get('app.kubernetes.io/instance')==release]
        # Only infer a controller endpoint from an unambiguous Helm association.
        front=[o for o in services_for_class if o.get('spec',{}).get('type') in ('NodePort','LoadBalancer')]
        service=front[0] if len(front)==1 else None
        controllers.append(dict(name=name,controller=identifier,service=(namespace+'/'+service['metadata']['name']) if service else None))
        matches=[route for route in routes if route.get('controller')==name or (route.get('controller')=='по умолчанию' and annotations.get('ingressclass.kubernetes.io/is-default-class')=='true')]
        for route in matches:
            route['controllerClass']=name;route['controller']=name+' · '+identifier
            if service:
                port=next((p for p in service['spec'].get('ports',[]) if p.get('port')==(443 if route.get('tls') else 80)),None)
                if port and service['spec']['type']=='NodePort':route['entryPort']=port.get('nodePort')
        if not matches:
            routes.append(dict(id='controller:'+name,name=name,namespace=namespace or 'cluster',kind='IngressController',host='',path='',controller=identifier,service=namespace+'/'+service['metadata']['name'] if service else None,port='',controllerOnly=True))
    return dict(nodes=nodes,services=services,pods=pods,routes=routes,endpoints=endpoints,controllers=controllers)


def attach_metrics(result, items):
    """Attach only observed usage; missing container samples remain unknown."""
    from lab_apps import resource_quantity
    indexed = {(m.get('metadata', {}).get('namespace'), m.get('metadata', {}).get('name')): m for m in items}
    for pod in result['pods']:
        sample = indexed.get((pod['namespace'], pod['name']), {})
        containers = {c['name']: c.get('usage', {}) for c in sample.get('containers', [])}
        for container in pod['containers']:
            usage = containers.get(container['name'], {})
            if 'cpu' not in usage or 'memory' not in usage:
                continue
            try:
                container['usage'] = dict(cpu=resource_quantity(usage['cpu'])*1000, memory=resource_quantity(usage['memory'])/1024**2, timestamp=sample.get('timestamp'), window=sample.get('window'))
            except ValueError:
                continue


def attach_summary(result, samples):
    indexed = {(p['namespace'], p['name']): p for p in result['pods']}
    for sample in samples:
        ref = sample.get('podRef', {})
        pod = indexed.get((ref.get('namespace'), ref.get('name')))
        if not pod:
            continue
        containers = {c['name']: c for c in sample.get('containers', [])}
        for container in pod['containers']:
            sample = containers.get(container['name'], {})
            cpu, memory = sample.get('cpu', {}), sample.get('memory', {})
            if 'usageNanoCores' in cpu and 'workingSetBytes' in memory:
                container['usage'] = dict(cpu=cpu['usageNanoCores']/1e6, memory=memory['workingSetBytes']/1024**2, timestamp=cpu.get('time'), window='kubelet')
