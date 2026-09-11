'use strict';
const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('token')) { sessionStorage.setItem('lab-token', fragment.get('token')); history.replaceState(null, '', '/'); }
const token = sessionStorage.getItem('lab-token') || '';
let selectedCluster = sessionStorage.getItem('lab-cluster') || 'default';
let state = null, currentAction = null, busy = false, lastJob = null;
async function api(path, data) {
  const response = await fetch('/api/' + path, {method: data ? 'POST' : 'GET', headers: {'X-Lab-Token':token,'X-Lab-Cluster':selectedCluster,'Content-Type':'application/json'}, ...(data ? {body:JSON.stringify(data)} : {})});
  const result = await response.json(); if (!response.ok) throw Error(result.error); return result;
}
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
function element(tag, text, cls) { const e=document.createElement(tag); if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e; }
function render() {
  const ready=state.nodes.filter(n=>n.state==='Ready').length;
  $('health').textContent=state.exists===false?'Не создан':state.reachable?'На связи':'Недоступен';
  $('health-detail').textContent=state.exists===false?'ВМ удалены. Сохранена только конфигурация.':state.reachable?'Kubernetes API отвечает':'Нет подключения к API';
  $('node-count').textContent=ready+' / '+state.nodes.length;
  $('roles').textContent=state.nodes.filter(n=>n.role==='server').length+' master · '+state.nodes.filter(n=>n.role==='workers').length+' workers';
  $('memory').textContent=(state.nodes.reduce((s,n)=>s+n.ram,0)/1024).toFixed(0)+' ГБ';
  $('version').textContent=state.version; $('provider').textContent=state.provider+' · ARM64';
  $('node-list').replaceChildren();
  if(!state.nodes.length){const row=element('tr'),cell=element('td','Кластер пуст. Нажмите «Создать / применить».');cell.colSpan=5;row.append(cell);$('node-list').append(row)}
  for (const node of state.nodes) {
    const tr=element('tr'),name=element('td');name.append(element('span',node.name,'node-name'),element('span',node.role==='server'?'CONTROL PLANE':'WORKER','role'));tr.append(name);
    const status=element('td');status.append(element('span',(node.state==='Absent'?'Не создан':node.state)+(node.vm_state==='poweroff'?' / VM выключена':''),'badge '+node.state));tr.append(status,element('td',node.ip),element('td',node.cpu+' CPU / '+node.ram/1024+' ГБ / '+node.disk+' ГБ диск'));
    const actions=element('td'),wrap=element('div',undefined,'nodebuttons');
    const edit=element('button','Настроить','textbutton');edit.dataset.action='resources';edit.dataset.node=node.name;wrap.append(edit);
    const protectedNode=node.role==='server'?state.nodes.find(n=>n.role==='server')===node:state.nodes.filter(n=>n.role==='workers').length<=1;
    if(!protectedNode){const remove=element('button','Удалить','textbutton remove');remove.dataset.action=node.role==='server'?'remove_master':'remove_worker';remove.dataset.node=node.name;wrap.append(remove)}
    actions.append(wrap);tr.append(actions);$('node-list').append(tr);
  }
  setBusy(busy);
}
function setBusy(value){busy=value;$('cluster-select').disabled=value;$('new-cluster').disabled=value;document.querySelectorAll('[data-action]').forEach(b=>b.disabled=value || (!!state && !state.nodes.length && !['create'].includes(b.dataset.action)))}
async function refresh(){try{$('refresh').disabled=true;state=await api('status');render();error(state.error||'')}catch(e){error(e.message)}finally{$('refresh').disabled=false}}
async function loadLinks(){if(state && !state.nodes.length){for(const name of ['rancher','traefik']){const a=$(name+'-link');a.removeAttribute('href');a.textContent='Появится после создания кластера'}return;}try{const links=await api('links');for(const name of ['rancher','traefik']){const a=$(name+'-link');if(state && !state[name]){a.textContent='Отключён в конфигурации';a.removeAttribute('href');continue}const url=new URL(links[name]);if(url.protocol!=='https:')throw Error('Некорректная ссылка');a.href=url.href;a.textContent=url.hostname+' ↗'}}catch(e){for(const name of ['rancher','traefik'])$(name+'-link').textContent='Адрес недоступен';error(e.message)}}
const definitions={create:['Создать / применить','Задайте состав кластера. Для существующих VM меняйте состав через добавление и удаление отдельных узлов.'],add_master:['Добавить master','Для устойчивости etcd нужны 3 master. Первый master остаётся адресом API.'],add_worker:['Добавить worker','Новая виртуальная машина присоединится к текущему кластеру.'],remove_master:['Удалить master','Будут выполнены snapshot etcd, drain и исключение узла из etcd. Данные VM будут удалены.'],remove_worker:['Удалить worker','Будут выполнены drain и удаление VM. Данные диска и emptyDir будут потеряны; локальные PV не переносятся автоматически.'],resources:['Ресурсы узла','Существующая VM будет перезагружена. Изменение master временно прервёт доступ к API.'],version:['Изменить версию k3s','Это пересоздание лаборатории: все VM и их данные будут удалены. Это не обновление с сохранением данных.'],destroy:['Удалить кластер','Все виртуальные машины этого проекта и данные их дисков будут удалены. Кэш загрузок сохранится.'],verify:['Проверить кластер','Проверим DNS, межузловую сеть и HTTP через Traefik. Тестовые ресурсы будут удалены после проверки.']};
function field(name,label,value='',type='text',min,max){const l=element('label',label);l.htmlFor='field-'+name;const input=element('input');input.id=l.htmlFor;input.name=name;input.type=type;input.value=value;input.required=true;if(min!==undefined)input.min=min;if(max!==undefined)input.max=max;$('fields').append(l,input)}
function openAction(action,nodeName){if(!state)return;currentAction=action;$('fields').replaceChildren();$('form-error').hidden=true;$('submit').hidden=false;$('submit').textContent='Подтвердить';$('modal-title').textContent=definitions[action][0];$('modal-description').textContent='Кластер: '+selectedCluster+'. '+definitions[action][1];
 if(nodeName){const input=element('input');input.type='hidden';input.name='node';input.value=nodeName;$('fields').append(input);$('modal-description').textContent='Кластер: '+selectedCluster+'. '+nodeName+'. '+definitions[action][1]}
 if(action==='create'){field('masters','Количество master',(state.nodes.filter(n=>n.role==='server').length||1),'number',1,7);field('workers','Количество workers',(state.nodes.filter(n=>n.role==='workers').length||2),'number',1,32);for(const role of ['server','workers']){const n=state.nodes.find(n=>n.role===role)||state.defaults[role];field(role+'_cpu',(role==='server'?'Master':'Worker')+': CPU на узел',n.cpu,'number',1,32);field(role+'_ram','ОЗУ на узел, МБ',n.ram,'number',state.rancher?4096:1024,65536);field(role+'_disk','Диск на узел, ГБ (от 64)',n.disk,'number',64,2048)}const label=element('label','Сеть кластера');label.htmlFor='network-mode';const select=element('select');select.name='network_mode';select.id='network-mode';for(const [value,text] of [['existing','Существующая: '+state.network],['new','Новая подсеть']]){const o=element('option',text);o.value=value;select.append(o)}$('fields').append(label,select);field('network','Подсеть с префиксом',state.network);const input=$('field-network');input.disabled=true;select.onchange=()=>{input.disabled=select.value==='existing'};$('fields').append(element('p','IP назначаются автоматически: обычно master с .11, workers с .21. Адрес .1 зарезервирован для Mac. Новая сеть и размеры дисков применяются при создании VM.'))}
 if(action.startsWith('add_')){const n=state.nodes.find(n=>n.role===(action==='add_master'?'server':'workers'));field('name','Имя узла');field('cpu','CPU — количество ядер',n.cpu,'number',1,32);field('ram','ОЗУ, МБ',n.ram,'number',state.rancher?4096:1024,65536);field('disk','Диск, ГБ',n.disk,'number',64,2048);field('ip','IPv4 — оставить пустым для автоматического назначения');$('field-ip').required=false;$('field-ip').placeholder='Автоматически из '+state.network;$('fields').append(element('p','Используется сеть текущего кластера: '+state.network+'. Новую сеть можно выбрать при создании кластера.'))}
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
$('action-form').addEventListener('submit',async e=>{e.preventDefault();if(!currentAction)return;const params=Object.fromEntries(new FormData(e.target));$('submit').disabled=true;try{if(currentAction==='new_cluster'){const result=await api('clusters',params);selectedCluster=result.name;sessionStorage.setItem('lab-cluster',selectedCluster);$('modal').close();await loadClusters();await refresh();await loadLinks();openAction('create');return;}await api('action',{action:currentAction,params,confirmed:true,confirmation:params.confirmation});$('modal').close();setBusy(true);$('operations').scrollIntoView({behavior:'smooth'});await poll()}catch(e){$('form-error').textContent=e.message;$('form-error').hidden=false}finally{$('submit').disabled=false}});
for(const id of ['cancel','close'])$(id).onclick=()=>$('modal').close();
$('refresh').onclick=async()=>{await refresh();await loadLinks()};
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav').forEach(n=>n.classList.remove('active'));b.classList.add('active');if(b.dataset.view==='overview')window.scrollTo({top:0,behavior:'smooth'});else $(b.dataset.view).scrollIntoView({behavior:'smooth',block:'start'})});
let polling=false;
async function poll(){if(polling)return;polling=true;try{const job=await api('job');if(job){setBusy(job.state==='running');$('job-status').textContent='['+(job.cluster||'default')+'] '+(job.state==='running'?'Выполняется…':job.state==='success'?'Завершено':'Ошибка — проверьте журнал');const log=$('log');const bottom=log.scrollHeight-log.scrollTop-log.clientHeight<50;log.textContent=job.log.replace(/\x1b\[[0-9;]*m/g,'')||'Запускаем операцию…';if(bottom)log.scrollTop=log.scrollHeight;if(lastJob!==job.id+job.state){lastJob=job.id+job.state;if(job.state!=='running'){await refresh();await loadLinks()}}}}catch(e){error(e.message)}finally{polling=false}}
async function loadClusters(){
  const names=await api('clusters');
  if(!names.includes(selectedCluster))selectedCluster='default';
  $('cluster-select').replaceChildren();
  for(const name of names){const option=element('option',name);option.value=name;$('cluster-select').append(option)}
  $('cluster-select').value=selectedCluster;
}
$('cluster-select').onchange=async()=>{selectedCluster=$('cluster-select').value;sessionStorage.setItem('lab-cluster',selectedCluster);await refresh();await loadLinks()};
$('new-cluster').onclick=()=>{
  currentAction='new_cluster';$('fields').replaceChildren();$('form-error').hidden=true;
  $('modal-title').textContent='Новый кластер';$('modal-description').textContent='Создайте отдельный профиль. Затем выберите число узлов и ресурсы для развёртывания. Текущий кластер сохранится.';
  field('name','Имя кластера, например lab2');field('network','Отдельная подсеть /24, например 192.168.59.0/24');
  $('submit').hidden=false;$('submit').textContent='Далее';$('modal').showModal();
};
(async()=>{try{await loadClusters()}catch(e){error(e.message)}await refresh();await loadLinks();await poll();setInterval(poll,2000)})();
