"""Foreground protocol tests with synthetic bundles, pipes and receipts only."""
import copy
import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests import test_bm_test_app as fixtures
from tests import test_bm_public_preservation_witness as semantic
from tools import bm_test_app as bm
from tools import bm_preservation_acquisition as bridge
from tools import bm_preservation_driver as driver

SECRET = 'synthetic-private-driver-value'
EXACT_ROWS = [('EXACT', (), 0)] * 5


def practical_block(*rows):
    """Five (classification, maintenance pairs, meaningful count) rows in witness order."""
    files = [{'file': name, 'classification': label, 'maintenance': [list(pair) for pair in pairs],
              'meaningful_count': count}
             for name, (label, pairs, count) in zip(semantic.w.FILES, rows)]
    labels = {row['classification'] for row in files}
    aggregate = next((label for label in ('INCONCLUSIVE', 'MEANINGFUL', 'MAINTENANCE_ONLY')
                      if label in labels), 'EXACT')
    return {'schema': 'bm-a15-practical-classification/1', 'classification': aggregate,
            'files': files, 'verdict': 'NOT_DECIDED', 'qualification': 'not_qualified'}


def public_witness():
    """Synthetic public witnesses with the shape public_state returns."""
    return {'bundle': {'identifier': 'org.xbmc.kodi'},
            'settings': {'readable': True, 'active_skin': 'skin.estuary', 'updater_policy': 'NOTIFY_ONLY'},
            'addons': {'count': 1, 'enabled_state_source': 'addons_db', 'id_mismatch': 0,
                       'skipped_invalid_names': 0, 'skipped_non_directories': 0, 'unreadable_addon_xml': 0,
                       'entries': [{'enabled': True, 'id': 'script.synthetic', 'version': '1.0.0'}]},
            'library': {'root_present': True,
                        'registry': {'file_present': True, 'sha256': 'a' * 64, 'size': 120,
                                     'entry_count': 1, 'entry_ids': ['build-one']},
                        'selection': {'file_present': True, 'selected': True, 'sha256': 'b' * 64,
                                      'size': 30, 'entry_id': 'build-one', 'device_profile_id': 'profile-one'}},
            'trees': {'build-library': {'registry.json': 'c' * 64},
                      'install_resolutions': {'resolution.json': 'd' * 64},
                      'frozen-artifacts': {'artifact.json': 'e' * 64}},
            'association': {'entry_id': 'build-one', 'artifact': 'f' * 64},
            'selection': ('build-one', 'profile-one'),
            'owners_absent': True, 'pending_publication_absent': True}


