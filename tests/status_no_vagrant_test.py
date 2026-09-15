import ast,json,re,tempfile
from pathlib import Path
source=Path(__file__).resolve().parents[1]/'web/server.py'
function=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='status')
with tempfile.TemporaryDirectory() as d:
 root=Path(d);id_path=root/'.vagrant/machines/worker1/virtualbox/id';id_path.parent.mkdir(parents=True);id_path.write_text('12345678-1234-1234-1234-123456789012')
 calls=[]
 def capture(args,timeout):
  calls.append(args)
  assert args[0]!='vagrant'
  if args[0]=='VBoxManage':return 'VMState="running"\n'
  return json.dumps({'items':[]})
 scope=dict(config=lambda:{'provider':'virtualbox','nodes':[{'name':'worker1','vagrant_id':'worker1'}]},verify_result=lambda root:None,active_root=lambda:root,capture=capture,re=re,json=json)
 exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),scope)
 assert scope['status']()['nodes'][0]['vm_state']=='running'
 id_path.unlink();calls.clear()
 assert scope['status']()['exists'] is False
 assert calls==[]
print('Status polling reads VirtualBox; absent VM makes no external calls; Vagrant never invoked')
