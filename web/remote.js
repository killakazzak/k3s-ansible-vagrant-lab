"use strict";
const connectRemote=element('button','↗ Подключить кластер','button secondary');
connectRemote.id='connect-remote';connectRemote.type='button';$('new-cluster').after(connectRemote);
const disconnectRemote=element('button','Удалить подключение','button secondary');disconnectRemote.type='button';disconnectRemote.hidden=true;connectRemote.after(disconnectRemote);
const remoteNote=element('p','Удалённый кластер · Только просмотр ресурсов, YAML и логов. Управление узлами и приложениями отключено.','panelnote');remoteNote.hidden=true;$('error').before(remoteNote);
function renderRemoteProfile(){
 const remote=!!state?.external;document.body.classList.toggle('remote-profile',remote);disconnectRemote.hidden=!remote;remoteNote.hidden=!remote;
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
