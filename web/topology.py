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
        elif kind=='IngressRoute':
            for route in spec.get('routes',[]):
                for backend in route.get('services',[]):
                    routes.append(dict(id=key+':'+str(len(routes)),name=name,namespace=ns,kind=kind,host=route.get('match',''),path='',controller='Traefik',service=(backend.get('namespace',ns)+'/'+backend['name']) if backend.get('kind','Service')=='Service' else None,internal=backend.get('name') if backend.get('kind')=='TraefikService' else None,port=backend.get('port',''),tls='tls' in spec))
    return dict(nodes=nodes,services=services,pods=pods,routes=routes,endpoints=endpoints)
