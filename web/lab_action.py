#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
from lab_apps import Apps, validate, namespace, templates

def main():
    root=Path(sys.argv[1]);data=json.load(sys.stdin) if len(sys.argv)<3 else {'action':sys.argv[2],'params':{}};action=data['action'];params=data.get('params',{});apps=Apps(root)
    if action=='rancher_install':
        subprocess.run(['bash',str(root/'scripts/install-rancher.sh')],cwd=root,check=True)
    elif action in ('stand_stop','stand_start'):
        print('TASK ['+('Остановка VM с сохранением дисков' if action=='stand_stop' else 'Запуск сохранённых VM')+']',flush=True)
        ids=list((root/'.vagrant/machines').glob('*/*/id'))
        if not ids:raise ValueError('Сохранённые VM не найдены. Сначала создайте кластер.')
        targets=sorted({p.parents[1].name for p in ids})
        selected=params.get('nodes',targets)
        if not isinstance(selected,list) or not selected or any(not isinstance(n,str) or n not in targets for n in selected):raise ValueError('Выберите существующие VM этого кластера')
        targets=sorted(set(selected))
        if action=='stand_start':
            result=subprocess.run(['vagrant','status','--machine-readable']+targets,cwd=root,check=True,capture_output=True,text=True,timeout=60)
            states={}
            for line in result.stdout.splitlines():
                fields=line.split(',')
                if len(fields)>=4 and fields[2]=='state':states[fields[1]]=fields[3]
            if any(states.get(n) not in ('running','poweroff','saved','aborted') for n in targets):
                raise ValueError('Часть VM удалена или её состояние неизвестно. Возобновление не создаёт новые VM; проверьте состояние стенда.')
            pending=[n for n in targets if states[n]!='running']
            if pending:subprocess.run(['vagrant','up','--no-provision','--parallel']+pending,cwd=root,check=True,timeout=600)
            print('TASK [Ожидание Ready возобновлённых узлов]',flush=True)
            inventory=json.loads(subprocess.check_output(['ruby','-ryaml','-rjson','-e',"puts JSON.generate(YAML.load_file('ansible/inventory.yml'))"],cwd=root,text=True))
            names=[name for group in inventory['all']['children'].values() for name,host in group['hosts'].items() if host['vagrant_id'] in targets]
            if len(names)!=len(targets):raise ValueError('VM не совпадают с inventory. Проверьте конфигурацию.')
            if not (root/'kubeconfig').exists():raise ValueError('VM включены, но kubeconfig отсутствует. Выполните создание / применение конфигурации.')
            import time
            deadline=time.monotonic()+180
            while True:
                try:
                    status=apps.get('nodes')
                    ready={n['metadata']['name'] for n in status.get('items',[]) if any(c.get('type')=='Ready' and c.get('status')=='True' for c in n.get('status',{}).get('conditions',[]))}
                    if set(names)<=ready:break
                except (ValueError,subprocess.SubprocessError):pass
                if time.monotonic()>=deadline:raise ValueError('VM включены, но узлы не стали Ready за 180 секунд. Проверьте master, API и сеть.')
                time.sleep(3)
            print('Стенд возобновлён: выбранные узлы Ready. Данные сохранены, Ansible не запускался.',flush=True)
        else:
            subprocess.run(['vagrant','halt']+targets,cwd=root,check=True,timeout=600)
    elif action in ('app_deploy','template_deploy'):
        configs=params.get('apps',[])
        if action=='template_deploy':
            import template_storage
            prepared=template_storage.prepare(apps,params)
            for plan in prepared:apps.deploy(plan[0],plan)
            return
        if not isinstance(configs,list) or not 1<=len(configs)<=10:raise ValueError('Выберите от 1 до 10 приложений')
        validated=[validate(c) for c in configs]
        if len({(c['namespace'],c['name']) for c in validated})!=len(validated):raise ValueError('Повторяются имена приложений')
        claims=[(c['namespace'],c['pvc']) for c in validated if c['storage_mode']=='existing']
        if len(claims)!=len(set(claims)):raise ValueError('Один PVC нельзя подключить к нескольким приложениям набора')
        prepared=[apps.preflight(c) for c in validated]
        hosts=[p[3] for p in prepared if p[3]]
        if len(set(hosts))!=len(hosts):raise ValueError('Повторяются hostname приложений')
        apps.check_capacity(prepared)
        for c,plan in zip(validated,prepared):apps.deploy(c,plan)
    elif action=='rabbit_plugins':
        apps.rabbit_plugins(params)
    elif action in ('app_start','app_stop','app_restart'):
        from lab_apps import dns, MANAGER
        targets=params.get('apps',[])
        if not isinstance(targets,list) or not 1<=len(targets)<=50:raise ValueError('Выберите от 1 до 50 приложений')
        workloads={}
        for target in targets:
            kind=target.get('kind');ns=namespace(target.get('namespace'),True);name=dns(target.get('name'))
            if kind not in ('Deployment','StatefulSet'):raise ValueError('Неизвестный тип приложения')
            obj=apps.get(kind,ns,name);workloads[(kind,ns,name)]=obj
            if obj['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')==MANAGER:
                panel=apps.find('Deployment',ns,name+'-ui')
                if panel and panel['metadata'].get('labels',{}).get('lab.k3s/panel-for')==name and panel['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')==MANAGER:
                    workloads[('Deployment',ns,name+'-ui')]=panel
        for (kind,ns,name),obj in workloads.items():
            target=kind.lower()+'/'+name
            print('TASK ['+action+' '+ns+'/'+name+']',flush=True)
            if action=='app_stop':
                replicas=obj.get('spec',{}).get('replicas',1)
                if replicas>0:
                    apps.kubectl(['annotate',target,'-n',ns,'lab.k3s/replicas-before-stop='+str(replicas),'--overwrite'])
                print(apps.kubectl(['scale',target,'-n',ns,'--replicas=0']),flush=True)
            elif obj.get('spec',{}).get('replicas',1)==0:
                replicas=int(obj['metadata'].get('annotations',{}).get('lab.k3s/replicas-before-stop','1'))
                if replicas<1:replicas=1
                print(apps.kubectl(['scale',target,'-n',ns,'--replicas='+str(replicas)]),flush=True)
                print(apps.wait_rollout(kind,name,ns,300),flush=True)
            elif action=='app_start':
                print('Приложение уже запущено; реплики не меняются.',flush=True)
            else:
                print(apps.kubectl(['rollout','restart',target,'-n',ns]),flush=True)
                print(apps.wait_rollout(kind,name,ns,300),flush=True)
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
