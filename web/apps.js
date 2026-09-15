'use strict';
const selectedApps=new Map();let selectionCluster=null;
let labSubmit=null,labCluster=null,appsLoading=false,labDraft=[],savedTemplates=[];
const catalogDefaults={nginx:{image:'nginx:1.30.4-alpine',port:80,memory:128},postgres:{image:'postgres:18.6-alpine',port:5432,memory:256},redis:{image:'redis:8.10.1-alpine',port:6379,memory:128},kafka:{image:'apache/kafka:4.3.1',port:9092,memory:1024},rabbitmq:{image:'rabbitmq:4.3.5-management',port:5672,memory:512},custom:{image:'',port:8080,memory:128}};
function labField(name,label,value='',type='text',options=null,parent=$('lab-fields')){
 const wrap=element('div');const l=element('label',label);l.htmlFor='lab-'+name;const input=document.createElement(options?'select':'input');input.id='lab-'+name;input.name=name;
 if(options){for(const option of options){const o=element('option',typeof option==='string'?option:option.label);o.value=typeof option==='string'?option:option.value;input.append(o)}}else{input.type=type;input.required=true;if(type==='number')input.min='0';}
 input.value=value;wrap.append(l,input);parent.append(wrap);return input;
}
function labOpen(title,description,submit){labCluster=selectedCluster;labSubmit=submit;$('lab-title').textContent=title;$('lab-description').textContent=description;$('lab-fields').replaceChildren();$('lab-extra').replaceChildren();$('lab-error').hidden=true;$('lab-submit').textContent='Подтвердить';$('lab-submit').hidden=!submit;$('lab-submit').disabled=false;$('lab-dialog').showModal();}
function labError(e){$('lab-error').textContent=e.message||String(e);$('lab-error').hidden=false;}
function sameCluster(){if(labCluster!==selectedCluster)throw Error('Кластер изменился. Закройте окно и повторите действие для нужного кластера.');}
async function labAction(action,params){sameCluster();await api('action',{action,params,confirmed:true});$('lab-dialog').close();await poll();}
$('lab-close').onclick=$('lab-cancel').onclick=()=>$('lab-dialog').close();
$('lab-dialog').addEventListener('close',()=>{labSubmit=null;$('lab-fields').replaceChildren();$('lab-extra').replaceChildren()});
$('lab-form').onsubmit=async e=>{e.preventDefault();if(!labSubmit)return;$('lab-submit').disabled=true;try{sameCluster();await labSubmit(Object.fromEntries(new FormData(e.target)))}catch(e){labError(e)}finally{$('lab-submit').disabled=false}};
function currentBundle(data){const c={...data};delete c.templateName;return [...labDraft.filter(x=>x.namespace!==c.namespace||x.name!==c.name),c];}
async function newAppName(type,namespace,reserved=[]){
 const base=type==='nginx'?'web':type==='custom'?'app':type;
 const result=await api('templates',{operation:'suggest-name',base,namespace,reserved});return result.name;
}
function openCatalog(templateOnly=false){
 labDraft=[];labOpen(templateOnly?'Создать шаблон':'Каталог приложений',templateOnly?'Соберите набор приложений и сохраните его. Развёртывание выполняется отдельно из списка шаблонов.':'Кластер: '+selectedCluster+'. Базы создаются с PVC; веб-панели устанавливаются автоматически.',async data=>{if(templateOnly){await api('templates',{name:data.templateName,apps:currentBundle(data)});$('lab-dialog').close();await loadTemplates();$('apps-message').textContent='Шаблон «'+data.templateName+'» сохранён.';}else await labAction('app_deploy',{apps:currentBundle(data)})});
 $('lab-submit').textContent=templateOnly?'Сохранить шаблон':'Развернуть приложения';
 const type=labField('type','Приложение','nginx','text',['nginx','postgres','redis','kafka','rabbitmq','custom']);
 labField('name','Имя приложения','web');labField('namespace','Namespace','dev');labField('image','Образ с версией',catalogDefaults.nginx.image);labField('port','Порт контейнера',80,'number');labField('replicas','Реплики',1,'number');labField('cpu','Запрос CPU, millicores (1000 = 1 ядро)',100,'number');labField('memory','Запрос RAM, MiB',128,'number');labField('storage','Постоянный диск, GiB',2,'number');const host=labField('host','URL: префикс (web) или полный hostname','web');host.required=false;
 addStorageFields(type);
 const nameInput=$('lab-name'),namespaceInput=$('lab-namespace');let nameRevision=0,manualName=false;
 const suggestName=async()=>{const revision=++nameRevision,cluster=selectedCluster,ns=namespaceInput.value,t=type.value;manualName=false;try{const name=await newAppName(t,ns,labDraft.filter(a=>a.namespace===ns).map(a=>a.name));if(revision!==nameRevision||!nameInput.isConnected||cluster!==selectedCluster||manualName)return;nameInput.value=name;const host=$('lab-host');if(['nginx','rabbitmq','custom'].includes(t))host.value=name;}catch(e){if(revision===nameRevision&&nameInput.isConnected)labError(e)}};
 nameInput.addEventListener('input',()=>{manualName=true;nameRevision++});namespaceInput.addEventListener('change',()=>{if(!manualName)suggestName()});
 type.addEventListener('change',()=>suggestName());suggestName();
 type.onchange=()=>{const t=type.value,d=catalogDefaults[t];$('lab-image').value=d.image;$('lab-port').value=d.port;$('lab-memory').value=d.memory;$('lab-name').value=t==='custom'?'api':t;const db=['postgres','redis','kafka','rabbitmq'].includes(t);$('lab-replicas').value=1;$('lab-replicas').max=db?'1':'10';$('lab-host').value=db&&t!=='rabbitmq'?'':t;$('lab-cpu').value=['kafka','rabbitmq'].includes(t)?500:100;$('lab-storage_mode').value=db?'new':'none';$('lab-storage_mode').dispatchEvent(new Event('change'));};
 const note=element('p','Лимиты CPU/RAM = 2 × запрос. PostgreSQL, Redis, Kafka и RabbitMQ — по одной реплике; увеличение числа реплик само по себе не создаёт репликацию базы.','lab-note');$('lab-extra').append(note);
 const draft=element('p','В наборе пока одно приложение.');$('lab-extra').append(draft);
 const add=element('button','＋ Добавить текущее в набор','button secondary');add.type='button';add.onclick=()=>{if(!$('lab-form').reportValidity())return;labDraft=currentBundle(Object.fromEntries(new FormData($('lab-form'))));draft.textContent='Набор: '+labDraft.map(a=>a.namespace+'/'+a.name).join(', ')+'. Измените имя и тип для следующего приложения.';};$('lab-extra').append(add);
 const template=labField('templateName',templateOnly?'Имя шаблона':'Имя шаблона для сохранения (необязательно)','');template.required=templateOnly;
 const save=element('button','Сохранить набор как шаблон','button secondary');save.type='button';save.onclick=async()=>{try{sameCluster();if(!$('lab-form').reportValidity())return;const data=Object.fromEntries(new FormData($('lab-form')));await api('templates',{name:data.templateName,apps:currentBundle(data)});$('lab-dialog').close();await loadTemplates();$('apps-message').textContent='Шаблон «'+data.templateName+'» сохранён.'}catch(e){labError(e)}};if(!templateOnly)$('lab-extra').append(save);
}
$('catalog-open').onclick=()=>openCatalog(false);
$('template-catalog').onclick=()=>openCatalog(true);
function templateCaption(t){const n=t.apps.length;return t.name+' · '+n+' '+(n%10===1&&n%100!==11?'приложение':n%10>=2&&n%10<=4&&(n%100<12||n%100>14)?'приложения':'приложений')}
function openTemplateMap(t){
 labOpen(t.name,'Состав шаблона. Линии показывают принадлежность к набору, а не сетевые связи приложений.',null);
 const map=element('div',undefined,'template-map');const hub=element('div',undefined,'template-map-hub');hub.append(element('span','▱','template-map-symbol'),element('strong',t.name),element('small',templateCaption(t).split(' · ').slice(1).join(' · ')));map.append(hub);
 const nodes=element('div',undefined,'template-map-nodes');
 const icons={postgres:'PG',redis:'R',kafka:'K',rabbitmq:'MQ',nginx:'N',custom:'APP'};
 for(const a of t.apps){const node=element('article',undefined,'template-map-node');const head=element('div',undefined,'template-map-node-head');head.append(element('span',icons[a.type]||'APP','template-map-symbol'),element('strong',a.name));node.append(head,element('code',a.image));const info=element('div',undefined,'template-map-spec');for(const text of [a.type,a.replicas+' репл.',a.cpu+'m CPU',a.memory+' MiB RAM'])info.append(element('span',text));node.append(info);if(a.storage_mode&&a.storage_mode!=='none')node.append(element('p',a.storage_mode==='existing'?'PVC: '+a.pvc+' · существующий':'Диск: '+a.storage+' GiB · новый PVC'));if(a.host)node.append(element('p','URL: '+a.host));if(['postgres','redis','kafka'].includes(a.type))node.append(element('p','+ '+({postgres:'pgAdmin',redis:'Redis Insight',kafka:'AKHQ'}[a.type])+' · веб-панель'));nodes.append(node)}
 map.append(nodes);$('lab-extra').append(map);const actions=element('div',undefined,'template-map-actions');const run=element('button','Развернуть →','button primary');run.type='button';run.disabled=busy;run.dataset.templateRun='true';run.onclick=()=>runTemplate(t);const del=element('button','Удалить шаблон','button secondary');del.type='button';del.onclick=()=>deleteTemplate(t.name);const edit=element('button','Редактировать','button secondary');edit.type='button';edit.onclick=()=>openTemplateEditor(t);actions.append(edit,del,run);$('lab-extra').append(actions);
}

