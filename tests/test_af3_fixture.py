"""Qualification-only AF3 provisioner; no native Kodi or protected-root IO."""
from contextlib import contextmanager, ExitStack
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

from tools import bm023a_adapter_support as support
from tools import bm_test_app as host
from resources.lib import frozen_install as fi
from resources.lib.addon_zip import publish_package


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'portable_data'
        self.addon = self.home / 'addons/script.build.manager'
        self.driver = self.home / 'addons/script.build.manager.bm023a_driver'
        for path in (self.addon, self.driver, self.home / 'userdata'):
            path.mkdir(parents=True, exist_ok=True)
        self.packages = {}
        self.nodes = []
        for aid, (version, digest, size) in support._AF3_PACKAGES.items():
            root = 'resource.font.robotcjksc' if aid == 'resource.font.robotocjksc' else aid
            xml = f'<addon id="{aid}" version="{version}"/>' .encode()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                z.writestr(root + '/addon.xml', xml)
                z.writestr(root + '/data.txt', 'synthetic fixture')
            self.packages[aid] = (buf.getvalue(), xml)
            self.nodes.append(SimpleNamespace(addon_id=aid, version=version))
        self.backend = Mock()
        self.details = {}
        self.installs = []
        self.fail_at = None
        self.backend.get_addon_details.side_effect = lambda aid: self.details.get(aid)
        def install(data, aid, target, version):
            self.installs.append(aid)
            if len(self.installs) == self.fail_at:
                raise RuntimeError('injected install failure')
            publish_package(data, aid, self.home / 'addons' / aid, version)
        self.publisher = install
        def registered(aid, version):
            detail = SimpleNamespace(version=version, enabled=False, broken=False)
            self.details[aid] = detail
            return detail
        self.backend._wait_for_exact.side_effect = registered
        from resources.lib.frozen import InstalledMetadata, InstalledOrigin
        self.backend.read_installed_metadata.side_effect = lambda aid: InstalledMetadata(self.packages[aid][1], InstalledOrigin.HOME)
        def enable(aid, enabled):
            self.details[aid].enabled = enabled
            return self.details[aid]
        self.backend.set_addon_enabled.side_effect = enable
        @contextmanager
        def native_binding(inventory):
            yield lambda: True
        self.backend._passive_build_binding.side_effect = native_binding
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(support, '_AF3_HOME', self.home))
        self.inputs = self.patches.enter_context(patch.object(support, '_af3_inputs',
            return_value=(SimpleNamespace(install_order=self.nodes), self.packages)))
        self.sources = self.patches.enter_context(patch.object(support, '_platform_sources', return_value=({}, {})))
        self.platform = self.patches.enter_context(patch.object(support, 'read_platform_check',
            return_value={'ok':True, 'platform_check':{'source':{},'overall':'requirements_verified'}}))
        self.state = self.patches.enter_context(patch.object(support, '_af3_runtime_state', return_value=('unchanged',)))
        self.patches.enter_context(patch.object(fi, 'KodiRuntimeFrozenArtifactBackend', return_value=self.backend))
        self.patches.enter_context(patch('resources.lib.addon_zip.publish_package', side_effect=self.publisher))

    @property
    def journal(self):
        return self.home / 'userdata/bm-af3-fixture-v1.jsonl'

    def run_fixture(self, verify=False):
        return support.run_af3_fixture(self.addon, self.driver, '{}', support._AF3_MANIFEST,
                                       support._AF3_STORE, verify=verify)

    def test_exact_fixture_publishes_once_enables_and_verifies_without_reinstall(self):
        result = self.run_fixture()
        self.assertTrue(result['ok'])
        self.assertEqual(len(self.installs),17)
        self.assertEqual(self.backend.set_addon_enabled.call_count,17)
        self.assertEqual(json.loads(self.journal.read_text().splitlines()[-1])['stage'],'complete')
        self.assertTrue((self.home/'addons/resource.font.robotocjksc/addon.xml').is_file())
        self.assertFalse((self.home/'addons/resource.font.robotcjksc').exists())
        self.assertEqual(self.run_fixture(verify=True)['af3_fixture']['status'],'verified')
        self.assertEqual(len(self.installs),17)
        with self.assertRaises(ValueError): self.run_fixture()
        self.assertEqual(len(self.installs),17)

    def test_input_or_native_requirement_failure_writes_nothing(self):
        for seam in (self.inputs, self.platform, self.sources, self.state):
            with self.subTest(seam=seam):
                seam.side_effect = ValueError('refused')
                with self.assertRaises(ValueError): self.run_fixture()
                self.assertFalse(self.journal.exists())
                self.assertEqual(self.installs,[])
                seam.side_effect = None

    def test_platform_unverified_is_not_substituted_by_authored_graph(self):
        self.platform.return_value = {'ok':False}
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.installs,[])

    def test_all_registered_collisions_refuse_even_exact_existing_version(self):
        aid, (version, _, _) = next(iter(support._AF3_PACKAGES.items()))
        self.details[aid] = SimpleNamespace(version=version,enabled=True,broken=False)
        with self.assertRaises(ValueError): self.run_fixture()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.installs,[])

    def test_directory_and_symlink_collisions_refuse_without_overwrite(self):
        aid = self.nodes[0].addon_id
        target=self.home/'addons'/aid
        target.mkdir();(target/'sentinel').write_text('retain')
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertEqual((target/'sentinel').read_text(),'retain')
        self.assertEqual(self.installs,[])
        (target/'sentinel').unlink();target.rmdir()
        target.symlink_to(self.driver, target_is_directory=True)
        with self.assertRaises(ValueError): self.run_fixture()
        self.assertTrue(target.is_symlink())
        self.assertFalse(self.journal.exists())

    def test_partial_failure_retains_published_package_and_fences_repeat(self):
        self.fail_at=2
        with self.assertRaises(RuntimeError):self.run_fixture()
        self.assertTrue((self.home/'addons'/self.nodes[0].addon_id/'addon.xml').is_file())
        self.assertTrue(self.journal.exists())
        original=self.journal.read_bytes()
        with self.assertRaises(ValueError):self.run_fixture()
        with self.assertRaises(ValueError):self.run_fixture(verify=True)
        self.assertEqual(self.journal.read_bytes(),original)
        self.assertEqual(len(self.installs),2)

    def test_empty_attempt_journal_fences_run_without_any_package(self):
        self.journal.write_bytes(b'')
        with self.assertRaises(FileExistsError):self.run_fixture()
        self.assertEqual(self.installs,[])
        self.assertEqual(self.journal.read_bytes(),b'')

    def test_changed_preservation_state_stops_before_first_package(self):
        self.state.side_effect=[('before',),('changed',)]
        with self.assertRaises(ValueError): self.run_fixture()
        self.assertTrue(self.journal.exists())
        self.assertEqual(self.installs,[])

    def test_build_identity_change_stops_before_first_package(self):
        @contextmanager
        def changed(inventory): yield lambda: False
        self.backend._passive_build_binding.side_effect=changed
        with self.assertRaises(ValueError): self.run_fixture()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.installs,[])

    def test_source_change_during_attempt_retains_evidence_without_next_install(self):
        count=[0]
        def check(*args):
            count[0]+=1
            if count[0] == 4: raise ValueError('source changed')
            return {},{}
        self.sources.side_effect=check
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertEqual(len(self.installs),1)
        self.assertTrue(self.journal.exists())

    def test_unhealthy_or_wrong_version_registered_result_cannot_complete(self):
        self.backend.set_addon_enabled.side_effect=lambda aid,enabled: None
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertNotEqual(json.loads(self.journal.read_text().splitlines()[-1])['stage'],'complete')

    def test_verifier_refuses_changed_declaration_and_tampered_completion_record(self):
        self.run_fixture()
        self.journal.write_text(self.journal.read_text().replace('started','untrusted',1))
        with self.assertRaises(ValueError):self.run_fixture(verify=True)
        self.assertEqual(len(self.installs),17)

    def test_forbidden_target_is_refused_before_sources_or_native_backend(self):
        for target in (Path('/Applications/Kodi.app'), Path('/tmp/other'),
                       Path('/System/Volumes/Data/Applications/Kodi.app')):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    support.run_af3_fixture(target,self.driver,'{}',support._AF3_MANIFEST,support._AF3_STORE)
        self.sources.assert_not_called()
        self.assertEqual(self.installs,[])