def precondition_entry(block, identifier):
    return next(item for item in block['prerequisites'] if item['id'] == identifier)


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
        self.invocation_patch = mock.patch.object(driver, 'trusted_invocation')
        self.invocation = self.invocation_patch.start()
        self.host_patch = mock.patch.object(driver, 'host_source')
        self.host = self.host_patch.start()
        mock.patch.object(bm, 'load_manifest', return_value=(self.manifest,'b'*64)).start()
        self.public = public_witness()
        self.public_patch = mock.patch.object(driver, 'public_state', return_value=self.public)
        self.public_call = self.public_patch.start()
        self.calls = []
        self.begin_result = bridge._result('before','ACQUIRED','baseline_held_in_memory')
        self.after_result = bridge._result('after','ACQUIRED','scoped_comparison',['PRESERVED']*5,
                                           practical=practical_block(*EXACT_ROWS))
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
        self.assertEqual(result['native_run_attribution'],'UNVERIFIED')
        self.assertIs(result['external_native_evidence_required'],True)
        self.assertIs(result['receipt_form_and_file_time_validated'],True)
        self.assertNotIn('graceful_receipt_validated',result)

    def test_false_success_or_graceful_quit_receipt_never_finishes(self):
        for flag in ('ok', 'graceful'):
            with self.subTest(flag=flag):
                self.evidence = self.tmp / '.qualification-evidence' / ('false-' + flag)
                self.output.seek(0); self.output.truncate(0); self.calls.clear()
                self.receipt_change = lambda value, key=flag: value.update({key: False})
                self.blocked('quit_unverified')
                self.assertEqual(self.calls, ['begin', 'close'])
                self.assertNotIn('finish', self.calls)

    def test_review_p01_recopy_old_receipt_only_proves_form_and_file_time(self):
        destination = self.evidence
        self.evidence = self.tmp/'earlier-window'; self.evidence.mkdir()
        self.write_receipt()
        earlier = (self.evidence/'quit.json').read_bytes()
        self.evidence = destination
        def replay():
            path = self.evidence/'quit.json'
            path.write_bytes(earlier); path.chmod(0o600)
        self.write_receipt = replay
        code,result = self.run_driver()
        self.assertEqual(code,0)
        self.assertEqual(result['state'],'SCOPED_PRESERVED')
        self.assertEqual(result['native_run_attribution'],'UNVERIFIED')
        self.assertTrue(result['external_native_evidence_required'])
        self.assertNotIn('graceful_receipt_validated',result)

    def test_review_p03_future_dated_receipt_is_refused(self):
        original = self.write_receipt
        def future():
            original()
            stamp = driver.time.time_ns() + 3600 * 10**9
            os.utime(self.evidence/'quit.json',ns=(stamp,stamp))
        self.write_receipt = future
        self.blocked('quit_unverified'); self.assertNotIn('finish',self.calls)

    def test_review_l02_finish_queued_during_begin_refuses_before_ready(self):
        original = self.session.begin
        def queued():
            os.write(self.w,b'FINISH\n')
            return original()
        self.session.begin = queued
        self.blocked('protocol_invalid')
        self.assertNotIn('READY',self.output.getvalue())
        self.assertEqual(self.calls,['begin','close'])

    def test_zero_native_activity_after_ready_can_only_be_scoped_preservation(self):
        # Default fake writes a receipt and FINISH directly at READY: no native UI.
        code,result = self.run_driver()
        self.assertEqual(code,0)
        self.assertEqual(result['native_run_attribution'],'UNVERIFIED')
        self.assertTrue(result['external_native_evidence_required'])

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

    def test_review_n13_after_state_alone_refuses_with_count_still_zero(self):
        self.receipt_change = lambda value:value['identity_after']['process'].update(state='running_portable')
        self.blocked('quit_unverified'); self.assertNotIn('finish',self.calls)

    def test_review_n13_after_count_alone_refuses_with_state_still_stopped(self):
        self.receipt_change = lambda value:value['identity_after']['process'].update(test_app_process_count=1)
        self.blocked('quit_unverified'); self.assertNotIn('finish',self.calls)

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
                                         ['PRESERVED']*4+['CHANGED_OR_MISSING'],
                                         practical=practical_block(*(EXACT_ROWS[:4]+[('MEANINGFUL',(),1)])))
        self.blocked('changed')

    def reset_run(self, name):
        self.evidence = self.tmp / '.qualification-evidence' / name
        self.output.seek(0); self.output.truncate(0); self.calls.clear()

    def test_practical_block_is_validated_and_persisted_beside_the_strict_result(self):
        code, result = self.run_driver()
        self.assertEqual(code, 0)
        self.assertEqual(result['state'], 'SCOPED_PRESERVED')
        self.assertEqual(result['after']['scope_result'], 'PRESERVED')
        practical = result['after']['practical']
        self.assertEqual(practical['classification'], 'EXACT')
        self.assertEqual(practical['verdict'], 'NOT_DECIDED')
        self.assertEqual(practical['qualification'], 'not_qualified')
        self.assertEqual([row['file'] for row in practical['files']], list(semantic.w.FILES))

    def test_maintenance_beside_a_strict_change_keeps_the_strict_refusal(self):
        rows = list(EXACT_ROWS)
        rows[2] = ('MAINTENANCE_ONLY', (('M1_UPTIME', 1),), 0)
        self.after_result = bridge._result('after','ACQUIRED','scoped_comparison',
                                           ['PRESERVED','PRESERVED','CHANGED_OR_MISSING','PRESERVED','PRESERVED'],
                                           practical=practical_block(*rows))
        code, result = self.run_driver()
        self.assertNotEqual(code, 0)
        self.assertEqual(result['state'], 'INCONCLUSIVE')
        self.assertEqual(result['reason'], 'changed')
        self.assertEqual(result['after']['practical']['classification'], 'MAINTENANCE_ONLY')
        self.assertEqual(result['after']['practical']['files'][2]['maintenance'], [['M1_UPTIME', 1]])

    def test_comparator_rejection_is_recorded_inconclusive_and_never_a_practical_pass(self):
        rows = [('INCONCLUSIVE', (), 0)] + EXACT_ROWS[1:]
        self.after_result = bridge._result('after','ACQUIRED','scoped_comparison',['PRESERVED']*5,
                                           practical=practical_block(*rows))
        code, result = self.run_driver()
        # The strict gate is unchanged, so a strict PRESERVED scope keeps its strict state.
        self.assertEqual(code, 0)
        self.assertEqual(result['state'], 'SCOPED_PRESERVED')
        practical = result['after']['practical']
        self.assertEqual(practical['classification'], 'INCONCLUSIVE')
        self.assertEqual(practical['verdict'], 'NOT_DECIDED')

    def test_malformed_practical_blocks_refuse_and_are_never_persisted(self):
        def first(block):
            return block['files'][0]
        cases = {
            'extra_top_level_field': lambda b: b.update(raw_private=SECRET),
            'pass_verdict': lambda b: b.update(verdict='PASS'),
            'wrong_schema': lambda b: b.update(schema='bm-a15-practical-classification/0'),
            'aggregate_mismatch': lambda b: b.update(classification='MAINTENANCE_ONLY'),
            'row_name_mismatch': lambda b: first(b).update(file='other.xml'),
            'extra_row_field': lambda b: first(b).update(path=SECRET),
            'unknown_label': lambda b: first(b).update(classification='PASS'),
            'unknown_class_name': lambda b: first(b).update(
                classification='MAINTENANCE_ONLY', maintenance=[[SECRET, 1]]),
            'bool_count': lambda b: first(b).update(
                classification='MAINTENANCE_ONLY', maintenance=[['M1_UPTIME', True]]),
            'zero_count': lambda b: first(b).update(
                classification='MAINTENANCE_ONLY', maintenance=[['M1_UPTIME', 0]]),
            'duplicate_class': lambda b: first(b).update(
                classification='MAINTENANCE_ONLY', maintenance=[['M1_UPTIME', 1], ['M1_UPTIME', 1]]),
            'unsorted_classes': lambda b: first(b).update(
                classification='MAINTENANCE_ONLY', maintenance=[['M2_SIZES_USECOUNT', 1], ['M1_UPTIME', 1]]),
            'exact_with_count': lambda b: first(b).update(meaningful_count=1),
            'meaningful_without_count': lambda b: first(b).update(
                classification='MEANINGFUL', meaningful_count=0),
            'meaningful_with_maintenance': lambda b: first(b).update(
                classification='MEANINGFUL', maintenance=[['M1_UPTIME', 1]], meaningful_count=1),
            'missing_row': lambda b: b['files'].pop(),
        }
        for name, edit in cases.items():
            with self.subTest(case=name):
                block = practical_block(*EXACT_ROWS)
                edit(block)
                self.reset_run('malformed-' + name)
                self.after_result = bridge._result('after','ACQUIRED','scoped_comparison',['PRESERVED']*5,
                                                   practical=block)
                result = self.blocked('finish_refused')
                self.assertNotIn('after', result)

    def test_failed_after_has_no_practical_acceptance(self):
        self.after_result = bridge._result('after','FAILED','acquisition_failed',
                                           practical=practical_block(*EXACT_ROWS))
        self.blocked('finish_refused')
        self.reset_run('failed-after-with-practical')
        self.after_result = bridge._result('after','FAILED','acquisition_failed')
        self.blocked('finish_refused')

    def test_practical_inconsistent_with_the_strict_status_refuses(self):
        cases = {
            'meaningful_under_preserved': (['PRESERVED']*5, [('MEANINGFUL',(),1)] + EXACT_ROWS[1:]),
            'exact_under_changed': (['CHANGED_OR_MISSING']+['PRESERVED']*4, EXACT_ROWS),
        }
        for name, (statuses, rows) in cases.items():
            with self.subTest(case=name):
                self.reset_run('inconsistent-' + name)
                self.after_result = bridge._result('after','ACQUIRED','scoped_comparison', statuses,
                                                   practical=practical_block(*rows))
                self.blocked('finish_refused')

    def test_maintenance_class_on_the_wrong_file_is_refused(self):
        # Each class name is closed and valid on some file, but not on this one. The strict
        # status is CHANGED so that only the per-file vocabulary can refuse the block.
        m1, m2 = ('M1_UPTIME', 1), ('M2_SIZES_USECOUNT', 1)
        cases = {
            'm1_on_addons33': (0, (m1,)), 'm1_on_textures13': (1, (m1,)),
            'm1_on_estuary': (3, (m1,)), 'm1_on_keyboard': (4, (m1,)),
            'm2_on_addons33': (0, (m2,)), 'm2_on_guisettings': (2, (m2,)),
            'm2_on_estuary': (3, (m2,)), 'm2_on_keyboard': (4, (m2,)),
        }
        for name, (index, pairs) in cases.items():
            with self.subTest(case=name):
                self.reset_run('wrong-file-' + name)
                rows = list(EXACT_ROWS)
                rows[index] = ('MAINTENANCE_ONLY', pairs, 0)
                statuses = ['PRESERVED'] * 5
                statuses[index] = 'CHANGED_OR_MISSING'
                self.after_result = bridge._result('after','ACQUIRED','scoped_comparison', statuses,
                                                   practical=practical_block(*rows))
                result = self.blocked('finish_refused')
                self.assertNotIn('after', result)

    def test_valid_maintenance_classes_on_their_own_file_still_pass(self):
        m2 = ['M2_SIZES_USECOUNT', 'M2_SIZES_LASTUSETIME', 'M2_TEXTURE_LASTHASHCHECK',
              'M2_CACHE_ROW_CREATE', 'M2_CACHE_ROW_EVICT', 'M2_CACHE_SIZES_CREATE', 'M2_CACHE_SIZES_EVICT']
        cases = [(2, ('M1_UPTIME', 1))] + [(1, (name, 1)) for name in m2]
        for index, pair in cases:
            with self.subTest(file=index, cls=pair[0]):
                self.reset_run('valid-' + pair[0])
                rows = list(EXACT_ROWS)
                rows[index] = ('MAINTENANCE_ONLY', (pair,), 0)
                statuses = ['PRESERVED'] * 5
                statuses[index] = 'CHANGED_OR_MISSING'
                self.after_result = bridge._result('after','ACQUIRED','scoped_comparison', statuses,
                                                   practical=practical_block(*rows))
                code, result = self.run_driver()
                # The strict gate still refuses the changed file, exactly as before.
                self.assertNotEqual(code, 0)
                self.assertEqual((result['state'], result['reason']), ('INCONCLUSIVE', 'changed'))
                row = result['after']['practical']['files'][index]
                self.assertEqual(row['classification'], 'MAINTENANCE_ONLY')
                self.assertEqual(row['maintenance'], [list(pair)])
                self.assertEqual(result['after']['practical']['verdict'], 'NOT_DECIDED')

    def test_host_source_binds_the_practical_comparator(self):
        self.assertIn('tools/bm_practical_preservation_comparator.py', driver.HOST_PATHS)

    def test_precondition_is_recorded_beside_the_unchanged_strict_outcome(self):
        code, result = self.run_driver()
        self.assertEqual(code, 0)
        self.assertEqual(result['state'], 'SCOPED_PRESERVED')
        self.assertEqual(result['reason'], 'scoped_comparison')
        block = result['practical_precondition']
        self.assertEqual(block['assessment'], 'INCONCLUSIVE')
        self.assertEqual(block['reason'], 'prerequisite_unverified')
        for identifier in ('S1', 'S2', 'S5', 'S7', 'FIVE_FILE'):
            self.assertEqual(precondition_entry(block, identifier)['status'], 'MET', identifier)
        self.assertEqual(precondition_entry(block, 'OPERATION_CORRELATION')['status'], 'UNVERIFIED')
        self.assertNotIn('practical_precondition', result['after'])
        self.assertEqual(result['after']['practical']['verdict'], 'NOT_DECIDED')

    def test_changed_library_keeps_the_strict_refusal_and_records_s1_not_met(self):
        changed = copy.deepcopy(self.public)
        changed['library']['registry']['sha256'] = '0' * 64
        self.public_call.side_effect = [self.public, changed]
        code, result = self.run_driver()
        self.assertNotEqual(code, 0)
        self.assertEqual(result['state'], 'INCONCLUSIVE')
        self.assertEqual(result['reason'], 'changed')
        self.assertEqual(precondition_entry(result['practical_precondition'], 'S1')['status'], 'NOT_MET')
        self.assertEqual(result['practical_precondition']['reason'], 'prerequisite_not_met')

    def test_refused_finish_records_a_not_reached_precondition(self):
        self.after_result = bridge._result('after', 'FAILED', 'acquisition_failed')
        result = self.blocked('finish_refused')
        self.assertEqual(result['practical_precondition']['assessment'], 'INCONCLUSIVE')
        self.assertEqual(result['practical_precondition']['reason'], 'not_reached')

    def test_malformed_public_witness_fails_closed_without_changing_the_strict_outcome(self):
        self.public_call.return_value = {'bundle': self.public['bundle'], 'public': 'same'}
        code, result = self.run_driver()
        self.assertEqual(code, 0)
        self.assertEqual(result['state'], 'SCOPED_PRESERVED')
        self.assertEqual(result['practical_precondition']['assessment'], 'INCONCLUSIVE')
        self.assertEqual(result['practical_precondition']['reason'], 'input_invalid')

    def test_host_source_binds_the_precondition_module(self):
        self.assertIn('tools/bm_practical_precondition.py', driver.HOST_PATHS)

    def test_real_host_git_provenance_rejects_precondition_tampering(self):
        self.host_patch.stop()
        repo, commit = fixtures.build_candidate_repo(self.tmp)
        with mock.patch.object(driver,'REPO',repo):
            driver.host_source(self.services,commit)
            (repo/'tools/bm_practical_precondition.py').write_text('# changed')
            with self.assertRaises(driver.Refused):driver.host_source(self.services,commit)

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

    def test_review_n14_replaced_directory_gets_no_durable_output_at_either_path(self):
        original = self.session.begin
        moved = self.evidence.with_name('moved')
        def replace():
            self.evidence.rename(moved); self.evidence.mkdir(mode=0o700)
            return original()
        self.session.begin = replace
        self.blocked(); self.assertNotIn('READY',self.output.getvalue())
        for root in (moved,self.evidence):
            self.assertFalse((root/'ready.json').exists())
            self.assertFalse((root/'result.json').exists())

    def test_ready_directory_fsync_failure_never_announces_ready(self):
        original = os.fsync; count = [0]
        def fail_directory(fd):
            count[0] += 1
            if count[0] == 2: raise OSError(SECRET)
            return original(fd)
        with mock.patch.object(driver.os,'fsync',side_effect=fail_directory): self.blocked()
        self.assertNotIn('READY',self.output.getvalue())
        self.assertNotIn('finish',self.calls)

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
        repo, commit = fixtures.build_candidate_repo(self.tmp)
        source = Path(driver.__file__).read_bytes()
        self.assertEqual((repo/'tools/bm_preservation_driver.py').read_bytes(), source)
        fixtures.git(repo,'ls-files','--error-unmatch','tools/bm_preservation_driver.py')
        with mock.patch.object(driver,'REPO',repo):
            driver.host_source(self.services,commit)
            (repo/'tools/bm_preservation_acquisition.py').write_text('# changed')
            with self.assertRaises(driver.Refused):driver.host_source(self.services,commit)

    def test_real_host_git_provenance_rejects_comparator_tampering(self):
        self.host_patch.stop()
        repo, commit = fixtures.build_candidate_repo(self.tmp)
        with mock.patch.object(driver,'REPO',repo):
            driver.host_source(self.services,commit)
            (repo/'tools/bm_practical_preservation_comparator.py').write_text('# changed')
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
        self.assertEqual(result['after']['practical']['classification'],'EXACT')

    def path(self, root, i):
        return root / semantic.w.FILES[i]

    def test_invalid_cli_does_not_construct_native_services_or_echo_input(self):
        with mock.patch.object(bm.Services,'production') as production, \
             mock.patch('sys.stdout',io.StringIO()) as out, mock.patch('sys.stderr',io.StringIO()) as err:
            self.assertEqual(driver.main(['--invalid',SECRET]),2)
        production.assert_not_called()
        self.assertNotIn(SECRET,out.getvalue()+err.getvalue())

    def test_help_is_informational_nonzero_without_services_or_evidence(self):
        for option in ('--help','-h'):
            with mock.patch.object(bm.Services,'production') as production, \
                 mock.patch('sys.stdout',io.StringIO()) as out:
                self.assertEqual(driver.main([option]),2)
            production.assert_not_called()
            self.assertFalse(self.evidence.exists())
            self.assertNotIn('READY',out.getvalue())

    def test_fixed_checkout_and_import_origin_checks_before_work(self):
        self.invocation_patch.stop()
        with mock.patch.object(driver,'REPO',fixtures.PROJECT):
            driver.trusted_invocation()
            with mock.patch.object(Path,'cwd',return_value=self.tmp), self.assertRaises(driver.Refused):
                driver.trusted_invocation()
            foreign = SimpleNamespace(__file__=str(self.tmp/'foreign.py'))
            with mock.patch.dict(sys.modules,{'tools.foreign':foreign}), self.assertRaises(driver.Refused):
                driver.trusted_invocation()
            with mock.patch.object(driver,'__file__',str(self.tmp/'bm_preservation_driver.py')), \
                 self.assertRaises(driver.Refused): driver.trusted_invocation()

    def test_discovery_preserves_strict_checkout_and_import_origin_checks(self):
        self.invocation_patch.stop()
        # Import every test module, but never execute the complete suite here.
        suite = unittest.defaultTestLoader.discover(str(fixtures.PROJECT / 'tests'),
                                                   top_level_dir=str(fixtures.PROJECT))
        self.assertGreater(suite.countTestCases(), 0)
        with mock.patch.object(driver, 'REPO', fixtures.PROJECT):
            driver.trusted_invocation()

    def test_noncanonical_test_import_path_is_still_refused(self):
        self.invocation_patch.stop()
        alias = str(fixtures.PROJECT / 'tests' / '..')
        with mock.patch.object(driver, 'REPO', fixtures.PROJECT):
            with mock.patch.object(sys, 'path', [alias, *sys.path]), self.assertRaises(driver.Refused):
                driver.trusted_invocation()
            driver.trusted_invocation()

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