function openTemplateEditor(template){
 const expected=JSON.parse(JSON.stringify(template));let items=JSON.parse(JSON.stringify(template.apps)),active=0;
 labOpen('Редактировать шаблон','Изменения сохраняются только в шаблоне. Развёртывание запускается отдельно.',async data=>{
  capture();await api('templates',{operation:'update',original_name:expected.name,expected,name:data.templateName,apps:items});
  $('lab-dialog').close();await loadTemplates();$('apps-message').textContent='Шаблон «'+data.templateName+'» обновлён.';
 });
 $('lab-submit').textContent='Сохранить изменения';labField('templateName','Имя шаблона',template.name);
 const layout=element('div',undefined,'template-editor'),side=element('div',undefined,'template-editor-list'),panel=element('div',undefined,'template-editor-panel');layout.append(side,panel);$('lab-extra').append(layout);
 const capture=()=>{if(!panel.childElementCount)return;const values={...items[active]};for(const input of panel.querySelectorAll('input,select'))values[input.name]=input.value;items[active]=values;};
 const valid=()=>[...panel.querySelectorAll('input,select')].every(input=>input.reportValidity());
 const drawList=()=>{side.replaceChildren();side.append(element('small','ПРИЛОЖЕНИЯ · '+items.length+'/10','template-editor-caption'));items.forEach((a,i)=>{const b=element('button',undefined,'template-editor-item'+(i===active?' active':''));b.type='button';b.setAttribute('aria-pressed',String(i===active));b.append(element('strong',a.name),element('small',a.type+' · '+a.namespace));b.onclick=()=>{if(!valid())return;capture();active=i;draw();};side.append(b)});
  const add=element('button','＋ Добавить приложение','button secondary');add.type='button';add.disabled=items.length>=10;
  add.onclick=()=>{if(!valid())return;capture();add.hidden=true;const picker=element('div',undefined,'template-app-picker');picker.append(element('strong','Выберите приложение'));
   const labels={nginx:'Nginx',postgres:'PostgreSQL',redis:'Redis',kafka:'Apache Kafka',rabbitmq:'RabbitMQ',custom:'Свой образ'};
   for(const [type,label] of Object.entries(labels)){const b=element('button',label,'button secondary');b.type='button';b.onclick=async()=>{const d=catalogDefaults[type],ns=items[active]?.namespace||'dev',cluster=selectedCluster;for(const button of picker.querySelectorAll('button'))button.disabled=true;try{const name=await newAppName(type,ns,items.map(a=>a.name));if(!picker.isConnected||cluster!==selectedCluster)return;items.push({type,name,namespace:ns,image:d.image,port:d.port,replicas:1,cpu:100,memory:d.memory,storage:2,storage_mode:['postgres','redis','kafka','rabbitmq'].includes(type)?'new':'none',pvc:'',storage_secret:'',mount_path:'/data',host:'',shovel:false});active=items.length-1;draw()}catch(e){if(picker.isConnected)labError(e)}finally{for(const button of picker.querySelectorAll('button'))button.disabled=false}};picker.append(b)}
   const cancel=element('button','Отмена','button secondary');cancel.type='button';cancel.onclick=()=>{picker.remove();add.hidden=false};picker.append(cancel);side.append(picker);
  };side.append(add);
 };
 const draw=()=>{panel.replaceChildren();const a=items[active];const head=element('div',undefined,'template-editor-heading');head.append(element('strong',a.name));const remove=element('button','Удалить из шаблона','button secondary');remove.type='button';remove.disabled=items.length===1;remove.onclick=()=>{items.splice(active,1);active=Math.min(active,items.length-1);draw()};head.append(remove);panel.append(head);
  const fields=element('div',undefined,'template-editor-fields');panel.append(fields);
  const field=(name,label,value,type='text',options=null)=>labField(name,label,value??'',type,options,fields);
  const type=field('type','Приложение',a.type,'text',Object.keys(catalogDefaults));const nameInput=field('name','Имя приложения',a.name);nameInput.addEventListener('input',()=>{items[active].name=nameInput.value;head.querySelector('strong').textContent=nameInput.value;drawList()});field('namespace','Namespace',a.namespace);field('image','Образ с версией',a.image);field('port','Порт контейнера',a.port,'number');field('replicas','Реплики',a.replicas,'number');field('cpu','CPU, millicores',a.cpu,'number');field('memory','RAM, MiB',a.memory,'number');field('storage','Диск, GiB',a.storage,'number');
  const mode=field('storage_mode','Хранилище',a.storage_mode||'none','text',[{value:'none',label:'Без PVC'},{value:'new',label:'Новый PVC'},{value:'existing',label:'Существующий PVC'}]);
  const pvc=field('pvc','Существующий PVC',a.pvc,'text',[{value:a.pvc||'',label:a.pvc||'Выберите PVC'}]);const secret=field('storage_secret','Secret с прежним паролем',a.storage_secret,'text',[{value:a.storage_secret||'',label:a.storage_secret||'Выберите Secret'}]);const mount=field('mount_path','Путь монтирования',a.mount_path||'/data');const host=field('host','URL: префикс или hostname',a.host);host.required=false;
  if(a.type==='rabbitmq')field('shovel','Shovel',String(a.shovel===true||a.shovel==='true'),'text',[{value:'false',label:'Выключен'},{value:'true',label:'Включён'}]);
  const storageState=()=>{const existing=mode.value==='existing',needsSecret=existing&&['postgres','rabbitmq'].includes(type.value);pvc.required=existing;pvc.parentElement.hidden=!existing;secret.required=needsSecret;secret.parentElement.hidden=!needsSecret;mount.required=mode.value!=='none';mount.parentElement.hidden=mode.value==='none';};mode.onchange=storageState;storageState();
  type.onchange=()=>{capture();const d=catalogDefaults[type.value],db=['postgres','redis','kafka','rabbitmq'].includes(type.value);Object.assign(items[active],{image:d.image,port:d.port,memory:d.memory,replicas:1,storage_mode:db?'new':'none',pvc:'',storage_secret:'',shovel:false});draw()};
  const storageResult=element('div','Проверяем хранилище…','storage-validation');storageResult.setAttribute('role','status');panel.append(storageResult);
  let storageTimer,storageRevision=0;
  const checkStorage=()=>{clearTimeout(storageTimer);const revision=++storageRevision;storageResult.className='storage-validation';storageResult.textContent='Проверяем хранилище на выбранном кластере…';storageTimer=setTimeout(async()=>{if(!storageResult.isConnected||labCluster!==selectedCluster)return;const app={...items[active]};for(const input of fields.querySelectorAll('input,select'))app[input.name]=input.value;
   if(app.storage_mode==='existing'&&(!app.pvc||(['postgres','rabbitmq'].includes(app.type)&&!app.storage_secret))){storageResult.textContent='Выберите свободный PVC и Secret с прежним паролем базы, если он требуется.';storageResult.className='storage-validation';return}
   try{const response=await api('templates',{operation:'check-storage',app});if(revision!==storageRevision||!storageResult.isConnected||labCluster!==selectedCluster)return;storageResult.textContent='✓ '+response.message;storageResult.className='storage-validation success'}catch(e){if(revision!==storageRevision||!storageResult.isConnected||labCluster!==selectedCluster)return;storageResult.textContent='⚠ '+e.message;storageResult.className='storage-validation failed'}
  },650)};
  let storageChoices=[],choiceRevision=0;
  const nsInput=fields.querySelector('[name="namespace"]');
  const loadChoices=async()=>{const revision=++choiceRevision,ns=nsInput.value,cluster=selectedCluster;if(mode.value!=='existing')return;
   pvc.disabled=true;secret.disabled=true;storageResult.textContent='Получаем PVC выбранного namespace…';
   try{const data=await api('templates',{operation:'editor-storage',namespace:ns});if(revision!==choiceRevision||!pvc.isConnected||ns!==nsInput.value||cluster!==selectedCluster)return;
    const previous=pvc.value,previousSecret=secret.value;storageChoices=data.pvcs;pvc.replaceChildren();pvc.append(new Option(data.pvcs.length?'Выберите PVC':'В этом namespace нет PVC',''));
    for(const item of data.pvcs){const option=new Option(item.name+' · '+item.capacity+(item.available?' · свободен':' · '+item.reason),item.name);option.disabled=!item.available;pvc.append(option)}
    if(data.pvcs.some(p=>p.name===previous&&p.available))pvc.value=previous;
    secret.replaceChildren();secret.append(new Option('Выберите Secret с ключом password',''));for(const name of data.secrets)secret.append(new Option(name,name));if(data.secrets.includes(previousSecret))secret.value=previousSecret;
    if(!data.pvcs.some(p=>p.available)){storageRevision++;clearTimeout(storageTimer);storageResult.textContent='⚠ Свободных готовых PVC в namespace '+ns+' нет. Создайте новый PVC или освободите существующий.';storageResult.className='storage-validation failed'}else checkStorage();
   }catch(e){if(revision===choiceRevision&&pvc.isConnected){pvc.replaceChildren(new Option('Не удалось загрузить PVC',''));secret.replaceChildren(new Option('Не удалось загрузить Secrets',''));storageRevision++;clearTimeout(storageTimer);storageResult.textContent='⚠ '+e.message;storageResult.className='storage-validation failed'}}finally{if(revision===choiceRevision){pvc.disabled=false;secret.disabled=false}}
  };
  pvc.addEventListener('change',()=>{const match=storageChoices.find(p=>p.name===pvc.value);secret.value=match?.secret||'';checkStorage()});
  mode.addEventListener('change',loadChoices);nsInput.addEventListener('input',()=>{choiceRevision++;storageChoices=[];pvc.replaceChildren(new Option('Выберите PVC',''));secret.replaceChildren(new Option('Выберите Secret',''))});nsInput.addEventListener('change',loadChoices);
  fields.addEventListener('input',checkStorage);fields.addEventListener('change',checkStorage);if(mode.value==='existing')loadChoices();else checkStorage();
  panel.append(element('p','Лимиты CPU/RAM = 2 × запрос. PVC и Secret должны находиться в namespace приложения. Для баз доступна одна реплика.','lab-note'));drawList();
 };draw();
}