class BindingTests(unittest.TestCase):
    def test_fixed_original_inventory_and_graph_passes_existing_validators(self):
        plan,packages=support._af3_inputs(support._AF3_MANIFEST,support._AF3_STORE)
        self.assertEqual(len(packages),17)
        self.assertEqual(sum(len(data) for data,xml in packages.values()),176256381)
        self.assertEqual(len(plan.nodes),22)
        self.assertEqual(sum(len(x.dependency_edges) for x in plan.nodes.values()),45)
        position={n.addon_id:i for i,n in enumerate(plan.install_order)}
        for n in plan.install_order:
            for edge in n.dependency_edges:
                if not edge.optional and edge.addon_id in position:
                    self.assertLess(position[edge.addon_id],position[n.addon_id])

    def test_unapproved_input_paths_refuse_before_read(self):
        with patch.object(support,'_platform_read',side_effect=AssertionError('must not read')):
            for path in ('/Applications/Kodi.app','/tmp/manifest','/System/Volumes/Data/Applications/Kodi.app'):
                with self.assertRaises(ValueError):support._af3_inputs(path,support._AF3_STORE)

    def test_manifest_bytes_mismatch_refuses(self):
        with patch.object(support,'_platform_read',return_value=b'{}'):
            with self.assertRaises(ValueError):support._af3_inputs(support._AF3_MANIFEST,support._AF3_STORE)

    def test_modes_are_explicit_and_http_mutation_requires_git_binding(self):
        for mode in support.AF3_FIXTURE_MODES:
            self.assertEqual(support.parse_adapter_mode([mode]),mode)
            self.assertEqual(support.parse_adapter_mode(['?mode='+mode]),mode)
            with self.assertRaises(host.HelperError):
                host.run_adapter(None,mode=mode,manifest={},manifest_sha256='',rpc={},git_repo=None,timeout=1)
            with self.assertRaises(host.HelperError):
                host.run_adapter(None,mode=mode,manifest={},manifest_sha256='',rpc={},git_repo=Path('/tmp'),timeout=1,rpc_transport='tcp')
        with self.assertRaises(support.AdapterBootstrapError):support.parse_adapter_mode(['af3_fixture','retry'])

    def test_success_projection_requires_fixture_and_complete_native_proof(self):
        with self.assertRaises(host.HelperError):host.project_adapter_result('af3_fixture',{'ok':True,'adapter_mode':'af3_fixture'})
        with self.assertRaises(ValueError):support.project_af3_fixture({'schema':1,'private':'do not expose'})


