"use strict";
const connectRemote=element('button','↗ Подключить кластер','button secondary');
connectRemote.id='connect-remote';connectRemote.type='button';$('new-cluster').after(connectRemote);
const disconnectRemote=element('button','Удалить подключение','button secondary');disconnectRemote.type='button';disconnectRemote.hidden=true;connectRemote.after(disconnectRemote);
const remoteNote=element('p','Удалённый кластер · Каталог приложений, шаблоны и установка ingress. Управление VM и произвольные команды отключены.','panelnote');remoteNote.hidden=true;$('error').before(remoteNote);
const verifyRemote=element('button','Проверить кластер','button secondary');verifyRemote.hidden=true;disconnectRemote.before(verifyRemote);
const installIngress=element('button','＋ Ingress-контроллер','button secondary');installIngress.hidden=true;verifyRemote.after(installIngress);
const manageIngress=element('button','Ingress-контроллеры','button secondary');manageIngress.id='manage-ingress';manageIngress.hidden=true;installIngress.after(manageIngress);
const remoteRancher=element('button','Rancher','button secondary');remoteRancher.id='remote-rancher';remoteRancher.hidden=true;manageIngress.after(remoteRancher);
const remotePanels=element('section',undefined,'remote-panels');remotePanels.id='remote-panels';remotePanels.hidden=true;
const panelHead=element('div',undefined,'sectionhead');panelHead.append(element('h2','Панели управления'));
const panelRefresh=element('button','Обновить','button secondary');panelRefresh.type='button';panelHead.append(panelRefresh);
const panelGrid=element('div',undefined,'services');remotePanels.append(panelHead,panelGrid);$('services').after(remotePanels);
let panelCluster=null,panelTime=0,panelRevision=0;panelRefresh.onclick=()=>refreshPanelBlock(true);
const remoteReports=new Map();
function renderRemoteProfile(){
 const remote=!!state?.external;$('services').hidden=true;document.body.classList.toggle('remote-profile',remote);disconnectRemote.hidden=!remote;remoteNote.hidden=!remote;verifyRemote.hidden=!state;installIngress.hidden=true;manageIngress.hidden=!state;remoteRancher.hidden=true;remotePanels.hidden=!state;if(state)refreshPanelBlock();
 $('memory').previousElementSibling.textContent=remote?'Память узлов':'Память VM';$('memory').nextElementSibling.textContent=remote?'Суммарная ёмкость узлов':'Выделено по конфигурации';
 $('version').previousElementSibling.textContent=remote?'Тип подключения':'Версия k3s';
 const head=$('node-list').closest('table').querySelectorAll('th')[3];head.textContent=remote?'Ёмкость узла':'Ресурсы VM';
 $('nodes').querySelector('.panelnote').textContent=remote?'Ресурсы получены из Kubernetes API. Доступность метрик зависит от прав подключения и настроек кластера.':'Конфигурация — выделенные VM ресурсы. Утилизация — данные kubelet. Обновление каждые 15 секунд.';
}
connectRemote.onclick=()=>{
 let content='';
 labOpen('Подключить существующий кластер','Загрузите kubeconfig со встроенными сертификатами или token. VPN и доступ к Kubernetes API должны работать на этом компьютере. Файл сохранится локально, вне Git.',async data=>{
  if(!content)throw Error('Выберите kubeconfig');
  const result=await api('connections',{operation:'connect',name:data.connection_name,context:data.connection_context,kubeconfig:content});
  selectedCluster=result.name;sessionStorage.setItem('lab-cluster',selectedCluster);$('lab-dialog').close();await loadClusters();$('cluster-select').dispatchEvent(new Event('change'));
 });
 const name=labField('connection_name','Имя подключения','','text');name.placeholder='test-cluster';name.maxLength=24;
 const file=document.createElement('input');file.type='file';file.id='remote-kubeconfig';const label=element('label','Файл kubeconfig');label.htmlFor=file.id;const upload=element('div',undefined,'remote-upload');upload.append(label,file);$('lab-fields').append(upload);
 const context=labField('connection_context','Контекст','','text',[]);context.required=true;context.disabled=true;
 const note=element('p','Подключение проверяется перед сохранением. Требуется право просмотра узлов.','lab-note');$('lab-extra').append(note);
 let revision=0;
 file.onchange=async()=>{const attempt=++revision;content='';context.replaceChildren();context.disabled=true;try{const chosen=file.files[0];if(!chosen)return;if(chosen.size>1048576)throw Error('Размер файла не должен превышать 1 МБ');const value=await chosen.text();note.textContent='Читаем контексты…';const result=await api('connections',{operation:'contexts',kubeconfig:value});if(attempt!==revision||!file.isConnected)return;for(const text of result.contexts){const option=element('option',text);option.value=text;context.append(option)}context.value=result.current||result.contexts[0];context.disabled=false;content=value;note.textContent='Контекст выбран. Нажмите «Подключить» для проверки API.';}catch(e){if(attempt===revision){note.textContent=e.message;labError(e)}}};
 $('lab-submit').textContent='Подключить';
};
disconnectRemote.onclick=()=>labOpen('Удалить подключение?','Будут удалены только локальный kubeconfig и профиль. Удалённый кластер, приложения и данные сохранятся.',async()=>{await api('connections',{operation:'disconnect',confirmed:true});selectedCluster='default';sessionStorage.setItem('lab-cluster','default');$('lab-dialog').close();await loadClusters();$('cluster-select').dispatchEvent(new Event('change'))});
if(state)renderRemoteProfile();

