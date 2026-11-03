"""Offline host health inspection tests. Fake Kodi only; no native target IO."""
from contextlib import ExitStack
import base64
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import bm_test_app as host
from tools import bm023a_adapter_support as support
from tests import test_d028_platform_check as platform_tests

READ_AUDIT=host._af3_health_audit
PROJECT=Path(__file__).parents[1]


class HealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform_tests.PlatformHostTests.setUpClass();cls.world=platform_tests.PlatformHostTests.world
    @classmethod
    def tearDownClass(cls):platform_tests.PlatformHostTests.tearDownClass()

    def setUp(self):
        self.w,self.platform=platform_tests.PlatformHostTests.setup_world(self)
        self.scope=ExitStack();self.addCleanup(self.scope.close)
        self.scope.enter_context(patch.object(host,'_AF3_HEALTH_SOURCE',self.w.manifest['candidate']['commit']))
        self.scope.enter_context(patch.object(host,'_AF3_HEALTH_STAGE_SHA','f'*64))
        self.scope.enter_context(patch.object(support,'_AF3_MANIFEST_SHA',self.platform['platform_check']['manifest_sha256']))
        self.scope.enter_context(patch.object(host,'_af3_health_audit',return_value={
            'status':'HISTORICAL_VERIFIED','fresh_runtime_measurement':False,'original_files':4497,
            'original_directories':254,'audit_seal_sha256':host._AF3_HEALTH_AUDIT_SHA}))
        self.journal=self.w.target.userdata_dir/'bm-af3-fixture-v1.jsonl'
        self.journal.write_bytes((PROJECT/'.qualification-evidence/item8-a11-af3-native-provisioning-20261103/fixture-journal.jsonl').read_bytes())
        self.original_journal=self.journal.read_bytes()
        self.native={aid:dict(addonid=aid,version=pin[0],enabled=True,broken=False)
                     for aid,pin in support._AF3_PACKAGES.items()}
        self.settings={'lookandfeel.skin':'skin.estuary','general.addonupdates':2}
        self.version={'major':21,'minor':3,'revision':support.PLATFORM_BUILD,'tag':'stable'}
        self.w.transport.password=self.w.password_to_return=self.world.SENTINEL_PASSWORD
        original=self.w.transport.default_handler
        def handler(request):
            password=self.w.transport.password
            if password is not None:
                expected='Basic '+base64.b64encode(('kodi:'+password).encode()).decode()
                if request['headers'].get('Authorization')!=expected:return original(request)
            method=request['body']['method'];params=request['body']['params']
            if method=='Settings.GetSettingValue':return self.w.transport.reply({'value':self.settings[params['setting']]})
            if method=='Application.GetProperties':return self.w.transport.reply({'version':self.version})
            if method=='Addons.GetAddonDetails' and params['addonid'] in support._AF3_PACKAGES:
                row=self.native.get(params['addonid'])
                if row is None:return self.w.transport.reply(error={'code':-32602,'message':'missing synthetic addon'})
                return self.w.transport.reply({'addon':row})
            return original(request)
        self.w.transport.handler=handler
        self.w.produce_on_sleep(self.platform)

    def run_health(self,**changes):
        values=dict(manifest=self.w.manifest,manifest_sha256='f'*64,
            git_repo=self.world.FIXTURE.repo,rpc={'host':'127.0.0.1','port':8080,'username':'kodi'})
        values.update(changes)
        return host.run_af3_health(self.w.services,**values)

    def assert_no_mutation(self):
        self.assertEqual(self.journal.read_bytes(),self.original_journal)
        self.assertEqual(self.w.executed,[{'addonid':host.DRIVER_ID,'params':'platform_check','wait':False}])
        self.assertLessEqual(set(self.w.methods()),{'JSONRPC.Ping','Addons.GetAddonDetails',
            'Addons.ExecuteAddon','Settings.GetSettingValue','Application.GetProperties'})

    def test_native_health_pass_keeps_all_four_categories_separate(self):
        cache=self.w.target.addons_dir/'plugin.video.themoviedb.helper/__pycache__'
        cache.mkdir(parents=True);(cache/'untrusted.pyc').write_bytes(b'untrusted synthetic bytes')
        report=self.run_health()
        self.assertTrue(report['ok']);self.assertTrue(report['authenticated'])
        self.assertEqual(len(report['native_registration_health']['packages']),17)
        self.assertEqual(report['native_registration_health']['status'],'PASS')
        self.assertEqual(report['original_package_source_integrity']['status'],'HISTORICAL_VERIFIED')
        self.assertFalse(report['original_package_source_integrity']['fresh_runtime_measurement'])
        self.assertEqual(report['executable_cache_extras']['trust'],'UNVERIFIED')
        self.assertEqual(report['executable_cache_extras']['historical_pyc_files'],76)
        self.assertEqual(report['original_provisioning']['status'],'FAIL')
        self.assertEqual(report['original_provisioning']['complete_records'],0)
        self.assertEqual(report['qualification'],'not_qualified');self.assertFalse(report['auto_keep_authorized'])
        self.assertEqual((cache/'untrusted.pyc').read_bytes(),b'untrusted synthetic bytes')
        self.assert_no_mutation()

    def test_missing_package_refuses(self):
        self.native.pop(next(iter(self.native)))
        with self.assertRaises(host.HelperError):self.run_health()
        self.assert_no_mutation()

    def test_wrong_version_refuses(self):
        next(iter(self.native.values()))['version']='9.9.9'
        with self.assertRaisesRegex(host.HelperError,'addon_view_mismatch'):self.run_health()
        self.assert_no_mutation()

    def test_disabled_package_refuses(self):
        self.native['skin.arctic.fuse.3']['enabled']=False
        with self.assertRaisesRegex(host.HelperError,'addon_view_mismatch'):self.run_health()
        self.assert_no_mutation()

    def test_broken_package_refuses(self):
        self.native['script.module.infotagger']['broken']=True
        with self.assertRaisesRegex(host.HelperError,'addon_view_mismatch'):self.run_health()
        self.assert_no_mutation()

    def test_malformed_native_fields_refuse_without_echo(self):
        next(iter(self.native.values())).pop('broken')
        with self.assertRaisesRegex(host.HelperError,'rpc_response_invalid'):self.run_health()
        self.assert_no_mutation()

    def test_unchallenged_connection_refuses_before_adapter_dispatch(self):
        self.w.transport.password=None
        with self.assertRaisesRegex(host.HelperError,'rpc_auth_failed'):self.run_health()
        self.assertEqual(self.w.executed,[]);self.assertEqual(self.journal.read_bytes(),self.original_journal)

    def test_wrong_credentials_refuse_before_dispatch(self):
        self.w.password_to_return='wrong-synthetic-password'
        with self.assertRaisesRegex(host.HelperError,'rpc_auth_failed'):self.run_health()
        self.assertEqual(self.w.executed,[])

    def test_wrong_listener_refuses_before_dispatch(self):
        self.w.listener_pids={991122}
        with self.assertRaisesRegex(host.HelperError,'listener_pid_mismatch'):self.run_health()
        self.assertEqual(self.w.executed,[])

    def test_wrong_source_refuses_before_dispatch(self):
        path=self.w.target.addon_dir(host.BUILD_MANAGER_ID)/'default.py';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(host.HelperError,'installed_tree_mismatch'):self.run_health()
        self.assertEqual(self.w.executed,[])

    def test_wrong_manifest_or_missing_git_binding_refuses(self):
        for changes in ({'manifest_sha256':'0'*64},{'git_repo':None}):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(host.HelperError,'argument_invalid'):self.run_health(**changes)
        self.assertEqual(self.w.executed,[])

    def test_changed_failed_journal_refuses_without_dispatch_or_repair(self):
        self.journal.write_bytes(self.original_journal+b'\n')
        with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):self.run_health()
        self.assertEqual(self.journal.read_bytes(),self.original_journal+b'\n');self.assertEqual(self.w.executed,[])

    def test_final_journal_change_refuses_and_preserves_changed_evidence(self):
        original=self.w.transport.handler
        def handler(request):
            if request['body']['method']=='Settings.GetSettingValue' and len(self.w.methods())>22:
                self.journal.write_bytes(self.original_journal+b'\n')
            return original(request)
        self.w.transport.handler=handler
        with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):self.run_health()
        self.assertEqual(self.journal.read_bytes(),self.original_journal+b'\n')

    def test_wrong_skin_or_updater_refuses(self):
        self.settings['general.addonupdates']=0
        with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):self.run_health()
        self.assert_no_mutation()

    def test_wrong_skin_refuses_without_switching_it(self):
        self.settings['lookandfeel.skin']='skin.arctic.fuse.3'
        with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):self.run_health()
        self.assertEqual(self.settings['lookandfeel.skin'],'skin.arctic.fuse.3');self.assert_no_mutation()

    def test_noninteger_updater_refuses(self):
        self.settings['general.addonupdates']=True
        with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):self.run_health()
        self.assert_no_mutation()

    def test_nonboolean_enabled_field_refuses(self):
        next(iter(self.native.values()))['enabled']=1
        with self.assertRaisesRegex(host.HelperError,'rpc_response_invalid'):self.run_health()
        self.assert_no_mutation()

    def test_transient_product_change_during_health_reads_refuses(self):
        original=self.w.transport.handler
        path=self.w.target.addon_dir(host.BUILD_MANAGER_ID)/'default.py';data=path.read_bytes()
        def handler(request):
            if (request['body']['method']=='Addons.GetAddonDetails'
                    and request['body']['params']['addonid']=='skin.arctic.fuse.3'):
                path.write_bytes(data+b'\n');path.write_bytes(data)
            return original(request)
        self.w.transport.handler=handler
        with self.assertRaisesRegex(host.HelperError,'platform_source_changed'):self.run_health()
        self.assertEqual(path.read_bytes(),data);self.assert_no_mutation()

    def test_wrong_running_build_refuses(self):
        self.version['revision']='different-build'
        with self.assertRaisesRegex(host.HelperError,'platform_build_mismatch'):self.run_health()
        self.assert_no_mutation()

    def test_cli_dispatches_only_the_read_only_health_surface(self):
        manifest=self.w.tc.tmp/'health-manifest.json'
        data=json.dumps(self.w.manifest,sort_keys=True).encode();manifest.write_bytes(data)
        with patch.object(host,'_AF3_HEALTH_STAGE_SHA',hashlib.sha256(data).hexdigest()):
            code,report,text=self.world.run_cli(self.w.services,'af3-health','--manifest',str(manifest),
                '--repo',str(self.world.FIXTURE.repo),'--rpc-host','127.0.0.1','--rpc-port','8080','--rpc-user','kodi')
        self.assertEqual(code,0);self.assertEqual(report['native_registration_health']['status'],'PASS')
        self.assertNotIn(self.world.SENTINEL_PASSWORD,text);self.assert_no_mutation()

    def test_platform_refusal_is_not_replaced_by_historical_audit(self):
        self.platform['ok']=False
        self.platform['platform_check']['overall']='unverified'
        self.platform['platform_check']['graph']={'status':'refused','failure_category':'platform_requirements_refused'}
        for row in self.platform['platform_check']['providers'].values():row['closure_status']='unverified'
        with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):self.run_health()
        self.assert_no_mutation()


class HistoricalEvidenceTests(unittest.TestCase):
    def test_exact_sealed_audit_remains_historical(self):
        result=READ_AUDIT()
        self.assertEqual(result['original_files'],4497);self.assertFalse(result['fresh_runtime_measurement'])

    def test_tampered_seal_and_member_refuse(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);original=host._AF3_HEALTH_AUDIT
            for path in original.iterdir():
                if path.is_file():shutil.copyfile(path,root/path.name)
            with patch.object(host,'_AF3_HEALTH_AUDIT',root):
                (root/'REPORT.md').write_bytes(b'changed')
                with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):READ_AUDIT()
                (root/'SHA256SUMS').write_bytes(b'changed')
                with self.assertRaisesRegex(host.HelperError,'af3_health_refused'):READ_AUDIT()

    def test_cli_has_no_tcp_no_git_bypass_or_recovery_options(self):
        parser=host.build_parser()
        for option in (['--rpc-transport','tcp'],['--no-git-binding'],['--recover']):
            with self.assertRaises(host.HelperError):parser.parse_args(['af3-health','--manifest','synthetic',*option])