function renderTemplateList(){const area=$('template-picker');area.replaceChildren();for(const t of savedTemplates){const b=element('button',undefined,'template-compact-item');b.type='button';b.append(element('span','▱','template-mini-icon'),element('strong',t.name),element('span',String(t.apps.length),'template-mini-count'),element('span','↗'));b.setAttribute('aria-label',templateCaption(t)+': показать карту');b.onclick=()=>openTemplateMap(t);area.append(b)}}
async function loadTemplates(){try{const values=await api('templates');savedTemplates=values;$('template-picker').hidden=!savedTemplates.length;$('template-hint').textContent=savedTemplates.length?'Нажмите шаблон, чтобы посмотреть состав.':'Сохраните набор приложений в каталоге.';renderTemplateList()}catch(e){$('apps-message').textContent=e.message}}
function runTemplate(t){
 let rows=[],checked='',generation=0,loaded=false,checkTimer,checkRevision=0;
 const payload=()=>({template:t.name,namespace:ns.value,storage:Object.fromEntries(rows.map(r=>[r.original,{name:r.name.value,storage_mode:r.mode.value,pvc:r.claim.value,storage_secret:r.secret.value,storage:r.size.value}]))});
 labOpen('Развернуть «'+t.name+'»','По умолчанию создаётся новый набор с новыми PVC и паролями. Существующие данные сохраняются. Для восстановления выберите свободный PVC и прежний Secret.',async()=>{
  if(!loaded||checked!==JSON.stringify(payload()))throw Error('Проверьте выбранные настройки перед развёртыванием.');
  await labAction('template_deploy',payload());
 });
 $('lab-submit').textContent='Развернуть';
 const ns=labField('namespace','Namespace для набора','dev');
 const cards=element('div',undefined,'template-storage-cards'),result=element('div','Получаем свободные имена и PVC…','lab-note');
 const check=element('button','Проверить перед развёртыванием','button secondary');check.type='button';check.disabled=true;
 $('lab-extra').append(cards,check,result);
 const invalidate=()=>{checked='';checkRevision++;clearTimeout(checkTimer);result.textContent='Проверка настроек…';result.className='storage-validation';if(loaded)checkTimer=setTimeout(()=>{if(cards.isConnected&&labCluster===selectedCluster)check.onclick()},650);};
 const load=async()=>{
  const request=++generation;loaded=false;checked='';check.disabled=true;cards.replaceChildren();rows=[];result.className='lab-note';result.textContent='Проверяем свободные имена и хранилища…';
  try{sameCluster();const data=await api('templates',{operation:'storage-options',template:t.name,namespace:ns.value});
   if(request!==generation||!cards.isConnected||labCluster!==selectedCluster)return;
   for(const [i,a] of t.apps.entries()){
    const card=element('article',undefined,'template-storage-card');card.append(element('strong',a.name+' · '+a.type));const fields=element('div',undefined,'template-editor-fields');card.append(fields);cards.append(card);
    const field=(key,label,value,type='text',options=null)=>labField('tpl-'+i+'-'+key,label,value,type,options,fields);
    const name=field('name','Имя нового приложения',data.names[a.name]);
    const storage=a.storage_mode!=='none';const mode=field('mode','Данные',storage?'new':'none','text',storage?[{value:'new',label:'Новый PVC · пустые данные'},{value:'existing',label:'Подключить существующий PVC'}]:[{value:'none',label:'Без PVC'},{value:'new',label:'Новый PVC'},{value:'existing',label:'Существующий PVC'}]);
    const size=field('size','Размер нового PVC, GiB',a.storage,'number');
    const claim=field('pvc','Свободный PVC','','text',[{value:'',label:'Выберите PVC'},...data.pvcs.filter(p=>p.available).map(p=>({value:p.name,label:p.name+' · '+p.capacity}))]);
    const secret=field('secret','Secret с прежним паролем базы','','text',[{value:'',label:'Выберите Secret'},...data.secrets.map(name=>({value:name,label:name}))]);
    const update=()=>{const existing=mode.value==='existing',credentials=existing&&['postgres','rabbitmq'].includes(a.type);claim.parentElement.hidden=!existing;claim.required=existing;secret.parentElement.hidden=!credentials;secret.required=credentials;size.parentElement.hidden=mode.value!=='new';size.required=mode.value==='new';invalidate();};
    mode.onchange=update;update();fields.addEventListener('input',invalidate);fields.addEventListener('change',invalidate);
    card.append(element('p','Выбор PVC не проверяет формат данных или соответствие пароля базе. Используйте диск этого же приложения и совместимую версию.','lab-note'));
    rows.push({original:a.name,name,mode,size,claim,secret});
   }
   loaded=true;check.disabled=false;invalidate();
  }catch(e){if(request===generation&&cards.isConnected){result.textContent=e.message;result.className='lab-note check-failed';}}
 };
 ns.addEventListener('input',()=>{generation++;loaded=false;check.disabled=true;invalidate()});ns.addEventListener('change',load);
 check.onclick=async()=>{const revision=++checkRevision;clearTimeout(checkTimer);try{sameCluster();if(!loaded)return;const inputs=[...$('lab-form').querySelectorAll('input,select')];if(inputs.some(i=>!i.checkValidity())){checked='';result.textContent='Выберите PVC и Secret, если они требуются, и заполните обязательные поля.';result.className='storage-validation failed';return}const data=payload(),signature=JSON.stringify(data);check.disabled=true;result.textContent='Проверяем PVC, Secrets, имена, URL и CPU/RAM…';const preview=await api('templates',{...data,operation:'check'});if(revision!==checkRevision||!cards.isConnected||signature!==JSON.stringify(payload())||labCluster!==selectedCluster)return;checked=signature;result.replaceChildren(element('strong','✓ Проверка пройдена'));for(const a of preview.apps)result.append(element('p',a.namespace+'/'+a.name+' · '+(a.mode==='new'?'новый PVC: '+a.pvc:a.mode==='existing'?'существующий PVC: '+a.pvc:'без PVC')+(a.secret?' · Secret: '+a.secret:'')));result.className='storage-validation success';}catch(e){if(revision!==checkRevision||!cards.isConnected||labCluster!==selectedCluster)return;checked='';result.textContent='⚠ '+e.message;result.className='storage-validation failed';}finally{if(revision===checkRevision)check.disabled=!loaded}};
 load();
}