verifyRemote.onclick=()=>{
 const cluster=selectedCluster;
 labOpen('Проверка удалённого кластера','Проверка API, прав чтения, узлов, системных Pods и метрик. Тестовые ресурсы не создаются. Проверка не проверяет DNS и межузловую сеть изнутри Pods.',async()=>{});
 $('lab-submit').hidden=true;
 const report=element('div',undefined,'remote-check-report');$('lab-extra').append(report);
 const run=element('button','Проверить снова','button secondary');run.type='button';$('lab-extra').append(run);
 const show=result=>{report.replaceChildren();for(const check of result.checks){const row=element('div',undefined,'remote-check-row');row.append(element('span',check.state==='success'?'✓':check.state==='failed'?'✕':'!','remote-check-icon '+check.state));const text=element('div');text.append(element('strong',check.title),element('p',check.message));row.append(text);report.append(row)}report.append(element('small','Проверено: '+new Date(result.finished*1000).toLocaleString()));};
 const check=async()=>{run.disabled=true;run.textContent='Проверяем…';report.replaceChildren(element('p','Проверяем доступность API и состояние кластера…'));try{if(selectedCluster!==cluster)throw Error('Кластер изменён. Откройте проверку заново.');const result=await api('connections',{operation:'verify'});remoteReports.set(cluster,result);if(report.isConnected)show(result);}catch(e){if(report.isConnected)report.replaceChildren(element('p',e.message,'error'));}finally{run.disabled=false;run.textContent='Проверить снова';}};
 run.onclick=check;const previous=remoteReports.get(cluster);if(previous)show(previous);else check();
 $('lab-dialog').addEventListener('close',()=>{$('lab-submit').hidden=false;},{once:true});
};

