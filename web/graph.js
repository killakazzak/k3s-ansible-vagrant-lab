'use strict';
let graphData=null,graphCluster=null,graphLoading=false,graphSignature='';
let graphPaused=false;
const graphReducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
function syncGraphMotion(){const paused=graphPaused||graphReducedMotion.matches||document.hidden;const svg=$('cluster-graph');svg.classList.toggle('motion-paused',paused);if(paused)svg.pauseAnimations();else svg.unpauseAnimations();$('graph-motion').textContent=graphPaused?'▶ Анимация':'Ⅱ Пауза';$('graph-motion').setAttribute('aria-pressed',String(graphPaused));}
const svgNS='http://www.w3.org/2000/svg';
function svgEl(tag,attrs={},text){const el=document.createElementNS(svgNS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;return el;}
function routeURLs(route){
 if(!route)return [];
 let host=route.host,paths=[route.path];
 if(route.kind==='IngressRoute'){
  // Only derive clickable URLs from a single literal Host rule.
  const hosts=[...host.matchAll(/\bHost\(`([^`]+)`\)/g)];
  if(hosts.length!==1||/HostRegexp|!\s*Host/.test(host))return [];
  paths=[...host.matchAll(/\bPath(?:Prefix)?\(`([^`]+)`\)/g)].map(m=>m[1]);
  if(!paths.length)paths=['/'];
  host=hosts[0][1];
 }
 if(!/^[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?$/.test(host)||host.includes('..'))return [];
 return [...new Set(paths)].filter(p=>typeof p==='string'&&p.startsWith('/')&&!/[?#\\\s]/.test(p)).map(path=>{
  if(route.internal==='api@internal'&&path==='/dashboard')path='/dashboard/';
  return (route.tls?'https://':'http://')+host+path;
 });
}
function workloadLabel(p){const w=p.workload;return w?`${w.kind} / ${w.name}`:'Владелец неизвестен';}
function serviceType(s){return s.type+(s.headless?' · Headless':'');}
function renderRouteInfo(route,svc,pods){
 const box=$('graph-route-info');box.replaceChildren();
 if(!route)return;
 const add=(tag,text,cls)=>{const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;};
 const heading=add('div','Куда ведёт ссылка','route-caption');box.append(heading);
 const urls=routeURLs(route);
 for(const url of urls){
  const row=add('div','','route-url-row');const link=add('a',url+' ↗','route-url');link.href=url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);
  const button=add('button','Копировать','button secondary');button.type='button';button.onclick=async()=>{try{await navigator.clipboard.writeText(url);button.textContent='Скопировано';setTimeout(()=>button.textContent='Копировать',1800)}catch{button.textContent='Выделите ссылку для копирования'}};row.append(button);box.append(row);
 }
 if(!urls.length)box.append(add('p','Точный URL нельзя вывести из этого правила. Хост / условие: '+route.host+' · '+route.path));
 const purpose=route.internal==='api@internal'?'Панель и API Traefik':route.name==='rancher'?'Rancher — управление Kubernetes':route.name==='nginx-demo'?'Тестовый сайт Nginx':'Приложение '+(svc?svc.name:route.name);
 box.append(add('div',purpose,'route-purpose'));
 const list=add('dl','','route-destinations');
 const item=(label,value)=>{list.append(add('dt',label),add('dd',value));};
 item('Ingress',`${route.namespace}/${route.name} · ${route.controller}`);
 item('Service',svc?`${svc.id} · порт ${typeof route.port==='object'?JSON.stringify(route.port):route.port}`:route.internal||'Не найден');
 if(svc)item('Тип Service',serviceType(svc)+' — '+({ClusterIP:svc.headless?'DNS указывает на endpoints без виртуального IP':'внутренний виртуальный IP',NodePort:'доступ через порт на узлах',LoadBalancer:'доступ через балансировщик',ExternalName:'DNS-псевдоним внешнего адреса'}[svc.type]||'тип из Kubernetes'));
 item('Рабочая нагрузка',pods.length?[...new Set(pods.map(workloadLabel))].join('\n'):route.internal?'Внутренний обработчик Traefik':'Поды не найдены');
 if(svc)item('Внутри кластера',svc.external||`${svc.name}.${svc.namespace}.svc.cluster.local · ${svc.ip}`);
 item('Pod → узел',pods.length?pods.map(p=>`${p.name} → ${p.node||'ещё не назначен'}`).join('\n'):route.internal?'Обрабатывается внутри контроллера Traefik':'Нет привязанных Pod endpoints');
 box.append(list);
 box.append(add('p','URL выше — вход в приложение через Ingress. Адрес Service доступен внутри кластера. Показан маршрут по конфигурации; доступность URL отдельно не проверялась.','route-note'));
}
function drawGraph(){
 const svg=$('cluster-graph');svg.replaceChildren();svg.setCurrentTime(0);
 if(!graphData)return;
 const route=graphData.routes.find(r=>r.id===$('graph-route').value);
 const svc=route&&graphData.services.find(s=>s.id===route.service);
 const endpoints=route?graphData.endpoints.filter(e=>e.service===route.service):[];
 const podIds=new Set(endpoints.map(e=>e.pod).filter(Boolean));
 const pods=graphData.pods.filter(p=>podIds.has(p.id));
 renderRouteInfo(route,svc,pods);
 const nodes=[...graphData.nodes].sort((a,b)=>a.role.localeCompare(b.role)||a.name.localeCompare(b.name));
 const h=Math.max(340,100+Math.max(pods.length,nodes.length)*105);svg.setAttribute('viewBox',`0 0 1280 ${h}`);svg.style.height=h+'px';
 const defs=svgEl('defs'),marker=svgEl('marker',{id:'route-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto'});marker.append(svgEl('path',{d:'M0 0 L10 5 L0 10 Z',fill:'#74a993'}));defs.append(marker);svg.append(defs);
 const edges=svgEl('g');svg.append(edges);
 const heads=['КЛИЕНТ','INGRESS / TRAEFIK','SERVICE','PODS','УЗЛЫ КЛАСТЕРА'];
 const xs=[20,255,510,765,1020];heads.forEach((t,i)=>svg.append(svgEl('text',{x:xs[i]+8,y:30,class:'graph-heading'},t)));
 const positions=new Map();
 function card(id,col,y,title,subtitle,type,ready,detail){
  const x=xs[col],g=svgEl('g',{class:'graph-card '+type,tabindex:'0',role:'button','aria-label':title,transform:`translate(${x},${y})`});
  g.style.animationDelay=(col*90)+'ms';
  g.append(svgEl('rect',{width:220,height:76,rx:12}));
  const color=ready===false?'#cf9350':ready===true?'#4f9977':'#88a1ac';
  g.append(svgEl('circle',{cx:16,cy:22,r:4,fill:color}));
  if(ready===true)g.append(svgEl('circle',{cx:16,cy:22,r:7,class:'graph-status-halo'}));
  g.append(svgEl('text',{x:29,y:26,class:'graph-title'},title.length>23?title.slice(0,21)+'…':title));
  g.append(svgEl('text',{x:14,y:50,class:'graph-subtitle'},subtitle.length>30?subtitle.slice(0,28)+'…':subtitle));
  g.append(svgEl('title',{},title+'\n'+subtitle));
  const show=()=>{$('graph-detail').textContent=detail;svg.querySelectorAll('.selected').forEach(e=>e.classList.remove('selected'));g.classList.add('selected');if(id.startsWith('pod:')){const pod=graphData.pods.find(p=>'pod:'+p.id===id);if(pod)window.dispatchEvent(new CustomEvent('lab-pod',{detail:pod}));}};
  g.addEventListener('click',show);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show()}});
  svg.append(g);positions.set(id,{x,y,col});
 }
 function link(from,to,dashed=false,ready=true){const a=positions.get(from),b=positions.get(to);if(!a||!b)return;const path=svgEl('path',{d:`M${a.x+220},${a.y+38} C${a.x+245},${a.y+38} ${b.x-25},${b.y+38} ${b.x},${b.y+38}`,'marker-end':dashed?'none':'url(#route-arrow)',class:'graph-edge'+(dashed?' placement':'')+(ready?'':' unavailable')});edges.append(path);
  if(!dashed&&ready){
   const particle=svgEl('g',{class:'graph-particle'});
   particle.append(svgEl('circle',{r:7,fill:'#5ab991',opacity:'.16'}));
   particle.append(svgEl('circle',{r:3,fill:'#258969',stroke:'#effff7','stroke-width':1}));
   const start=a.col*.23;
   const motion=svgEl('animateMotion',{path:path.getAttribute('d'),dur:'5s',repeatCount:'indefinite',keyPoints:'0;0;1;1',keyTimes:`0;${start};${start+.2};1`,calcMode:'linear'});
   particle.append(motion);
   particle.append(svgEl('animate',{attributeName:'opacity',values:'0;0;1;1;0;0',keyTimes:`0;${Math.max(.001,start)};${start+.02};${start+.18};${start+.2};1`,dur:'5s',repeatCount:'indefinite'}));
   edges.append(particle);
  }
 }
 nodes.forEach((n,i)=>card('node:'+n.id,4,60+i*105,n.name,n.role+' · '+n.ip,'node '+(n.role==='Master'?'master':''),n.ready,`${n.role}: ${n.name} · IP ${n.ip} · ${n.ready?'Ready':'NotReady'} · На узле размещено ${graphData.pods.filter(p=>p.node===n.id).length} Pod.`));
 if(!route){syncGraphMotion();card('empty',1,100,'Нет Ingress','Узлы показаны справа','',null,'Создайте Ingress или IngressRoute, чтобы увидеть путь запроса.');return;}
 card('user',0,100,'Пользователь','HTTP / HTTPS','client',null,'Клиент обращается по хосту и пути выбранного маршрута.');
 card('ingress',1,100,route.name,route.kind+' · '+route.namespace,'ingress',null,`${route.kind}: ${route.namespace}/${route.name} · ${route.host} ${route.path} · Контроллер: ${route.controller} · Порт backend: ${JSON.stringify(route.port)}`);
 link('user','ingress');
 card('svc',2,100,svc?svc.name:route.internal||'Service не найден',svc?serviceType(svc)+' · '+svc.ip:route.internal?'Внутренний сервис Traefik':'Нет backend Service','service',svc?null:!!route.internal,svc?`Service ${svc.id} · ${serviceType(svc)} · ${svc.external||svc.ip} · Порты: ${svc.ports.map(p=>p.port+' → '+p.targetPort).join(', ')} · Endpoints: ${endpoints.length}`:route.internal?'Внутренний обработчик Traefik '+route.internal+', не Kubernetes Service.':'Backend Service не найден или тип backend не поддерживается.');
 link('ingress','svc',false,!!svc||!!route.internal);
 pods.forEach((p,i)=>{const ep=endpoints.filter(e=>e.pod===p.id);const ready=ep.some(e=>e.ready!==false);card('pod:'+p.id,3,60+i*105,p.name,(p.workload?p.workload.kind:'Pod')+' · '+(p.ready?'Ready':p.phase),'pod',p.ready,`Pod ${p.id} · Владелец: ${workloadLabel(p)} · Цепочка: ${(p.workload?.chain||[]).map(o=>o.kind+"/"+o.name).join(" → ")||"без контроллера"} · IP ${p.ip||'не назначен'} · ${p.phase} · Узел ${p.node||'ещё не назначен'} · Endpoint: ${ready?'доступен или ready не указан':'not ready'}`);link('svc','pod:'+p.id,false,ready);link('pod:'+p.id,'node:'+p.node,true)});
 if(!pods.length){card('no-pod',3,100,route.internal?'Внутри Traefik':'Нет Pod endpoints',svc&&svc.external?svc.external:'Нажмите для подробностей','pod',null,endpoints.length?'У EndpointSlice нет targetRef на известный Pod. Адреса: '+endpoints.flatMap(e=>e.addresses).join(', '):route.internal?'Этот маршрут обслуживает сам контроллер Traefik.':'У Service пока нет EndpointSlice с привязкой к Pod.');link('svc','no-pod',false,false)}
 syncGraphMotion();
}
async function refreshGraph(){
 if(graphLoading)return;graphLoading=true;
 const cluster=selectedCluster;
 if(graphCluster!==cluster){graphData=null;$('pod-map').replaceChildren();graphSignature='';$('graph-route-info').replaceChildren();$('cluster-graph').replaceChildren();$('graph-route').replaceChildren();$('graph-detail').textContent='Загружаем карту выбранного кластера…';}
 $('graph-status').textContent='Получаем данные Kubernetes…';
 try{const data=await api('topology');if(cluster!==selectedCluster)return;const old=$('graph-route').value;const signature=JSON.stringify([cluster,data.nodes,data.services,data.pods,data.routes,data.endpoints]);const changed=signature!==graphSignature;graphSignature=signature;graphCluster=cluster;graphData=data;drawPlacement();$('graph-route').replaceChildren();
 for(const r of data.routes){const o=document.createElement('option');o.value=r.id;o.textContent=`${routeURLs(r)[0]||r.host+' '+r.path} → ${r.namespace}/${r.name}`;$('graph-route').append(o)}
 if(data.routes.some(r=>r.id===old))$('graph-route').value=old;
 else {const demo=data.routes.find(r=>r.host.startsWith('nginx.'));if(demo)$('graph-route').value=demo.id;}
 $('graph-status').textContent=(data.warning?data.warning+' · ':'')+'Обновлено '+new Date(data.updated*1000).toLocaleTimeString();if(changed){$('graph-detail').textContent='Нажмите на Ingress, Service, Pod или узел — здесь появятся подробности.';drawGraph();}
 }catch(e){if(cluster===selectedCluster){graphData=null;$('pod-map').replaceChildren();graphSignature='';$('graph-route-info').replaceChildren();$('cluster-graph').replaceChildren();$('graph-route').replaceChildren();$('graph-status').textContent=e.message;$('graph-detail').textContent='Карта недоступна. Проверьте состояние выбранного кластера.';}}
 finally{graphLoading=false;if(cluster!==selectedCluster)refreshGraph();}
}
$('graph-route').onchange=drawGraph;$('graph-refresh').onclick=refreshGraph;$('cluster-select').addEventListener('change',refreshGraph);
setInterval(()=>{if(!document.hidden)refreshGraph()},15000);refreshGraph();