function openUpdate(app){labOpen('Версия и реплики · '+app.name,'Кластер '+selectedCluster+', namespace '+app.namespace+'. Обновление образа выполняется постепенно. PVC сохраняются. Смена major PostgreSQL здесь недоступна.',data=>labAction('app_update',{...data,kind:app.kind,name:app.name,namespace:app.namespace}));const input=labField('container','Контейнер',app.containers[0].name,'text',app.containers.map(c=>c.name));labField('image','Новый образ с тегом',app.containers[0].image);labField('replicas','Число реплик (0 — остановить приложение)',app.replicas,'number');input.onchange=()=>{$('lab-image').value=app.containers.find(c=>c.name===input.value).image};}
function appConfirm(app,action){labOpen(action==='app_rollback'?'Откатить '+app.name:'Проверить '+app.name,action==='app_rollback'?'Возврат к предыдущей ревизии шаблона Pod. Реплики и данные на диске не откатываются.':'Проверим готовность, DNS и Service. Для приложений каталога — также PostgreSQL SELECT 1 или Redis PING; при наличии HTTP Ingress проверим URL.',()=>labAction(action,{kind:app.kind,name:app.name,namespace:app.namespace}));}
async function refreshApps(){
 if(appsLoading)return;appsLoading=true;const cluster=selectedCluster;
 const sum=state?state.nodes.reduce((a,n)=>({cpu:a.cpu+n.cpu,ram:a.ram+n.ram,disk:a.disk+n.disk}),{cpu:0,ram:0,disk:0}):null;
 if(sum)$('stand-budget').textContent=`Конфигурация VM: ${sum.cpu} CPU · ${Math.round(sum.ram/1024*10)/10} GiB RAM · ${sum.disk} GiB дисков`;
 try{const apps=await api('apps');if(cluster!==selectedCluster)return;if(selectionCluster!==cluster){selectedApps.clear();selectionCluster=cluster}const keys=new Set(apps.map(appKey));for(const key of selectedApps.keys())if(!keys.has(key))selectedApps.delete(key);$('apps-list').replaceChildren();$('apps-message').textContent=apps.length?'Приложения выбранного кластера. Системные namespace скрыты.':'Приложений пока нет. Откройте каталог.';
 for(const app of apps){const card=element('article',undefined,'app-card');const pick=element('label',undefined,'app-pick');const cb=document.createElement('input');cb.type='checkbox';cb.checked=selectedApps.has(appKey(app));cb.disabled=busy;cb.onchange=()=>{if(cb.checked)selectedApps.set(appKey(app),app);else selectedApps.delete(appKey(app));card.classList.toggle('app-picked',cb.checked);updateBulk()};pick.append(cb,element('span','Выбрать '+app.name));card.classList.toggle('app-picked',cb.checked);card.append(pick);card.append(element('h3',app.name),element('p',`${app.namespace} · ${app.kind} · Ready ${app.ready}/${app.replicas}`),element('code',app.containers.map(c=>c.image).join('\n')));for(const u of app.urls||[]){const link=element('a',u.title+' ↗','route-url');link.href=u.url;link.target='_blank';link.rel='noopener noreferrer';card.append(link)}const controls=element('div',undefined,'app-controls');for(const [label,fn] of [['Плагины',()=>rabbitPlugins(app)],['Ссылки и пароли',()=>showAppAccess(app)],['Pods / логи',()=>openAppPods(app)],['Версия / реплики',()=>openUpdate(app)],['Откат',()=>appConfirm(app,'app_rollback')],['Проверить',()=>appConfirm(app,'app_check')],['Запустить',()=>bulkLifecycle('app_start',[app])],['Остановить',()=>bulkLifecycle('app_stop',[app])],['Перезапустить',()=>bulkLifecycle('app_restart',[app])],['Удалить',()=>deleteApp(app)]]){if(label==='Плагины'&&app.type!=='rabbitmq')continue;if(label==='Откат'&&['postgres','redis','kafka','rabbitmq'].includes(app.type))continue;const b=element('button',label,'button secondary');b.disabled=busy;b.onclick=fn;if(label==='Проверить'){const result=app.check?.state;const captions={success:'✓ Проверка пройдена',failed:'✕ Проверка не пройдена',running:'◌ Проверяется…'};b.textContent=captions[result]||'Проверить';b.classList.add('check-'+(result||'unknown'));b.title=app.check?'Последняя проверка: '+new Date(app.check.time*1000).toLocaleString():'Ещё не проверено'}if(label==='Удалить')b.classList.add('danger');controls.append(b)}card.append(controls);$('apps-list').append(card)}updateBulk()}catch(e){if(cluster===selectedCluster){$('apps-list').replaceChildren();$('apps-message').textContent='Приложения недоступны: '+e.message}}finally{appsLoading=false;if(cluster!==selectedCluster)refreshApps()}}