installIngress.onclick=()=>{
 let plan=null;
 labOpen('Установить ingress-контроллер','Создаст отдельные namespace, IngressClass, Service и права RBAC. Существующий класс по умолчанию не изменится. Для установки нужны административные права kubeconfig.',async()=>{if(!plan)throw Error('Сначала проверьте установку');await labAction('remote_ingress_install',plan.params)});
 $('lab-dialog').dataset.requiresPreview='true';
 const controller=labField('ingress-controller','Контроллер','traefik','text',[{value:'traefik',label:'Traefik'},{value:'nginx',label:'NGINX · F5'},{value:'haproxy',label:'HAProxy'}]);
 const service=labField('ingress-service','Доступ','NodePort','text',[{value:'NodePort',label:'NodePort · порт на узлах'},{value:'LoadBalancer',label:'LoadBalancer · внешний балансировщик'}]);
 const note=element('p','NodePort назначается автоматически. LoadBalancer требует облачного балансировщика или MetalLB. Установка не добавляет DNS-записи и TLS-сертификаты.','lab-note');$('lab-extra').append(note);
 const status=element('div',undefined,'ingress-preflight');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
 const helmStep=element('p','1. Подготовка Helm'),clusterStep=element('p','2. Проверка кластера и установки'),hint=element('p','Нажмите «Подготовить и проверить». Helm будет найден или скачан автоматически.','lab-note');status.append(helmStep,clusterStep,hint);$('lab-extra').append(status);
 const result=element('pre','','remote-ingress-preview');result.hidden=true;$('lab-extra').append(result);
 const check=element('button','Подготовить и проверить','button secondary');check.type='button';$('lab-extra').append(check);$('lab-submit').textContent='Установить';$('lab-submit').disabled=true;
 let revision=0;
 const invalidate=()=>{revision++;plan=null;$('lab-dialog').dataset.requiresPreview='true';$('lab-submit').disabled=true;result.hidden=true;result.textContent='';helmStep.textContent='1. Подготовка Helm';clusterStep.textContent='2. Проверка кластера и установки';hint.textContent='Параметры изменены. Повторите проверку перед установкой.';check.textContent='Подготовить и проверить';status.dataset.state='idle'};
 controller.onchange=service.onchange=invalidate;
 check.onclick=async()=>{
 const current=++revision,cluster=selectedCluster;let stage=1;const started=Date.now();
 const active=()=>current===revision&&status.isConnected&&$('lab-dialog').open&&cluster===selectedCluster;
 plan=null;$('lab-dialog').dataset.requiresPreview='true';$('lab-submit').disabled=true;check.disabled=controller.disabled=service.disabled=true;check.textContent='Подготовка…';result.hidden=true;$('lab-error').hidden=true;status.dataset.state='running';
 helmStep.textContent='⏳ Проверяем Helm; если отсутствует — скачиваем и проверяем файл…';clusterStep.textContent='2. Проверка кластера — ожидает';
 const tick=()=>{if(active())hint.textContent='Прошло '+Math.floor((Date.now()-started)/1000)+' с. '+(stage===1?'Готовим инструмент на компьютере платформы.':'Проверяем права, занятые имена и версию chart. Загрузка зависит от сети.')};tick();const timer=setInterval(tick,1000);
 try{
 sameCluster();await api('connections',{operation:'prepare-helm'});if(!active())return;
 helmStep.textContent='✓ Helm готов';stage=2;clusterStep.textContent='⏳ Проверяем кластер и получаем Helm chart…';check.textContent='Проверка…';tick();
 const data=await api('connections',{operation:'ingress-preview',controller:controller.value,service:service.value});if(!active())return;
 plan=data;$('lab-dialog').dataset.requiresPreview='false';clusterStep.textContent='✓ Проверка пройдена';status.dataset.state='success';hint.textContent='Всё готово. Нажмите «Установить», чтобы развернуть контроллер.';
 result.textContent=[data.title+' · chart '+data.params.version,'Namespace: '+data.params.namespace,'IngressClass: '+data.params.name,'Публикация: '+data.params.service,'Реплик: 1 · класс по умолчанию не изменится'].join('\n');result.hidden=false;$('lab-submit').disabled=false;check.textContent='Проверить снова';
 }catch(e){if(active()){status.dataset.state='failed';if(stage===1)helmStep.textContent='✕ Не удалось подготовить Helm';else clusterStep.textContent='✕ Проверка не пройдена';hint.textContent=e.message;check.textContent='Повторить проверку'}}
 finally{clearInterval(timer);check.disabled=controller.disabled=service.disabled=false;}
 };

};