$('graph-motion').onclick=()=>{graphPaused=!graphPaused;syncGraphMotion()};
graphReducedMotion.addEventListener('change',syncGraphMotion);
document.addEventListener('visibilitychange',syncGraphMotion);

const placementNamespaces=new Map();
function drawPlacement(){
 const box=$('pod-map');box.replaceChildren();if(!graphData)return;const query=$('pod-filter').value.toLowerCase();
 const namespaces=[...new Set(graphData.pods.map(p=>p.namespace))].sort();const select=$('pod-namespace');let chosen=placementNamespaces.get(selectedCluster)||'';if(!namespaces.includes(chosen))chosen='';placementNamespaces.set(selectedCluster,chosen);select.replaceChildren();
 for(const ns of ['',...namespaces]){const option=element('option',(ns||'Все (All)')+' · '+graphData.pods.filter(p=>!ns||p.namespace===ns).length);option.value=ns;select.append(option)}select.value=chosen;
 const visible=graphData.pods.filter(p=>(!chosen||p.namespace===chosen)&&JSON.stringify([p.name,p.namespace,p.containers]).toLowerCase().includes(query));
 $('pod-filter-summary').textContent=`${chosen||'Все namespace'} · показано ${visible.length} из ${graphData.pods.length} Pod · обновление каждые 15 секунд`;
 for(const node of [...graphData.nodes,{id:null,name:'Ожидают назначения',role:'Pending'}]){
  const pods=visible.filter(p=>p.node===node.id||(!node.id&&!p.node));if(!pods.length)continue;
  const column=element('article',undefined,'placement-node');column.append(element('h3',node.name),element('p',`${node.role} · ${node.ip||'—'} · ${pods.length} Pod`));
  for(const pod of pods){const b=element('button',undefined,'placement-pod '+(pod.ready?'ready':'waiting'));b.append(element('strong',pod.name),element('span',pod.namespace+' · '+(pod.workload?.kind||'Pod')),element('span',(pod.ready?'● Ready':pod.phase)+' · рестарты '+(pod.statuses||[]).reduce((sum,c)=>sum+c.restarts,0)));b.onclick=()=>{labOpen(pod.name,pod.namespace+' · '+pod.node,null);const details=element('pre',JSON.stringify({workload:pod.workload,ip:pod.ip,created:pod.created,qos:pod.qos,containers:pod.containers,statuses:pod.statuses,volumes:pod.volumes,labels:pod.labels},null,2),'diagnostic-output');const logs=element('button','Логи, события и терминал','button primary');logs.type='button';logs.onclick=()=>showPodDiagnostics(pod);$('lab-extra').append(details,logs)};column.append(b)}box.append(column);
 }
 if(!visible.length)box.append(element('p','В выбранном namespace по этому запросу Pod не найдены.','panelnote'));
}
$('pod-filter').oninput=drawPlacement;
$('pod-namespace').onchange=()=>{placementNamespaces.set(selectedCluster,$('pod-namespace').value);drawPlacement()};