$('apps-refresh').onclick=()=>{refreshApps();loadTemplates()};
function standAction(action){
 const nodes=state.nodes.filter(n=>n.vm_state!=='not_created');
 labOpen(action==='stand_stop'?'Выключить выбранные VM':'Включить выбранные VM','Выберите VM. Диски сохраняются. Выключение master может сделать API недоступным; выключение worker прервёт его приложения.',()=>{const selected=[...$('lab-extra').querySelectorAll('input:checked')].map(x=>x.value);if(!selected.length)throw Error('Выберите хотя бы одну VM');return labAction(action,{nodes:selected})});
 const budget=element('p','','lab-note');
 const update=()=>{const selected=[...$('lab-extra').querySelectorAll('input:checked')].map(x=>x.value);const chosen=nodes.filter(n=>selected.includes(n.vagrant_id));budget.textContent=`Выбрано: ${chosen.length} VM · ${chosen.reduce((s,n)=>s+n.cpu,0)} CPU · ${(chosen.reduce((s,n)=>s+n.ram,0)/1024).toFixed(1)} GiB RAM · ${chosen.reduce((s,n)=>s+n.disk,0)} GiB дисков`;};
 for(const n of nodes){const label=element('label',undefined,'vm-choice');const input=document.createElement('input');input.type='checkbox';input.value=n.vagrant_id;input.onchange=update;label.append(input,document.createTextNode(`${n.name||n.vagrant_id} · ${n.vm_state||'unknown'} · ${n.cpu} CPU / ${n.ram} MiB`));$('lab-extra').append(label)}
 $('lab-extra').append(budget);update();
}
$('rancher-install').onclick=()=>labOpen('Установить Rancher','Установка в выбранный кластер с cert-manager. Требуется работающий API и минимум 4 ГБ RAM на master. VM сохраняются.',()=>labAction('rancher_install',{}));
setInterval(()=>{$('rancher-install-row').hidden=!state||!!state.rancher;document.querySelector('[data-credentials="rancher"]').hidden=!state?.rancher;$('rancher-install').disabled=busy||!state?.nodes?.length},1000);
$('stand-stop').onclick=()=>standAction('stand_stop');$('stand-start').onclick=()=>standAction('stand_start');
let diagnosticRequest=0;
async function openPodTerminal(pod,container){
 if($('lab-dialog').open)await new Promise(resolve=>{ $('lab-dialog').addEventListener('close',resolve,{once:true});$('lab-dialog').close()});
 await openPodDebug(pod,{mode:'shell',container,autoConnect:true});
}
async function showPodDiagnostics(pod){
 labOpen('Диагностика Pod',pod.namespace+' / '+pod.name,null);
 const dialog=$('lab-dialog');dialog.classList.add('diagnostics-dialog');$('lab-cancel').textContent='Закрыть';
 const expand=resourceButton('⛶ Развернуть',()=>{const full=dialog.classList.toggle('diagnostics-expanded');expand.textContent=full?'↙ Свернуть':'⛶ Развернуть';expand.setAttribute('aria-pressed',String(full))},'button secondary diagnostic-expand');expand.setAttribute('aria-pressed','false');$('lab-close').before(expand);
 dialog.addEventListener('close',()=>{dialog.classList.remove('diagnostics-dialog','diagnostics-expanded');expand.remove()},{once:true});
 const selector=labField('container','Контейнер','','text',[]);const previous=labField('previous','Логи','false','text',[{value:'false',label:'Текущий запуск'},{value:'true',label:'Предыдущий запуск'}]);
 const actions=element('div',undefined,'diagnostic-actions'),tabs=element('div',undefined,'diagnostic-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Диагностика Pod');
 const body=element('div',undefined,'diagnostic-panel');body.id='pod-diagnostic-panel';body.setAttribute('role','tabpanel');body.tabIndex=0;
 let data=null,tab='state',query='';const message=element('span','Получаем состояние…','diagnostic-summary');
 const render=()=>{
  for(const button of tabs.children){const active=button.dataset.tab===tab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;if(active)body.setAttribute('aria-labelledby',button.id)}
  previous.parentElement.hidden=tab!=='logs';body.replaceChildren();if(!data){body.append(element('p','Получаем состояние…','lab-note'));return}
  if(tab==='state'){
   const summary=element('div',undefined,'diagnostic-overview');summary.append(element('strong',data.phase||'Unknown'),element('span','Узел: '+(data.node||'Не назначен')));body.append(summary);
   const conditions=element('div',undefined,'diagnostic-conditions');for(const c of data.conditions||[]){const card=element('div',undefined,'diagnostic-condition '+(c.status==='True'?'good':'warn'));card.append(element('strong',c.type),element('span',c.status==='True'?'✓ Да':c.status==='False'?'Нет':'Неизвестно'));if(c.reason||c.message)card.append(element('small',[c.reason,c.message].filter(Boolean).join(' · ')));conditions.append(card)}body.append(conditions);
   for(const c of data.statuses||[]){const card=element('article',undefined,'diagnostic-container-card');card.append(element('strong',c.name),element('span',(c.ready?'Ready':'Не готов')+' · рестарты: '+c.restarts));const reason=c.state?.waiting?.reason||c.state?.terminated?.reason;if(reason)card.append(element('p',reason,'error'));const detail=document.createElement('details');detail.append(element('summary','Техническое состояние'),element('pre',JSON.stringify({state:c.state,previous:c.lastState},null,2),'diagnostic-json'));card.append(detail);body.append(card)}
  }else if(tab==='events'){
   if(!(data.events||[]).length)body.append(element('p','Событий пока нет.','lab-note'));
   for(const event of data.events||[]){const warning=event.type==='Warning'||/Unhealthy|Failed|BackOff|Evict/i.test(event.reason||'');const card=element('article',undefined,'diagnostic-event '+(warning?'warning':''));const heading=element('div');heading.append(element('strong',event.reason||'Событие'),element('small','×'+(event.count||1)+' · '+(event.time||'Время не указано')));card.append(heading,element('p',event.message||''));body.append(card)}
  }else{
   const input=document.createElement('input');input.type='search';input.placeholder='Фильтр строк логов…';input.setAttribute('aria-label','Фильтр логов диагностики');input.value=query;
   const output=element('pre','','diagnostic-log');const update=()=>{query=input.value;output.textContent=debugLogLines(data.logs||'',query).join('\n')||(query?'Совпадений нет.':'Логов пока нет.')};input.oninput=update;update();body.append(input,output);
  }
 };
 for(const [key,label] of [['state','Состояние'],['events','События'],['logs','Логи']]){const button=resourceButton(label,()=>{tab=key;render()},'diagnostic-tab');button.dataset.tab=key;button.id='diagnostic-tab-'+key;button.setAttribute('role','tab');button.setAttribute('aria-controls',body.id);button.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const list=[...tabs.children],index=list.indexOf(button),next=e.key==='Home'?0:e.key==='End'?list.length-1:(index+(e.key==='ArrowRight'?1:list.length-1))%list.length;list[next].click();list[next].focus()};tabs.append(button)}
 const load=async()=>{const request=++diagnosticRequest;message.textContent='Обновление…';refresh.disabled=true;try{sameCluster();const result=await api('pod',{namespace:pod.namespace,name:pod.name,container:selector.value||undefined,previous:previous.value==='true'});if(request!==diagnosticRequest||!body.isConnected||labCluster!==selectedCluster)return;data=result;selector.replaceChildren();for(const c of result.containers||[]){const option=element('option',c);option.value=c;selector.append(option)}selector.value=result.container;terminal.disabled=!selector.value;message.textContent=(result.phase||'Unknown')+' · '+(result.node||'Узел не назначен');render()}catch(e){if(request===diagnosticRequest&&body.isConnected){message.textContent='Не удалось обновить';labError(e)}}finally{if(body.isConnected)refresh.disabled=false}};
 const refresh=resourceButton('↻ Обновить',load,'button secondary');
 const terminal=resourceButton('>_ Терминал',()=>openPodTerminal(pod,selector.value).catch(labError),'button primary');terminal.disabled=true;
 const live=resourceButton('Онлайн-логи',async()=>{await new Promise(resolve=>{dialog.addEventListener('close',resolve,{once:true});dialog.close()});await openPodDebug(pod)},'button secondary');
 actions.append(terminal,live,refresh,message);$('lab-extra').append(actions,tabs,body);selector.onchange=previous.onchange=load;render();load();
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

setInterval(()=>{for(const id of ['stand-stop','stand-start'])$(id).disabled=busy||!state?.nodes.length;document.querySelectorAll('[data-template-run]').forEach(b=>b.disabled=busy);if(labSubmit)$('lab-submit').disabled=busy;},1000);

async function showAppAccess(app){
 labOpen('Доступ · '+app.name,'Ссылки и учётные данные выбранного приложения.',null);
 try{const data=await api('app-access',app);sameCluster();if(!$('lab-dialog').open)return;
 const field=(label,value,secret=false)=>{const row=element('div',undefined,'access-row');row.append(element('label',label));const input=document.createElement('input');input.type=secret?'password':'text';input.readOnly=true;input.value=value;row.append(input);if(secret){const show=element('button','Показать','button secondary');show.type='button';show.onclick=()=>{input.type=input.type==='password'?'text':'password';show.textContent=input.type==='password'?'Показать':'Скрыть'};row.append(show)}const copy=element('button','Копировать','button secondary');copy.type='button';copy.onclick=()=>navigator.clipboard.writeText(value).catch(labError);row.append(copy);$('lab-extra').append(row)};
 for(const panel of data.panels){const link=element('a',panel.title+' ↗','route-url');link.href=panel.url;link.target='_blank';link.rel='noopener noreferrer';$('lab-extra').append(link);field('URL',panel.url);if(panel.username)field('Логин панели',panel.username);if(panel.password)field('Пароль панели',panel.password,true)}
 field('Адрес внутри Kubernetes',data.connection);if(data.username)field('Пользователь приложения',data.username);if(data.password)field('Пароль приложения',data.password,true);if(data.note)$('lab-extra').append(element('p',data.note));
 }catch(e){labError(e)}
}

function deleteApp(app){
 labOpen('Удалить '+app.name,'Кластер '+selectedCluster+' · '+app.namespace+(app.managed?'. Будут удалены приложение, сервисы, Ingress и его веб-панель. Namespace и другие приложения сохранятся.':'. Будет удалён workload и его Pod. Внешние Service/Ingress сохранятся, поскольку их принадлежность приложению не подтверждена.'),async data=>{sameCluster();await api('action',{action:'app_delete',confirmed:true,confirmation:data.confirmation,params:{kind:app.kind,name:app.name,namespace:app.namespace,delete_data:data.delete_data==='true'}});$('lab-dialog').close();await poll();await refreshApps()});
 $('lab-extra').append(element('p','Ранее существовавший PVC, подключённый к приложению, сохраняется при любом выборе.','lab-note'));
 labField('delete_data','Данные приложения','false','text',[{value:'false',label:'Сохранить PVC и пароль базы'},{value:'true',label:'Удалить также PVC и пароль базы без восстановления'}]);labField('confirmation','Введите УДАЛИТЬ','');
}