manageIngress.onclick=()=>{
 const cluster=selectedCluster;
 labOpen('Ingress-контроллеры','Установленные контроллеры, публикация и маршруты приложений.',null);$('lab-submit').hidden=true;
 const toolbar=element('div',undefined,'ingress-toolbar'),add=element('button','＋ Добавить контроллер','button'),refresh=element('button','Обновить','button secondary');add.type=refresh.type='button';add.onclick=()=>installIngress.onclick();toolbar.append(add,refresh);
 const list=element('div',undefined,'ingress-list');$('lab-extra').append(toolbar,list);
 const load=async()=>{refresh.disabled=true;list.replaceChildren(element('p','Загружаем контроллеры…'));try{if(cluster!==selectedCluster)throw Error('Кластер изменён');const data=await api('connections',{operation:'ingress-list'});if(!list.isConnected||cluster!==selectedCluster)return;list.replaceChildren();if(!data.controllers.length)list.append(element('p','Ingress-контроллеры не найдены. Добавьте контроллер для публикации приложений.'));for(const c of data.controllers){
 const card=element('section',undefined,'ingress-card'),header=element('div',undefined,'ingress-card-header');header.append(element('h3',c.name),element('span',c.replicas?c.ready+'/'+c.replicas+' готово':'Статус неизвестен','ingress-status'));card.append(header,element('p',c.controller,'lab-note'));
 const details=element('dl',undefined,'ingress-details');for(const [label,value] of [['Namespace',c.namespace||'—'],['Публикация',c.service||'Не определена'],['Внешний адрес',c.addresses.join(', ')||(c.service==='LoadBalancer'?'Ожидает IP':'—')],['Порты',c.ports.map(p=>p.port+(c.service==='NodePort'?' → '+p.nodePort:'')+'/'+p.protocol).join(', ')||'—'],['Маршруты Ingress',String(c.routes.length)]])details.append(element('dt',label),element('dd',value));card.append(details);
 if(c.routes.length){const routes=element('details');routes.append(element('summary','Показать маршруты'),element('p',c.routes.join(', '),'lab-note'));card.append(routes)}
 if(c.managed){const actions=element('div',undefined,'ingress-toolbar'),edit=element('button','Редактировать','button secondary'),remove=element('button','Удалить','button secondary danger');edit.type=remove.type='button';edit.onclick=()=>editIngress(c);remove.onclick=()=>deleteIngress(c);actions.append(edit,remove);if(c.kind==='traefik'){const dashboard=element('button','Веб-панель','button secondary');dashboard.type='button';dashboard.onclick=()=>traefikDashboard(c);actions.append(dashboard)}card.append(actions)}else card.append(element('p','Внешняя установка. Управляйте настройками через исходный Helm release или манифест.','lab-note'));list.append(card)}
 }catch(e){if(list.isConnected)list.replaceChildren(element('p',e.message,'error'))}finally{refresh.disabled=false}};
 refresh.onclick=load;load();
};
function editIngress(c){
 labOpen('Настройки · '+c.name,'Изменения сохраняются в Helm. LoadBalancer создаёт оплачиваемый облачный ресурс; переход на NodePort удаляет балансировщик и может изменить адреса приложений.',async data=>labAction('remote_ingress_update',{...data,controller:c.kind,uid:c.uid,...(c.kind==='traefik'?{dashboard:data.dashboard==='true'}:{})}));
 labField('service','Способ публикации',c.service,'text',[{value:'NodePort',label:'NodePort · порт на узлах'},{value:'LoadBalancer',label:'LoadBalancer · внешний IP'}]);
 if(c.kind==='traefik')labField('dashboard','Веб-панель через локальный туннель',String(c.dashboard||false),'text',[{value:'false',label:'Выключена'},{value:'true',label:'Включена · доступ через port-forward'}]);
 const count=labField('replicas','Количество реплик',c.replicas,'number');count.min=1;count.max=10;
 labField('policy','Внешний трафик',c.policy,'text',[{value:'Local',label:'Local · только узлы с контроллером'},{value:'Cluster',label:'Cluster · любой узел'}]);
 $('lab-extra').append(element('p','Local сохраняет IP клиента. Cluster допускает передачу трафика на другой узел. Текущий адрес: '+(c.addresses.join(', ')||'не назначен')+'. Версия контроллера сохраняется.','lab-note'));
 $('lab-submit').hidden=false;$('lab-submit').textContent='Сохранить настройки';
}
function deleteIngress(c){
 labOpen('Удалить '+c.name+'?','Контроллер и связанный облачный балансировщик будут удалены. Приложения, PVC и правила Ingress сохранятся, но публикация через этот контроллер перестанет работать.',async data=>{if(data.confirmation!=='УДАЛИТЬ')throw Error('Введите УДАЛИТЬ');await labAction('remote_ingress_delete',{controller:c.kind,uid:c.uid,confirmation:data.confirmation})});
 $('lab-extra').append(element('p','Маршруты: '+(c.routes.join(', ')||'стандартных Ingress не найдено')+'. Также могут использоваться нестандартные маршруты.','lab-note'));
 const confirm=labField('confirmation','Для подтверждения введите УДАЛИТЬ','');confirm.pattern='УДАЛИТЬ';
 $('lab-submit').hidden=false;$('lab-submit').textContent='Удалить контроллер';
}

