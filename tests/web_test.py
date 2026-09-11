import importlib.util
import json
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('console', Path(__file__).resolve().parents[1] / 'web/server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class ConsoleTests(unittest.TestCase):
    def setUp(self):
        app.JOB = None
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
    def request(self, path='/api/job', payload=None, token=True, headers=None):
        hdr = {'X-Lab-Token': app.TOKEN} if token else {}
        hdr.update(headers or {})
        req = Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps(payload).encode() if payload is not None else None, headers=hdr)
        try:
            with urlopen(req) as response: return response.status, response.read()
        except HTTPError as e: return e.code, e.read()
    def test_kubeconfig_download_is_authenticated_and_scoped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'ROOT', Path(directory)):
            root = Path(directory)
            (root / 'kubeconfig').write_bytes(b'default-test-config')
            profile = root / '.clusters/k8s-cluster2'
            profile.mkdir(parents=True)
            (profile / 'kubeconfig').write_bytes(b'second-test-config')
            self.assertEqual(self.request('/api/kubeconfig', token=False)[0], 401)
            self.assertEqual(self.request('/api/kubeconfig'), (200, b'default-test-config'))
            self.assertEqual(self.request('/api/kubeconfig', headers={'X-Lab-Cluster':'k8s-cluster2'}), (200, b'second-test-config'))
            (profile / 'kubeconfig').unlink()
            code, body = self.request('/api/kubeconfig', headers={'X-Lab-Cluster':'k8s-cluster2'})
            self.assertEqual(code, 409)
            self.assertIn('пока не готов', json.loads(body)['error'])
            (profile / 'kubeconfig').symlink_to(root / 'kubeconfig')
            self.assertEqual(self.request('/api/kubeconfig', headers={'X-Lab-Cluster':'k8s-cluster2'})[0],409)
            req=Request(f'http://127.0.0.1:{self.port}/api/kubeconfig',headers={'X-Lab-Token':app.TOKEN})
            with urlopen(req) as response:
                self.assertEqual(response.headers['Content-Disposition'], 'attachment; filename="k8s-cluster1-kubeconfig.yaml"')
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
        app.CONTEXT.root = app.ROOT

    def test_new_cluster_requires_final_confirmation(self):
        with patch.object(app, 'new_cluster') as create:
            code, _ = self.request('/api/clusters', {'name':'lab','network':'192.168.60.0/24'})
            self.assertEqual(code,400)
            create.assert_not_called()

    def test_confirmed_cluster_starts_one_scoped_job(self):
        called=threading.Event()
        with patch.object(app, 'new_cluster', return_value={'name':'k8s-cluster4'}) as create, patch.object(app, 'execute', side_effect=lambda *args: called.set()):
            code, _ = self.request('/api/clusters', {'name':'','network':'192.168.60.0/24','confirmed':True,'params':{'masters':1}})
            self.assertEqual(code,201)
            self.assertTrue(called.wait(2))
            create.assert_called_once()
            self.assertEqual(app.JOB['cluster'],'k8s-cluster4')
            self.assertEqual(app.JOB['action'],'create')

    def test_password_endpoint_requires_auth(self):
        with patch.object(app, 'credentials') as fetch:
            self.assertEqual(self.request('/api/credentials/traefik', token=False)[0], 401)
            fetch.assert_not_called()
    def test_password_decoding(self):
        import base64
        encoded = lambda text: base64.b64encode(text.encode()).decode()
        with patch.object(app, 'capture', return_value=json.dumps({'data': {'username': encoded('admin'), 'password': encoded('test-only')}})):
            self.assertEqual(app.credentials('traefik'), {'username': 'admin', 'password': 'test-only'})
    def test_password_errors_do_not_leak_output(self):
        with patch.object(app, 'capture', side_effect=RuntimeError('secret-value')):
            code, body = self.request('/api/credentials/rancher')
            self.assertEqual(code, 500)
            self.assertNotIn(b'secret-value', body)
    def test_requires_token(self):
        self.assertEqual(self.request(token=False)[0], 401)
    def test_rejects_foreign_origin_and_host(self):
        self.assertEqual(self.request(headers={'Origin':'https://example.com'})[0],403)
        self.assertEqual(self.request(headers={'Host':'attacker.test'})[0],403)
    def test_destructive_confirmation_and_allowlist(self):
        for payload in [{'action':'destroy','confirmed':True},{'action':'shell','confirmed':True},{'action':'verify','confirmed':False}]:
            self.assertEqual(self.request('/api/action',payload)[0],400)
        self.assertIsNone(app.JOB)
    def test_one_job_at_a_time(self):
        app.JOB={'state':'running'}
        self.assertEqual(self.request('/api/action',{'action':'verify','confirmed':True})[0],409)
    def test_dispatches_allowed_job_without_real_mutation(self):
        called=threading.Event()
        def fake(job,payload): called.set()
        with patch.object(app,'execute',side_effect=fake):
            self.assertEqual(self.request('/api/action',{'action':'verify','confirmed':True})[0],202)
            self.assertTrue(called.wait(2))
        self.assertEqual(app.JOB['action'],'verify')
    def test_static_no_path_traversal(self):
        self.assertEqual(self.request('/../ansible/inventory.yml')[0],404)

