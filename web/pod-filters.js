/* Shared pure selectors for the Pod table and placement map. */
const PodFilters = (() => {
 const compare=(a,b)=>String(a||'').localeCompare(String(b||''),'ru',{numeric:true,sensitivity:'base'});
 const containers=p=>[...new Set((p.containers||[]).map(c=>c.name).filter(Boolean))].sort(compare);
 const status=p=>{
  const states=p.statuses||[];
  const waiting=states.map(c=>c.state?.waiting?.reason).filter(Boolean);
  const error=waiting.find(s=>!['ContainerCreating','PodInitializing'].includes(s));
  if(error)return error;
  const failed=states.find(c=>c.state?.terminated?.exitCode>0);
  if(failed)return failed.state.terminated.reason||'Error';
  if(waiting.length)return waiting[0];
  return p.ready?'Ready':p.phase||'Unknown';
 };
 const statuses=p=>[...new Set([status(p),p.phase||'Unknown',...(p.statuses||[]).map(c=>c.state?.waiting?.reason).filter(Boolean)])];
 const node=p=>p.node||'Не назначен';
 const usage=(p,key,container='')=>{
  const selected=(p.containers||[]).filter(c=>!container||c.name===container);
  if(!selected.length||selected.some(c=>!Number.isFinite(c.usage?.[key])))return null;
  return selected.reduce((sum,c)=>sum+c.usage[key],0);
 };
 function apply(pods,filter){
  const nameQuery=(filter.podName||'').trim().toLowerCase();
  const items=pods.filter(p=>String(p.name||'').toLowerCase().includes(nameQuery)&&(!filter.podStatus||statuses(p).includes(filter.podStatus))&&(!filter.podContainer||containers(p).includes(filter.podContainer))&&(!filter.podNode||node(p)===filter.podNode));
  const value=p=>filter.podSort==='status'?status(p):filter.podSort==='container'?containers(p).join(', '):filter.podSort==='node'?node(p):p.name;
  const direction=filter.podDirection==='desc'?-1:1;
  if(['cpu','memory'].includes(filter.podSort))return items.sort((a,b)=>{const x=usage(a,filter.podSort,filter.podContainer),y=usage(b,filter.podSort,filter.podContainer);return x===null?(y===null?compare(a.name,b.name):1):y===null?-1:direction*(x-y)||compare(a.name,b.name)});
  return items.sort((a,b)=>direction*(compare(value(a),value(b))||compare(a.namespace+'/'+a.name,b.namespace+'/'+b.name)));
 }
 return {containers,status,statuses,node,apply,compare,usage};
})();
if(typeof module!=='undefined')module.exports=PodFilters;