function traefikDashboard(c){
 if(c.dashboard_url){labOpen('Публичная панель Traefik','HTTPS и вход по логину и паролю. По умолчанию Traefik использует самоподписанный сертификат: браузер покажет предупреждение о доверии.',null);const a=element('a','Открыть Traefik ↗','button secondary');a.href=c.dashboard_url;a.target='_blank';a.rel='noopener noreferrer';const b=element('button','Логин и пароль','button secondary');b.type='button';b.onclick=showTraefikLogin;$('lab-extra').append(a,b);return}

 labOpen('Веб-панель Traefik','Панель доступна через локальный туннель на компьютере, где выполнен kubectl. Порт панели не публикуется в LoadBalancer.',null);
 const publish=element('button','Создать публичную ссылку','button secondary');publish.type='button';publish.onclick=()=>labOpen('Опубликовать Traefik','Создаст HTTPS-ссылку sslip.io на IP балансировщика и защитит панель автоматически созданным паролем. Сертификат по умолчанию самоподписанный.',()=>labAction('remote_traefik_publish',{uid:c.uid}));$('lab-extra').append(publish);
 if(!c.dashboard){$('lab-extra').append(element('p','Веб-панель выключена. В настройках контроллера включите «Веб-панель через локальный туннель», сохраните и дождитесь завершения операции.','lab-note'));const b=element('button','Настроить контроллер','button secondary');b.type='button';b.onclick=()=>editIngress(c);$('lab-extra').append(b);return}
 const command='kubectl --kubeconfig .connections/'+selectedCluster+'/kubeconfig -n '+c.namespace+' port-forward deployment/'+c.release+' 19000:'+c.dashboard_port+' --address 127.0.0.1';
 $('lab-extra').append(element('p','В терминале из папки платформы выполните:'),element('pre',command,'remote-ingress-preview'));
 const a=element('a','Открыть панель Traefik ↗','button secondary');a.href='http://127.0.0.1:19000/dashboard/';a.target='_blank';a.rel='noopener noreferrer';$('lab-extra').append(a,element('p','Откройте ссылку на том же компьютере. Терминал должен оставаться открытым; Ctrl+C закроет туннель.','lab-note'));
}
remoteRancher.onclick=async()=>{
 const cluster=selectedCluster;labOpen('Rancher','Панель управления Kubernetes в подключённом кластере.',null);
 const box=element('div');$('lab-extra').append(box);box.textContent='Проверяем установку…';
 try{const current=await api('connections',{operation:'rancher-status'});if(!box.isConnected||selectedCluster!==cluster)return;box.replaceChildren();
 if(current.installed){box.append(element('p','Готовность: '+current.ready+'/'+current.replicas));if(current.url){const a=element('a','Открыть Rancher ↗','button secondary');a.href=current.url;a.target='_blank';a.rel='noopener noreferrer';box.append(a)}const b=element('button','Начальный пароль','button secondary');b.type='button';b.onclick=()=>showPassword('rancher');box.append(b);return}
 const add=element('button','Установить Rancher','button secondary');add.type='button';add.onclick=openRemoteRancher;box.append(element('p','Rancher не установлен.'),add);
 }catch(e){if(box.isConnected)box.textContent=e.message}
};
function openRemoteRancher(){
 let plan=null;const cluster=selectedCluster;
 labOpen('Установить Rancher','Установка из официального stable-репозитория. При необходимости будет установлен cert-manager. Используется сертификат Rancher: браузер может попросить подтвердить доверие. Запрос ресурсов — 500m CPU и 1 ГБ RAM на реплику, плюс cert-manager.',async()=>{if(!plan)throw Error('Выполните проверку');await labAction('remote_rancher_install',plan)});
 $('lab-dialog').dataset.requiresPreview='true';$('lab-submit').disabled=true;$('lab-submit').textContent='Установить';
 const publication=labField('publication','Публикация','ingress','text',[{value:'ingress',label:'HTTPS через Ingress'}]);publication.parentElement.hidden=true;
 const ingress=labField('ingress_class','Ingress-контроллер','','text',[{value:'',label:'Выберите контроллер'}]);const host=labField('host','Hostname','');
 const replicas=labField('replicas','Реплики','1','number');replicas.min=1;replicas.max=3;
 const address=publicationAddress(host,publication,ingress,$('lab-fields'),()=> 'rancher',()=> '', 'https');
 const report=element('p','','lab-note'),check=element('button','Проверить установку','button secondary');check.type='button';$('lab-extra').append(report,check);
 let revision=0;const invalidate=()=>{revision++;plan=null;$('lab-dialog').dataset.requiresPreview='true';$('lab-submit').disabled=true;report.textContent=''};$('lab-fields').addEventListener('input',invalidate);$('lab-fields').addEventListener('change',invalidate);
 api('connections',{operation:'app-options'}).then(data=>{if(!host.isConnected||cluster!==selectedCluster)return;for(const name of data.ingressClasses){const o=element('option',name);o.value=name;ingress.append(o)}if(data.ingressClasses.length===1)ingress.value=data.ingressClasses[0];address.configure(data)}).catch(labError);
 check.onclick=async()=>{const current=++revision;check.disabled=true;plan=null;report.textContent='Проверяем Rancher, cert-manager и версии Helm charts…';try{sameCluster();const data=await api('connections',{operation:'rancher-preview',host:host.value,ingress_class:ingress.value,replicas:replicas.value});if(current!==revision||!host.isConnected||cluster!==selectedCluster)return;plan=data;$('lab-dialog').dataset.requiresPreview='false';$('lab-submit').disabled=false;report.textContent='Rancher '+data.version+' · '+(data.install_cert?'установить cert-manager '+data.cert_version:'использовать существующий cert-manager')+' · https://'+data.host+'/'}catch(e){labError(e)}finally{check.disabled=false}};
}

