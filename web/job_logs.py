"""Private, complete operation logs independent of the UI tail buffer."""
import json,os,re,time
from pathlib import Path
ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
def paths(root,ident):
 if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{16}',ident):raise ValueError('Некорректный номер операции')
 folder=Path(root)/'.cache/operation-logs'
 return folder/ (ident+'.log'),folder/(ident+'.json')
def save(root,job,line=None,begin=False):
 try:
  log,meta=paths(root,job['id']);log.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  if begin:
   with os.fdopen(os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:f.write(job.get('log',''))
  if line is not None:
   with log.open('a') as f:f.write(line)
  if begin or line is None:
   data={k:v for k,v in job.items() if k!='log'};temp=meta.with_suffix('.tmp')
   with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:json.dump(data,f,ensure_ascii=False)
   os.replace(temp,meta)
 except OSError:
  job['log_warning']='Полный журнал не удалось сохранить на диск; доступен только буфер интерфейса.'
def latest(root):
 folder=Path(root)/'.cache/operation-logs'
 for meta in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
  try:
   job=json.loads(meta.read_text());log,_=paths(root,job['id'])
   with log.open('rb') as f:f.seek(max(0,log.stat().st_size-600000));job['log']=f.read().decode('utf-8',errors='replace')[-150000:]
   if job['state']=='running':job.update(state='failed',log=job['log']+'\nВеб-сервер перезапущен; итог операции неизвестен. Проверьте состояние кластера.\n')
   return job
  except (OSError,ValueError,KeyError):continue
 return None
def export(root,ident,current=None):
 log,meta=paths(root,ident)
 if current and current['id']==ident:
  job=dict(current);text=log.read_text() if log.exists() and not job.get('log_warning') else job.get('log','');partial=not log.exists() or bool(job.get('log_warning'))
 else:
  if not meta.exists():raise ValueError('Журнал операции не найден')
  job=json.loads(meta.read_text());text=log.read_text();partial=False
 clean=lambda v:re.sub(r'[^a-zA-Z0-9_.-]','-',str(v))
 stamp=time.strftime('%Y-%m-%d_%H-%M-%S',time.gmtime(job['started']))
 duration=round(job.get('finished',time.time())-job['started'])
 header=f"K3S LAB — журнал операции\nКластер: {job.get('cluster','default')}\nОперация: {job['action']}\nСостояние: {job['state']}\nДлительность: {duration} с\nНачало (UTC): {stamp}\n"
 if partial or job.get('log_partial'):header+='Внимание: сохранён доступный буфер; начало журнала могло быть обрезано.\n'
 return dict(filename=f"{clean(job.get('cluster','default'))}-{clean(job['action'])}-{stamp}.log",text=header+'\n'+ANSI.sub('',text))
