'use strict';
let graphData=null,graphCluster=null,graphLoading=false,graphSignature='';
let graphPaused=false;
const graphReducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
function syncGraphMotion(){const paused=graphPaused||graphReducedMotion.matches||document.hidden;const svg=$('cluster-graph');svg.classList.toggle('motion-paused',paused);if(paused)svg.pauseAnimations();else svg.unpauseAnimations();$('graph-motion').textContent=graphPaused?'▶ Анимация':'Ⅱ Пауза';$('graph-motion').setAttribute('aria-pressed',String(graphPaused));}
const svgNS='http://www.w3.org/2000/svg';
function svgEl(tag,attrs={},text){const el=document.createElementNS(svgNS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;return el;}
function drawGraph(){
 const svg=$('cluster-graph');svg.replaceChildren();svg.setCurrentTime(0);
 if(!graphData)return;
 const route=graphData.routes.find(r=>r.id===$('graph-route').value);
 const svc=route&&graphData.services.find(s=>s.id===route.service);
 const endpoints=route?graphData.endpoints.filter(e=>e.service===route.service):[];
 const podIds=new Set(endpoints.map(e=>e.pod).filter(Boolean));
 const pods=graphData.pods.filter(p=>podIds.has(p.id));
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
  const show=()=>{$('graph-detail').textContent=detail;svg.querySelectorAll('.selected').forEach(e=>e.classList.remove('selected'));g.classList.add('selected');};
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
 card('svc',2,100,svc?svc.name:route.internal||'Service не найден',svc?svc.type+' · '+svc.ip:route.internal?'Внутренний сервис Traefik':'Нет backend Service','service',svc?null:!!route.internal,svc?`Service ${svc.id} · ${svc.type} · ${svc.external||svc.ip} · Порты: ${svc.ports.map(p=>p.port+' → '+p.targetPort).join(', ')} · Endpoints: ${endpoints.length}`:route.internal?'Внутренний обработчик Traefik '+route.internal+', не Kubernetes Service.':'Backend Service не найден или тип backend не поддерживается.');
 link('ingress','svc',false,!!svc||!!route.internal);
 pods.forEach((p,i)=>{const ep=endpoints.filter(e=>e.pod===p.id);const ready=ep.some(e=>e.ready!==false);card('pod:'+p.id,3,60+i*105,p.name,p.phase+' · '+(p.ready?'Ready':'NotReady'),'pod',p.ready,`Pod ${p.id} · IP ${p.ip||'не назначен'} · ${p.phase} · Узел ${p.node||'ещё не назначен'} · Endpoint: ${ready?'доступен или ready не указан':'not ready'}`);link('svc','pod:'+p.id,false,ready);link('pod:'+p.id,'node:'+p.node,true)});
 if(!pods.length){card('no-pod',3,100,route.internal?'Внутри Traefik':'Нет Pod endpoints',svc&&svc.external?svc.external:'Нажмите для подробностей','pod',null,endpoints.length?'У EndpointSlice нет targetRef на известный Pod. Адреса: '+endpoints.flatMap(e=>e.addresses).join(', '):route.internal?'Этот маршрут обслуживает сам контроллер Traefik.':'У Service пока нет EndpointSlice с привязкой к Pod.');link('svc','no-pod',false,false)}
 syncGraphMotion();
}
async function refreshGraph(){
 if(graphLoading)return;graphLoading=true;
 const cluster=selectedCluster;
 if(graphCluster!==cluster){graphData=null;graphSignature='';$('cluster-graph').replaceChildren();$('graph-route').replaceChildren();$('graph-detail').textContent='Загружаем карту выбранного кластера…';}
 $('graph-status').textContent='Получаем данные Kubernetes…';
 try{const data=await api('topology');if(cluster!==selectedCluster)return;const old=$('graph-route').value;const signature=JSON.stringify([cluster,data.nodes,data.services,data.pods,data.routes,data.endpoints]);const changed=signature!==graphSignature;graphSignature=signature;graphCluster=cluster;graphData=data;$('graph-route').replaceChildren();
 for(const r of data.routes){const o=document.createElement('option');o.value=r.id;o.textContent=`${r.host}${r.path} · ${r.namespace}/${r.name}`;$('graph-route').append(o)}
 if(data.routes.some(r=>r.id===old))$('graph-route').value=old;
 else {const demo=data.routes.find(r=>r.host.startsWith('nginx.'));if(demo)$('graph-route').value=demo.id;}
 $('graph-status').textContent=(data.warning?data.warning+' · ':'')+'Обновлено '+new Date(data.updated*1000).toLocaleTimeString();if(changed){$('graph-detail').textContent='Нажмите на Ingress, Service, Pod или узел — здесь появятся подробности.';drawGraph();}
 }catch(e){if(cluster===selectedCluster){graphData=null;graphSignature='';$('cluster-graph').replaceChildren();$('graph-route').replaceChildren();$('graph-status').textContent=e.message;$('graph-detail').textContent='Карта недоступна. Проверьте состояние выбранного кластера.';}}
 finally{graphLoading=false;if(cluster!==selectedCluster)refreshGraph();}
}
$('graph-route').onchange=drawGraph;$('graph-refresh').onclick=refreshGraph;$('cluster-select').addEventListener('change',refreshGraph);
setInterval(()=>{if(!document.hidden)refreshGraph()},15000);refreshGraph();

$('graph-motion').onclick=()=>{graphPaused=!graphPaused;syncGraphMotion()};
graphReducedMotion.addEventListener('change',syncGraphMotion);
document.addEventListener('visibilitychange',syncGraphMotion);
