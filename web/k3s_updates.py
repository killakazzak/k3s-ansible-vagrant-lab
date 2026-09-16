"""Sequential patch and minor upgrades for platform-managed Vagrant k3s clusters."""
import hashlib, json, re, shlex, subprocess, time
from urllib.request import urlopen, Request


def version(value):
    match=re.fullmatch(r"v(1)\.(\d+)\.(\d+)\+k3s(\d+)",str(value))
    if not match:raise ValueError('Поддерживаются только стабильные версии k3s')
    return tuple(map(int,match.groups()))


def stable_releases():
    request=Request('https://api.github.com/repos/k3s-io/k3s/releases?per_page=100',headers={'Accept':'application/vnd.github+json','User-Agent':'k3s-lab'})
    try:
        with urlopen(request,timeout=20) as response:releases=json.load(response)
    except Exception:
        raise ValueError('Не удалось получить версии k3s из GitHub. Проверьте подключение и повторите попытку.') from None
    tags=set()
    for release in releases:
        if release.get('draft') or release.get('prerelease'):continue
        tag=release.get('tag_name','')
        try:version(tag)
        except ValueError:continue
        tags.add(tag)
    result=sorted(tags,key=version,reverse=True)[:5]
    if not result:raise ValueError('GitHub не вернул стабильные версии k3s')
    return {'versions':result}


def yaml_file(root,path):
    return json.loads(subprocess.check_output(['ruby','-ryaml','-rjson','-e','puts JSON.generate(YAML.load_file(ARGV[0]))',str(root/path)],text=True,timeout=15))


def preview(apps,requested=None):
    root=apps.root
    if (root/'connection.json').exists():raise ValueError('Удалённый кластер обновляется через провайдера или администратора узлов')
    config=yaml_file(root,'ansible/group_vars/all.yml')
    if config.get('k3s_embedded_etcd') is not True:raise ValueError('Обновление пока поддерживает только кластеры с embedded etcd')
    inventory=yaml_file(root,'ansible/inventory.yml')['all']['children']
    nodes=apps.get('nodes')['items'];live={n['metadata']['name']:n for n in nodes};ordered=[]
    for role in ('server','workers'):
        for name,host in inventory[role]['hosts'].items():
            n=live.get(name)
            if not n or not any(c.get('type')=='Ready' and c.get('status')=='True' for c in n.get('status',{}).get('conditions',[])):raise ValueError('Все узлы должны быть доступны и Ready: '+name)
            vm=host.get('vagrant_id',name)
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*',vm):raise ValueError('Некорректный идентификатор VM')
            ordered.append(dict(name=name,vm=vm,role=role,version=n['status']['nodeInfo']['kubeletVersion'],uid=n['metadata']['uid'],cordoned=bool(n.get('spec',{}).get('unschedulable'))))
    if not ordered or set(live)!={n['name'] for n in ordered}:raise ValueError('Состав узлов отличается от inventory')
    versions=[version(n['version']) for n in ordered]
    oldest=min(versions);newest=max(versions);mixed=oldest[:2]!=newest[:2]
    if newest[1]-oldest[1]>1:raise ValueError('Узлы отличаются более чем на одну minor-версию; требуется ручное восстановление')
    servers=[version(n['version']) for n in ordered if n['role']=='server']
    workers=[version(n['version']) for n in ordered if n['role']=='workers']
    if not servers or (workers and max(workers)[:2]>min(servers)[:2]):raise ValueError('Worker новее server; сначала восстановите совместимость версий узлов')
    choices=[];warnings=[]
    from urllib.parse import unquote
    from urllib.error import HTTPError
    for minor in ([newest[1]] if mixed else [oldest[1],oldest[1]+1]):
        channel='https://update.k3s.io/v1-release/channels/v1.'+str(minor)
        try:
            with urlopen(channel,timeout=20) as response:tag=unquote(response.geturl().rstrip('/').rsplit('/',1)[-1])
            value=version(tag)
            if value[:2]!=(1,minor):raise ValueError('Канал вернул другую minor-версию')
        except HTTPError as error:
            if minor>newest[1] and error.code==404:continue
            raise ValueError('Не удалось проверить канал k3s v1.'+str(minor)) from None
        except Exception:
            if minor>newest[1]:
                warnings.append('Не удалось проверить следующую minor-ветку. Повторите проверку позже.');continue
            raise ValueError('Не удалось проверить канал текущей версии k3s') from None
        if value<newest:raise ValueError('Установленная версия новее канала; понижение запрещено')
        choices.append(dict(version=tag,minor_upgrade=minor>oldest[1],available=any(v<value for v in versions),channel=channel))
    selected=next((c for c in choices if c['version']==requested),None) if requested else choices[0]
    if not selected:raise ValueError('Выбранная версия недоступна. Повторите проверку. Понижение и пропуск minor-версий запрещены.')
    fingerprint=hashlib.sha256(json.dumps({'nodes':ordered,'config':config},sort_keys=True).encode()).hexdigest()
    return dict(target=selected['version'],nodes=ordered,available=selected['available'],minor_upgrade=selected['minor_upgrade'],fingerprint=fingerprint,channel=selected['channel'],choices=choices,warnings=warnings,mixed=mixed,current_branch='1.'+str(oldest[1]))