async function openControllerCard(app,action){
 const cluster=selectedCluster;
 labOpen(app.name,'Получаем актуальные настройки Ingress-контроллера…',null);
 try{const data=await api('connections',{operation:'ingress-list'});if(selectedCluster!==cluster||!$('lab-dialog').open)return;
 const controller=data.controllers.find(c=>c.kind===app.ingress_controller&&c.namespace===app.namespace);
 if(!controller||!controller.managed)throw Error('Контроллер не найден или недоступен для управления. Обновите список.');
 if(action==='routes'){
 labOpen('Адреса и маршруты · '+controller.name,'Ingress-контроллер принимает запросы и направляет их в приложения. Пароли приложений находятся в их собственных карточках.',null);
 for(const text of ['Публикация: '+controller.service,'Внешний адрес: '+(controller.addresses.join(', ')||'Не назначен'),'Порты: '+controller.ports.map(p=>p.port+(controller.service==='NodePort'?' → '+p.nodePort:'')+'/'+p.protocol).join(', ')])$('lab-extra').append(element('p',text));
 $('lab-extra').append(element('h3','Маршруты Ingress'));if(controller.routes.length){const list=element('ul');for(const route of controller.routes)list.append(element('li',route));$('lab-extra').append(list)}else $('lab-extra').append(element('p','Маршруты пока не созданы. Выберите этот контроллер при публикации приложения.'));
 }else if(action==='dashboard')traefikDashboard(controller);else editIngress(controller);
 }catch(e){if(selectedCluster===cluster)labError(e)}
}

