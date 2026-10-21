"""Offline native diagnostic transport: exact sources, real verifier, fake Kodi APIs."""
import ast
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from resources.lib import frozen as fr, frozen_install as fi, artifacts
from tools import bm023a_adapter_support as support, build_bm023a_adapter as builder, bm_test_app as host
from tests import test_d028_passive as passive, test_d028_builtin_authority as authority
from tests import test_frozen as capture, test_d028_b1 as b1

PROJECT = Path(__file__).parents[1]
SECRET = 'PRIVATE_VALUE_MUST_NOT_APPEAR_19283'


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file()}


class Fixture:
    def __init__(self, case, *, pin=True):
        self.case = case
        self.native = native = passive.PassiveFixture(case)
        old_bundle = native.bundle
        native.bundle = native.root / 'Kodi Build Manager Test.app'
        old_bundle.rename(native.bundle)
        native.app = native.bundle / 'Contents/Resources/Kodi/addons'
        native.exe = native.bundle / 'Contents/MacOS/Kodi'
        native.home = native.bundle / 'Contents/Resources/Kodi/portable_data/addons'
        native.home.mkdir(parents=True)
        self.profile = native.home.parent / 'userdata'
        self.data = self.profile / 'addon_data/script.build.manager'
        self.data.mkdir(parents=True)
        self.addon = native.home / 'script.build.manager'
        self.addon.mkdir()
        shutil.copytree(PROJECT/'resources', self.addon/'resources', ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('addon.xml','default.py','service.py'): shutil.copyfile(PROJECT/name, self.addon/name)
        for aid in support.PLATFORM_IDS[:3]: native.info[aid]['path'] = str(native.app / aid)
        python = native.app / 'xbmc.python/addon.xml'
        python.parent.mkdir()
        python.write_text(authority.BUILTIN)
        native.info['xbmc.python'] = dict(id='xbmc.python', version='3.0.1', path=str(python.parent), type='unknown')
        native.conditions.update({'System.HasAddon(xbmc.python)':True,'System.AddonIsEnabled(xbmc.python)':True})
        p = patch.object(fi, '_native_process_executable', return_value=str(native.exe));p.start();case.addCleanup(p.stop)
        self.store = artifacts.ArtifactStore(native.root/'public-artifacts')
        incoming = (('xbmc.gui','5.17.0'),('kodi.resource','1.0.0'),('xbmc.python','3.0.0'))
        raw = b1.xml('plugin.test','1.0.0','<requires>'+''.join(
            '<import addon="'+aid+'" version="'+minimum+'"/>' for aid,minimum in incoming)+'</requires>')
        artifact = self.store.import_zip(capture._zip('plugin.test',xml_bytes=raw),
            expected_addon_id='plugin.test',expected_version='1.0.0')
        managed = fr.AddonCaptureNode('plugin.test','1.0.0','xbmc.python.pluginsource',True,
            fr.ProvenanceStatus.UNKNOWN,artifact=artifact,
            dependency_edges=tuple(fr.DependencyEdge(aid,minimum) for aid,minimum in incoming))
        systems = tuple(fr.AddonCaptureNode(aid, native.info[aid]['version'], 'system', True,
            fr.ProvenanceStatus.UNKNOWN,system=True,status=fr.CaptureStatus.SYSTEM,
            dependency_edges=() if aid=='xbmc.core' else (fr.DependencyEdge('xbmc.core','0.1.0'),))
            for aid in support.PLATFORM_IDS)
        self.manifest = fr.FrozenBuildManifest(1,'platform-check','Public diagnostic','now','21.3','macos',
            fr.CaptureStatus.COMPLETE,(managed,)+systems)
        self.manifest_path = native.root / 'reviewed-public-manifest.json'
        self.manifest_path.write_text(self.manifest.to_json())
        self.pin = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest() if pin else ''
        self.values = dict(MANIFEST_PATH=str(self.manifest_path),ARTIFACT_ROOT=str(self.store.root),
            CONFIGURATION_PATH=str(native.root/SECRET/'configuration'), OVERLAY_SOURCE=str(native.root/SECRET/'private-overlay'),
            DEVICE_PROFILE_ID='diagnostic',EXPECTED_OVERLAY_ID='not-loaded')
        archive = builder.build_adapter(native.root/'generated',self.values,
            candidate_commit='a'*40,platform_manifest_sha256=self.pin)
        self.driver = archive.parent / support.DRIVER_ADDON_ID
        config = host._parse_adapter_config((self.driver/'adapter_config.py').read_bytes())
        self.binding = config['PLATFORM_SOURCE_BINDING']
        self.calls = []
        reader = native.backend.read_verified_builtin_metadata
        def read(edge):
            self.calls.append(edge.addon_id)
            case.assertIn(edge.addon_id,support.PLATFORM_IDS)
            return reader(edge)
        native.backend.read_verified_builtin_metadata = read
        self.modules = {}
        for name, module in [('frozen_install',fi),('frozen',fr),('artifacts',artifacts)]:
            clone = ModuleType('resources.lib.'+name)
            clone.__dict__.update(module.__dict__)
            clone.__file__ = str(self.addon/'resources/lib'/ (name+'.py'))
            clone.__spec__ = importlib.machinery.ModuleSpec(clone.__name__,None,origin=clone.__file__)
            self.modules['resources.lib.'+name] = clone
        self.factory_calls = 0
        def factory():
            self.factory_calls += 1
            return native.backend
        self.modules['resources.lib.frozen_install'].KodiRuntimeFrozenArtifactBackend = factory
        def forbidden(*args,**kwargs):case.fail('diagnostic invoked mutation or constructor')
        for name in ('FrozenInstallCoordinator','FrozenInstallStore'):
            setattr(self.modules['resources.lib.frozen_install'],name,forbidden)
        self.modules['resources.lib.artifacts'].ArtifactStore = forbidden
        for name in ('install_exact','resolve_repository_current','set_addon_enabled','assert_mutable_target'):
            setattr(native.backend,name,forbidden)

    @contextmanager
    def imports(self, *, cache=False):
        original = importlib.import_module
        def imported(name, *args, **kwargs):
            if name in self.modules:
                if cache:sys.modules[name] = self.modules[name]
                return self.modules[name]
            if name=='resources.lib' and cache:
                mod=ModuleType(name);mod.__file__=str(self.addon/'resources/lib/__init__.py')
                mod.__path__=[str(self.addon/'resources/lib')]
                sys.modules[name]=mod
                return mod
            return original(name,*args,**kwargs)
        with patch.object(importlib,'import_module',side_effect=imported): yield

    def run(self):
        with self.imports():
            return support.read_platform_check(self.addon,self.driver,self.binding,self.manifest_path,self.store.root)

    def entrypoint(self, mode='platform_check'):
        saved = {name:sys.modules.pop(name) for name in list(sys.modules)
            if name=='resources' or name.startswith('resources.') or name in ('adapter_config','adapter_support')}
        before_path=list(sys.path);before_argv=sys.argv
        xbmc=ModuleType('xbmc');xbmc.executeJSONRPC=lambda *_:self.case.fail('unapproved entrypoint RPC')
        vfs=ModuleType('xbmcvfs')
        paths={'special://profile/':self.profile,'special://home/addons':self.native.home,
            'special://home/addons/script.build.manager':self.addon}
        vfs.translatePath=lambda value:str(paths[value])
        try:
            sys.path.insert(0,str(self.driver));sys.argv=[str(self.driver/'default.py')]+([mode] if isinstance(mode,str) else mode)
            with self.imports(cache=True), patch.dict(sys.modules,{'xbmc':xbmc,'xbmcvfs':vfs}), \
                    patch.object(sys,'dont_write_bytecode',False):
                runpy.run_path(str(self.driver/'default.py'),run_name='__main__')
                self.case.assertFalse(sys.dont_write_bytecode)
        finally:
            sys.path[:]=before_path;sys.argv=before_argv
            for name in list(sys.modules):
                if name=='resources' or name.startswith('resources.') or name in ('adapter_config','adapter_support'):
                    sys.modules.pop(name,None)
            sys.modules.update(saved)
        return json.loads((self.data/'bm023a_live_result.json').read_text())


class PlatformCheckTests(unittest.TestCase):
    def test_complete_pinned_fixture_uses_real_verifiers_and_no_mutations(self):
        f=Fixture(self);before=snapshot(f.native.root);result=f.run()
        self.assertTrue(result['ok'],result)
        d=result['platform_check'];self.assertEqual('requirements_verified',d['overall'])
        self.assertEqual('not_qualified',d['qualification'])
        self.assertEqual(set(support.PLATFORM_IDS),set(f.calls))
        self.assertEqual(before,snapshot(f.native.root))
        self.assertEqual(d,support.project_platform_check(d))
        for row in d['providers'].values():self.assertEqual('verified',row['closure_status'])

    def test_entrypoint_writes_only_fresh_sanitized_result_and_never_repairs_sources(self):
        f=Fixture(self);before=snapshot(f.native.root);result=f.entrypoint()
        self.assertTrue(result['ok'],result)
        self.assertEqual('platform_check',result['adapter_mode'])
        after=snapshot(f.native.root)
        self.assertEqual({str((f.data/'bm023a_live_result.json').relative_to(f.native.root))},
            {key for key in set(before)|set(after) if before.get(key)!=after.get(key)})
        self.assertNotIn(SECRET,json.dumps(result));self.assertNotIn(str(f.native.root),json.dumps(result))
        self.assertNotIn('frozen_install_source',result)

    def test_mode_is_exact_and_cannot_supply_providers_or_methods(self):
        for token in ('platform_check','?mode=platform_check'):
            self.assertEqual('platform_check',support.parse_adapter_mode([token]))
        for args in (['platform_check','xbmc.evil'],['platform_check;install'],['?mode=platform_check&method=install'],['xbmc.gui']):
            with self.assertRaises(support.AdapterBootstrapError):support.parse_adapter_mode(args)

    def test_early_location_failure_never_creates_result_directories(self):
        for existing_parent, malformed in ((True,False),(False,False),(True,True),(False,True)):
            with self.subTest(existing_parent=existing_parent,malformed=malformed):
                f=Fixture(self)
                if not malformed:f.addon.rename(f.addon.with_name('retained-product'))
                if not existing_parent:f.data.rmdir()
                before=snapshot(f.native.root)
                mode=['platform_check','install'] if malformed else 'platform_check'
                with patch.object(Path,'mkdir',side_effect=AssertionError('diagnostic attempted mkdir')):
                    if malformed:
                        with self.assertRaises(SystemExit):f.entrypoint(mode)
                    elif existing_parent:
                        result=f.entrypoint(mode)
                        self.assertFalse(result['ok'])
                        self.assertEqual('platform_check',result['adapter_mode'])
                    else:
                        with self.assertRaises(FileNotFoundError):f.entrypoint(mode)
                after=snapshot(f.native.root)
                expected={str((f.data/'bm023a_live_result.json').relative_to(f.native.root))} if existing_parent and not malformed else set()
                self.assertEqual(expected,{key for key in set(before)|set(after) if before.get(key)!=after.get(key)})
                self.assertEqual(0,f.factory_calls)

    def test_oversized_manifest_refuses_before_artifact_or_plan_validation(self):
        f=Fixture(self)
        extra=tuple(fr.AddonCaptureNode('kodi.synthetic.'+str(i),'1.0.0','system',True,
            fr.ProvenanceStatus.UNKNOWN,system=True,status=fr.CaptureStatus.SYSTEM) for i in range(501))
        f.manifest=replace(f.manifest,addons=f.manifest.addons+extra)
        f.manifest_path.write_text(f.manifest.to_json())
        binding=json.loads(f.binding)
        binding['manifest_sha256']=hashlib.sha256(f.manifest_path.read_bytes()).hexdigest()
        f.binding=json.dumps(binding,sort_keys=True,separators=(',',':'))
        module=f.modules['resources.lib.frozen_install']
        with patch.object(module,'validate_frozen_manifest',wraps=module.validate_frozen_manifest) as validate:
            result=f.run()
        validate.assert_not_called()
        self.assertFalse(result['ok'])
        self.assertEqual('manifest_invalid',result['platform_check']['graph']['failure_category'])

    def test_missing_and_invalid_source_binding_fail_before_backend_or_manifest(self):
        for binding in (None,'{}','not-json',json.dumps({'candidate_commit':SECRET})):
            f=Fixture(self);f.binding=binding;result=f.run()
            self.assertFalse(result['ok']);self.assertEqual(0,f.factory_calls)
            self.assertEqual('source_binding_invalid',result['platform_check']['graph']['failure_category'])
            self.assertNotIn(SECRET,json.dumps(result))

    def test_modified_source_or_adapter_refuses_without_repair(self):
        for relative in ('resources/lib/frozen.py','resources/lib/frozen_install.py'):
            f=Fixture(self);p=f.addon/relative;p.write_bytes(p.read_bytes()+b'\n# changed\n')
            before=snapshot(f.native.root);result=f.run()
            self.assertFalse(result['ok']);self.assertEqual(0,f.factory_calls)
            self.assertEqual(before,snapshot(f.native.root))
        f=Fixture(self);p=f.driver/'adapter_support.py';p.write_bytes(p.read_bytes()+b'\n# changed\n')
        self.assertFalse(f.run()['ok'])

    def test_wrong_build_and_wrong_process_are_unverified(self):
        for wrong in ('build','process'):
            f=Fixture(self)
            if wrong=='build':f.native.version['revision']=SECRET
            else:
                p=patch.object(fi,'_native_process_executable',return_value=str(f.native.root/'other/Kodi'))
                p.start();self.addCleanup(p.stop)
            result=f.run();self.assertFalse(result['ok'])
            self.assertEqual('runtime_or_build_unverified',result['platform_check']['graph']['failure_category'])
            self.assertNotIn(SECRET,json.dumps(result))

    def test_any_single_disabled_provider_blocks_complete_graph(self):
        for aid in support.PLATFORM_IDS:
            with self.subTest(aid=aid):
                f=Fixture(self);f.native.conditions['System.AddonIsEnabled('+aid+')']=False
                result=f.run();self.assertFalse(result['ok'])
                self.assertNotEqual('verified',result['platform_check']['providers'][aid]['status'])
                self.assertNotEqual('verified',result['platform_check']['graph']['status'])

    def test_constructor_failure_never_leaks_exception_or_triggers_fallback(self):
        f=Fixture(self)
        def broken(aid):raise RuntimeError(SECRET)
        f.native.api.Addon=broken
        result=f.run();self.assertFalse(result['ok']);self.assertNotIn(SECRET,json.dumps(result))

    def test_missing_manifest_binding_is_not_invented_or_overall_pass(self):
        f=Fixture(self,pin=False);result=f.run();d=result['platform_check']
        self.assertFalse(result['ok']);self.assertEqual('manifest_binding_missing',d['graph']['failure_category'])
        self.assertEqual('verified',d['providers']['xbmc.gui']['status'])
        self.assertEqual('unverified',d['providers']['xbmc.gui']['closure_status'])
        self.assertEqual(set(support.PLATFORM_IDS),set(f.calls))

    def test_changed_manifest_or_missing_artifacts_cannot_establish_closure(self):
        for kind in ('manifest','artifact'):
            f=Fixture(self)
            if kind=='manifest':f.manifest_path.write_text('{}')
            else:next(f.store.artifacts_dir.glob('*.zip')).unlink()
            result=f.run();self.assertFalse(result['ok'])
            self.assertNotEqual('verified',result['platform_check']['graph']['status'])

    def test_malformed_metadata_and_missing_abi_cannot_be_verified(self):
        for value in (None,{},fr.InstalledMetadata(b'<addon id="xbmc.gui" version="5.17.0"/>',fr.InstalledOrigin.APPLICATION)):
            f=Fixture(self);reader=f.native.backend.read_verified_builtin_metadata
            f.native.backend.read_verified_builtin_metadata=lambda edge: value if edge.addon_id=='xbmc.gui' else reader(edge)
            result=f.run();self.assertFalse(result['ok'])
            self.assertNotEqual('verified',result['platform_check']['providers']['xbmc.gui']['status'])

    def test_unknown_builtin_in_graph_never_reaches_native_provider(self):
        f=Fixture(self)
        plan=fi.validate_frozen_manifest(f.manifest,f.store)
        unknown=fr.AddonCaptureNode('xbmc.inject', '1.0.0','system',True,fr.ProvenanceStatus.UNKNOWN,
            system=True,status=fr.CaptureStatus.SYSTEM)
        f.manifest=replace(f.manifest,addons=f.manifest.addons+(unknown,))
        f.manifest_path.write_text(f.manifest.to_json())
        binding=json.loads(f.binding);binding['manifest_sha256']=hashlib.sha256(f.manifest_path.read_bytes()).hexdigest()
        f.binding=json.dumps(binding,sort_keys=True,separators=(',',':'))
        result=f.run();self.assertFalse(result['ok']);self.assertNotIn('xbmc.inject',f.calls)

    def test_partial_or_injected_host_results_fail_closed(self):
        f=Fixture(self);result=f.run();raw=dict(result,adapter_mode='platform_check')
        projected,_=host.project_adapter_result('platform_check',raw);self.assertTrue(projected['ok'])
        for kind in ('missing','provider','abi','closure','qualification','category'):
            changed=json.loads(json.dumps(raw));d=changed['platform_check']
            if kind=='missing':del changed['platform_check']
            if kind=='provider':d['providers']['xbmc.evil']=d['providers']['xbmc.gui']
            if kind=='abi':d['providers']['xbmc.gui']['abi']=SECRET
            if kind=='closure':d['providers']['xbmc.gui']['closure_status']='unverified'
            if kind=='qualification':d['qualification']='native_pass'
            if kind=='category':d['graph']['failure_category']={'secret':SECRET}
            with self.subTest(kind=kind),self.assertRaises(host.HelperError):host.project_adapter_result('platform_check',changed)

    def test_read_only_capabilities_have_no_mutation_api(self):
        for cls in (support._PlatformArtifacts,support._PlatformBackend):
            for name in ('import_zip','install_exact','resolve_repository_current','set_addon_enabled','create','transition'):
                self.assertFalse(hasattr(cls,name),(cls,name))

    def test_source_and_manifest_changes_after_native_observation_refuse(self):
        for kind in ('source','manifest'):
            f=Fixture(self);original=f.native.backend.read_verified_builtin_metadata;calls=[]
            def reader(edge):
                value=original(edge);calls.append(edge.addon_id)
                if len(calls)==1:
                    p=f.addon/'resources/lib/frozen.py' if kind=='source' else f.manifest_path
                    p.write_bytes(p.read_bytes()+b' ')
                return value
            f.native.backend.read_verified_builtin_metadata=reader
            self.assertFalse(f.run()['ok'])


class PlatformHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from types import SimpleNamespace
        from tests import test_bm_test_app as world
        cls.world = world
        cls.previous = world.FIXTURE
        world.FIXTURE = SimpleNamespace(base=None,repo=None,good=None,variants={},plan=None,counter=0)
        world.setUpModule()

    @classmethod
    def tearDownClass(cls):
        cls.world.tearDownModule()
        cls.world.FIXTURE = cls.previous

    def setup_world(self):
        helper = self.world.TripwireTestCase()
        helper.setUp();self.addCleanup(helper.doCleanups)
        world = self.world.RunWorld(helper)
        native = Fixture(self)
        candidate = self.world.good_plan()[0]
        values = dict(self.world.ADAPTER_VALUES,PLATFORM_MANIFEST_SHA256=native.pin)
        driver = host.build_driver(candidate,values,self.world.new_workspace(helper),sys.executable)
        folder=world.target.addon_dir(host.DRIVER_ID)
        # Replace only this disposable synthetic fixture's driver.
        shutil.rmtree(folder)
        host.write_tree(folder,[(name,data,0o644) for name,data in driver.files])
        world.manifest=host.build_manifest(candidate,driver,host.config_fingerprint(values),'2026-10-21T00:00:00Z')
        native.binding=host._parse_adapter_config(driver.data('adapter_config.py'))['PLATFORM_SOURCE_BINDING']
        result=native.run()
        self.assertTrue(result['ok'],result)
        result['adapter_mode']='platform_check'
        return world,result

    def test_host_preserves_authenticated_dispatch_source_identity_and_freshness(self):
        world,result=self.setup_world();world.password_to_return=self.world.SENTINEL_PASSWORD
        world.transport.password=self.world.SENTINEL_PASSWORD
        world.produce_on_sleep(result)
        report=world.run('platform_check',git_repo=self.world.FIXTURE.repo)
        self.assertTrue(report['ok'],report)
        self.assertEqual('fresh',report['freshness']['verdict'])
        self.assertTrue(report['invocation']['authenticated'])
        self.assertEqual(result,report['result'])
        self.assertEqual([{'addonid':host.DRIVER_ID,'params':'platform_check','wait':False}],world.executed)
        self.assertNotIn(SECRET,json.dumps(report));self.assertNotIn(self.world.SENTINEL_PASSWORD,json.dumps(report))

    def test_host_missing_or_stale_result_never_uses_execute_acknowledgement(self):
        world,_=self.setup_world()
        with self.assertRaisesRegex(host.HelperError,'result_not_produced'):world.run('platform_check',timeout=2,git_repo=self.world.FIXTURE.repo)
        world,result=self.setup_world();world.write_result(result)
        with self.assertRaisesRegex(host.HelperError,'result_stale'):world.run('platform_check',timeout=2,git_repo=self.world.FIXTURE.repo)

    def test_host_refuses_forged_candidate_identity_in_fresh_result(self):
        world,result=self.setup_world()
        result['platform_check']['source']['candidate_commit']='f'*40
        world.produce_on_sleep(result)
        with self.assertRaisesRegex(host.HelperError,'result_malformed'):world.run('platform_check',git_repo=self.world.FIXTURE.repo)

    def test_host_refuses_mismatched_reviewed_manifest_identity(self):
        world,result=self.setup_world();result['platform_check']['manifest_sha256']='e'*64
        world.produce_on_sleep(result)
        with self.assertRaisesRegex(host.HelperError,'result_malformed'):world.run('platform_check',git_repo=self.world.FIXTURE.repo)

    def test_host_refuses_missing_source_binding_before_any_rpc(self):
        world,_=self.setup_world()
        config=world.target.addon_dir(host.DRIVER_ID)/'adapter_config.py'
        config.write_text('MANIFEST_PATH = "'+SECRET+'"\n')
        # Existing tree verification must stop even before binding extraction.
        with self.assertRaisesRegex(host.HelperError,'installed_tree_mismatch'):world.run('platform_check',git_repo=self.world.FIXTURE.repo)
        self.assertEqual([],world.methods())

    def test_host_rejects_arbitrary_mode_before_rpc(self):
        world,_=self.setup_world()
        with self.assertRaisesRegex(host.HelperError,'argument_invalid'):world.run('platform_check;install')
        self.assertEqual([],world.methods())

    def test_host_requires_git_binding_before_runtime_or_rpc(self):
        world,result=self.setup_world();world.produce_on_sleep(result)
        with self.assertRaisesRegex(host.HelperError,'argument_invalid'):world.run('platform_check',git_repo=None)
        self.assertEqual([],world.events)


class PlatformMutationTests(unittest.TestCase):
    def detected(self, owner, name, before, after, case):
        import inspect,textwrap
        original=getattr(owner,name);source=textwrap.dedent(inspect.getsource(original))
        self.assertIn(before,source)
        namespace=dict(inspect.getmodule(original).__dict__)
        exec(compile(source.replace(before,after),'<isolated diagnostic transport mutation>','exec'),namespace)
        with patch.object(owner,name,namespace[name]):
            result=unittest.TestResult();case.run(result)
        self.assertEqual([],result.errors,str(result.errors));self.assertEqual([],result.skipped)
        self.assertGreater(len(result.failures),0,'transport guard removal escaped assertions')
        print('PLATFORM_TRANSPORT_MUTATION_ASSERTION_PASS '+name,flush=True)

    def test_source_sha_guard_removal_is_detected(self):
        self.detected(support,'_platform_sources','hashlib.sha256(data).hexdigest() != expected','False',
            PlatformCheckTests('test_modified_source_or_adapter_refuses_without_repair'))

    def test_fixed_provider_guard_removal_is_detected(self):
        self.detected(support._PlatformBackend,'read_verified_builtin_metadata',
            'if edge.addon_id not in PLATFORM_IDS: return None','if False: return None',
            PlatformCheckTests('test_unknown_builtin_in_graph_never_reaches_native_provider'))

    def test_host_source_identity_guard_removal_is_detected(self):
        PlatformHostTests.setUpClass()
        try:
            self.detected(host,'run_adapter','if diagnostic_source != expected_source:','if False:',
                PlatformHostTests('test_host_refuses_forged_candidate_identity_in_fresh_result'))
        finally:PlatformHostTests.tearDownClass()

    def test_host_git_binding_requirement_removal_is_detected(self):
        PlatformHostTests.setUpClass()
        try:
            self.detected(host,'run_adapter','if mode == "platform_check" and git_repo is None:',
                'if False:',PlatformHostTests('test_host_requires_git_binding_before_runtime_or_rpc'))
        finally:PlatformHostTests.tearDownClass()