let pvcData=[];
const pvcNamespaces=new Map();
function renderPVCList(){
 const namespaces=[...new Set(pvcData.map(p=>p.namespace))].sort();const select=$('pvc-namespace');let chosen=pvcNamespaces.get(selectedCluster)||'';if(!namespaces.includes(chosen))chosen='';pvcNamespaces.set(selectedCluster,chosen);select.replaceChildren();
 for(const ns of ['',...namespaces]){const option=element('option',(ns||'Все (All)')+' · '+pvcData.filter(p=>!ns||p.namespace===ns).length);option.value=ns;select.append(option)}select.value=chosen;
 const data=pvcData.filter(p=>!chosen||p.namespace===chosen);const box=$('pvc-list');box.replaceChildren();for(const p of data)box.append(renderPVC(p));if(!data.length)box.append(element('p','В кластере пока нет PVC.'));
}
$('pvc-namespace').onchange=()=>{pvcNamespaces.set(selectedCluster,$('pvc-namespace').value);renderPVCList()};
async function refreshPVCs(){const cluster=selectedCluster;try{const data=await api('pvcs');if(cluster!==selectedCluster)return;pvcData=data;renderPVCList();}catch(e){if(cluster===selectedCluster)$('pvc-list').textContent='PVC недоступны: '+e.message}}
function addStorageFields(type){
 const mode=labField('storage_mode','Хранилище','none','text',[{value:'none',label:'Без PVC (Nginx / свой образ)'},{value:'new',label:'Создать новый PVC'},{value:'existing',label:'Подключить существующий PVC'}]);
 const claim=labField('pvc','Существующий PVC','','text',[]);const mount=labField('mount_path','Путь монтирования (Nginx / свой образ)','/data');const secret=labField('storage_secret','Secret с прежним паролем базы','','text',[]);secret.required=false;
 const note=element('p','PVC доступен только приложению в том же namespace. Новый PVC создаётся в namespace приложения. Существующий PVC подключается без очистки. Версия и формат данных должны соответствовать приложению. Для PostgreSQL/RabbitMQ выберите имя Secret с прежним паролем пользователя app. Пароль вручную вводить не нужно. Наличие ключа password не гарантирует, что Secret подходит к данным PVC.','lab-note');$('lab-extra').append(note);
 const update=()=>{const db=['postgres','redis','kafka','rabbitmq'].includes(type.value);if(db&&mode.value==='none')mode.value='new';claim.parentElement.hidden=mode.value!=='existing';claim.required=mode.value==='existing';$('lab-storage').parentElement.hidden=mode.value!=='new';mount.parentElement.hidden=db||mode.value==='none';secret.parentElement.hidden=mode.value!=='existing'||!['postgres','rabbitmq'].includes(type.value);secret.required=!secret.parentElement.hidden;const old=claim.value;claim.replaceChildren();const blank=element('option','Выберите PVC');blank.value='';claim.append(blank);for(const p of pvcData.filter(p=>p.namespace===$('lab-namespace').value)){const o=element('option',p.name+' · '+p.capacity+' · '+p.phase+(p.pods.length?' · занят':''));o.value=p.name;o.disabled=p.phase!=='Bound'||p.pods.length>0;claim.append(o)}if([...claim.options].some(o=>o.value===old))claim.value=old;const previous=secret.value;secret.replaceChildren();const placeholder=element('option','Выберите Secret с ключом password');placeholder.value='';secret.append(placeholder);for(const item of secretData.filter(s=>s.namespace===$('lab-namespace').value&&s.hasPassword)){const option=element('option',item.name+' · '+item.namespace+' · password ✓');option.value=item.name;secret.append(option)}if([...secret.options].some(o=>o.value===previous))secret.value=previous;};
 mode.onchange=update;$('lab-namespace').addEventListener('input',update);update();Promise.all([refreshPVCs(),refreshSecrets()]).then(()=>{if($('lab-dialog').open&&$('lab-storage_mode')===mode)update()});
}
$('pvc-refresh').onclick=refreshPVCs;$('cluster-select').addEventListener('change',()=>{pvcData=[];$('pvc-list').replaceChildren();refreshPVCs()});setInterval(()=>{if(!document.hidden)refreshPVCs()},15000);refreshPVCs();

function renderPVC(p){
 const row=element('article',undefined,'pvc-card');const head=element('div',undefined,'pvc-card-head');head.append(element('span','▤','pvc-icon'),element('h3',p.name),element('span',p.phase,'pvc-state '+(p.phase==='Bound'?'bound':'pending')));row.append(head);
 const overview=element('div',undefined,'pvc-overview');overview.append(element('span',p.capacity||'—','pvc-capacity'),element('span','Namespace: '+p.namespace,'pvc-namespace-badge'));row.append(overview);
 const location=p.location||{};const place=element('div',undefined,'pvc-location');place.append(element('span','РАСПОЛОЖЕНИЕ ДАННЫХ','eyebrow'));
 const nodes=location.nodes||[];place.append(element('strong',location.server||nodes.map(n=>n.name+(n.ip?' · '+n.ip:'')).join(', ')||'Сервер не определён'));
 const path=element('code',location.path||'Путь не предоставлен хранилищем');place.append(path);
 if(location.path){const copy=element('button','Копировать путь','button secondary');copy.type='button';copy.onclick=()=>navigator.clipboard.writeText(location.path).then(()=>{copy.textContent='Скопировано'}).catch(labError);place.append(copy)}
 place.append(element('small',location.note||''));row.append(place);
 const details=element('dl',undefined,'pvc-details');for(const [label,value] of [['Хранилище',p.storageClass||'—'],['Тип',location.kind||'—'],['Доступ',p.accessModes.join(', ')],['PV',p.volume||'не назначен'],['Используют Pod',p.pods.join(', ')||'Не используется']])details.append(element('dt',label),element('dd',value));row.append(details);return row;
}

let secretData=[];
const secretNamespaces=new Map();
function renderSecrets(){
 const namespaces=[...new Set(secretData.map(s=>s.namespace))].sort();const select=$('secret-namespace');let chosen=secretNamespaces.get(selectedCluster)||'';if(!namespaces.includes(chosen))chosen='';secretNamespaces.set(selectedCluster,chosen);select.replaceChildren();
 for(const ns of ['',...namespaces]){const option=element('option',(ns||'Все (All)')+' · '+secretData.filter(s=>!ns||s.namespace===ns).length);option.value=ns;select.append(option)}select.value=chosen;
 const data=secretData.filter(s=>!chosen||s.namespace===chosen);const box=$('secret-list');box.replaceChildren();for(const s of data){const card=element('article',undefined,'app-card');card.append(element('h3',s.name),element('span','Namespace: '+s.namespace,'pvc-namespace-badge'),element('p','Тип: '+s.type),element('p','Ключи: '+(s.keys.join(', ')||'нет')),element('p',s.hasPassword?'✓ Есть ключ password — можно выбрать при подключении базы':'Нет ключа password'));box.append(card)}if(!data.length)box.append(element('p','Secrets приложений пока нет.'));
}
async function refreshSecrets(){const cluster=selectedCluster;try{const data=await api('secret-info');if(cluster!==selectedCluster)return;secretData=data;renderSecrets();}catch(e){if(cluster===selectedCluster)$('secret-list').textContent=e.message}}
$('secret-namespace').onchange=()=>{secretNamespaces.set(selectedCluster,$('secret-namespace').value);renderSecrets()};
$('secret-refresh').onclick=refreshSecrets;$('cluster-select').addEventListener('change',()=>{secretData=[];$('secret-list').replaceChildren();refreshSecrets()});setInterval(()=>{if(!document.hidden)refreshSecrets()},15000);refreshSecrets();

function deleteTemplate(name){labOpen('Удалить шаблон «'+name+'»?','Будет удалён только сохранённый набор. Установленные приложения и их данные сохранятся.',async()=>{await api('templates',{operation:'delete',name});$('lab-dialog').close();await loadTemplates()})};
$('template-from-apps').onclick=async()=>{
 const cluster=selectedCluster;
 try{const apps=(await api('apps')).filter(a=>a.managed);if(cluster!==selectedCluster)return;
 labOpen('Шаблон из приложений','Сохраняются образы, реплики, запросы CPU/RAM и размеры дисков. Лимиты при развёртывании = 2 × запрос. Диски будут новыми, пароли сгенерируются заново, URL получат адрес нового кластера. Данные, Secrets и произвольные настройки не копируются.',async data=>{const selected=[...$('lab-extra').querySelectorAll('input:checked')].map(i=>{const a=apps[Number(i.value)];return {kind:a.kind,name:a.name,namespace:a.namespace}});if(!selected.length)throw Error('Выберите приложения');await api('templates',{operation:'from_apps',name:data.name,selected});$('lab-dialog').close();await loadTemplates()});
 labField('name','Имя шаблона','my-stand');
 if(!apps.length)$('lab-extra').append(element('p','Нет приложений из каталога в выбранном кластере.'));
 apps.forEach((a,i)=>{const label=element('label',undefined,'template-app-choice');const input=document.createElement('input');input.type='checkbox';input.value=i;const text=element('span',a.namespace+'/'+a.name);text.append(element('small',a.containers.map(c=>c.image).join(', ')));label.append(input,text);$('lab-extra').append(label)});
 }catch(e){$('apps-message').textContent=e.message}
};

