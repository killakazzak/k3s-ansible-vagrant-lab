import sys, unittest, json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'web'))
import lab_apps, remote_clusters
class ResourceCrudTests(unittest.TestCase):
 def test_create_dry_run_and_identity(self):
  app=lab_apps.Apps('/tmp');obj=dict(apiVersion='v1',kind='Secret',metadata=dict(name='test',namespace='dev'),stringData=dict(password='test-only'))
  with patch.object(app,'kubectl',return_value=json.dumps(obj)) as cmd:
   candidate,diff=app.yaml_preview(dict(type='secrets',operation='create',yaml=json.dumps(obj)))
   self.assertEqual(cmd.call_args.args[0][0:2],['create','--dry-run=server']);self.assertEqual(candidate,obj)
   with self.assertRaises(ValueError):app.yaml_create_preview(dict(type='configmaps'),obj)
   obj['metadata']['uid']='old'
   with self.assertRaises(ValueError):app.yaml_create_preview(dict(type='secrets'),obj)
 def test_delete_requires_identity_and_atomic_preconditions(self):
  app=lab_apps.Apps('/tmp');obj=dict(apiVersion='v1',kind='Secret',metadata=dict(name='test',namespace='dev',uid='uid1',resourceVersion='5'))
  data=dict(type='secrets',name='test',namespace='dev')
  with patch.object(app,'yaml_edit_object',return_value=obj),patch.object(app,'kubectl') as cmd:
   identity=app.resource_delete(data);cmd.assert_not_called()
   with self.assertRaises(ValueError):app.resource_delete(dict(data,confirmed=True,confirmation='test',uid='old',resourceVersion='5'))
   with self.assertRaises(ValueError):app.resource_delete(dict(data,confirmed=True,confirmation='wrong',uid='uid1',resourceVersion='5'))
   app.resource_delete(dict(data,confirmed=True,confirmation='test',uid='uid1',resourceVersion='5'))
   self.assertEqual(cmd.call_args.args[0],['delete','--raw','/api/v1/namespaces/dev/secrets/test','-f','-'])
   self.assertEqual(cmd.call_args.args[1]['preconditions'],dict(uid='uid1',resourceVersion='5'))
 def test_remote_permits_resource_crud(self):
  for path in ['/api/yaml-preview','/api/yaml-apply','/api/resource-delete']:remote_clusters.permit(path,{})