// Compact resource browser shares existing polling data; it does not fetch secrets' values.
let resourceTab='pods',resourceView='table',resourceSignature='',resourceSelected=null;
const resourceTypes=[['pods','Pods'],['deployments','Deployments'],['statefulsets','StatefulSets'],['daemonsets','DaemonSets'],['jobs','Jobs'],['cronjobs','CronJobs'],['services','Services'],['ingresses','Ingress'],['configmaps','ConfigMaps'],['pvcs','PVC'],['secrets','Secrets']];
let extraResources=[],extraCluster=null,extraLoading=false,extraError='';
async function refreshExtraResources(){if(extraLoading)return;extraLoading=true;const cluster=selectedCluster;try{const data=await api('resources');if(cluster===selectedCluster){extraResources=data;extraCluster=cluster;extraError=''}}catch(e){if(cluster===selectedCluster){extraResources=[];extraCluster=cluster;extraError=e.message}}finally{extraLoading=false;renderResources(true);if(cluster!==selectedCluster)refreshExtraResources()}}
for(const [type,label] of resourceTypes){if($('resource-tab-'+type))continue;const b=element('button',label);b.id='resource-tab-'+type;b.setAttribute('role','tab');$('resource-tab-pods').parentElement.append(b)}
const resourceFilters=new Map();
function resourceItems(){const more={};for(const [key,label] of resourceTypes){if(['pods','pvcs','secrets'].includes(key))continue;const kinds={deployments:'Deployment',statefulsets:'StatefulSet',daemonsets:'DaemonSet',jobs:'Job',cronjobs:'CronJob',services:'Service',ingresses:'Ingress',configmaps:'ConfigMap'};more[key]=extraCluster===selectedCluster?extraResources.filter(r=>r.kind===kinds[key]):[]}return {...more,pods:graphCluster===selectedCluster?(graphData?.pods||[]):[],pvcs:pvcData,secrets:secretData};}
function resourceKey(p){return p.namespace+'/'+p.name;}
function resourceFilter(){if(!resourceFilters.has(selectedCluster))resourceFilters.set(selectedCluster,{namespace:'',search:'',podName:'',podStatus:'',podContainer:'',podNode:'',podSort:'name',podDirection:'asc'});return resourceFilters.get(selectedCluster);}
function resourceButton(label,fn,cls='button secondary'){const b=element('button',label,cls);b.type='button';b.onclick=fn;return b;}
function showResource(type,item){resourceSelected={type,key:resourceKey(item),cluster:selectedCluster};renderResourceDetail(item);renderResources(true);}
function renderResourceDetail(item){
 const body=$('resource-detail-body');body.replaceChildren();$('resource-detail').hidden=false;
 const resourceType=resourceSelected.type;const yamlActions=element('div',undefined,'resource-yaml-actions');yamlActions.append(resourceButton('Просмотреть YAML',()=>openResourceYaml(resourceType,item)),resourceButton('↓ Скачать YAML',()=>openResourceYaml(resourceType,item,true)));body.append(yamlActions);
 if(resourceSelected.type==='pvcs'){body.append(renderPVC(item));for(const name of item.pods){const pod=resourceItems().pods.find(p=>p.namespace===item.namespace&&p.name===name);if(pod)body.append(resourceButton('Pod → '+name,()=>showResource('pods',pod)))}return;}
 body.append(element('h3',item.name),element('span',item.namespace,'pvc-namespace-badge'));
 const list=element('dl',undefined,'pvc-details');const entry=(label,value)=>list.append(element('dt',label),element('dd',value||'—'));
 if(item.details){for(const [k,v] of Object.entries(item.details))entry(k,typeof v==='object'?JSON.stringify(v,null,2):String(v));entry('Тип',item.kind);entry('Статус',item.state);body.append(list);return;}
 if(resourceSelected.type==='secrets'){entry('Тип',item.type);entry('Ключи',item.keys.join(', '));entry('password',item.hasPassword?'Есть':'Нет');body.append(list,element('p','Значения скрыты. Для подключения базы выберите этот Secret в форме приложения.','panelnote'));return;}
 entry('Статус',PodFilters.status(item));entry('Узел',item.node||'Не назначен');entry('IP',item.ip);entry('Владелец',workloadLabel(item));entry('Создан',item.created?new Date(item.created).toLocaleString():'—');entry('QoS',item.qos);entry('Рестарты',String((item.statuses||[]).reduce((a,c)=>a+c.restarts,0)));body.append(list);
 for(const c of item.containers||[]){const block=element('div',undefined,'resource-container');block.append(element('strong',c.name),element('code',c.image));const r=c.resources||{};block.append(element('p','Requests: CPU '+(r.requests?.cpu||'—')+' / RAM '+(r.requests?.memory||'—')),element('p','Limits: CPU '+(r.limits?.cpu||'—')+' / RAM '+(r.limits?.memory||'—')));body.append(block)}
 for(const v of item.volumes||[]){if(!v.claim)continue;const pvc=pvcData.find(p=>p.namespace===item.namespace&&p.name===v.claim);body.append(resourceButton('PVC → '+v.claim,()=>{if(pvc)showResource('pvcs',pvc)},'button secondary'))}
 const actions=element('div',undefined,'pod-detail-actions');actions.append(resourceButton('>_ Терминал',()=>openPodTerminal(item).catch(labError),'button primary'),resourceButton('Онлайн-дебаг',()=>openPodDebug(item),'button primary'),resourceButton('Логи и события',()=>showPodDiagnostics(item),'button secondary'));body.prepend(actions);
 const extra=document.createElement('details');extra.className='pod-detail-extra';extra.open=!!resourceSelected.expanded;const summary=element('summary');const caption=element('span');caption.append(element('strong','Технические подробности'),element('small','Состояния контейнеров и метки'));summary.append(caption);extra.append(summary,element('pre',JSON.stringify({statuses:item.statuses,labels:item.labels},null,2),'diagnostic-output'));extra.ontoggle=()=>{if(extra.isConnected&&resourceSelected)resourceSelected.expanded=extra.open};body.append(extra);
}
function podTableHead(pods,filter){
 const head=document.createElement('thead'),row=document.createElement('tr');
 const scoped=pods.filter(p=>!filter.namespace||p.namespace===filter.namespace);
 const columns=[['Имя','name'],['Namespace',null,'namespace',pods.map(p=>p.namespace)],['Статус','status','podStatus',scoped.flatMap(PodFilters.statuses)],['Контейнеры','container','podContainer',scoped.flatMap(PodFilters.containers)],['Узел','node','podNode',scoped.map(PodFilters.node)],['Рестарты']];
 for(const [label,sortKey,filterKey,values] of columns){
  const th=document.createElement('th');th.scope='col';
  if(sortKey){
   const active=(filter.podSort||'name')===sortKey;
   th.setAttribute('aria-sort',active?(filter.podDirection==='desc'?'descending':'ascending'):'none');
   const button=resourceButton('',()=>{filter.podDirection=active&&filter.podDirection!=='desc'?'desc':'asc';filter.podSort=sortKey;renderResources(true)},'column-sort');
   button.append(element('span',label),element('span',active?(filter.podDirection==='desc'?'↓':'↑'):'↕','column-sort-arrow'));button.title='Сортировать: '+label;th.append(button);
  }else th.append(element('span',label,'column-heading'));
  if(sortKey==='name'){
   const input=document.createElement('input');input.type='text';input.id='column-podName';input.className='column-filter'+(filter.podName?' active':'');input.placeholder='Найти по имени…';input.setAttribute('aria-label','Фильтр по имени Pod');input.autocomplete='off';input.value=filter.podName||'';
   input.oninput=()=>{filter.podName=input.value;renderResources(true)};th.append(input);
  }
  if(filterKey){
   const select=document.createElement('select');select.id='column-'+filterKey;select.className='column-filter'+(filter[filterKey]?' active':'');select.setAttribute('aria-label','Фильтр: '+label);
   for(const value of ['',...new Set([...values,...(filter[filterKey]?[filter[filterKey]]:[])].sort(PodFilters.compare))]){const option=element('option',value||'Все');option.value=value;select.append(option)}
   select.value=filter[filterKey]||'';select.onchange=()=>{filter[filterKey]=select.value;renderResources(true);$('column-'+filterKey)?.focus()};th.append(select);
  }
  row.append(th);
 }
 head.append(row);return head;
}
const podReset=resourceButton('Сбросить фильтры',()=>{Object.assign(resourceFilter(),{podName:'',podStatus:'',podContainer:'',podNode:'',podSort:'name',podDirection:'asc'});renderResources(true)},'column-reset');
$('resource-summary').after(podReset);
function renderResources(force=false){
 const nameInput=document.activeElement?.id==='column-podName'?document.activeElement:null;
 const nameCursor=nameInput?[nameInput.selectionStart,nameInput.selectionEnd]:null;
 if(!force&&document.activeElement?.classList.contains('column-filter'))return;
 const sets=resourceItems(),filter=resourceFilter();const signature=JSON.stringify([selectedCluster,resourceTab,resourceView,filter,sets]);if(!force&&signature===resourceSignature)return;resourceSignature=signature;
 const namespaces=[...new Set(Object.values(sets).flat().map(p=>p.namespace))].sort();const select=$('resource-namespace');select.replaceChildren();for(const ns of ['',...new Set([...namespaces,...(filter.namespace?[filter.namespace]:[])])]){const o=element('option',ns||'Все пространства');o.value=ns;select.append(o)}select.value=filter.namespace;if($('resource-search').value!==filter.search)$('resource-search').value=filter.search;
 for(const [type,label] of resourceTypes){const tab=$('resource-tab-'+type);tab.replaceChildren(element('span',label),element('span',String(sets[type].filter(p=>!filter.namespace||p.namespace===filter.namespace).length),'resource-tab-count'));tab.setAttribute('aria-selected',String(type===resourceTab));tab.tabIndex=type===resourceTab?0:-1;}
 $('resource-view-controls').hidden=resourceTab!=='pods';$('resource-table-view').setAttribute('aria-pressed',String(resourceView==='table'));$('resource-map-view').setAttribute('aria-pressed',String(resourceView==='map'));
 podReset.hidden=resourceTab!=='pods'||(!filter.podName&&!filter.podStatus&&!filter.podContainer&&!filter.podNode&&(filter.podSort||'name')==='name'&&(filter.podDirection||'asc')==='asc');
 const query=filter.search.toLowerCase();let items=sets[resourceTab].filter(p=>(!filter.namespace||p.namespace===filter.namespace)&&JSON.stringify(p).toLowerCase().includes(query));if(resourceTab==='pods')items=PodFilters.apply(items,filter);const content=$('resource-content');content.replaceChildren();
 $('resource-summary').textContent=`${items.length} из ${sets[resourceTab].length} · автообновление 15 с`;
 const errorText=!['pods','pvcs','secrets'].includes(resourceTab)?extraError:resourceTab==='pods'?(!graphData?$('graph-status').textContent:''):resourceTab==='pvcs'?$('pvc-list').textContent:$('secret-list').textContent;
 if(!items.length&&resourceTab!=='pods'){content.append(element('p','Ресурсов по выбранным фильтрам нет.','resource-empty'));if(errorText&&/недоступ|ошиб|token|отказ/i.test(errorText))content.append(element('p',errorText,'error'));}
 else if(resourceTab==='pods'&&resourceView==='map'){
  const filterTable=document.createElement('table');filterTable.className='resource-table pod-map-filters';filterTable.append(podTableHead(sets.pods,filter));content.append(filterTable);
  if(!items.length)content.append(element('p','Ресурсов по выбранным фильтрам нет.','resource-empty'));
  const map=element('div',undefined,'resource-map');const groups=[...new Set(items.map(p=>p.node||'Не назначен'))];for(const node of groups){const column=element('article',undefined,'placement-node');column.append(element('h3',node));for(const p of items.filter(p=>(p.node||'Не назначен')===node)){const b=resourceButton('',()=>showResource('pods',p),'placement-pod '+(p.ready?'ready':'waiting'));b.append(element('strong',p.name),element('span',p.namespace+' · '+PodFilters.status(p)));column.append(b)}map.append(column)}content.append(map);
 }else{
  const table=document.createElement('table');table.className='resource-table';const head=document.createElement('thead'),tr=document.createElement('tr');const headers=resourceTab==='pods'?['Имя','Namespace','Статус','Контейнеры','Узел','Рестарты']:resourceTab==='pvcs'?['Имя','Namespace','Размер','Статус','Сервер']:resourceTab==='secrets'?['Имя','Namespace','Тип','Ключи']:['Имя','Namespace','Статус / тип','Сводка'];for(const h of headers)tr.append(element('th',h));head.append(tr);table.append(resourceTab==='pods'?podTableHead(sets.pods,filter):head);const tbody=document.createElement('tbody');
  if(!items.length){const empty=document.createElement('tr'),cell=element('td','Ресурсов по выбранным фильтрам нет.','resource-empty');cell.colSpan=headers.length;empty.append(cell);tbody.append(empty);}
  for(const p of items){const row=document.createElement('tr');if(resourceSelected?.cluster===selectedCluster&&resourceSelected.type===resourceTab&&resourceSelected.key===resourceKey(p))row.className='selected';const name=document.createElement('td');const nameButton=resourceButton('',()=>showResource(resourceTab,p),'resource-name');const icon=element('span',{pods:'◇',pvcs:'▤',secrets:'⌘'}[resourceTab]||'▱','resource-type-icon');icon.setAttribute('aria-hidden','true');nameButton.append(icon,element('span',p.name));name.append(nameButton);row.append(name);const values=resourceTab==='pods'?[p.namespace,PodFilters.status(p),PodFilters.containers(p).join(', ')||'—',p.node||'Не назначен',String((p.statuses||[]).reduce((a,c)=>a+c.restarts,0))]:resourceTab==='pvcs'?[p.namespace,p.capacity,p.phase,p.location?.server||(p.location?.nodes||[]).map(n=>n.name).join(', ')||'—']:resourceTab==='secrets'?[p.namespace,p.type,p.keys.join(', ')]:[p.namespace,p.state,p.summary];for(const [index,value] of values.entries()){const td=element('td');const isStatus=(resourceTab==='pods'&&index===1)||(resourceTab==='pvcs'&&index===2);if(index===0)td.append(element('span',value,'resource-ns-chip'));else if(isStatus){const tone=['Ready','Bound','Succeeded'].includes(value)?'good':['Pending','Running'].includes(value)?'warn':'bad';td.append(element('span',value,'resource-status-chip '+tone))}else td.append(element('span',value));row.append(td)}row.onclick=e=>{if(!e.target.closest('button'))showResource(resourceTab,p)};tbody.append(row)}table.append(tbody);content.append(table);
 }
 if(nameCursor&&$('column-podName')){$('column-podName').focus({preventScroll:true});$('column-podName').setSelectionRange(...nameCursor);}
 if(resourceSelected){const selected=resourceSelected.cluster===selectedCluster&&sets[resourceSelected.type].find(p=>resourceKey(p)===resourceSelected.key);if(!selected){resourceSelected=null;$('resource-detail').hidden=true}else renderResourceDetail(selected);}
}
for(const [type] of resourceTypes)$('resource-tab-'+type).onclick=()=>{resourceTab=type;resourceSelected=null;$('resource-detail').hidden=true;renderResources(true)};
const resourceTabs=resourceTypes.map(t=>t[0]);for(const type of resourceTabs)$('resource-tab-'+type).onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const index=e.key==='Home'?0:e.key==='End'?resourceTabs.length-1:(resourceTabs.indexOf(type)+(e.key==='ArrowRight'?1:resourceTabs.length-1))%resourceTabs.length;const b=$('resource-tab-'+resourceTabs[index]);b.click();b.focus()};
$('resource-detail-close').onclick=()=>{resourceSelected=null;$('resource-detail').hidden=true;renderResources(true)};
$('resource-namespace').onchange=()=>{resourceFilter().namespace=$('resource-namespace').value;renderResources(true)};
$('resource-search').oninput=()=>{resourceFilter().search=$('resource-search').value;renderResources(true)};
$('resource-table-view').onclick=()=>{resourceView='table';renderResources(true)};$('resource-map-view').onclick=()=>{resourceView='map';renderResources(true)};
$('resources-refresh').onclick=async()=>{const b=$('resources-refresh');b.disabled=true;try{await Promise.allSettled([refreshGraph(),refreshPVCs(),refreshSecrets(),refreshExtraResources()]);renderResources(true)}finally{b.disabled=false}};
$('cluster-select').addEventListener('change',()=>{resourceSelected=null;$('resource-detail').hidden=true;renderResources(true)});
setInterval(()=>{if(!document.hidden)renderResources()},2000);renderResources();