class ClusterIsolationTests(unittest.TestCase):
    def test_profiles_and_networks_are_isolated(self):
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ['ansible', 'scripts', 'web']:
                shutil.copytree(app.ROOT / folder, root / folder)
            for name in ['Vagrantfile','cluster.sh','deploy.sh','kubectl.sh','ansible.cfg']:
                shutil.copy2(app.ROOT / name, root / name)
            (root / 'vendor').mkdir()
            original = (root / 'ansible/inventory.yml').read_bytes()
            vm_id = root / '.vagrant/machines/existing-master/virtualbox/id'
            vm_id.parent.mkdir(parents=True)
            vm_id.write_text('existing-cluster-vm')
            with patch.object(app, 'ROOT', root):
                app.CONTEXT.root = root
                current = app.config()['network']
                candidates = ['192.168.60.0/24','192.168.61.0/24','192.168.62.0/24']
                net = next(n for n in candidates if n != current)
                self.assertEqual(app.next_cluster_name(), 'k8s-cluster2')
                params={'masters':1,'workers':3,'server_cpu':4,'server_ram':4096,'server_disk':25,'workers_cpu':2,'workers_ram':4096,'workers_disk':25}
                with self.assertRaises(ValueError):
                    app.new_cluster('invalid-plan', net, dict(params,server_disk=24))
                self.assertFalse((root / '.clusters/invalid-plan').exists())
                self.assertFalse(list((root / '.clusters').glob('.new-*')))
                app.new_cluster('', net, params)
                self.assertEqual(app.cluster_names(), ['default','k8s-cluster2'])
                self.assertEqual((root / 'ansible/inventory.yml').read_bytes(), original)
                profile = app.cluster_root('k8s-cluster2')
                self.assertFalse((profile / '.vagrant').exists())
                self.assertEqual(vm_id.read_text(), 'existing-cluster-vm')
                import subprocess
                plan = subprocess.run(['ruby', '-rjson', '-e', "require File.expand_path('scripts/web-action',Dir.pwd); m=WebAction.new(Dir.pwd,[]); p={'masters'=>1,'workers'=>2,'server_cpu'=>4,'server_ram'=>4096,'server_disk'=>64,'workers_cpu'=>2,'workers_ram'=>4096,'workers_disk'=>64,'network_mode'=>'existing'}; puts JSON.generate(m.creation_plan(p)[0])"], cwd=profile, capture_output=True, text=True)
                self.assertEqual(plan.returncode, 0, plan.stderr)
                self.assertIn('k8s-cluster2-master1', plan.stdout)
                self.assertFalse((profile / 'kubeconfig').exists())
                app.CONTEXT.root = profile
                result = app.config()
                self.assertEqual(result['network'], net)
                self.assertEqual(len(result['nodes']),4)
                self.assertTrue(all(n['disk']==25 for n in result['nodes']))
                self.assertEqual(app.next_cluster_name(), 'k8s-cluster3')
                self.assertEqual(result['node_prefix'], 'k8s-cluster2')
                self.assertTrue(all(n['name'].startswith('k8s-cluster2-') for n in result['nodes']))
                with self.assertRaises(ValueError): app.new_cluster('lab3', net)
                with self.assertRaises(ValueError): app.cluster_root('../escape')
                env = app.cluster_env(profile)
                self.assertEqual(env['VAGRANT_DOTFILE_PATH'], str(profile / '.vagrant'))
                # Remove all inventory entries and VM state, then reuse number 1.
                empty = 'all:\n  children:\n    server:\n      hosts: {}\n    workers:\n      hosts: {}\n'
                (root / 'ansible/inventory.yml').write_text(empty)
                (profile / 'ansible/inventory.yml').write_text(empty)
                vm_id.unlink()
                self.assertEqual(app.next_cluster_name(), 'k8s-cluster1')
                app.new_cluster('', net, params)
                first = root / '.clusters/k8s-cluster1'
                self.assertEqual(app.next_cluster_name(), 'k8s-cluster2')
                (first / 'ansible/inventory.yml').write_text(empty)
                (first / 'saved-history.txt').write_text('keep')
                app.new_cluster('', net, params)
                self.assertTrue(first.exists())
                backups = list((root / '.cache/archived-profiles').glob('k8s-cluster1-*/profile/saved-history.txt'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(), 'keep')
            app.CONTEXT.root = app.ROOT
    def test_deleted_vms_are_not_reported_as_cluster(self):
        cfg = {'nodes':[{'name':'one','vagrant_id':'one'}]}
        with patch.object(app, 'config', return_value=cfg), patch.object(app, 'capture', return_value='0,one,state,not_created') as run:
            state = app.status()
            self.assertFalse(state['exists'])
            self.assertFalse(state['reachable'])
            self.assertEqual(state['nodes'][0]['state'], 'Absent')
            self.assertEqual(run.call_count, 1)

class RepeatedLaunchTests(unittest.TestCase):
    def test_reuses_existing_server_and_keeps_private_url(self):
        import tempfile, shutil, subprocess, sys, os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'web').mkdir()
            shutil.copy(Path(app.__file__), root / 'web/server.py')
            command = [sys.executable, str(root / 'web/server.py'), '--port', '0']
            first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(first.stdout.readline().strip(), '')
                initial = first.stdout.readline().strip().split(' → ')[1]
                again = subprocess.run(command, capture_output=True, text=True, timeout=5)
                self.assertEqual(again.returncode, 0)
                self.assertIn(initial, again.stdout)
                self.assertEqual(os.stat(root / '.cache/web.lock').st_mode & 0o777, 0o600)
            finally:
                first.terminate()
                first.communicate(timeout=5)

