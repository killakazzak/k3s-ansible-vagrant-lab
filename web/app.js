'use strict';
const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('token')) { sessionStorage.setItem('lab-token', fragment.get('token')); history.replaceState(null, '', '/'); }
const token = sessionStorage.getItem('lab-token') || '';
let selectedCluster = sessionStorage.getItem('lab-cluster') || 'default';
let state = null, currentAction = null, busy = false, lastJob = null;
let clusterCount = 0, refreshPromise = null;
async function api(path, data) {
  const response = await fetch('/api/' + path, {method: data ? 'POST' : 'GET', headers: {'X-Lab-Token':token,'X-Lab-Cluster':selectedCluster,'Content-Type':'application/json'}, ...(data ? {body:JSON.stringify(data)} : {})});
  const result = await response.json(); if (!response.ok) throw Error(result.error); return result;
}
let deployingCluster = null;
function error(message) {
  const pending = /kubeconfig is missing|Доступ к кластеру пока не готов/.test(message || '');
  const creating = deployingCluster === selectedCluster;
  $('error').className = pending ? 'notice' : 'error';
  $('error').setAttribute('role', pending ? 'status' : 'alert');
  $('error').textContent = pending
    ? (creating ? 'Кластер создаётся. Доступ появится после завершения настройки. Ход развёртывания — в журнале ниже.' : 'Кластер пока не готов к подключению. Если создание уже запущено, дождитесь завершения. Для создания нового кластера нажмите «Новый кластер».')
    : message;
  $('error').hidden = !message;
}
function element(tag, text, cls) { const e=document.createElement(tag); if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e; }
let activeJob = null;
function renderProgress() {
  renderClusterCheck();
  const job = activeJob;
  const own = job && (job.cluster || 'default') === selectedCluster;
  const running = own && job.state === 'running';
  const panel = $('operation-progress');
  panel.hidden = !own;
  if (!own) return;
  const labels = {create:'Кластер создаётся',version:'Кластер пересоздаётся',add_master:'Добавляется master',add_worker:'Добавляется worker',destroy:'Кластер удаляется',verify:'Кластер проверяется',resources:'Ресурсы обновляются'};
  panel.className = 'operation-progress ' + job.state;
  $('progress-title').textContent = running ? (labels[job.action] || 'Операция выполняется') : job.state === 'success' ? 'Операция завершена успешно' : 'Операция остановлена с ошибкой';
  const seconds = Math.max(0, Math.floor(((job.finished || Date.now()/1000) - job.started)));
  $('progress-time').textContent = 'Прошло: ' + Math.floor(seconds/60) + ' мин ' + seconds%60 + ' с';
  if (running) {
    const estimate = job.estimated_seconds;
    const remaining = estimate - seconds;
    $('progress-time').textContent += Number.isFinite(estimate) && estimate > 0
      ? (remaining > 0 ? ' · Осталось ≈ ' + Math.ceil(remaining/60) + ' мин' : ' · Дольше прогноза — выполнение продолжается')
      : ' · Оставшееся время: пока нет данных';
    $('progress-time').title = estimate > 0
      ? 'Примерная оценка по последним успешным операциям с такими параметрами. Скорость сети и нагрузка Mac могут изменить время.'
      : 'После первого успешного выполнения появится оценка для следующих запусков с такими параметрами.';
  } else {
    $('progress-time').title = '';
  }
  const lines = (job.log || '').replace(/\x1b\[[0-9;]*[A-Za-z]/g, '').split('\n');
  const stage = lines.filter(line => /^(TASK \[|PLAY \[|==>)/.test(line)).pop();
  $('progress-stage').textContent = running
    ? (stage ? stage.replace(/\*+$/,'').trim() : 'Запуск скрипта…')
    : job.state === 'success' ? 'Скрипт полностью завершил работу.' : 'Подробности и причина ошибки — в журнале операций ниже.';
  panel.querySelector('.progress-track').hidden = !running;
  if (running) {
    $('health').textContent = job.action === 'create' ? 'Создаётся' : 'В процессе';
    $('health-detail').textContent = 'Ждём завершения всех этапов скрипта';
  }
}
function render() {
  if(typeof renderRemoteProfile==='function')renderRemoteProfile();
  if(typeof renderMetricsServer==='function')renderMetricsServer({enabled:state.metricsEnabled,exists:state.exists});
  const ready=state.nodes.filter(n=>n.state==='Ready').length;
  $('health').textContent=state.exists===false?'Не создан':state.paused?'Остановлен':state.reachable?'На связи':'Недоступен';
  $('health-detail').textContent=state.exists===false?'ВМ удалены. Сохранена только конфигурация.':state.paused?'VM выключены, диски и данные сохранены.':state.reachable?'Kubernetes API отвечает':'Нет подключения к API';
  $('node-count').textContent=ready+' / '+state.nodes.length;
  $('roles').textContent=state.nodes.filter(n=>n.role==='server').length+' master · '+state.nodes.filter(n=>n.role==='workers').length+' workers';
  $('memory').textContent=(state.nodes.reduce((s,n)=>s+n.ram,0)/1024).toFixed(0)+' ГБ';
  $('version').textContent=state.version; $('provider').textContent=state.external?'Удалённый кластер · только просмотр':state.provider+' · ARM64';
  $('node-list').replaceChildren();
  if(!state.nodes.length){const row=element('tr'),cell=element('td','Кластер пуст. Нажмите «Новый кластер».');cell.colSpan=6;row.append(cell);$('node-list').append(row)}
  for (const node of state.nodes) {
    const tr=element('tr'),name=element('td');name.append(element('span',node.name,'node-name'),element('span',node.role==='server'?'CONTROL PLANE':'WORKER','role'));tr.append(name);
    const status=element('td');status.append(element('span',(node.state==='Absent'?'Не создан':node.state)+(node.vm_state==='poweroff'?' / VM выключена':''),'badge '+node.state));tr.append(status,element('td',node.ip),element('td',node.cpu+' CPU / '+(node.ram/1024).toFixed(1)+' ГБ'+(state.external?'':' / '+node.disk+' ГБ диск')));
    const usage=element('td',undefined,'node-utilization');usage.dataset.node=node.name;tr.append(usage);
    const actions=element('td'),wrap=element('div',undefined,'nodebuttons');
    const edit=element('button','Настроить','textbutton');edit.dataset.action='resources';edit.dataset.node=node.name;wrap.append(edit);
    const protectedNode=node.role==='server'?state.nodes.find(n=>n.role==='server')===node:state.nodes.filter(n=>n.role==='workers').length<=1;
    if(!protectedNode){const remove=element('button','Удалить','textbutton remove');remove.dataset.action=node.role==='server'?'remove_master':'remove_worker';remove.dataset.node=node.name;wrap.append(remove)}
    actions.append(wrap);tr.append(actions);$('node-list').append(tr);
  }
  setBusy(busy);
  renderNodeUsage();
  renderProgress();
}
function setBusy(value){busy=value;if(typeof renderMetricsServer==='function')renderMetricsServer();$('cluster-select').disabled=clusterCount===0;$('new-cluster').disabled=value;$('create-cluster').disabled=value;document.querySelectorAll('[data-action]').forEach(b=>b.disabled=value || !!state?.external || (!!state && !state.nodes.length && !['create'].includes(b.dataset.action)))}
async function refresh(){
  while(refreshPromise){await refreshPromise;}
  const cluster=selectedCluster;
  const request=(async()=>{try{$('refresh').disabled=true;const result=await api('status');if(cluster!==selectedCluster)return;state=result;render();renderClusterCheck();error(state.error||'')}catch(e){if(cluster===selectedCluster)error(e.message)}finally{$('refresh').disabled=false}})();
  refreshPromise=request;
  await request;
  if(refreshPromise===request)refreshPromise=null;
}
async function loadLinks(){const cluster=selectedCluster;if(state?.external)return;if(state && !state.nodes.length){for(const name of ['rancher','traefik']){const a=$(name+'-link');a.removeAttribute('href');a.textContent='Появится после создания кластера'}return;}try{const links=await api('links');if(cluster!==selectedCluster)return;for(const name of ['rancher','traefik']){const a=$(name+'-link');if(state && !state[name]){a.textContent='Отключён в конфигурации';a.removeAttribute('href');continue}const url=new URL(links[name]);if(url.protocol!=='https:')throw Error('Некорректная ссылка');a.href=url.href;a.textContent=url.hostname+' ↗'}}catch(e){if(cluster!==selectedCluster)return;for(const name of ['rancher','traefik'])$(name+'-link').textContent='Адрес недоступен';error(e.message)}}
function componentChoice(){
 const metricsLabel=element('label');const metrics=element('select');metrics.name='metrics_enabled';metrics.id='field-metrics_enabled';metricsLabel.htmlFor=metrics.id;metricsLabel.textContent='Метрики CPU/RAM';for(const [value,text] of [['true','Включены — Metrics Server'],['false','Не устанавливать']]){const o=element('option',text);o.value=value;metrics.append(o)}$('fields').append(metricsLabel,metrics);

 const label=element('label','Компоненты');label.htmlFor='field-rancher_enabled';
 const select=element('select');select.id='field-rancher_enabled';select.name='rancher_enabled';
 for(const [value,text] of [['false','Быстрый старт: Kubernetes + Traefik'],['true','Kubernetes + Traefik + Rancher']]){const option=element('option',text);option.value=value;select.append(option)}
 select.value='false';$('fields').append(label,select,element('p','Rancher можно установить позднее. Образы и charts повторно используются из локального кеша.'));
 const update=()=>{for(const role of ['server','workers']){const input=$('field-'+role+'_ram');if(input){input.min=select.value==='true'?'4096':'1024';if(Number(input.value)<Number(input.min))input.value=input.min}}};select.onchange=()=>{update();showCreationBudget()};update();
}
const definitions={create:['Создать кластер','Выберите количество узлов, ресурсы и сеть нового кластера.'],add_master:['Добавить master','Для устойчивости etcd нужны 3 master. Первый master остаётся адресом API.'],add_worker:['Добавить worker','Новая виртуальная машина присоединится к текущему кластеру.'],remove_master:['Удалить master','Будут выполнены snapshot etcd, drain и исключение узла из etcd. Данные VM будут удалены.'],remove_worker:['Удалить worker','Будут выполнены drain и удаление VM. Данные диска и emptyDir будут потеряны; локальные PV не переносятся автоматически.'],resources:['Ресурсы узла','Существующая VM будет перезагружена. Изменение master временно прервёт доступ к API.'],version:['Изменить версию k3s','Это пересоздание лаборатории: все VM и их данные будут удалены. Это не обновление с сохранением данных.'],destroy:['Удалить кластер','Все виртуальные машины этого проекта и данные их дисков будут удалены. Кэш загрузок сохранится.'],verify:['Проверить кластер','Проверим DNS, межузловую сеть и HTTP через Traefik. Тестовые ресурсы будут удалены после проверки.']};
function field(name,label,value='',type='text',min,max){const l=element('label',label);l.htmlFor='field-'+name;const input=element('input');input.id=l.htmlFor;input.name=name;input.type=type;input.value=value;input.required=true;if(min!==undefined)input.min=min;if(max!==undefined)input.max=max;$('fields').append(l,input)}
function openAction(action,nodeName){if(!state)return;currentAction=action;$('fields').replaceChildren();$('form-error').hidden=true;$('submit').hidden=false;$('submit').textContent='Подтвердить';$('modal-title').textContent=definitions[action][0];$('modal-description').textContent='Кластер: '+selectedCluster+'. '+definitions[action][1];
 if(nodeName){const input=element('input');input.type='hidden';input.name='node';input.value=nodeName;$('fields').append(input);$('modal-description').textContent='Кластер: '+selectedCluster+'. '+nodeName+'. '+definitions[action][1]}
 if(action==='create'){$('modal-title').textContent='Развёртывание: '+selectedCluster;field('masters','Количество master',(state.nodes.filter(n=>n.role==='server').length||1),'number',1,7);field('workers','Количество workers',(state.nodes.filter(n=>n.role==='workers').length||2),'number',1,32);for(const role of ['server','workers']){const n=state.nodes.find(n=>n.role===role)||state.defaults[role];field(role+'_cpu',(role==='server'?'Master':'Worker')+': CPU на узел',n.cpu,'number',1,32);field(role+'_ram','ОЗУ на узел, МБ',n.ram,'number',state.rancher?4096:1024,65536);field(role+'_disk','Диск на узел, ГБ (от 25)',n.disk,'number',25,2048)}componentChoice();const label=element('label','Сеть кластера');label.htmlFor='network-mode';const select=element('select');select.name='network_mode';select.id='network-mode';for(const [value,text] of [['existing','Существующая: '+state.network],['new','Новая подсеть']]){const o=element('option',text);o.value=value;select.append(o)}$('fields').append(label,select);field('network','Подсеть с префиксом',state.network);const input=$('field-network');input.disabled=true;select.onchange=()=>{input.disabled=select.value==='existing'};$('fields').append(element('p','IP назначаются автоматически: обычно master с .11, workers с .21. Адрес .1 зарезервирован для Mac. Новая сеть и размеры дисков применяются при создании VM.'))}
 if(action.startsWith('add_')){const n=state.nodes.find(n=>n.role===(action==='add_master'?'server':'workers'));const role=action==='add_master'?'master':'worker';let index=1;while(state.nodes.some(node=>node.name===state.node_prefix+'-'+role+index))index++;field('name','Имя узла',state.node_prefix+'-'+role+index);field('cpu','CPU — количество ядер',n.cpu,'number',1,32);field('ram','ОЗУ, МБ',n.ram,'number',state.rancher?4096:1024,65536);field('disk','Диск, ГБ',n.disk,'number',25,2048);field('ip','IPv4 — оставить пустым для автоматического назначения');$('field-ip').required=false;$('field-ip').placeholder='Автоматически из '+state.network;$('fields').append(element('p','Используется сеть текущего кластера: '+state.network+'. Новую сеть можно выбрать при создании кластера.'))}
 if(action==='resources'){const n=state.nodes.find(n=>n.name===nodeName);field('cpu','CPU',n.cpu,'number',1,32);field('ram','RAM, МБ',n.ram,'number',state.rancher?4096:1024,65536)}
 if(action==='version')field('version','Точная версия (например v1.36.4+k3s1)',state.version);
 if(['destroy','version','remove_master','remove_worker'].includes(action))field('confirmation','Для подтверждения введите УДАЛИТЬ');
 $('modal').showModal();}
let credentialRequest = 0;
async function showPassword(service) {
  const request = ++credentialRequest;
  currentAction = null;
  $('fields').replaceChildren(); $('form-error').hidden = true;
  $('modal-title').textContent = 'Пароль · ' + (service === 'rancher' ? 'Rancher' : 'Traefik');
  $('modal-description').textContent = service === 'rancher' ? 'Первоначальный пароль Rancher. Если вы уже сменили его в Rancher, используйте новый пароль.' : 'Текущие учётные данные Traefik.';
  $('fields').append(element('p', 'Получаем пароль…'));
  $('submit').hidden = true; $('modal').showModal();
  try {
    const login = await api('credentials/' + service);
    if (request !== credentialRequest || !$('modal').open) return;
    $('fields').replaceChildren();
    $('fields').append(element('label', 'Логин'), element('pre', login.username, 'credential'), element('label', 'Пароль'), element('pre', login.password, 'credential'));
  } catch (e) {
    if (request !== credentialRequest || !$('modal').open) return;
    $('fields').replaceChildren(); $('form-error').textContent = e.message; $('form-error').hidden = false;
  }
}
$('modal').addEventListener('close', () => { credentialRequest++; $('fields').replaceChildren(); });
document.addEventListener('click', e => {
  const a = e.target.closest('[data-action]'); if (a) openAction(a.dataset.action, a.dataset.node);
  const c = e.target.closest('[data-credentials]'); if (c) showPassword(c.dataset.credentials);
});
$('action-form').addEventListener('submit',async e=>{e.preventDefault();if(!currentAction)return;const params=Object.fromEntries(new FormData(e.target));$('submit').disabled=true;try{if(currentAction==='new_cluster'){const result=await api('clusters',{name:params.name,network:params.network,params,confirmed:true});selectedCluster=result.name;sessionStorage.setItem('lab-cluster',selectedCluster);$('modal').close();setBusy(true);await loadClusters();await poll();return;}await api('action',{action:currentAction,params,confirmed:true,confirmation:params.confirmation});$('modal').close();setBusy(true);$('operations').scrollIntoView({behavior:'smooth'});await poll()}catch(e){$('form-error').textContent=e.message;$('form-error').hidden=false}finally{$('submit').disabled=false}});
for(const id of ['cancel','close'])$(id).onclick=()=>$('modal').close();
$('refresh').onclick=async()=>{await loadClusters();await refresh();await loadLinks()};
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav').forEach(n=>n.classList.remove('active'));b.classList.add('active');if(b.dataset.view==='overview')window.scrollTo({top:0,behavior:'smooth'});else $(b.dataset.view).scrollIntoView({behavior:'smooth',block:'start'})});
let polling=false;
async function poll(){if(polling)return;polling=true;try{const job=await api('job');activeJob=job;renderProgress();if(job){deployingCluster=job.state==='running' && ['create','version','add_master','add_worker'].includes(job.action)?(job.cluster||'default'):null;setBusy(job.state==='running');$('job-status').textContent='['+(job.cluster||'default')+'] '+(job.state==='running'?'Выполняется…':job.state==='success'?'Завершено':'Ошибка — проверьте журнал');const log=$('log');const bottom=log.scrollHeight-log.scrollTop-log.clientHeight<50;log.textContent=job.log.replace(/\x1b\[[0-9;]*m/g,'')||'Запускаем операцию…';if(bottom)log.scrollTop=log.scrollHeight;if(lastJob!==job.id+job.state){lastJob=job.id+job.state;if(job.state!=='running')await loadClusters();await refresh();if(job.state!=='running'){await loadLinks()}}}}catch(e){error(e.message)}finally{polling=false}}
async function loadClusters(){
  const names=await api('clusters');
  clusterCount=names.length;
  if(!names.includes(selectedCluster))selectedCluster=names[0]||'default';
  sessionStorage.setItem('lab-cluster',selectedCluster);
  $('cluster-select').replaceChildren();
  if(!names.length){const empty=element('option','Нет кластеров — создайте новый');empty.value='default';$('cluster-select').append(empty)}
  for(const name of names){const option=element('option',name==='default'?'k8s-cluster1 (основной)':name.startsWith('remote-')?'↗ '+name.slice(7):name);option.value=name;$('cluster-select').append(option)}
  $('cluster-select').value=selectedCluster;
  $('cluster-select').disabled=!names.length;
  renderKubectl();
}
$('cluster-select').onchange=async()=>{selectedCluster=$('cluster-select').value;sessionStorage.setItem('lab-cluster',selectedCluster);await refresh();await loadLinks()};
$('create-cluster').onclick=()=>{ $('new-cluster').click(); };
$('new-cluster').onclick=()=>{
  currentAction='new_cluster';$('fields').replaceChildren();$('form-error').hidden=true;
  $('modal-title').textContent='Новый кластер';$('modal-description').textContent='Выберите имя, сеть и ресурсы. Кластер сохранится и начнёт создаваться только после нажатия «Подтвердить».';
  field('name','Имя кластера — автоматически, если оставить пустым');$('field-name').required=false;$('field-name').placeholder='Первый свободный номер: k8s-cluster1, k8s-cluster2, …';field('network','Отдельная подсеть /24, например 192.168.59.0/24');
  field('masters','Количество master',1,'number',1,7);field('workers','Количество workers',2,'number',1,32);
  for(const role of ['server','workers']){
    const n=state.defaults[role];
    field(role+'_cpu',(role==='server'?'Master':'Worker')+': CPU на узел',n.cpu,'number',1,32);
    field(role+'_ram','ОЗУ на узел, МБ',n.ram,'number',state.rancher?4096:1024,65536);
    field(role+'_disk','Диск на узел, ГБ',n.disk,'number',25,2048);
  }
  componentChoice();$('submit').hidden=false;$('submit').textContent='Подтвердить';$('modal').showModal();
};
let autoRefreshing=false;
async function autoRefresh(){
  if(autoRefreshing || document.hidden || $('modal').open || refreshPromise)return;
  autoRefreshing=true;
  try{
    const previous=selectedCluster;
    await loadClusters();await refresh();
    if(previous!==selectedCluster || (state && !state.nodes.length))await loadLinks();
  }catch(e){error(e.message)}finally{autoRefreshing=false}
}
setInterval(autoRefresh,15000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)autoRefresh()});
setInterval(renderProgress,1000);
(async()=>{try{await loadClusters()}catch(e){error(e.message)}await refresh();await loadLinks();await poll();setInterval(poll,2000)})();

$('download-kubeconfig').onclick=async()=>{
  const button=$('download-kubeconfig');
  const cluster=selectedCluster;
  button.disabled=true;
  try {
    const response=await fetch('/api/kubeconfig',{headers:{'X-Lab-Token':token,'X-Lab-Cluster':cluster}});
    if(!response.ok){const result=await response.json();throw Error(result.error)}
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a');
    link.href=url;link.download=(cluster==='default'?'k8s-cluster1':cluster)+'-kubeconfig.yaml';
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    error('');
  } catch(e){error(e.message)} finally{button.disabled=false}
};

const shellSessions = new Map();
let openingShell = false;
function renderKubectl() {
  $('kubectl-cluster').textContent = selectedCluster === 'default' ? 'k8s-cluster1' : selectedCluster;
  const session = shellSessions.get(selectedCluster);
  for (const [name, item] of shellSessions) item.element.hidden = name !== selectedCluster;
  $('shell-status').textContent = session ? session.status : 'Не подключён';
  $('shell-open').disabled = openingShell || !!session;
  $('shell-close').disabled = !session;
  if (session) fitShell(session);
}
async function terminalApi(cluster, data) {
  const response = await fetch('/api/terminal', {method:'POST', headers:{'X-Lab-Token':token,'X-Lab-Cluster':cluster,'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error);
  return result;
}
function fitShell(session) {
  if (session.element.hidden) return;
  const previous = session.term.cols;
  session.fit.fit();
  if (session.term.cols !== previous) terminalApi(session.cluster, {operation:'resize',id:session.id,cols:session.term.cols,rows:session.term.rows}).catch(()=>{});
}
async function pollShell(session) {
  while (!session.closed) {
    try {
      const result = await terminalApi(session.cluster, {operation:'poll',id:session.id,offset:session.offset});
      if (session.closed) return;
      session.offset = result.offset;
      if (result.truncated) session.term.writeln('\r\n[Часть старого вывода пропущена]');
      const bytes = Uint8Array.from(atob(result.output), c=>c.charCodeAt(0));
      if (bytes.length) await new Promise(resolve=>session.term.write(bytes,resolve));
      if (result.finished) { session.status='Сессия завершена'; renderKubectl(); return; }
    } catch (e) {
      session.status=e.message; renderKubectl();
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  }
}
$('shell-open').onclick=async()=>{
  const cluster=selectedCluster;
  openingShell=true;renderKubectl();
  try {
    const result=await terminalApi(cluster,{operation:'open'});
    const element=document.createElement('div');element.className='shell-screen';$('shell-host').append(element);
    const term=new Terminal({cursorBlink:true,fontSize:14,fontFamily:'Menlo, monospace',rows:24,scrollback:3000,theme:{background:'#142e31',foreground:'#dbece7'}});
    const fit=new FitAddon.FitAddon();term.loadAddon(fit);
    term.open(element);
    const session={id:result.id,cluster,element,term,fit,offset:0,status:'Подключён',closed:false,queue:Promise.resolve()};
    shellSessions.set(cluster,session);
    term.onData(data=>{
      for (let i=0;i<data.length;i+=512) {
        const input=data.slice(i,i+512);
        session.queue=session.queue.then(()=>terminalApi(cluster,{operation:'input',id:session.id,input})).catch(e=>{session.status=e.message;renderKubectl()});
      }
    });
    term.attachCustomKeyEventHandler(e=>!(e.shiftKey && e.key==='Tab'));
    renderKubectl();term.focus();pollShell(session);
  } catch(e){error(e.message)} finally{openingShell=false;renderKubectl()}
};
$('shell-close').onclick=async()=>{
  const cluster=selectedCluster, session=shellSessions.get(cluster);
  if (!session) return;
  try {
    await terminalApi(cluster,{operation:'close',id:session.id});
    session.closed=true;session.term.dispose();session.element.remove();shellSessions.delete(cluster);renderKubectl();
  }catch(e){error(e.message)}
};
$('cluster-select').addEventListener('change',renderKubectl);
window.addEventListener('resize',()=>{for(const session of shellSessions.values())fitShell(session)});
window.addEventListener('pagehide',()=>{
  for(const session of shellSessions.values())fetch('/api/terminal',{method:'POST',keepalive:true,headers:{'X-Lab-Token':token,'X-Lab-Cluster':session.cluster,'Content-Type':'application/json'},body:JSON.stringify({operation:'close',id:session.id})});
});

function renderClusterCheck(){
 const card=$('cluster-check-card');if(!card)return;
 const job=activeJob;const own=job&&(job.cluster||'default')===selectedCluster&&job.action==='verify';
 const result=own?{state:job.state,finished:job.finished,duration:Math.floor((job.finished||Date.now()/1000)-job.started)}:state?.verification;
 const status=result?.state||'unknown';card.dataset.check=status;
 $('cluster-check-result').textContent={success:'✓ Проверка пройдена',failed:'✕ Проверка не пройдена',running:'◌ Выполняется проверка'}[status]||'Ещё не проверено';
 $('cluster-check-time').textContent=result?(status==='running'?`Прошло ${result.duration} с · дождитесь результата`:`${new Date(result.finished*1000).toLocaleString()} · ${result.duration} с · ${status==='success'?'Повторить проверку':'Повторить · подробности в журнале'}`):'Нажмите, чтобы проверить DNS, сеть и Traefik';
}

let nodeUsage=[],nodeUsageCluster=null,nodeUsageBusy=false,nodeUsageError='';
function renderNodeUsage(){
 for(const cell of document.querySelectorAll('.node-utilization')){cell.replaceChildren();const data=nodeUsageCluster===selectedCluster?nodeUsage.find(n=>n.name===cell.dataset.node):null;
 if(data?.allocation){const a=data.allocation;for(const [k,label] of [['cpu','CPU'],['memory','RAM']]){const format=v=>k==='cpu'?v.toFixed(2)+' яд.':(v/1024**3).toFixed(2)+' GiB';const percent=a.allocatable[k]?Math.round(100*a.requests[k]/a.allocatable[k]):0;cell.append(element('small',label+' requests: '+format(a.requests[k])+' / '+format(a.allocatable[k])+' ('+percent+'%)','usage-note'),element('small','Limits: '+format(a.limits[k])+(a.unlimited[k]?' + '+a.unlimited[k]+' конт. без лимита':''),'usage-note'))}}
 if(!data||data.error){cell.append(element('small',data?.error||nodeUsageError||'Получаем метрики…','usage-note'));continue;}
 for(const [key,label] of [['cpu','CPU'],['memory','RAM'],['disk','Диск']]){const m=data[key];const line=element('div',undefined,'usage-line');const stale=m.time&&Date.now()-Date.parse(m.time)>120000;const format=v=>key==='cpu'?v.toFixed(2)+' яд.':(v/1024**3).toFixed(1)+' GiB';const value=m.percent===null?'Нет данных':format(m.used)+' / '+format(m.total)+' · '+m.percent.toFixed(1)+'%';line.append(element('span',label),element('strong',value));const track=element('div',undefined,'usage-track');const fill=element('div',undefined,'usage-fill '+(m.percent>=90?'high':m.percent>=75?'medium':''));fill.style.width=Math.min(100,Math.max(0,m.percent||0))+'%';track.append(fill);cell.append(line,track);if(m.time)track.title='Измерено: '+new Date(m.time).toLocaleString()+(stale?' · устарело':'');}
 const times=[data.cpu.time,data.memory.time,data.disk.time].filter(Boolean).sort();const oldest=times[0];cell.append(element('small',oldest?((Date.now()-Date.parse(oldest)>120000?'⚠ Данные устарели · ':'')+new Date(oldest).toLocaleTimeString()):'Время измерения неизвестно','usage-note'));
 }
}
async function refreshNodeUsage(){if(nodeUsageBusy)return;nodeUsageBusy=true;const cluster=selectedCluster;try{const data=await api('node-utilization');if(cluster!==selectedCluster)return;nodeUsage=data;nodeUsageCluster=cluster;nodeUsageError='';}catch(e){if(cluster===selectedCluster){nodeUsage=[];nodeUsageCluster=cluster;nodeUsageError='Метрики недоступны';}}finally{nodeUsageBusy=false;renderNodeUsage();if(cluster!==selectedCluster)refreshNodeUsage()}}
$('cluster-select').addEventListener('change',()=>{nodeUsage=[];nodeUsageCluster=null;nodeUsageError='';renderNodeUsage();refreshNodeUsage()});$('refresh').addEventListener('click',refreshNodeUsage);setInterval(()=>{if(!document.hidden)refreshNodeUsage()},15000);refreshNodeUsage();