$('cluster-select').addEventListener('change',refreshExtraResources);setInterval(()=>{if(!document.hidden)refreshExtraResources()},15000);refreshExtraResources();

async function openResourceYaml(type,item,download=false){
 const cluster=selectedCluster;
 labOpen('YAML · '+item.name,'Кластер '+cluster+' · '+item.namespace+'. Текущий объект Kubernetes, включая status и служебные поля; это не очищенный шаблон для переноса.'+(type==='secrets'?' Secret содержит значения в base64 — это не шифрование.':''),null);
 const output=element('pre','Загрузка YAML…','resource-yaml-output');$('lab-extra').append(output);
 try{const data=await api('resource-yaml',{type,name:item.name,namespace:item.namespace});if(cluster!==selectedCluster||!output.isConnected)return;output.textContent=data.yaml;
 const save=()=>{const blob=new Blob([data.yaml],{type:'application/yaml;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=data.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)};
 const controls=element('div',undefined,'resource-yaml-actions');controls.append(resourceButton('Редактировать YAML',()=>editResourceYaml(type,item,data.yaml)),resourceButton('↓ Скачать YAML',save));$('lab-extra').prepend(controls);if(download)save();
 }catch(e){if(output.isConnected)output.textContent='Не удалось получить YAML: '+e.message}
}

function editResourceYaml(type,item,source){
 labOpen('Редактировать YAML · '+item.name,'Проверьте изменения перед применением. Изменение spec может перезапустить Pod. Поле status не редактируется; имя, namespace, uid и resourceVersion должны сохраниться.',null);
 const editor=document.createElement('textarea');editor.className='resource-yaml-editor';editor.value=source;editor.spellcheck=false;editor.setAttribute('aria-label','Редактор YAML');
 const preview=element('div',undefined,'resource-yaml-diff');const message=element('p','','lab-note');message.setAttribute('role','status');const actions=element('div',undefined,'resource-yaml-actions');let token=null;
 const apply=resourceButton('Применить изменения',async()=>{try{sameCluster();apply.disabled=true;await api('yaml-apply',{token,confirmed:true});token=null;message.textContent='Изменения применены.';await Promise.allSettled([refreshExtraResources(),refreshGraph(),refreshPVCs(),refreshSecrets()])}catch(e){token=null;message.textContent=e.message}finally{apply.disabled=true}},'button primary');apply.disabled=true;
 const check=resourceButton('Проверить и показать изменения',async()=>{try{sameCluster();token=null;apply.disabled=true;check.disabled=true;const text=editor.value;message.textContent='Проверка Kubernetes…';const result=await api('yaml-preview',{type,name:item.name,namespace:item.namespace,yaml:text});if(!editor.isConnected||labCluster!==selectedCluster)return;if(editor.value!==text){message.textContent='Текст изменён. Повторите проверку.';return}preview.replaceChildren();for(const line of result.diff.split('\n'))preview.append(element('div',line||' ',line.startsWith('+')?'yaml-added':line.startsWith('-')?'yaml-removed':''));token=result.token;apply.disabled=!result.changed;message.textContent=result.changed?'Проверка пройдена. Просмотрите изменения и нажмите «Применить изменения».':'Изменений нет.'}catch(e){message.textContent=e.message}finally{check.disabled=false}});
 editor.oninput=()=>{token=null;apply.disabled=true;preview.replaceChildren();message.textContent='Текст изменён. Требуется повторная проверка.'};actions.append(check,apply);$('lab-extra').append(editor,actions,message,preview);
}