if __name__ == '__main__': unittest.main()

class TimingTests(unittest.TestCase):
    def test_history_survives_reload_and_separates_sizes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'ROOT', Path(directory)):
            key = app.timing_key({'action':'create', 'params':{'masters':1, 'workers':2}})
            self.assertEqual(app.timing_samples(key), [])
            for seconds in [100, 200, 300, 400, 500, 600]:
                app.record_duration(key, seconds)
            self.assertEqual(app.timing_samples(key), [200, 300, 400, 500, 600])
            self.assertEqual(app.statistics.median(app.timing_samples(key)), 400)
            other = app.timing_key({'action':'create', 'params':{'masters':3, 'workers':2}})
            self.assertEqual(app.timing_samples(other), [])
            (Path(directory) / '.cache/durations.json').write_text('broken')
            self.assertEqual(app.timing_samples(key), [])

class VisibleClusterTests(unittest.TestCase):
    def test_empty_profiles_hidden_but_pending_creation_visible(self):
        original = app.active_root()
        with patch.object(app, 'cluster_names', return_value=['default','k8s-cluster2']), patch.object(app, 'cluster_root', side_effect=lambda n: n), patch.object(app, 'config', side_effect=lambda: {'nodes': [] if app.active_root() == 'default' else [{'name':'master'}]}):
            self.assertEqual(app.visible_clusters(), ['k8s-cluster2'])
        self.assertEqual(app.active_root(), original)
        with patch.object(app, 'cluster_names', return_value=['default']), patch.object(app, 'config', return_value={'nodes':[]}):
            self.assertEqual(app.visible_clusters(), [])

class NetworkReservationTests(unittest.TestCase):
    def test_deleted_network_reusable_but_live_or_partial_profile_reserved(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = {'nodes': [], 'network': '192.168.60.0/24'}
            network = app.ipaddress.ip_network(cfg['network'])
            previous = app.active_root()
            with patch.object(app, 'cluster_names', return_value=['k8s-cluster3']), patch.object(app, 'cluster_root', return_value=root), patch.object(app, 'config', return_value=cfg):
                app.check_cluster_network(network)
                self.assertEqual(app.active_root(), previous)
                cfg['nodes'] = [{'name':'master'}]
                with self.assertRaisesRegex(ValueError, 'k8s-cluster3'):
                    app.check_cluster_network(network)
                app.check_cluster_network(network, exclude='k8s-cluster3')
                cfg['nodes'] = []
                vm = root / '.vagrant/machines/master/virtualbox/id'
                vm.parent.mkdir(parents=True)
                vm.write_text('test-vm')
                with self.assertRaises(ValueError):
                    app.check_cluster_network(network)
                self.assertEqual(app.active_root(), previous)