class EntrypointTests(unittest.TestCase):
    def test_both_modes_use_source_isolation_without_entering_coordinator(self):
        from tests.test_d028_platform_check import Fixture
        from tests.test_d028_platform_check_b1_b2 import execute, rebind_driver
        for mode in support.AF3_FIXTURE_MODES:
            with self.subTest(mode=mode):
                fixture=Fixture(self)
                path=fixture.driver/'adapter_support.py'
                path.write_text(path.read_text()+'''\n
def run_af3_fixture(addon_root, driver_root, binding, manifest_path, artifact_root, *, verify=False):
    return {'ok': True, 'fixture_dispatch_only': True, 'verify_requested': verify}
''')
                rebind_driver(fixture)
                result=execute(fixture,(mode,))
                self.assertTrue(result['ok'],result)
                self.assertTrue(result['fixture_dispatch_only'])
                self.assertEqual(result['adapter_mode'],mode)
                self.assertEqual(result['verify_requested'],mode.endswith('_verify'))
                # The real main/bootstrap ran with an explicitly fake fixture
                # action; a fall-through to ordinary install cannot succeed.
                self.assertNotIn('transaction',result)

    def test_malformed_fixture_mode_refuses_before_result_or_import(self):
        from tests.test_d028_platform_check import Fixture, snapshot
        from tests.test_d028_platform_check_b1_b2 import execute
        fixture=Fixture(self);before=snapshot(fixture.native.root)
        for arguments in (('af3_fixture;install',),('?mode=af3_fixture&x=1',),('af3_fixture','install')):
            with self.assertRaises(SystemExit):execute(fixture,arguments)
            self.assertEqual(snapshot(fixture.native.root),before)


class HostWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_d028_platform_check import PlatformHostTests
        PlatformHostTests.setUpClass();cls.owner=PlatformHostTests;cls.world=PlatformHostTests.world
    @classmethod
    def tearDownClass(cls):cls.owner.tearDownClass()
    def fixture_world(self):
        return self.owner.setup_world(self)

    def test_only_fixture_roots_may_be_added_and_platform_witness_stays_strict(self):
        world,_=self.fixture_world()
        before=host._af3_invocation_snapshot(world.target,world.manifest)
        strict=host._platform_invocation_snapshot(world.target,world.manifest)
        aid=next(iter(support._AF3_PACKAGES))
        (world.target.addons_dir/aid).mkdir()
        self.assertEqual(host._af3_invocation_snapshot(world.target,world.manifest),before)
        self.assertNotEqual(host._platform_invocation_snapshot(world.target,world.manifest),strict)
        (world.target.addons_dir/'unrelated-addon').mkdir()
        self.assertNotEqual(host._af3_invocation_snapshot(world.target,world.manifest),before)

    def test_fixture_source_window_detects_transient_source_restore(self):
        world,_=self.fixture_world();before=host._af3_invocation_snapshot(world.target,world.manifest)
        path=world.target.addon_dir(host.DRIVER_ID)/'default.py'
        data=path.read_bytes();path.write_bytes(data+b'\n');path.write_bytes(data)
        self.assertNotEqual(host._af3_invocation_snapshot(world.target,world.manifest),before)

    def test_fixture_root_symlink_is_refused(self):
        world,_=self.fixture_world();aid=next(iter(support._AF3_PACKAGES))
        (world.target.addons_dir/aid).symlink_to(world.target.addon_dir(host.DRIVER_ID),target_is_directory=True)
        with self.assertRaises(host.HelperError):host._af3_invocation_snapshot(world.target,world.manifest)

    def test_host_dispatch_accepts_only_fresh_bound_complete_fixture_result(self):
        world,result=self.fixture_world()
        result=dict(result,adapter_mode='af3_fixture',af3_fixture={
            'schema':1,'status':'complete','package_count':17,'manifest_sha256':support._AF3_MANIFEST_SHA,
            'preservation_checked':True,'native_health_checked':True})
        world.produce_on_sleep(result)
        report=world.run('af3_fixture',git_repo=self.owner.world.FIXTURE.repo)
        self.assertTrue(report['ok'],report)
        self.assertEqual(world.executed,[{'addonid':host.DRIVER_ID,'params':'af3_fixture','wait':False}])
        self.assertEqual(report['result']['af3_fixture']['status'],'complete')


