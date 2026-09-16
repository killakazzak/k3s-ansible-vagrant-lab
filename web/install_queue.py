"""FIFO waiting installs. Caller holds the server lock for every mutation."""
import copy
INSTALL_ACTIONS={'app_deploy','template_deploy'}
class InstallQueue:
 def __init__(self):self.items=[]
 def add(self,job,payload,active):
  if active and active['state']=='running' and active['action'] not in INSTALL_ACTIONS:raise ValueError('Во время изменения кластера установка приложений недоступна')
  if len(self.items)>=20:raise ValueError('В очереди уже 20 установок')
  occupied={(j['cluster'],ns,name) for j,_ in self.items for ns,name in j.get('targets',[])}
  if active and active['state']=='running':occupied.update((active['cluster'],ns,name) for ns,name in active.get('targets',[]))
  if any((job['cluster'],ns,name) in occupied for ns,name in job['targets']):raise ValueError('Это приложение уже устанавливается или находится в очереди')
  self.items.append((job,copy.deepcopy(payload)))
 def pop(self):return self.items.pop(0) if self.items else None
 def cancel(self,ident):
  for i,(job,_) in enumerate(self.items):
   if job['id']==ident:return self.items.pop(i)[0]
  raise ValueError('Установка уже началась или отсутствует в очереди')
 def summary(self):return [{k:j[k] for k in ('id','cluster','action','state','title','queued_at')} for j,_ in self.items]
