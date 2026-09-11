'use strict';
let labSubmit=null,labCluster=null,appsLoading=false,labDraft=[],savedTemplates=[];
const catalogDefaults={nginx:{image:'nginx:1.30.4-alpine',port:80,memory:128},postgres:{image:'postgres:17-alpine',port:5432,memory:256},redis:{image:'redis:7.4-alpine',port:6379,memory:128},kafka:{image:'apache/kafka:4.0.0',port:9092,memory:1024},rabbitmq:{image:'rabbitmq:4.1-management',port:5672,memory:512},custom:{image:'',port:8080,memory:128}};
function labField(name,label,value='',type='text',options=null){
 const wrap=element('div');const l=element('label',label);l.htmlFor='lab-'+name;const input=document.createElement(options?'select':'input');input.id='lab-'+name;input.name=name;
 if(options){for(const option of options){const o=element('option',typeof option==='string'?option:option.label);o.value=typeof option==='string'?option:option.value;input.append(o)}}else{input.type=type;input.required=true;if(type==='number')input.min='0';}
 input.value=value;wrap.append(l,input);$('lab-fields').append(wrap);return input;
}
function labOpen(title,description,submit){labCluster=selectedCluster;labSubmit=submit;$('lab-title').textContent=title;$('lab-description').textContent=description;$('lab-fields').replaceChildren();$('lab-extra').replaceChildren();$('lab-error').hidden=true;$('lab-submit').hidden=!submit;$('lab-submit').disabled=false;$('lab-dialog').showModal();}
function labError(e){$('lab-error').textContent=e.message||String(e);$('lab-error').hidden=false;}
function sameCluster(){if(labCluster!==selectedCluster)throw Error('Кластер изменился. Закройте окно и повторите действие для нужного кластера.');}
async function labAction(action,params){sameCluster();await api('action',{action,params,confirmed:true});$('lab-dialog').close();await poll();}
$('lab-close').onclick=$('lab-cancel').onclick=()=>$('lab-dialog').close();
$('lab-dialog').addEventListener('close',()=>{labSubmit=null;$('lab-fields').replaceChildren();$('lab-extra').replaceChildren()});
$('lab-form').onsubmit=async e=>{e.preventDefault();if(!labSubmit)return;$('lab-submit').disabled=true;try{sameCluster();await labSubmit(Object.fromEntries(new FormData(e.target)))}catch(e){labError(e)}finally{$('lab-submit').disabled=false}};
function currentBundle(data){const c={...data};delete c.templateName;return [...labDraft.filter(x=>x.namespace!==c.namespace||x.name!==c.name),c];}
function openCatalog(){
 labDraft=[];labOpen('Каталог приложений','Кластер: '+selectedCluster+'. Базы создаются с PVC. HTTP-адрес можно оставить пустым. После развёртывания запускаются проверки.',data=>labAction('app_deploy',{apps:currentBundle(data)}));
 const type=labField('type','Приложение','nginx','text',['nginx','postgres','redis','kafka','rabbitmq','custom']);
 labField('name','Имя приложения','web');labField('namespace','Namespace','dev');labField('image','Образ с версией',catalogDefaults.nginx.image);labField('port','Порт контейнера',80,'number');labField('replicas','Реплики',1,'number');labField('cpu','Запрос CPU, millicores (1000 = 1 ядро)',100,'number');labField('memory','Запрос RAM, MiB',128,'number');labField('storage','Постоянный диск, GiB',2,'number');const host=labField('host','URL: префикс (web) или полный hostname','web');host.required=false;
 type.onchange=()=>{const t=type.value,d=catalogDefaults[t];$('lab-image').value=d.image;$('lab-port').value=d.port;$('lab-memory').value=d.memory;$('lab-name').value=t==='custom'?'api':t;const db=['postgres','redis','kafka','rabbitmq'].includes(t);$('lab-replicas').value=1;$('lab-replicas').max=db?'1':'10';$('lab-host').value=db&&t!=='rabbitmq'?'':t;$('lab-cpu').value=['kafka','rabbitmq'].includes(t)?500:100;};
 const note=element('p','Лимиты CPU/RAM = 2 × запрос. PostgreSQL, Redis, Kafka и RabbitMQ — по одной реплике; увеличение числа реплик само по себе не создаёт репликацию базы.','lab-note');$('lab-extra').append(note);
 const draft=element('p','В наборе пока одно приложение.');$('lab-extra').append(draft);
 const add=element('button','＋ Добавить текущее в набор','button secondary');add.type='button';add.onclick=()=>{if(!$('lab-form').reportValidity())return;labDraft=currentBundle(Object.fromEntries(new FormData($('lab-form'))));draft.textContent='Набор: '+labDraft.map(a=>a.namespace+'/'+a.name).join(', ')+'. Измените имя и тип для следующего приложения.';};$('lab-extra').append(add);
 const template=labField('templateName','Имя шаблона для сохранения (необязательно)','');template.required=false;
 const save=element('button','Сохранить набор как шаблон','button secondary');save.type='button';save.onclick=async()=>{try{sameCluster();if(!$('lab-form').reportValidity())return;const data=Object.fromEntries(new FormData($('lab-form')));await api('templates',{name:data.templateName,apps:currentBundle(data)});draft.textContent='Шаблон сохранён. Можно развернуть его на любом кластере.';await loadTemplates()}catch(e){labError(e)}};$('lab-extra').append(save);
}
$('catalog-open').onclick=openCatalog;
async function loadTemplates(){try{savedTemplates=await api('templates');const old=$('template-list').value;$('template-list').replaceChildren();if(!savedTemplates.length){const o=element('option','Нет шаблонов — сохраните набор из каталога');o.value='';$('template-list').append(o)}for(const t of savedTemplates){const o=element('option',t.name+' · '+t.apps.length+' приложений');o.value=t.name;$('template-list').append(o)}if(savedTemplates.some(t=>t.name===old))$('template-list').value=old;}catch(e){$('apps-message').textContent=e.message}}
$('template-run').onclick=()=>{const t=savedTemplates.find(t=>t.name===$('template-list').value);if(!t)return;labOpen('Развернуть «'+t.name+'»','Кластер: '+selectedCluster+'. '+t.apps.map(a=>a.name+' ('+a.type+')').join(', ')+'. К префиксам URL добавится namespace и адрес кластера; полные hostname сохранятся.',data=>labAction('template_deploy',{template:t.name,namespace:data.namespace}));labField('namespace','Namespace для всех приложений','dev');};
function openUpdate(app){labOpen('Версия и реплики · '+app.name,'Кластер '+selectedCluster+', namespace '+app.namespace+'. Обновление образа выполняется постепенно. PVC сохраняются. Смена major PostgreSQL здесь недоступна.',data=>labAction('app_update',{...data,kind:app.kind,name:app.name,namespace:app.namespace}));const input=labField('container','Контейнер',app.containers[0].name,'text',app.containers.map(c=>c.name));labField('image','Новый образ с тегом',app.containers[0].image);labField('replicas','Число реплик (0 — остановить приложение)',app.replicas,'number');input.onchange=()=>{$('lab-image').value=app.containers.find(c=>c.name===input.value).image};}
function appConfirm(app,action){labOpen(action==='app_rollback'?'Откатить '+app.name:'Проверить '+app.name,action==='app_rollback'?'Возврат к предыдущей ревизии шаблона Pod. Реплики и данные на диске не откатываются.':'Проверим готовность, DNS и Service. Для приложений каталога — также PostgreSQL SELECT 1 или Redis PING; при наличии HTTP Ingress проверим URL.',()=>labAction(action,{kind:app.kind,name:app.name,namespace:app.namespace}));}
async function refreshApps(){
 if(appsLoading)return;appsLoading=true;const cluster=selectedCluster;
 const sum=state?state.nodes.reduce((a,n)=>({cpu:a.cpu+n.cpu,ram:a.ram+n.ram,disk:a.disk+n.disk}),{cpu:0,ram:0,disk:0}):null;
 if(sum)$('stand-budget').textContent=`Конфигурация VM: ${sum.cpu} CPU · ${Math.round(sum.ram/1024*10)/10} GiB RAM · ${sum.disk} GiB дисков`;
 try{const apps=await api('apps');if(cluster!==selectedCluster)return;$('apps-list').replaceChildren();$('apps-message').textContent=apps.length?'Приложения выбранного кластера. Системные namespace скрыты.':'Приложений пока нет. Откройте каталог.';
 for(const app of apps){const card=element('article',undefined,'app-card');card.append(element('h3',app.name),element('p',`${app.namespace} · ${app.kind} · Ready ${app.ready}/${app.replicas}`),element('code',app.containers.map(c=>c.image).join('\n')));const controls=element('div',undefined,'app-controls');for(const [label,fn] of [['Pods / логи',()=>openAppPods(app)],['Версия / реплики',()=>openUpdate(app)],['Откат',()=>appConfirm(app,'app_rollback')],['Проверить',()=>appConfirm(app,'app_check')]]){const b=element('button',label,'button secondary');b.disabled=busy;b.onclick=fn;controls.append(b)}card.append(controls);$('apps-list').append(card)}}catch(e){if(cluster===selectedCluster){$('apps-list').replaceChildren();$('apps-message').textContent='Приложения недоступны: '+e.message}}finally{appsLoading=false;if(cluster!==selectedCluster)refreshApps()}}