class AdditionalRefusalTests(unittest.TestCase):
    setUp = FixtureTests.setUp
    journal = FixtureTests.journal
    run_fixture = FixtureTests.run_fixture
    def test_final_member_change_is_not_accepted_as_healthy_source(self):
        self.run_fixture()
        path=self.home/'addons'/self.nodes[0].addon_id/'data.txt'
        path.write_text('changed package implementation')
        with self.assertRaises(ValueError):self.run_fixture(verify=True)
        self.assertEqual(path.read_text(),'changed package implementation')
        self.assertEqual(len(self.installs),17)

    def test_wrong_native_version_leaves_journal_incomplete(self):
        def wrong(aid,version):
            detail=SimpleNamespace(version='0.0.0',enabled=False,broken=False)
            self.details[aid]=detail;return detail
        self.backend._wait_for_exact.side_effect=wrong
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertEqual(len(self.installs),1)
        self.assertEqual(json.loads(self.journal.read_text().splitlines()[-1])['stage'],'installing')

    def test_journal_durability_failure_prevents_package_publication(self):
        with patch.object(support.os,'fsync',side_effect=OSError('synthetic fsync refusal')):
            with self.assertRaises(OSError):self.run_fixture()
        self.assertTrue(self.journal.exists())
        self.assertEqual(self.installs,[])

    def test_symlink_ancestor_refuses_without_modifying_destination(self):
        addons=self.home/'addons';retained=self.home/'addons-retained'
        addons.rename(retained);addons.symlink_to(retained,target_is_directory=True)
        with self.assertRaises(OSError):self.run_fixture()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.installs,[])

    def test_final_native_platform_failure_cannot_write_complete(self):
        self.platform.side_effect=[{'ok':True,'platform_check':{'source':{},'overall':'requirements_verified'}},{'ok':False}]
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertNotEqual(json.loads(self.journal.read_text().splitlines()[-1])['stage'],'complete')

    def test_current_application_origin_is_required_for_installed_metadata(self):
        from resources.lib.frozen import InstalledMetadata, InstalledOrigin
        self.backend.read_installed_metadata.side_effect=lambda aid:InstalledMetadata(self.packages[aid][1],InstalledOrigin.APPLICATION)
        with self.assertRaises(ValueError):self.run_fixture()
        self.assertNotEqual(json.loads(self.journal.read_text().splitlines()[-1])['stage'],'complete')


class RuntimeStateTests(unittest.TestCase):
    def setUp(self):
        import sys
        self.scope=ExitStack();self.addCleanup(self.scope.close)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.home=Path(temp.name).resolve()/'portable'
        self.bm=self.home/'userdata/addon_data/script.build.manager';self.bm.mkdir(parents=True)
        (self.home/'addons').mkdir()
        self.scope.enter_context(patch.object(support,'_AF3_HOME',self.home))
        vfs=SimpleNamespace(translatePath=lambda path:str({
            'special://home/':self.home,'special://profile/':self.home/'userdata',
            'special://home/addons':self.home/'addons'}[path]))
        self.vfs=vfs;self.scope.enter_context(patch.dict(sys.modules,{'xbmcvfs':vfs}))
        self.frozen=Mock();self.frozen.inspect.return_value=None
        self.restart=Mock();self.restart.inspect.return_value=None
        self.capture=Mock();self.capture.read.return_value=None
        self.library=Mock();self.library.pending_publication.return_value=None
        self.library.current_applied_association.return_value=SimpleNamespace(entry_id='entry',device_profile_id='profile')
        self.library.selection_state.return_value=('selected',SimpleNamespace(entry_id='entry',device_profile_id='profile'))
        self.scope.enter_context(patch.object(fi,'default_frozen_install_root',return_value=self.bm))
        self.scope.enter_context(patch.object(fi,'FrozenInstallStore',return_value=self.frozen))
        self.scope.enter_context(patch('resources.lib.transaction.TransactionStore',return_value=self.restart))
        self.scope.enter_context(patch('resources.lib.capture_lifecycle.CaptureStore',return_value=self.capture))
        self.holds=self.scope.enter_context(patch('resources.lib.activation.current_activation_holds',return_value=frozenset()))
        self.scope.enter_context(patch('resources.lib.build_library.default_build_library',return_value=self.library))
        self.backend=Mock()
        self.skin='skin.estuary'
        self.updater=0
        self.keymap=('1.4.0',False,False)
        def rpc(method,params):
            if method=='Settings.GetSettingValue':
                return {'result':{'value':self.skin if params['setting']=='lookandfeel.skin' else self.updater}}
            return {'result':{'addons':[dict(addonid='script.keymap',version=self.keymap[0],enabled=self.keymap[1],broken=self.keymap[2])]}}
        self.backend._rpc.side_effect=rpc

    def test_native_state_is_read_only_and_preserves_exact_public_bytes(self):
        public=self.bm/'build-library';public.mkdir();(public/'selection.json').write_text('synthetic public data')
        state=support._af3_runtime_state(self.backend)
        self.assertEqual(support._af3_runtime_state(self.backend),state)
        self.assertEqual((public/'selection.json').read_text(),'synthetic public data')
        self.assertEqual(set(c.args[0] for c in self.backend._rpc.call_args_list),{'Settings.GetSettingValue','Addons.GetAddons'})

    def test_transactions_holds_pending_publication_and_invalid_selection_refuse(self):
        for method in (self.frozen.inspect,self.restart.inspect,self.capture.read,self.library.pending_publication):
            with self.subTest(method=method):
                method.return_value=object()
                with self.assertRaises(ValueError):support._af3_runtime_state(self.backend)
                method.return_value=None
        self.holds.return_value=frozenset({'held'})
        with self.assertRaises(ValueError):support._af3_runtime_state(self.backend)
        self.holds.return_value=frozenset()
        self.library.selection_state.return_value=('invalid',None)
        with self.assertRaises(ValueError):support._af3_runtime_state(self.backend)

    def test_wrong_runtime_profile_skin_policy_or_keymap_refuse(self):
        self.skin='skin.other'
        with self.assertRaises(ValueError):support._af3_runtime_state(self.backend)
        self.skin='skin.estuary';self.updater=True
        with self.assertRaises(ValueError):support._af3_runtime_state(self.backend)
        self.updater=0;self.keymap=('2.0.0',False,False)
        with self.assertRaises(ValueError):support._af3_runtime_state(self.backend)
        self.keymap=('1.4.0',False,False)
        self.vfs.translatePath=lambda path:'/tmp/unapproved'
        with self.assertRaises(ValueError):support._af3_runtime_state(self.backend)