async function refreshPanelBlock(force=false){
 if(!state)return;const cluster=selectedCluster;if(!force&&panelCluster===cluster&&Date.now()-panelTime<30000)return;
 const changed=panelCluster!==cluster;panelCluster=cluster;panelTime=Date.now();const revision=++panelRevision;panelRefresh.disabled=true;
 if(changed)panelGrid.replaceChildren(element('p','Проверяем панели управления…'));
 const results=await Promise.allSettled([api('connections',{operation:'rancher-status'}),api('connections',{operation:'ingress-list'})]);
 if(revision!==panelRevision||cluster!==selectedCluster||!state)return;panelRefresh.disabled=false;panelGrid.replaceChildren();
 const card=(title,letter,label,text,blue=false)=>{const box=element('article',undefined,'service'),body=element('div',undefined,'service-body');body.append(element('span',label,'eyebrow'),element('h2',title),element('p',text));box.append(element('div',letter,'serviceicon'+(blue?' blue':'')),body);panelGrid.append(box);return body};
 const actions=body=>{const row=element('div',undefined,'panel-card-actions');body.append(row);return row};
 const button=(row,text,fn)=>{const b=element('button',text,'button secondary');b.type='button';b.onclick=fn;row.append(b)};
 const link=(body,text,url)=>{const a=element('a',text+' ↗','service-link');a.href=url;a.target='_blank';a.rel='noopener noreferrer';body.append(a)};
 const rancher=card('Rancher','R','УПРАВЛЕНИЕ KUBERNETES','Рабочие нагрузки, проекты и доступ к кластеру.');
 if(results[0].status==='rejected')rancher.append(element('p','Статус недоступен: '+results[0].reason.message,'panelnote'));
 else{const r=results[0].value;rancher.append(element('p',r.installed?'Готовность: '+r.ready+'/'+r.replicas:'Не установлен','panel-status'));if(r.url)link(rancher,r.url,r.url);const row=actions(rancher);if(r.installed)button(row,'Начальный пароль',()=>showPassword('rancher'));else button(row,'Установить Rancher ↗',openRemoteRancher)}
 const network=card('Ingress-контроллеры','↗','СЕТЬ И МАРШРУТИЗАЦИЯ','Публикация приложений и маршрутизация входящих запросов.',true);
 const toolbar=element('div',undefined,'network-toolbar');network.append(toolbar);button(toolbar,'＋ Добавить контроллер',()=>installIngress.onclick());
 if(results[1].status==='rejected')network.append(element('p','Статус недоступен: '+results[1].reason.message,'panelnote'));
 else{const controllers=results[1].value.controllers||[];
 if(!controllers.length)network.append(element('p','Контроллеры пока не установлены. Добавьте NGINX, Traefik или HAProxy.','panelnote'));
 for(const c of controllers){
 const kind=c.kind||(c.controller?.includes('traefik')?'traefik':c.controller?.includes('nginx')?'nginx':c.controller?.includes('haproxy')?'haproxy':'custom');
 const title={nginx:'NGINX',traefik:'Traefik',haproxy:'HAProxy'}[kind]||c.name;
 const item=element('section',undefined,'network-controller');item.dataset.controller=c.name;network.append(item);
 const head=element('div',undefined,'network-controller-heading'),identity=element('div');identity.append(element('h3',title),element('span',c.name,'panelnote'));head.append(identity,element('span',c.replicas?'Ready '+c.ready+'/'+c.replicas:'Статус неизвестен','network-state'+(c.replicas&&c.ready===c.replicas?' ready':'')));item.append(head);
 item.append(element('p',(c.service||'Способ публикации не определён')+' · '+(c.addresses.join(', ')||(c.service==='LoadBalancer'?'Ожидание внешнего IP':'Внешний IP не назначен')),'network-address'));
 if(c.ports?.length)item.append(element('p','Порты: '+c.ports.map(p=>p.port+(c.service==='NodePort'?' → '+p.nodePort:'')+'/'+p.protocol).join(', '),'panelnote'));
 const routes=element('details',undefined,'network-routes');routes.append(element('summary','Маршруты Ingress · '+c.routes.length));if(c.routes.length){const list=element('ul');for(const route of c.routes)list.append(element('li',route));routes.append(list)}else routes.append(element('p','Маршруты пока не созданы.'));item.append(routes);
 const row=element('div',undefined,'network-actions');item.append(row);
 if(c.managed){button(row,'Редактировать',()=>editIngress(c));button(row,'Удалить',()=>deleteIngress(c))}else item.append(element('p','Установка вне каталога контроллеров · настройки задаются её исходной конфигурацией.','panelnote'));
 if(c.workload)button(row,'Pods / логи',()=>openAppPods(c.workload));
 if(kind==='traefik'){
 const dashboard=element('div',undefined,'network-dashboard');item.append(dashboard);
 if(!state?.external&&!c.managed&&c.name==='traefik'&&$('traefik-link').hasAttribute('href')){link(dashboard,'Открыть веб-панель',$('traefik-link').href);button(dashboard,'Логин и пароль',()=>showPassword('traefik'))}
 else if(c.dashboard_url){link(dashboard,'Открыть веб-панель',c.dashboard_url);if(c.managed)button(dashboard,'Логин и пароль',showTraefikLogin)}
 else if(c.dashboard){link(dashboard,'Локальная веб-панель','http://127.0.0.1:19000/dashboard/');dashboard.append(element('small','Требуется локальный туннель.','panelnote'))}
 if(c.managed)button(dashboard,c.dashboard_url?'Настройки доступа':'Подключить веб-панель',()=>traefikDashboard(c));
 }
 }
 }
}

