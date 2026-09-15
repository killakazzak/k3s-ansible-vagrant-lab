"""Read-only template storage selection and deployment checks."""
from lab_apps import templates, validate, namespace, dns, claim_referenced


def configs(data):
    template=next((t for t in templates() if t['name']==data.get('template')),None)
    if not template:raise ValueError('Шаблон не найден')
    ns=namespace(data.get('namespace'),True)
    selections=data.get('storage',{})
    if not isinstance(selections,dict) or set(selections)-{c['name'] for c in template['apps']}:raise ValueError('Некорректный выбор хранилища')
    result=[]
    for original in template['apps']:
        c=dict(original,namespace=ns)
        choice=selections.get(c['name'],{})
        if not isinstance(choice,dict):raise ValueError('Некорректный выбор хранилища')
        c['name']=dns(choice.get('name',c['name']))
        c['storage_mode']=choice.get('storage_mode','none' if c.get('storage_mode')=='none' else 'new')
        c['pvc']=choice.get('pvc','');c['storage_secret']=choice.get('storage_secret','')
        c['storage']=choice.get('storage',c['storage'])
        if c['host'] and '.' not in c['host']:
            if c['name']!=original['name']:c['host']=c['name']
            c['host']+='-'+ns
        result.append(validate(c))
    return result


def options(apps,data):
    values=configs(dict(data,storage={}))
    ns=values[0]['namespace']
    resources=apps.get('deployments,statefulsets,daemonsets,jobs,cronjobs,services,ingresses,configmaps,secrets,pvc',ns)['items']
    pods=apps.get('pods',ns)['items']
    names={o['metadata']['name'] for o in resources}
    def occupied(name):
        return any(n==name or n.startswith(name+'-') or n.startswith('data-'+name+'-') for n in names)
    suggestions={}
    for c in values:
        base=c['name'];candidate=base;i=1
        while occupied(candidate):
            i+=1;candidate=base[:45]+'-'+str(i)
        suggestions[base]=candidate;names.add(candidate)
    claims=[];credentials=[]
    for o in resources:
        m=o['metadata'];name=m['name']
        if o['kind']=='PersistentVolumeClaim':
            used=claim_referenced(name,pods+resources)
            available=not used and not m.get('deletionTimestamp') and o.get('status',{}).get('phase')=='Bound' and o.get('spec',{}).get('volumeMode','Filesystem')=='Filesystem'
            claims.append(dict(name=name,available=available,capacity=o.get('status',{}).get('capacity',{}).get('storage',''),reason='занят или не готов' if not available else 'свободен'))
        elif o['kind']=='Secret' and o.get('data',{}).get('password'):credentials.append(name)
    return dict(names=suggestions,pvcs=claims,secrets=credentials)


def prepare(apps,data):
    values=configs(data)
    if len({c['name'] for c in values})!=len(values):raise ValueError('Повторяются имена приложений')
    claims=[c['pvc'] for c in values if c['storage_mode']=='existing']
    if len(claims)!=len(set(claims)):raise ValueError('Один PVC нельзя подключить к нескольким приложениям набора')
    plans=[apps.preflight(c) for c in values]
    hosts=[o['spec']['rules'][0]['host'] for p in plans for o in p[2] if o['kind']=='Ingress']
    if len(hosts)!=len(set(hosts)):raise ValueError('Повторяются hostname приложений')
    apps.check_capacity(plans)
    return plans


def preview(apps,data):
    plans=prepare(apps,data)
    return dict(ok=True,apps=[dict(name=c['name'],namespace=c['namespace'],mode=c['storage_mode'],pvc=c['pvc'] or ('data-'+c['name']+'-0' if kind=='StatefulSet' else c['name']+'-data') if c['storage_mode']!='none' else '',secret=c['storage_secret'] or (c['name']+'-auth' if c['type'] in ('postgres','rabbitmq') else '')) for c,kind,objects,host in plans])


def suggest_name(apps,data):
    ns=namespace(data.get('namespace'),True)
    base=dns(data.get('base'),'основа имени')
    reserved=data.get('reserved',[])
    if not isinstance(reserved,list) or len(reserved)>100:raise ValueError('Некорректный список имён')
    names={dns(value) for value in reserved}
    names.update(o['metadata']['name'] for o in apps.get('deployments,statefulsets,daemonsets,services,ingresses,configmaps,secrets,pvc',ns)['items'])
    return dict(name=free_name(base,names))


def free_name(base,names):
    base=base[:45].rstrip('-')
    for index in range(1,10001):
        candidate=base+'-'+str(index)
        if not any(n==candidate or n.startswith(candidate+'-') or n.startswith('data-'+candidate+'-') for n in names):return candidate
    raise ValueError('Не удалось подобрать имя. Измените основу имени.')


def editor_storage(apps,data):
    import re
    ns=namespace(data.get('namespace'),True)
    objects=apps.get('pvc,secrets,pods,deployments,statefulsets,daemonsets,jobs,cronjobs',ns)['items']
    credentials=sorted(o['metadata']['name'] for o in objects if o['kind']=='Secret' and o.get('data',{}).get('password'))
    claims=[]
    for o in objects:
        if o['kind']!='PersistentVolumeClaim':continue
        name=o['metadata']['name'];phase=o.get('status',{}).get('phase','Pending')
        reason=''
        if o['metadata'].get('deletionTimestamp'):reason='удаляется'
        elif phase!='Bound':reason=phase
        elif o.get('spec',{}).get('volumeMode','Filesystem')!='Filesystem':reason='не Filesystem'
        elif claim_referenced(name,objects):reason='занят приложением'
        match=re.fullmatch(r'data-(.+)-[0-9]+',name)
        candidate=match[1]+'-auth' if match else ''
        claims.append(dict(name=name,available=not reason,reason=reason,capacity=o.get('status',{}).get('capacity',{}).get('storage',''),secret=candidate if candidate in credentials else ''))
    return dict(pvcs=sorted(claims,key=lambda p:p['name']),secrets=credentials)
