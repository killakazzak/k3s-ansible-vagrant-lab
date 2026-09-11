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
        subprocess.run((['vagrant','halt'] if action=='stand_stop' else ['vagrant','up','--no-provision'])+targets,cwd=root,check=True,timeout=600)
        if action=='stand_start':print(apps.kubectl(['wait','--for=condition=Ready','nodes','--all','--timeout=180s'],timeout=190),flush=True)
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
        prepared=[apps.preflight(c) for c in validated]
        hosts=[p[3] for p in prepared if p[3]]
        if len(set(hosts))!=len(hosts):raise ValueError('Повторяются hostname приложений')
        for c,plan in zip(validated,prepared):apps.deploy(c,plan)
    elif action in ('app_update','app_rollback','app_check'):
        print('TASK ['+action+']',flush=True);apps.change(params,action)
    else:raise ValueError('Неизвестная операция')
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Ошибка: '+str(e),flush=True);sys.exit(1)