$('apps-refresh').onclick=()=>{refreshApps();loadTemplates()};
function standAction(action){
 const nodes=state.nodes.filter(n=>n.vm_state!=='not_created');
 labOpen(action==='stand_stop'?'Выключить выбранные VM':'Включить выбранные VM','Выберите VM. Диски сохраняются. Выключение master может сделать API недоступным; выключение worker прервёт его приложения.',()=>{const selected=[...$('lab-extra').querySelectorAll('input:checked')].map(x=>x.value);if(!selected.length)throw Error('Выберите хотя бы одну VM');return labAction(action,{nodes:selected})});
 const budget=element('p','','lab-note');
 const update=()=>{const selected=[...$('lab-extra').querySelectorAll('input:checked')].map(x=>x.value);const chosen=nodes.filter(n=>selected.includes(n.vagrant_id));budget.textContent=`Выбрано: ${chosen.length} VM · ${chosen.reduce((s,n)=>s+n.cpu,0)} CPU · ${(chosen.reduce((s,n)=>s+n.ram,0)/1024).toFixed(1)} GiB RAM · ${chosen.reduce((s,n)=>s+n.disk,0)} GiB дисков`;};
 for(const n of nodes){const label=element('label',undefined,'vm-choice');const input=document.createElement('input');input.type='checkbox';input.value=n.vagrant_id;input.onchange=update;label.append(input,document.createTextNode(`${n.name||n.vagrant_id} · ${n.vm_state||'unknown'} · ${n.cpu} CPU / ${n.ram} MiB`));$('lab-extra').append(label)}
 $('lab-extra').append(budget);update();
}
$('stand-stop').onclick=()=>standAction('stand_stop');$('stand-start').onclick=()=>standAction('stand_start');
let diagnosticRequest=0;
async function showPodDiagnostics(pod){
 labOpen('Диагностика · '+pod.name,'Кластер '+selectedCluster+' · '+pod.namespace,null);
 const selector=labField('container','Контейнер','','text',[]);const previous=labField('previous','Логи','false','text',[{value:'false',label:'Текущий запуск'},{value:'true',label:'Предыдущий запуск'}]);
 const statusBox=element('pre','Получаем состояние…','diagnostic-output');const logs=element('pre','','diagnostic-output');$('lab-extra').append(statusBox,element('h3','Логи'),logs);
 const load=async()=>{const request=++diagnosticRequest;try{sameCluster();const result=await api('pod',{namespace:pod.namespace,name:pod.name,container:selector.value||undefined,previous:previous.value==='true'});if(request!==diagnosticRequest||!$('lab-dialog').open||labCluster!==selectedCluster)return;selector.replaceChildren();for(const c of result.containers){const o=element('option',c);o.value=c;selector.append(o)}selector.value=result.container;statusBox.textContent=`${result.phase} · узел ${result.node||'не назначен'}\n\n`+result.statuses.map(c=>`${c.name}: Ready=${c.ready}, рестарты=${c.restarts}\n${JSON.stringify(c.state,null,2)}\nПредыдущее состояние: ${JSON.stringify(c.lastState)}`).join('\n')+'\n\nУсловия\n'+result.conditions.map(c=>`${c.type}: ${c.status} ${c.reason} ${c.message}`).join('\n')+'\n\nСобытия\n'+result.events.map(e=>`${e.time||''} ${e.reason} (×${e.count}): ${e.message}`).join('\n');logs.textContent=result.logs||'Логов пока нет.'}catch(e){labError(e)}};
 selector.onchange=previous.onchange=load;
 const refresh=element('button','Обновить диагностику','button secondary');refresh.type='button';refresh.onclick=load;$('lab-extra').append(refresh);
 const exec=element('button','Терминал контейнера','button primary');exec.type='button';exec.onclick=async()=>{try{sameCluster();const container=selector.value;if(!container)throw Error('Выберите контейнер');const cluster=selectedCluster;$('lab-dialog').close();if(!shellSessions.has(cluster))await $('shell-open').onclick();const session=shellSessions.get(cluster);if(!session)throw Error('Терминал не открылся');const quote=s=>"'"+s.replace(/'/g,"'\\''")+"'";await session.queue;await terminalApi(cluster,{operation:'input',id:session.id,input:'\x03'});await terminalApi(cluster,{operation:'input',id:session.id,input:`kubectl exec -it -n ${quote(pod.namespace)} ${quote(pod.name)} -c ${quote(container)} -- sh\r`});session.term.focus();session.element.scrollIntoView({behavior:'smooth',block:'center'});}catch(e){error(e.message)}};$('lab-extra').append(exec);load();
}
$('lab-dialog').addEventListener('close',()=>{diagnosticRequest++});
window.addEventListener('lab-pod',event=>showPodDiagnostics(event.detail));
$('cluster-select').addEventListener('change',()=>{refreshApps();loadTemplates()});
setInterval(()=>{if(!document.hidden&&!$('lab-dialog').open){refreshApps();loadTemplates()}},15000);refreshApps();loadTemplates();

function showCreationBudget(){
 if(!['new_cluster','create'].includes(currentAction))return;
 const fields=$('fields');let note=document.getElementById('creation-budget');if(!note){note=element('p','','lab-note');note.id='creation-budget';fields.append(note)}
 const val=name=>Number(fields.querySelector(`[name="${name}"]`)?.value||0);
 const masters=val('masters'),workers=val('workers');
 note.textContent=`Всего: ${masters+workers} VM · ${masters*val('server_cpu')+workers*val('workers_cpu')} CPU · ${((masters*val('server_ram')+workers*val('workers_ram'))/1024).toFixed(1)} GiB RAM · ${masters*val('server_disk')+workers*val('workers_disk')} GiB дисков (логическая ёмкость).`;
}
$('action-form').addEventListener('input',showCreationBudget);
$('new-cluster').addEventListener('click',showCreationBudget);

async function openAppPods(app){
 labOpen('Pods · '+app.name,'Выберите Pod для логов, событий и терминала.',null);
 try{const pods=await api('pods',{name:app.name,namespace:app.namespace,kind:app.kind});if(!$('lab-dialog').open||labCluster!==selectedCluster)return;if(!pods.length)$('lab-extra').append(element('p','Подов нет. Проверьте число реплик.'));for(const pod of pods){const b=element('button',pod.name+' · '+pod.phase,'button secondary');b.type='button';b.onclick=()=>showPodDiagnostics(pod);$('lab-extra').append(b)}}catch(e){labError(e)}
}

setInterval(()=>{for(const id of ['stand-stop','stand-start'])$(id).disabled=busy||!state?.nodes.length;$('template-run').disabled=busy||!savedTemplates.length;if(labSubmit)$('lab-submit').disabled=busy;},1000);