function appKey(a){return a.namespace+'/'+a.kind+'/'+a.name}
function updateBulk(){const n=selectedApps.size;for(const [id,label] of [['apps-delete-selected','Удалить выделенное'],['apps-start-selected','Запустить выделенное'],['apps-stop-selected','Остановить выделенное'],['apps-restart-selected','Перезапустить выделенное']]){$(id).textContent=label+(n?' · '+n:'');$(id).disabled=busy||!n}$('apps-clear-selected').hidden=!n}
$('apps-clear-selected').onclick=()=>{selectedApps.clear();refreshApps();updateBulk()};
$('apps-delete-selected').onclick=()=>{const items=[...selectedApps.values()];if(!items.length)return;labOpen('Удалить выбранные приложения?','Кластер '+selectedCluster+'. PVC и пароли сохранятся. Для приложений каталога также удалятся их сервисы, Ingress и веб-панели.',async data=>{sameCluster();await api('action',{action:'app_delete',confirmed:true,confirmation:data.confirmation,params:{apps:items.map(a=>({kind:a.kind,name:a.name,namespace:a.namespace}))}});selectedApps.clear();$('lab-dialog').close();updateBulk();await poll()});for(const a of items)$('lab-extra').append(element('p',a.namespace+'/'+a.name+' · '+a.kind,'lab-note'));labField('confirmation','Введите УДАЛИТЬ','')};
setInterval(updateBulk,1000);

function bulkLifecycle(action,items=[...selectedApps.values()]){if(!items.length)return;const subject=items.length===1?items[0].name:'выделенные приложения';labOpen((action==='app_start'?'Запустить ':action==='app_stop'?'Остановить ':'Перезапустить ')+subject+'?',action==='app_start'?'Остановленные приложения и веб-панели будут запущены. Уже работающие приложения не перезапускаются.':action==='app_stop'?'Приложения и их веб-панели будут уменьшены до 0 реплик. Данные сохранятся. Для запуска нажмите «Запустить».':'Pod приложений и веб-панелей будут перезапущены последовательно. Возможен перерыв в доступности. Остановленные приложения запустятся с прежним числом реплик (если оно не сохранено — с одной репликой).',async()=>{sameCluster();await api('action',{action,confirmed:true,params:{apps:items.map(a=>({kind:a.kind,name:a.name,namespace:a.namespace}))}});$('lab-dialog').close();await poll()});for(const a of items)$('lab-extra').append(element('p',a.namespace+'/'+a.name+' · '+a.kind,'lab-note'))}
$('apps-stop-selected').onclick=()=>bulkLifecycle('app_stop');
$('apps-restart-selected').onclick=()=>bulkLifecycle('app_restart');

$('apps-start-selected').onclick=()=>bulkLifecycle('app_start');

function rabbitPlugins(app){labOpen('Плагины RabbitMQ · '+app.name,'Shovel переносит сообщения между очередями или брокерами. Вместе включается Shovel Management. Применение пересоздаст Pod и кратковременно прервёт подключения. Данные PVC сохранятся. Отключение остановит передачу через Shovel.',data=>labAction('rabbit_plugins',{name:app.name,namespace:app.namespace,enabled:data.enabled==='true'}));labField('enabled','Shovel — сохранённая настройка',String(!!app.shovel),'text',[{value:'false',label:'Выключен'},{value:'true',label:'Включён + управление в веб-панели'}]);$('lab-extra').append(element('p','Настройка применяется при каждом старте Pod и переносится в шаблон из приложений. Маршруты передачи настраиваются отдельно: RabbitMQ → Admin → Shovel Management.','lab-note'));}

