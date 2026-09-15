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
 function apply(pods,filter){
  const items=pods.filter(p=>(!filter.podStatus||statuses(p).includes(filter.podStatus))&&(!filter.podContainer||containers(p).includes(filter.podContainer))&&(!filter.podNode||node(p)===filter.podNode));
  const value=p=>filter.podSort==='status'?status(p):filter.podSort==='container'?containers(p).join(', '):filter.podSort==='node'?node(p):p.name;
  const direction=filter.podDirection==='desc'?-1:1;
  return items.sort((a,b)=>direction*(compare(value(a),value(b))||compare(a.namespace+'/'+a.name,b.namespace+'/'+b.name)));
 }
 return {containers,status,statuses,node,apply,compare};
})();
if(typeof module!=='undefined')module.exports=PodFilters;
