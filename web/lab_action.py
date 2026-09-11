#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
from lab_apps import Apps, validate, namespace, templates

def main():
    root=Path(sys.argv[1]);data=json.load(sys.stdin) if len(sys.argv)<3 else {'action':sys.argv[2],'params':{}};action=data['action'];params=data.get('params',{});apps=Apps(root)
    if action in ('stand_stop','stand_start'):
        print('TASK ['+('Остановка VM с сохранением дисков' if action=='stand_stop' else 'Запуск сохранённых VM')+']',flush=True)
        ids=list((root/'.vagrant/machines').glob('*/*/id'))
        if not ids:raise ValueError('Сохранённые VM не найдены. Сначала создайте кластер.')
        targets=sorted({p.parents[1].name for p in ids})
        selected=params.get('nodes',targets)
        if not isinstance(selected,list) or not selected or any(not isinstance(n,str) or n not in targets for n in selected):raise ValueError('Выберите существующие VM этого кластера')
        targets=sorted(set(selected))
        subprocess.run((['vagrant','halt'] if action=='stand_stop' else ['vagrant','up','--no-provision'])+targets,cwd=root,check=True,timeout=600)
        if action=='stand_start':print('Выбранные VM запущены. Готовность Kubernetes смотрите в статусе: API требует работающего control plane.',flush=True)
    elif action in ('app_deploy','template_deploy'):
        configs=params.get('apps',[])
        if action=='template_deploy':
            template=next((t for t in templates() if t['name']==params.get('template')),None)
            if not template:raise ValueError('Шаблон не найден')
            ns=namespace(params.get('namespace'),True)
            configs=[dict(c,namespace=ns,host=(c['host']+'-'+ns if c['host'] and '.' not in c['host'] else c['host'])) for c in template['apps']]
        if not isinstance(configs,list) or not 1<=len(configs)<=10:raise ValueError('Выберите от 1 до 10 приложений')
        validated=[validate(c) for c in configs]
        if len({(c['namespace'],c['name']) for c in validated})!=len(validated):raise ValueError('Повторяются имена приложений')
        claims=[(c['namespace'],c['pvc']) for c in validated if c['storage_mode']=='existing']
        if len(claims)!=len(set(claims)):raise ValueError('Один PVC нельзя подключить к нескольким приложениям набора')
        prepared=[apps.preflight(c) for c in validated]
        hosts=[p[3] for p in prepared if p[3]]
        if len(set(hosts))!=len(hosts):raise ValueError('Повторяются hostname приложений')
        for c,plan in zip(validated,prepared):apps.deploy(c,plan)
    elif action=='app_delete':
        targets=params.get('apps')
        if targets is None:apps.delete(params)
        else:
            if not isinstance(targets,list) or not 1<=len(targets)<=50:raise ValueError('Выберите от 1 до 50 приложений')
            checked=[]
            for target in targets:
                kind=target.get('kind');ns=namespace(target.get('namespace'),True);name=target.get('name')
                if kind not in ('Deployment','StatefulSet'):raise ValueError('Неизвестный тип приложения')
                from lab_apps import dns
                name=dns(name);apps.get(kind,ns,name)
                item=dict(kind=kind,namespace=ns,name=name,delete_data=False)
                if item not in checked:checked.append(item)
            for target in checked:
                print('TASK [Удалить '+target['namespace']+'/'+target['name']+']',flush=True)
                apps.delete(target)
    elif action in ('app_update','app_rollback','app_check'):
        print('TASK ['+action+']',flush=True)
        if action=='app_check':
            obj=apps.get(params.get('kind'),namespace(params.get('namespace'),True),params.get('name'))
            apps.record_check(obj,'running')
            try:apps.change(params,action)
            except Exception:
                apps.record_check(obj,'failed');raise
        else:apps.change(params,action)
    else:raise ValueError('Неизвестная операция')
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Ошибка: '+str(e),flush=True);sys.exit(1)