class LegacyScopeTests(unittest.TestCase):
    def test_ordinary_main_matches_immediate_base_after_removing_only_fixture_dispatch(self):
        import ast
        import subprocess
        root=Path(__file__).parents[1]
        old=ast.parse(subprocess.check_output(['git','show','7eb0ba023fb1d801dc5450a1ae18603313126cb4:tools/bm023a_adapter/default.py.in'],cwd=root).decode())
        new=ast.parse((root/'tools/bm023a_adapter/default.py.in').read_text())
        class StripFixture(ast.NodeTransformer):
            def visit_Assign(self,node):
                if any(isinstance(n,ast.Name) and n.id=='fixture_mode' for n in node.targets):return None
                return self.generic_visit(node)
            def visit_If(self,node):
                test=ast.unparse(node.test)
                if test=='fixture_mode is not None':return None
                if test=='fixture_mode is None':return node.body
                return self.generic_visit(node)
            def visit_Call(self,node):
                if isinstance(node.func,ast.Name) and node.func.id=='identify_adapter_result':
                    node.args[1]=ast.Name(id='mode',ctx=ast.Load())
                return self.generic_visit(node)
        original=next(n for n in ast.walk(old) if isinstance(n,ast.FunctionDef) and n.name=='main')
        current=next(n for n in ast.walk(new) if isinstance(n,ast.FunctionDef) and n.name=='main')
        self.assertEqual(ast.dump(original,include_attributes=False),ast.dump(StripFixture().visit(current),include_attributes=False))

    def test_changed_artifact_bytes_refuse_without_weakening_zip_validator(self):
        original=support._PlatformArtifacts
        class Changed(original):
            def read_bytes(self,digest):return super().read_bytes(digest)+b'changed'
        with patch.object(support,'_PlatformArtifacts',Changed):
            with self.assertRaises(Exception):support._af3_inputs(support._AF3_MANIFEST,support._AF3_STORE)
