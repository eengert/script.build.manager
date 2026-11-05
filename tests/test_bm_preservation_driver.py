"""Foreground protocol tests with synthetic bundles, pipes and receipts only."""
import copy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests import test_bm_test_app as fixtures
from tests import test_bm_public_preservation_witness as semantic
from tools import bm_test_app as bm
from tools import bm_preservation_acquisition as bridge
from tools import bm_preservation_driver as driver

SECRET = 'synthetic-private-driver-value'


class DriverTests(fixtures.TripwireTestCase):
    def setUp(self):
        super().setUp()
        fake = fixtures.make_fake_app(self.tmp)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(bm, 'AUTHORIZED_TEST_APP', str(fake.root)).start()
        self.target = bm.TestAppTarget(fake.root, production=True)
        self.services = fixtures.make_services(self.target)
        mock.patch.object(driver, 'REPO', self.tmp).start()
        (self.tmp/'.qualification-evidence').mkdir()
        self.evidence = self.tmp/'.qualification-evidence'/'run'
        self.manifest = {'candidate':{'commit':'a'*40}}
        self.host_patch = mock.patch.object(driver, 'host_source')
        self.host = self.host_patch.start()
        mock.patch.object(bm, 'load_manifest', return_value=(self.manifest,'b'*64)).start()
        self.public = {'bundle':{'identifier':'org.xbmc.kodi'},'public':'same'}
        self.public_patch = mock.patch.object(driver, 'public_state', return_value=self.public)
        self.public_call = self.public_patch.start()
        self.calls = []
        self.begin_result = bridge._result('before','ACQUIRED','baseline_held_in_memory')
        self.after_result = bridge._result('after','ACQUIRED','scoped_comparison',['PRESERVED']*5)
        owner = self
        class Session:
            def begin(self): owner.calls.append('begin'); return owner.begin_result
            def finish(self): owner.calls.append('finish'); return owner.after_result
            def close(self): owner.calls.append('close')
        self.session = Session()
        self.factory_patch = mock.patch.object(driver, 'AcquisitionSession', return_value=self.session)
        self.factory = self.factory_patch.start()
        r, self.w = os.pipe(); self.signals = os.fdopen(r,'rb',buffering=0)
        self.addCleanup(self.signals.close); self.addCleanup(self.close_writer)
        self.signal = b'FINISH\n'; self.receipt = True; self.receipt_change = lambda x: None
        class Output(io.StringIO):
            def write(self, text):
                result = super().write(text)
                if text == 'READY\n':
                    if owner.receipt: owner.write_receipt()
                    if owner.signal is None: owner.close_writer()
                    else: os.write(owner.w, owner.signal)
                return result
        self.output = Output()

    def close_writer(self):
        if self.w is not None:
            w, self.w = self.w, None; os.close(w)

    def write_receipt(self):
        value = {'schema':bm.OUTPUT_SCHEMA,'tool':bm.tool_identity(),'command':'quit','ok':True,'graceful':True,
            'identity_before':{'bundle':self.public['bundle'],'process':{
                'state':'running_portable','portable_flag':True,'pid':99,'test_app_process_count':1}},
            'identity_after':{'bundle':self.public['bundle'],'process':{
                'state':'not_running','test_app_process_count':0}},
            'invocation':{'authenticated':True,'listener_pid_verified':True,
                          'method':'Application.Quit','test_app_pid':99},
            'shutdown':{'accepted':True,'exited':True,'forced_termination':False}}
        self.receipt_change(value)
        path = self.evidence/'quit.json'
        path.write_text(json.dumps(value)); path.chmod(0o600)

    def run_driver(self):
        code = driver.run(self.services, manifest_path=self.tmp/'manifest.json',
                          evidence_path=self.evidence, host_commit='c'*40,
                          signals=self.signals, output=self.output)
        texts = [self.output.getvalue()]
        result = None
        for name in ('ready.json','result.json'):
            path = self.evidence/name
            if path.exists():
                texts.append(path.read_text())
                if name == 'result.json': result = json.loads(texts[-1])
        self.assertNotIn(SECRET, ''.join(texts))
        return code, result

    def blocked(self, reason=None):
        code, result = self.run_driver()
        self.assertNotEqual(code, 0)
        if result is not None:
            self.assertEqual(result['state'], 'INCONCLUSIVE')
            if reason: self.assertEqual(result['reason'], reason)
        return result

    def test_success_uses_same_session_once_and_emits_only_scoped_result(self):
        code, result = self.run_driver()
        self.assertEqual(code,0)
        self.assertEqual(result['state'],'SCOPED_PRESERVED')
        self.assertEqual(result['complete_preservation'],'UNVERIFIED')
        self.assertEqual(result['qualification'],'not_qualified')
        self.assertEqual(self.calls,['begin','finish','close'])
        self.factory.assert_called_once()
        self.assertEqual(self.output.getvalue(),'READY\nDONE\n')
        self.assertEqual(self.public_call.call_count,2)
        self.assertEqual(self.host.call_count,2)

    def test_begin_refusal_including_returned_cancellation_never_announces_ready(self):
        self.begin_result = bridge._result('before','FAILED','acquisition_failed')
        self.blocked('begin_refused')
        self.assertNotIn('READY', self.output.getvalue())
        self.assertNotIn('finish',self.calls)

    def test_finish_refusal_is_not_success(self):
        self.after_result = bridge._result('after','REFUSED','input_changed')
        self.blocked('finish_refused'); self.assertEqual(self.calls.count('finish'),1)

    def test_cancel_discards_baseline_without_finishing(self):
        self.signal = b'CANCEL\n'; self.blocked('cancelled')
        self.assertEqual(self.calls,['begin','close'])

    def test_eof_process_controller_loss_is_inconclusive(self):
        self.signal = None; self.blocked('eof')
        self.assertNotIn('finish',self.calls)

    def test_timeout_never_controls_kodi_or_finishes(self):
        self.signal = b''
        with mock.patch.object(driver,'WAIT_SECONDS',0.01): self.blocked('timeout')
        self.assertNotIn('finish',self.calls)

    def test_queued_out_of_order_signal_refuses_before_begin(self):
        os.write(self.w,b'FINISH\n')
        self.blocked('protocol_invalid'); self.assertEqual(self.calls,[])

    def test_repeated_signals_refuse_without_second_finish(self):
        self.signal = b'FINISH\nFINISH\n'; self.blocked('protocol_invalid')
        self.assertNotIn('finish',self.calls)

    def test_arbitrary_commands_are_never_executed_or_echoed(self):
        self.signal = (SECRET+'\n').encode(); self.blocked('protocol_invalid')

    def test_missing_quit_receipt_blocks_before_finish(self):
        self.receipt = False; self.blocked()
        self.assertNotIn('finish',self.calls)

    def test_forced_quit_or_unauthenticated_receipt_refuses(self):
        self.receipt_change = lambda value: value['shutdown'].update(forced_termination=True)
        self.blocked('quit_unverified'); self.assertNotIn('finish',self.calls)

    def test_wrong_bundle_receipt_refuses(self):
        self.receipt_change = lambda value: value['identity_after'].update(bundle={'wrong':True})
        self.blocked('quit_unverified')

    def test_unauthenticated_receipt_refuses(self):
        self.receipt_change = lambda value: value['invocation'].update(authenticated=False)
        self.blocked('quit_unverified'); self.assertNotIn('finish',self.calls)

    def test_pre_ready_receipt_is_not_adopted(self):
        def premature(*args):
            self.write_receipt()
            return self.public
        self.public_call.side_effect = premature
        self.blocked('quit_unverified'); self.assertNotIn('READY',self.output.getvalue())

    def test_stale_or_insecure_receipt_refuses(self):
        original = self.write_receipt
        def stale():
            original(); os.utime(self.evidence/'quit.json',ns=(1,1))
        self.write_receipt = stale
        self.blocked('quit_unverified'); self.assertNotIn('finish',self.calls)

    def test_symlink_quit_receipt_is_not_followed(self):
        original = self.write_receipt
        def linked():
            original()
            path = self.evidence/'quit.json'; saved = self.tmp/'saved-quit.json'
            path.rename(saved); path.symlink_to(saved)
        self.write_receipt = linked
        self.blocked(); self.assertNotIn('finish',self.calls)

    def test_unexpected_quit_fields_are_refused_without_echo(self):
        self.receipt_change = lambda value: value.update(raw=SECRET)
        self.blocked('quit_unverified')

    def test_public_admission_failure_before_or_after_refuses(self):
        self.public_call.side_effect = [self.public, RuntimeError(SECRET)]
        self.blocked(); self.assertNotIn('finish',self.calls)

    def test_missing_public_baseline_never_readies(self):
        self.public_call.side_effect = RuntimeError(SECRET)
        self.blocked(); self.assertEqual(self.calls,[])

    def test_public_change_cannot_be_promoted_by_bridge_equality(self):
        self.public_call.side_effect = [self.public, {'bundle':self.public['bundle'],'public':'changed'}]
        self.blocked('changed')

    def test_semantic_change_is_not_harmless_maintenance(self):
        self.after_result = bridge._result('after','ACQUIRED','scoped_comparison',
                                         ['PRESERVED']*4+['CHANGED_OR_MISSING'])
        self.blocked('changed')

    def test_host_source_drift_blocks_before_finish(self):
        self.host.side_effect = [None, RuntimeError(SECRET)]
        self.blocked(); self.assertNotIn('finish',self.calls)

    def test_exception_or_session_loss_does_not_leak_private_baseline(self):
        self.session.finish = mock.Mock(side_effect=SystemExit(SECRET))
        self.blocked('interrupted'); self.assertEqual(self.calls,['begin','close'])

    def test_keyboard_interrupt_still_closes_session(self):
        with mock.patch.object(driver,'wait_signal',side_effect=KeyboardInterrupt()):
            self.blocked('interrupted')
        self.assertEqual(self.calls,['begin','close'])

    def test_cleanup_failure_invalidates_success(self):
        self.session.close = mock.Mock(side_effect=RuntimeError(SECRET))
        self.blocked('cleanup_failed')

    def test_unexpected_bridge_fields_are_never_persisted(self):
        self.begin_result['raw_private'] = SECRET
        self.blocked('begin_refused')

    def test_private_or_contradictory_after_values_are_not_persisted(self):
        self.after_result['files'][0]['status'] = SECRET
        self.blocked('finish_refused')

    def test_contradictory_begin_reason_refuses(self):
        self.begin_result['reason'] = SECRET
        self.blocked('begin_refused')

    def test_fresh_evidence_is_required_and_existing_files_untouched(self):
        self.evidence.mkdir(); (self.evidence/'old').write_text('retained')
        self.blocked(); self.assertEqual((self.evidence/'old').read_text(),'retained')
        self.assertEqual(self.calls,[])

    def test_fresh_child_inside_historical_evidence_is_not_allowed(self):
        old = self.evidence.parent/'historical'; old.mkdir()
        (old/'retained').write_text('sealed')
        self.evidence = old/'new-child'
        self.blocked(); self.assertFalse(self.evidence.exists())
        self.assertEqual((old/'retained').read_text(),'sealed')
        self.assertEqual(self.calls,[])

    def test_ready_output_failure_cannot_authorize_finish(self):
        self.output.write = mock.Mock(side_effect=OSError(SECRET))
        self.blocked(); self.assertNotIn('finish',self.calls)

    def test_short_ready_output_does_not_finish(self):
        self.output.write = mock.Mock(return_value=1)
        self.blocked('output_failed'); self.assertNotIn('finish',self.calls)

    def test_symlinked_evidence_parent_is_refused_without_following(self):
        parent = self.evidence.parent; renamed = parent.with_name('saved-evidence')
        parent.rename(renamed); parent.symlink_to(renamed)
        self.blocked(); self.assertEqual(self.calls,[])

    def test_result_durability_failure_is_nonzero(self):
        original = driver.Evidence.write
        def write(evidence, name, value):
            if name == 'result.json': raise OSError(SECRET)
            return original(evidence,name,value)
        with mock.patch.object(driver.Evidence,'write',write): self.blocked()

    def test_evidence_close_failure_has_nonzero_exit_even_if_result_exists(self):
        close = driver.Evidence.close
        def failure(evidence):
            close(evidence); raise OSError(SECRET)
        with mock.patch.object(driver.Evidence,'close',failure):
            code, result = self.run_driver()
        self.assertEqual(code,2)
        self.assertEqual(result['state'],'SCOPED_PRESERVED')

    def test_real_host_git_provenance_rejects_source_tampering(self):
        self.host_patch.stop()
        repo, unused = fixtures.build_candidate_repo(self.tmp)
        source = Path(driver.__file__).read_bytes()
        (repo/'tools/bm_preservation_driver.py').write_bytes(source)
        fixtures.git(repo,'add','tools/bm_preservation_driver.py')
        fixtures.git(repo,'commit','-q','-m','driver fixture')
        commit = fixtures.git(repo,'rev-parse','HEAD').decode().strip()
        with mock.patch.object(driver,'REPO',repo):
            driver.host_source(self.services,commit)
            (repo/'tools/bm_preservation_acquisition.py').write_text('# changed')
            with self.assertRaises(driver.Refused):driver.host_source(self.services,commit)

    def test_unchanged_real_bridge_lifecycle_on_synthetic_five_file_profile(self):
        self.factory_patch.stop()
        semantic.PreservationTests.populate(self, self.target.portable_data)
        with mock.patch.object(bm,'validate_manifest',side_effect=lambda value:value), \
             mock.patch.object(bm,'verify_installed',return_value={
                 'installed_equals_candidate':True,'installed_equals_manifest':True,
                 'git_binding':{'checked':True,'ok':True}}):
            code, result = self.run_driver()
        self.assertEqual(code,0); self.assertEqual(result['state'],'SCOPED_PRESERVED')

    def path(self, root, i):
        return root / semantic.w.FILES[i]

    def test_invalid_cli_does_not_construct_native_services_or_echo_input(self):
        with mock.patch.object(bm.Services,'production') as production, \
             mock.patch('sys.stdout',io.StringIO()) as out, mock.patch('sys.stderr',io.StringIO()) as err:
            self.assertEqual(driver.main(['--invalid',SECRET]),2)
        production.assert_not_called()
        self.assertNotIn(SECRET,out.getvalue()+err.getvalue())

    def test_public_witness_composition_never_uses_creating_transaction_inspect(self):
        self.public_patch.stop()
        root = self.target.bm_data_dir; root.mkdir(parents=True)
        snapshot = {'ok':True,'stage_verification':{'installed_equals_candidate':True,
                    'installed_equals_manifest':True,'git_binding':{'checked':True,'ok':True}},
            'settings':{'readable':True,'active_skin':'skin.estuary','updater_policy':'NEVER_CHECK'},
            'installed_addons':{'enabled_state_source':'addons_db','unreadable_addon_xml':0,
                'id_mismatch':0,'skipped_invalid_names':0,'skipped_non_directories':0,'entries':[]},
            'build_library':{'root_present':True,'registry':{'file_present':True},
                             'selection':{'selected':True}},'identity':{'bundle':self.public['bundle']}}
        library = mock.Mock()
        library.pending_publication.return_value = None
        library.current_applied_association.return_value = SimpleNamespace(to_dict=lambda:{'public':'association'})
        library.selection_state.return_value = ('selected',SimpleNamespace(entry_id='a'*64,device_profile_id='public'))
        with mock.patch.object(bm,'run_snapshot',return_value=snapshot), \
             mock.patch.object(driver,'BuildLibrary',return_value=library), \
             mock.patch.object(driver.support,'_af3_public_tree',return_value={}), \
             mock.patch.object(driver.FrozenInstallStore,'inspect',side_effect=AssertionError('write lock')):
            driver.public_state(self.services,self.manifest,'b'*64)
            (root/'create_capture_transaction.json').write_text(SECRET)
            with self.assertRaises(driver.Refused):driver.public_state(self.services,self.manifest,'b'*64)
            self.assertFalse((root/'frozen_install_transaction.lock').exists())