def ssh(apps,node,script,timeout=180):
    subprocess.run(['vagrant','ssh',node['vm'],'-c','sudo bash -ec '+shlex.quote(script)],cwd=apps.root,check=True,timeout=timeout)


def upgrade(apps,params):
    plan=preview(apps,params.get('target'))
    if params.get('target')!=plan['target'] or params.get('fingerprint')!=plan['fingerprint']:raise ValueError('Состояние кластера или доступная версия изменились. Повторите проверку обновлений.')
    if not plan['available']:raise ValueError('Все узлы уже обновлены')
    if plan.get('minor_upgrade') and params.get('minor_confirmed') is not True:raise ValueError('Подтвердите проверку совместимости приложений перед сменой minor-версии')
    target=plan['target'];stamp=str(int(time.time()))
    pending=[n for n in plan['nodes'] if n['version']!=target]
    # Stage and verify all binaries before touching any running service.
    for n in pending:
        print('TASK [Загрузка и проверка SHA256: '+n['name']+']',flush=True)
        ssh(apps,n,"""set -eu
case $(uname -m) in x86_64) asset=k3s; arch=amd64;; aarch64) asset=k3s-arm64; arch=arm64;; *) exit 1;; esac
stage=/var/lib/rancher/k3s/lab-upgrade/"""+target+"""
install -d -m 700 "$stage"
cd "$stage"
base=https://github.com/k3s-io/k3s/releases/download/"""+target+"""
curl -fL --connect-timeout 15 --max-time 300 --retry 3 "$base/$asset" -o "$asset"
curl -fL --connect-timeout 15 --max-time 60 --retry 3 "$base/sha256sum-$arch.txt" -o sums
awk -v file="$asset" '$2 == file || $2 == "*" file {print}' sums > selected
[ $(wc -l < selected) -eq 1 ]
sha256sum -c selected
chmod 755 "$asset"
./"$asset" --version | head -1
""",timeout=1500)
    for n in plan['nodes']:
        if n['role']=='server':
            print('TASK [Резервная копия etcd: '+n['name']+']',flush=True)
            ssh(apps,n,'k3s etcd-snapshot save --name lab-pre-upgrade-'+stamp+'; install -m 600 /var/lib/rancher/k3s/server/token /var/lib/rancher/k3s/server/db/snapshots/lab-pre-upgrade-'+stamp+'.token',timeout=180)
    for n in pending:
        print('TASK [Обновление '+n['name']+' → '+target+']',flush=True)
        if not n['cordoned']:apps.kubectl(['cordon',n['name']])
        service='k3s' if n['role']=='server' else 'k3s-agent'
        ssh(apps,n,"""set -eu
stage=/var/lib/rancher/k3s/lab-upgrade/"""+target+"""
case $(uname -m) in x86_64) asset=k3s;; aarch64) asset=k3s-arm64;; *) exit 1;; esac
cp -p /usr/local/bin/k3s "$stage/previous-k3s"
install -m 755 "$stage/$asset" /usr/local/bin/k3s.lab-new
mv /usr/local/bin/k3s.lab-new /usr/local/bin/k3s
systemctl restart """+service,timeout=180)
        deadline=time.monotonic()+240
        while True:
            try:
                live=apps.get('node',None,n['name'])
                ready=any(c.get('type')=='Ready' and c.get('status')=='True' for c in live.get('status',{}).get('conditions',[]))
                if ready and live['status']['nodeInfo']['kubeletVersion']==target:break
            except (ValueError,subprocess.SubprocessError):pass
            if time.monotonic()>deadline:raise ValueError('Узел '+n['name']+' не подтвердил новую версию и Ready. Обновление остановлено, узел оставлен cordoned. Проверьте журнал службы; автоматический downgrade не выполняется.')
            time.sleep(3)
        if not n['cordoned']:apps.kubectl(['uncordon',n['name']])
        print(n['name']+': '+target+' · Ready',flush=True)
    # Update desired version only after every node has completed successfully.
    path=apps.root/'ansible/group_vars/all.yml';text=path.read_text()
    updated,count=re.subn(r'^k3s_version:.*$', 'k3s_version: '+target,text,flags=re.M)
    if count!=1:raise ValueError('Узлы обновлены, но k3s_version нужно сохранить в конфигурации вручную')
    temporary=path.with_suffix('.upgrade.tmp');temporary.write_text(updated);temporary.chmod(path.stat().st_mode & 0o777);temporary.replace(path)
    print('Готово: k3s обновлён. VM, приложения и PVC сохранены. Резервные копии etcd и token находятся на server-узлах в /var/lib/rancher/k3s/server/db/snapshots/.',flush=True)
