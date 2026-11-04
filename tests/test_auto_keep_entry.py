"""Guarded synthetic qualification path; production activator and UI are real."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import bm023a_adapter_support as support
from tools import bm_test_app as host
from resources.lib import frozen_install as fi
from resources.lib.skin import SkinActivator
from tests.test_auto_keep import Kodi

ROOT = Path(__file__).parents[1]


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'portable_data'
        self.addon = self.home / 'addons/script.build.manager'
        self.driver = self.home / 'addons/script.build.manager.bm023a_driver'
        for p in (self.addon, self.driver, self.home/'userdata'): p.mkdir(parents=True, exist_ok=True)
        self.entry_bytes = (ROOT/'default.py').read_bytes()
        (self.addon/'default.py').write_bytes(self.entry_bytes)
        self.binding = json.dumps({'product':{'default.py':hashlib.sha256(self.entry_bytes).hexdigest()}})
        self.journal = self.home/'userdata/bm-af3-fixture-v1.jsonl'
        self.journal.write_bytes(b'permanent failed attempt synthetic evidence')
        self.kodi = Kodi(); self.backend = Mock()
        @contextmanager
        def native_binding(*args): yield lambda: True
        self.backend._passive_build_binding.side_effect=native_binding
        self.scope = ExitStack(); self.addCleanup(self.scope.close)
        self.scope.enter_context(patch.object(support, '_AF3_HOME', self.home))
        self.sources = self.scope.enter_context(patch.object(support, '_platform_sources'))
        self.platform = self.scope.enter_context(patch.object(support, 'read_platform_check',
            return_value={'ok':True, 'platform_check':{'overall':'requirements_verified','manifest_sha256':support._AF3_MANIFEST_SHA}}))
        self.state = self.scope.enter_context(patch.object(support, '_auto_keep_state', return_value=('unchanged',)))
        self.scope.enter_context(patch.object(fi, 'KodiRuntimeFrozenArtifactBackend', return_value=self.backend))
        self.scope.enter_context(patch.object(fi, 'FrozenInstallCoordinator',
            side_effect=AssertionError('coordinator forbidden')))
        # Real production SkinActivator, only its clock/sleep are injected.
        def activator(backend):
            return SkinActivator(backend, timeout=3, clock=self.kodi.clock, sleep=self.kodi.clock.sleep)
        self.scope.enter_context(patch('resources.lib.skin.SkinActivator', side_effect=activator))
        self.kodi.gui.Dialog = Mock()
        self.scope.enter_context(patch.dict('sys.modules', {'xbmc':self.kodi, 'xbmcgui':self.kodi.gui,
            'xbmcaddon':SimpleNamespace(Addon=Mock(return_value=Mock()))}))
        self.original_topmost = self.kodi.topmost
        self.kodi.gui.getCurrentWindowDialogId = lambda: -1 if self.kodi.dialog is None else self.original_topmost()
        self.original_journal = self.journal.read_bytes()

    def run_entry(self):
        return support.run_auto_keep(self.addon,self.driver,self.binding,support._AF3_MANIFEST,support._AF3_STORE)

    def test_production_callback_success_once_and_repeat_fenced(self):
        result = self.run_entry()
        self.assertTrue(result['ok']); self.assertEqual(self.kodi.clicks,['keep'])
        self.kodi.progress.create.assert_called_once(); self.kodi.progress.close.assert_called_once()
        self.assertEqual(self.kodi.configured,'skin.arctic.fuse.3')
        support.project_auto_keep(result['auto_keep'])
        marker=self.home/'userdata/bm-auto-keep-attempt-v1.json'; original=marker.read_bytes()
        with self.assertRaises(FileExistsError): self.run_entry()
        self.assertEqual(self.kodi.clicks,['keep']); self.assertEqual(marker.read_bytes(),original)
        self.assertEqual(self.journal.read_bytes(),self.original_journal)
        self.backend.set_addon_enabled.assert_not_called()
        self.backend.install_exact.assert_not_called()

    def test_wrong_prompts_timeouts_and_reversion_close_progress_without_retry(self):
        # Separate disposable attempt fence per independent synthetic case.
        for mode in ('during_prepare','wrong_heading','wrong_body','wrong_topmost',
                     'early_replacement','never','declined','reverted','stuck','unreadable','click_typeerror'):
            with self.subTest(mode=mode):
                self.kodi.mode=mode;self.kodi.dialog=None;self.kodi.configured='skin.estuary'
                self.kodi.clicks=[];self.kodi.modal_checks=0;self.kodi.progress.reset_mock()
                result=self.run_entry();self.assertFalse(result['ok'])
                self.assertLessEqual(len(self.kodi.clicks),1)
                self.kodi.progress.close.assert_called_once()
                (self.home/'userdata/bm-auto-keep-attempt-v1.json').unlink()  # synthetic fixture only
        self.assertEqual(self.journal.read_bytes(),self.original_journal)

    def test_preexisting_modal_refuses_without_claim_or_mutation(self):
        self.kodi.dialog='unrelated'
        with self.assertRaises(ValueError): self.run_entry()
        self.assertEqual(self.kodi.mutations,[]);self.assertEqual(self.kodi.clicks,[])
        self.assertFalse((self.home/'userdata/bm-auto-keep-attempt-v1.json').exists())

    def test_runtime_or_platform_or_source_refusal_precedes_attempt(self):
        for seam in (self.state,self.platform,self.sources):
            seam.side_effect=ValueError('private detail')
            with self.assertRaises(ValueError):self.run_entry()
            seam.side_effect=None
            self.assertEqual(self.kodi.mutations,[])
        self.assertFalse((self.home/'userdata/bm-auto-keep-attempt-v1.json').exists())

    def test_changed_entry_source_refuses_before_callback(self):
        (self.addon/'default.py').write_text('raise AssertionError("untrusted")')
        with self.assertRaises(ValueError):self.run_entry()
        self.assertEqual(self.kodi.mutations,[])

    def test_changed_native_identity_refuses_before_consuming_attempt(self):
        @contextmanager
        def changed(*args): yield lambda: False
        self.backend._passive_build_binding.side_effect=changed
        with self.assertRaises(ValueError):self.run_entry()
        self.assertEqual(self.kodi.mutations,[])
        self.assertFalse((self.home/'userdata/bm-auto-keep-attempt-v1.json').exists())

    def test_unverified_platform_refuses_before_callback(self):
        self.platform.return_value={'ok':False}
        with self.assertRaises(ValueError):self.run_entry()
        self.assertEqual(self.kodi.mutations,[])

    def test_busy_creation_failure_consumes_attempt_and_never_activates(self):
        self.kodi.progress.create.side_effect=RuntimeError('private native detail')
        with self.assertRaises(RuntimeError):self.run_entry()
        self.assertEqual(self.kodi.mutations,[])
        self.kodi.progress.close.assert_called_once()
        with self.assertRaises(FileExistsError):self.run_entry()

    def test_cleanup_failure_is_not_reported_success_and_never_retried(self):
        self.kodi.progress.close.side_effect=RuntimeError('private native detail')
        with self.assertRaises(RuntimeError):self.run_entry()
        self.assertEqual(self.kodi.clicks,['keep'])
        with self.assertRaises(FileExistsError):self.run_entry()

    def test_preservation_or_source_failure_cannot_report_success(self):
        self.state.side_effect=[('before',),('before',),('changed',)]
        self.assertFalse(self.run_entry()['ok'])
        self.assertEqual(self.kodi.clicks,['keep'])

    def test_symlink_claim_refuses_without_following_or_activation(self):
        sentinel=self.home/'retain';sentinel.write_bytes(b'retain')
        (self.home/'userdata/bm-auto-keep-attempt-v1.json').symlink_to(sentinel)
        with self.assertRaises(FileExistsError):self.run_entry()
        self.assertEqual(sentinel.read_bytes(),b'retain');self.assertEqual(self.kodi.mutations,[])

    def test_typed_prerequisites_enforce_build_packages_and_journal(self):
        association=SimpleNamespace(entry_id=support._AUTO_KEEP_ENTRY,
            device_profile_id='current-device-8794224972c6',resolution_fingerprint=support._AUTO_KEEP_RESOLUTION)
        lib=Mock();lib.current_applied_association.return_value=association
        self.backend.get_addon_details.side_effect=lambda aid: SimpleNamespace(
            version=support._AF3_PACKAGES[aid][0],enabled=True,broken=False)
        original=REAL_STATE
        with patch('resources.lib.build_library.default_build_library',return_value=lib), patch.object(
                support,'_af3_runtime_state',return_value=({'lookandfeel.skin':'skin.estuary'},'public')), patch.object(
                support,'_AUTO_KEEP_JOURNAL_SHA',hashlib.sha256(self.original_journal).hexdigest()):
            original(self.backend,'skin.estuary')
            for field,value in (('entry_id','wrong'),('device_profile_id','wrong'),('resolution_fingerprint','wrong')):
                saved=getattr(association,field);setattr(association,field,value)
                with self.assertRaises(ValueError):original(self.backend,'skin.estuary')
                setattr(association,field,saved)
            for detail in (None,SimpleNamespace(version='wrong',enabled=True,broken=False),
                           SimpleNamespace(version='6.17.9',enabled=False,broken=False),
                           SimpleNamespace(version='6.17.9',enabled=True,broken=True)):
                self.backend.get_addon_details.side_effect=None;self.backend.get_addon_details.return_value=detail
                with self.assertRaises(ValueError):original(self.backend,'skin.estuary')


REAL_STATE=support._auto_keep_state


from tests import test_d028_platform_check as platform_tests


class HostEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform_tests.PlatformHostTests.setUpClass(); cls.world=platform_tests.PlatformHostTests.world
    @classmethod
    def tearDownClass(cls): platform_tests.PlatformHostTests.tearDownClass()

    def setUp(self):
        self.w,self.payload=platform_tests.PlatformHostTests.setup_world(self)
        self.w.transport.password=self.w.password_to_return=self.world.SENTINEL_PASSWORD
        self.payload['adapter_mode']='auto_keep'
        self.payload['auto_keep']={'initial_skin':'skin.estuary','prerequisites_verified':True,
            'attempt_consumed':True,'callback_returned':True,'progress_cleanup_returned':True,
            'status':'activated','failure_code':None,'final_setting':'skin.arctic.fuse.3',
            'reported_active':'skin.arctic.fuse.3','scoped_preservation':True,
            'atomic_dialog_ownership':False,'loaded_object_authenticated':False,
            'cache_trust':'UNVERIFIED','original_provisioning':'FAIL_INCOMPLETE'}
        self.w.produce_on_sleep(self.payload)

    def run_host(self, **changes):
        args=dict(mode='auto_keep',manifest=self.w.manifest,manifest_sha256='f'*64,
            rpc={'host':'127.0.0.1','port':8080,'username':'kodi'},
            git_repo=self.world.FIXTURE.repo,timeout=3)
        args.update(changes)
        return host.run_adapter(self.w.services,**args)

    def test_authenticated_bound_http_dispatches_exactly_once(self):
        report=self.run_host();self.assertTrue(report['ok'])
        self.assertTrue(report['invocation']['authenticated'])
        self.assertEqual(self.w.executed,[{'addonid':host.DRIVER_ID,'params':'auto_keep','wait':False}])

    def test_unchallenged_http_refuses_before_dispatch(self):
        self.w.transport.password=None
        with self.assertRaisesRegex(host.HelperError,'rpc_auth_failed'):self.run_host()
        self.assertEqual(self.w.executed,[])

    def test_wrong_endpoint_transport_or_git_refuses_without_dispatch(self):
        for changes in ({'git_repo':None},{'rpc_transport':'tcp'},
                        {'rpc':{'host':'localhost','port':8080,'username':'kodi'}},
                        {'rpc':{'host':'127.0.0.1','port':8081,'username':'kodi'}},
                        {'rpc':{'host':'127.0.0.1','port':8080,'username':'other'}}):
            with self.assertRaises(host.HelperError):self.run_host(**changes)
        self.assertEqual(self.w.executed,[])

    def test_wrong_listener_refuses_before_dispatch(self):
        self.w.listener_pids={999}
        with self.assertRaises(host.HelperError):self.run_host()
        self.assertEqual(self.w.executed,[])

    def test_missing_result_is_not_retried(self):
        self.w.clock.on_sleep=None
        with self.assertRaises(host.HelperError):self.run_host()
        self.assertEqual(len(self.w.executed),1)

    def test_changed_source_window_refuses(self):
        original=host._platform_invocation_snapshot
        calls=[0]
        def witness(*args,**kwargs):
            value=original(*args,**kwargs);calls[0]+=1
            return value if calls[0]==1 else ('changed',)
        with patch.object(host,'_platform_invocation_snapshot',side_effect=witness):
            with self.assertRaisesRegex(host.HelperError,'platform_source_changed'):self.run_host()
        self.assertEqual(len(self.w.executed),1)

    def test_projector_rejects_false_success_private_or_missing_evidence(self):
        for key,value in (('scoped_preservation',False),('final_setting','private'),
                          ('loaded_object_authenticated',True),('status','failed')):
            saved=self.payload['auto_keep'][key];self.payload['auto_keep'][key]=value
            with self.assertRaises(host.HelperError):host.project_adapter_result('auto_keep',self.payload)
            self.payload['auto_keep'][key]=saved
        self.payload.pop('auto_keep')
        with self.assertRaises(host.HelperError):host.project_adapter_result('auto_keep',self.payload)


class BootstrapTests(unittest.TestCase):
    def test_mode_uses_source_only_bootstrap_without_coordinator(self):
        from tests.test_d028_platform_check import Fixture
        from tests.test_d028_platform_check_b1_b2 import execute, rebind_driver
        fixture=Fixture(self)
        path=fixture.driver/'adapter_support.py'
        path.write_text(path.read_text()+'''\n\ndef run_auto_keep(*args):
    return {'ok': True, 'dispatch_probe': True}
''')
        rebind_driver(fixture)
        result=execute(fixture,('auto_keep',))
        self.assertTrue(result['ok'],result);self.assertTrue(result['dispatch_probe'])
        self.assertEqual(result['adapter_mode'],'auto_keep');self.assertNotIn('transaction',result)

    def test_malformed_request_refuses_before_any_result_write(self):
        from tests.test_d028_platform_check import Fixture, snapshot
        from tests.test_d028_platform_check_b1_b2 import execute
        fixture=Fixture(self);before=snapshot(fixture.native.root)
        for args in (('auto_keep;install',),('?mode=auto_keep&skin=x',),('auto_keep','auto_keep')):
            with self.assertRaises(SystemExit):execute(fixture,args)
            self.assertEqual(snapshot(fixture.native.root),before)


from tests import test_af3_fixture as fixture_tests


class NativePrerequisiteTests(unittest.TestCase):
    def setUp(self):
        fixture_tests.RuntimeStateTests.setUp(self)
        self.library.current_applied_association.return_value=SimpleNamespace(
            entry_id=support._AUTO_KEEP_ENTRY,device_profile_id='current-device-8794224972c6',
            resolution_fingerprint=support._AUTO_KEEP_RESOLUTION)
        self.library.selection_state.return_value=('selected',SimpleNamespace(
            entry_id=support._AUTO_KEEP_ENTRY,device_profile_id='current-device-8794224972c6'))
        self.backend.get_addon_details.side_effect=lambda aid:SimpleNamespace(
            version=support._AF3_PACKAGES[aid][0],enabled=True,broken=False)
        raw=b'original failed synthetic journal\n'
        (self.home/'userdata/bm-af3-fixture-v1.jsonl').write_bytes(raw)
        self.scope.enter_context(patch.object(support,'_AUTO_KEEP_JOURNAL_SHA',hashlib.sha256(raw).hexdigest()))

    def test_estuary_and_af3_observations_have_equal_unrelated_witness(self):
        before=support._auto_keep_state(self.backend,'skin.estuary')
        self.skin='skin.arctic.fuse.3'
        self.assertEqual(support._auto_keep_state(self.backend,self.skin),before)
        self.frozen.create.assert_not_called();self.library.publish_applied.assert_not_called()

    def test_wrong_initial_skin_and_policy_refuse(self):
        self.skin='skin.other'
        with self.assertRaises(ValueError):support._auto_keep_state(self.backend,'skin.estuary')
        self.skin='skin.estuary'
        for value in (0,1,True,None,'2'):
            self.updater=value
            with self.assertRaises(ValueError):support._auto_keep_state(self.backend,'skin.estuary')

    def test_all_transaction_hold_and_publication_conflicts_refuse(self):
        for method in (self.frozen.inspect,self.restart.inspect,self.capture.read,self.library.pending_publication):
            method.return_value=object()
            with self.assertRaises(ValueError):support._auto_keep_state(self.backend,'skin.estuary')
            method.return_value=None
        self.holds.return_value={'held'}
        with self.assertRaises(ValueError):support._auto_keep_state(self.backend,'skin.estuary')

    def test_wrong_portable_identity_or_journal_refuses(self):
        (self.home/'userdata/bm-af3-fixture-v1.jsonl').write_bytes(b'changed')
        with self.assertRaises(ValueError):support._auto_keep_state(self.backend,'skin.estuary')
        self.vfs.translatePath=lambda _: '/private/tmp/wrong-runtime'
        with self.assertRaises(ValueError):support._auto_keep_state(self.backend,'skin.estuary')