async function showTraefikLogin(){
 labOpen('Вход в Traefik','Учётные данные публичной панели.',null);const cluster=selectedCluster;
 try{const c=await api('connections',{operation:'traefik-credentials'});if(cluster!==selectedCluster||!$('lab-dialog').open)return;labField('dashboard_username','Логин',c.username).readOnly=true;const password=labField('dashboard_password','Пароль',c.password,'password');password.readOnly=true;password.style.cursor='copy';password.title='Нажмите, чтобы скопировать пароль';password.setAttribute('aria-label','Пароль. Нажмите или используйте Enter для копирования');
 const copyStatus=element('small','Нажмите на пароль, чтобы скопировать','lab-note');copyStatus.setAttribute('role','status');password.parentElement.append(copyStatus);
 let copying=false;
 const copyPassword=async()=>{if(copying)return;copying=true;try{
  if(navigator.clipboard?.writeText&&window.isSecureContext)await navigator.clipboard.writeText(password.value);
  else{const buffer=document.createElement('textarea');buffer.value=password.value;buffer.style.cssText='position:fixed;opacity:0;pointer-events:none;width:1px;height:1px';$('lab-dialog').append(buffer);try{buffer.focus();buffer.select();if(!document.execCommand('copy'))throw Error('Браузер не разрешил копирование')}finally{buffer.value='';buffer.remove();password.focus()}}
  copyStatus.textContent='✓ Скопировано';
 }catch(e){copyStatus.textContent='Не удалось скопировать пароль. Проверьте разрешение браузера.'}finally{copying=false}};
 password.addEventListener('click',copyPassword);password.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();copyPassword()}});
 const show=element('button','Показать пароль','button secondary');show.type='button';show.onclick=()=>{password.type=password.type==='password'?'text':'password';show.textContent=password.type==='password'?'Показать пароль':'Скрыть пароль'};$('lab-extra').append(show)}catch(e){labError(e)}
}