let podDebugSession=null;
async function closePodDebug(preserve=false){const s=podDebugSession;podDebugSession=null;if(!s)return;s.closed=true;s.observer?.disconnect();clearTimeout(s.resizeTimer);if(preserve&&s.term){s.term.options.disableStdin=true;s.term.options.cursorBlink=false;s.retainedHost._debugTerm=s.term}else s.term?.dispose();try{await terminalApi(s.cluster,{operation:'close',id:s.id})}catch(e){}}
$('lab-dialog').addEventListener('close',()=>{closePodDebug();const d=$('lab-dialog');d.classList.remove('debug-dialog','debug-expanded');d.style.removeProperty('width');d.style.removeProperty('height');d.querySelector('.debug-expand')?.remove();$('lab-cancel').textContent='Отмена'});
$('cluster-select').addEventListener('change',()=>{if(podDebugSession){closePodDebug();$('lab-dialog').close()}});
function debugLogLines(text,query){if(!text)return [];const q=query.trim().toLowerCase();return text.split('\n').filter(line=>!q||line.toLowerCase().includes(q));}
async function openPodDebug(pod,options={}){
 await closePodDebug();labOpen('Онлайн-дебаг',pod.namespace+' / '+pod.name,null);
 const dialog=$('lab-dialog');dialog.classList.add('debug-dialog');$('lab-cancel').textContent='Закрыть';
 const expand=resourceButton('⛶ Развернуть',()=>{const full=dialog.classList.toggle('debug-expanded');expand.textContent=full?'↙ Свернуть':'⛶ Развернуть';expand.setAttribute('aria-pressed',String(full))},'button secondary debug-expand');expand.setAttribute('aria-pressed','false');$('lab-close').before(expand);
 const container=labField('debug-container','Контейнер','','text',[]);const mode=labField('debug-mode','Режим',options.mode||'logs','text',[{value:'logs',label:'Онлайн-логи'},{value:'shell',label:'Терминал'}]);const shell=labField('debug-shell','Shell','bash','text',[{value:'bash',label:'Bash (если нет — sh)'},{value:'sh',label:'sh'}]);
 const status=element('p','Загрузка контейнеров…','debug-status');status.setAttribute('role','status');
 const host=element('div',undefined,'pod-debug-terminal');const clearTerminal=()=>{host._debugTerm?.dispose();host._debugTerm=null};dialog.addEventListener('close',clearTerminal,{once:true});const logOutput=element('pre','','debug-log-output');logOutput.tabIndex=0;logOutput.setAttribute('aria-label','Логи контейнера');host.append(logOutput);
 const controls=element('div',undefined,'debug-connect-controls');const toolbar=element('div',undefined,'debug-log-toolbar');
 const query=document.createElement('input');query.type='search';query.placeholder='Фильтр логов: текст, ошибка, request ID…';query.setAttribute('aria-label','Фильтр строк логов');
 const count=element('span','0 строк','debug-log-count');const follow=document.createElement('input');follow.type='checkbox';follow.checked=true;const followLabel=element('label',undefined,'debug-follow');followLabel.append(follow,document.createTextNode('Автопрокрутка'));toolbar.append(query,count,followLabel);
 let text='';const renderLogs=()=>{const lines=debugLogLines(text,query.value);logOutput.textContent=lines.join('\n');count.textContent=(query.value?lines.length+' / ':'')+(text?text.split('\n').length:0)+' строк';if(follow.checked)logOutput.scrollTop=logOutput.scrollHeight;exportAll.disabled=!text;exportFiltered.disabled=!lines.some(line=>line.length)};query.oninput=renderLogs;follow.onchange=renderLogs;
 const clear=resourceButton('Очистить',()=>{text='';renderLogs()},'button secondary');toolbar.append(clear);
 const downloadLogs=filtered=>{
  const output=filtered?debugLogLines(text,query.value).join('\n'):text;
  if(!output)return;
  const safe=value=>String(value||'unknown').replace(/[^a-zA-Z0-9._-]/g,'_');
  const stamp=new Date().toISOString().replace(/[:.]/g,'-');
  const filename=[labCluster,pod.namespace,pod.name,container.value,filtered?'filtered':'buffer',stamp].map(safe).join('_')+'.log';
  const url=URL.createObjectURL(new Blob([output],{type:'text/plain;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
 };
 const exportAll=resourceButton('↓ Скачать .log',()=>downloadLogs(false),'button secondary');exportAll.title='Скачать весь загруженный буфер логов';exportAll.disabled=true;
 const exportFiltered=resourceButton('↓ По фильтру',()=>downloadLogs(true),'button secondary');exportFiltered.title='Скачать только строки, соответствующие текущему фильтру';exportFiltered.disabled=true;
 const exportBar=element('div',undefined,'debug-export-bar');exportBar.append(element('span','Экспорт UTF-8 · загруженные строки','debug-export-caption'),exportAll,exportFiltered);

 const stop=resourceButton('Отключить',async()=>{await closePodDebug(true);status.textContent='Отключено · вывод сохранён';stop.disabled=true;start.disabled=false;start.textContent='Подключиться'});stop.disabled=true;
 const start=resourceButton('Подключиться',async()=>{start.disabled=true;start.textContent='Подключение…';status.textContent='Подключаемся к контейнеру…';container.disabled=true;mode.disabled=true;shell.disabled=true;
 try{sameCluster();await closePodDebug();clearTerminal();text='';host.replaceChildren();const cluster=selectedCluster,sessionMode=mode.value;const result=await terminalApi(cluster,{operation:'open',pod:pod.name,namespace:pod.namespace,container:container.value,mode:sessionMode,shell:shell.value});if(!host.isConnected||cluster!==selectedCluster){await terminalApi(cluster,{operation:'close',id:result.id});return}
 const actualShell=result.shell||shell.value;const session={id:result.id,cluster,closed:false,term:null,retainedHost:host};podDebugSession=session;stop.disabled=false;start.textContent='Подключено';
 if(sessionMode==='logs'){host.append(logOutput);renderLogs();status.textContent='● Логи обновляются';await terminalApi(cluster,{operation:'resize',id:session.id,cols:400,rows:40})}
 else{
  const term=new Terminal({cursorBlink:true,fontSize:13,scrollback:2000,theme:{background:'#142e31',foreground:'#dbece7'}});session.term=term;const fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open(host);
  const resize=()=>{if(session.closed)return;fit.fit();terminalApi(cluster,{operation:'resize',id:session.id,cols:term.cols,rows:term.rows}).catch(e=>{if(!session.closed)status.textContent=e.message})};
  session.observer=new ResizeObserver(()=>{clearTimeout(session.resizeTimer);session.resizeTimer=setTimeout(resize,100)});session.observer.observe(host);resize();let queue=Promise.resolve();term.onData(input=>{for(let i=0;i<input.length;i+=512)queue=queue.then(()=>session.closed?null:terminalApi(cluster,{operation:'input',id:session.id,input:input.slice(i,i+512)})).catch(e=>{status.textContent=e.message})});term.focus();status.textContent='● '+actualShell+' подключён · exit — выйти';
 }
 (async()=>{let offset=0;const decoder=new TextDecoder();try{while(!session.closed){const result=await terminalApi(cluster,{operation:'poll',id:session.id,offset});if(session.closed)break;offset=result.offset;if(result.output){const bytes=Uint8Array.from(atob(result.output),c=>c.charCodeAt(0));if(session.term){text=(text+decoder.decode(bytes,{stream:true})).slice(-2000000);await new Promise(resolve=>session.term.write(bytes,resolve))}else{text+=decoder.decode(bytes,{stream:true}).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/\r/g,'');text=text.split('\n').slice(-10000).join('\n').slice(-2000000);renderLogs()}}if(result.finished){const missingShell=sessionMode==='shell'&&/executable file not found|exec:.*not found|stat .*no such file/i.test(text);status.textContent=missingShell?'В контейнере нет '+actualShell+'. Откройте онлайн-логи или выберите другой контейнер.':(/error:|Error from server|command terminated with exit code/i.test(text)?'Не удалось подключиться · причина указана ниже':'Сессия завершена · вывод сохранён');stop.disabled=true;start.disabled=false;start.textContent='Подключиться';await closePodDebug(true);break}}}catch(e){if(!session.closed){status.textContent=e.message;stop.disabled=true;start.disabled=false;start.textContent='Повторить';await closePodDebug(true)}}})();
 }catch(e){status.textContent=e.message;await closePodDebug(true);stop.disabled=true}finally{if(host.isConnected){start.disabled=!!podDebugSession&&!podDebugSession.closed;if(!start.disabled)start.textContent='Подключиться';container.disabled=false;mode.disabled=false;shell.disabled=false}}},'button primary');
 const updateMode=()=>{const logs=mode.value==='logs';shell.parentElement.hidden=logs;toolbar.hidden=!logs;exportBar.hidden=!logs;host.classList.toggle('logs-mode',logs)};
 const change=async()=>{await closePodDebug();clearTerminal();stop.disabled=true;start.disabled=false;start.textContent='Подключиться';host.replaceChildren(logOutput);text='';renderLogs();updateMode();status.textContent='Настройки изменены · нажмите «Подключиться»'};mode.onchange=change;container.onchange=change;shell.onchange=change;updateMode();
 controls.append(start,stop,status);$('lab-extra').append(controls,toolbar,exportBar,host,element('p','Буфер: до 10 000 строк / 2 млн символов. Экспорт сохраняет только загруженный буфер, не всю историю контейнера. Тяните за любой край или угол окна, чтобы изменить размер.','debug-hint'));start.disabled=true;
 try{const data=await api('pod',{name:pod.name,namespace:pod.namespace});if(!host.isConnected)return;for(const name of data.containers){const option=element('option',name);option.value=name;container.append(option)}start.disabled=!data.containers.length;if(options.container&&data.containers.includes(options.container))container.value=options.container;status.textContent=data.containers.length?'Готово к подключению':'Контейнеры не найдены';if(options.autoConnect&&!start.disabled)start.click()}catch(e){status.textContent=e.message}
}

// Resize diagnostic windows from any edge, including when initially maximized.
(()=>{
 const dialog=$('lab-dialog');let drag=null;
 const enabled=()=>dialog.open&&(dialog.classList.contains('debug-dialog')||dialog.classList.contains('diagnostics-dialog'));
 const edges=e=>{const r=dialog.getBoundingClientRect(),x=e.clientX,y=e.clientY;if(x<r.left||x>r.right||y<r.top||y>r.bottom)return '';return (y-r.top<12?'n':r.bottom-y<12?'s':'')+(x-r.left<12?'w':r.right-x<12?'e':'')};
 const cursor=edge=>({n:'ns',s:'ns',w:'ew',e:'ew',nw:'nwse',se:'nwse',ne:'nesw',sw:'nesw'}[edge]||'')+'-resize';
 const finish=()=>{if(!drag)return;const id=drag.id;drag=null;if(dialog.hasPointerCapture(id))dialog.releasePointerCapture(id);dialog.classList.remove('dialog-resizing');dialog.style.removeProperty('cursor')};
 dialog.addEventListener('pointerdown',e=>{
  if(!enabled()||e.button!==0)return;const edge=edges(e);if(!edge)return;
  e.preventDefault();const r=dialog.getBoundingClientRect();drag={id:e.pointerId,edge,x:e.clientX,y:e.clientY,left:r.left,top:r.top,right:r.right,bottom:r.bottom};
  dialog.classList.remove('debug-expanded','diagnostics-expanded');const expand=dialog.querySelector('.debug-expand,.diagnostic-expand');if(expand){expand.textContent='⛶ Развернуть';expand.setAttribute('aria-pressed','false')}
  Object.assign(dialog.style,{margin:'0',left:r.left+'px',top:r.top+'px',right:'auto',bottom:'auto',width:r.width+'px',height:r.height+'px',cursor:cursor(edge)});
  dialog.classList.add('dialog-resizing');dialog.setPointerCapture(e.pointerId);
 },true);
 dialog.addEventListener('pointermove',e=>{
  if(!enabled())return;
  if(!drag){const edge=edges(e);if(edge)dialog.style.cursor=cursor(edge);else dialog.style.removeProperty('cursor');return}
  e.preventDefault();const d=drag,dx=e.clientX-d.x,dy=e.clientY-d.y,minW=Math.min(540,innerWidth-24),minH=Math.min(420,innerHeight-24);
  let l=d.left,r=d.right,t=d.top,b=d.bottom;
  if(d.edge.includes('w'))l=Math.max(12,Math.min(d.left+dx,r-minW));
  if(d.edge.includes('e'))r=Math.min(innerWidth-12,Math.max(d.right+dx,l+minW));
  if(d.edge.includes('n'))t=Math.max(12,Math.min(d.top+dy,b-minH));
  if(d.edge.includes('s'))b=Math.min(innerHeight-12,Math.max(d.bottom+dy,t+minH));
  Object.assign(dialog.style,{left:l+'px',top:t+'px',width:(r-l)+'px',height:(b-t)+'px'});
 });
 for(const event of ['pointerup','pointercancel','lostpointercapture'])dialog.addEventListener(event,finish);
 dialog.addEventListener('pointerleave',()=>{if(!drag)dialog.style.removeProperty('cursor')});
 dialog.addEventListener('close',()=>{finish();for(const key of ['margin','left','top','right','bottom','width','height','cursor'])dialog.style.removeProperty(key)});
})();
