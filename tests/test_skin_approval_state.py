"""A11 dormant durable protocol: real store/locks, synthetic identity witnesses.

No runtime approval, source authentication provider, skin/configuration action,
or publication is supplied by this state foundation.
"""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from resources.lib.build_library import (BuildLibrary, LibraryInstallTarget, LibrarySource,
    AppliedBuildAssociation, isolated_library_install_authority)
from resources.lib.frozen_install import (FrozenInstallTransaction, FrozenInstallStore,
    FrozenInstallPhase as P, FrozenInstallCoordinator, FrozenInstallStateConflict,
    run_frozen_install_startup)
from resources.lib.skin_approval_state import (SkinApprovalBinding, SkinApprovalState, SkinApprovalJournal,
    AWAITING, CANCELLED)
from resources.lib.update_guard import AddonUpdatePolicy as Policy, AddonUpdateGuard
from tests.test_frozen_install import FakePolicy, SESSION_A


class SkinApprovalStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root/'library').mkdir()
        self.library = BuildLibrary(self.root/'library')
        scope = isolated_library_install_authority(self.library)
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)
        self.store = FrozenInstallStore(self.root/'state')
        self.journal = SkinApprovalJournal(self.store)
        self.policy = FakePolicy()
        self.binding = SkinApprovalBinding('build', 'profile', 'a'*64, 'b'*64,
            'c'*64, 'd'*64, 'skin.estuary', AppliedBuildAssociation('e'*64, 'profile', 'f'*64),
            previous_skin_version='5.0.0')  # Synthetic authority, not a native version claim.
        self.tx = FrozenInstallTransaction(transaction_id=SESSION_A, build_id='build',
            manifest_path='', device_profile_id='profile', manifest_fingerprint='b'*64,
            phase=P.NEEDS_ATTENTION, originating_kodi_session_id=SESSION_A,
            original_update_policy=Policy.AUTOMATIC, created_at='2026-10-31T00:00:00Z',
            updated_at='2026-10-31T00:00:00Z', library_target=LibraryInstallTarget(
                LibrarySource(str(self.library.root), 'a'*64), 'profile'),
            skin_approval=SkinApprovalState(self.binding))

    def begin(self):
        self.journal.reserve(self.tx)
        # Future coordinator must persist before engaging even updater protection.
        self.assertEqual(self.store.inspect(), self.tx)
        AddonUpdateGuard(self.policy).engage_with_original(self.tx.original_update_policy)
        return self.journal.begin_transition(self.tx, self.binding, policy_backend=self.policy)

    def pending(self):
        tx = self.begin()
        return self.journal.confirm_transition(tx, self.binding, policy_backend=self.policy,
            observed_skin=self.binding.skin_id, observed_version='3.3.12', stable=True, witness='1'*64)

    def observe(self, skin=None):
        skin = skin or self.binding.skin_id
        return dict(policy_backend=self.policy, observed_skin=skin,
                    observed_version=(self.binding.previous_skin_version
                                      if skin == self.binding.previous_skin else self.binding.skin_version),
                    stable=True)

    def test_real_roundtrip_pending_and_binding(self):
        tx = self.pending()
        self.assertEqual(self.store.inspect(), tx)
        self.assertEqual(tx.skin_approval.phase, AWAITING)
        self.assertEqual(tx.phase, P.NEEDS_ATTENTION)
        self.assertEqual(tx.skin_approval.revision, 2)
        raw = json.loads(self.store.transaction_path.read_text())
        self.assertEqual(raw['schema_version'], 5)
        self.assertEqual(FrozenInstallTransaction.from_dict(raw), tx)
        self.assertEqual(tx.skin_approval.binding.previous_applied, self.binding.previous_applied)
        self.assertEqual(self.policy.policy, Policy.NEVER_CHECK)

    def test_authorization_is_durable_before_any_external_side_effect(self):
        with patch.object(self.store, '_write_unlocked', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                self.journal.reserve(self.tx)
        self.assertIsNone(self.store.inspect())
        self.assertEqual(self.policy.calls, [])
        self.journal.reserve(self.tx)
        def observe_write(policy):
            self.assertEqual(self.store.inspect(), self.tx)
            self.policy.policy = policy
        with patch.object(self.policy, 'set_policy', side_effect=observe_write):
            AddonUpdateGuard(self.policy).engage_with_original(self.tx.original_update_policy)

    def test_duplicate_and_stale_cas_refused(self):
        tx = self.begin()
        with self.assertRaises(FrozenInstallStateConflict):
            self.journal.begin_transition(self.tx, self.binding, policy_backend=self.policy)
        pending = self.journal.confirm_transition(tx, self.binding, **self.observe(), witness='1'*64)
        with self.assertRaises(FrozenInstallStateConflict):
            self.journal.confirm_transition(tx, self.binding, **self.observe(), witness='1'*64)
        self.assertEqual(self.store.inspect(), pending)

    def test_quarantine_required_without_policy_writes(self):
        self.journal.reserve(self.tx)
        with self.assertRaises(Exception):
            self.journal.begin_transition(self.tx, self.binding, policy_backend=self.policy)
        self.assertEqual(self.store.inspect(), self.tx)
        self.assertEqual(self.policy.calls, [])

    def test_wrong_source_profile_skin_version_and_review_refused(self):
        tx = self.begin()
        for field,value in [('source_entry_id','0'*64),('profile_id','other'),
                ('frozen_fingerprint','0'*64),('configuration_fingerprint','0'*64),
                ('first_review_fingerprint','0'*64),('previous_skin_version','5.0.1')]:
            with self.subTest(field=field), self.assertRaises(FrozenInstallStateConflict):
                self.journal.confirm_transition(tx, replace(self.binding, **{field:value},
                    **({'previous_applied':None} if field=='profile_id' else {})), **self.observe(), witness='1'*64)
        for field,value in [('observed_skin','skin.other'),('observed_version','3.3.11'),('stable',False)]:
            args=self.observe();args[field]=value
            with self.subTest(field=field), self.assertRaises(FrozenInstallStateConflict):
                self.journal.confirm_transition(tx, self.binding, **args, witness='1'*64)
        self.assertEqual(self.store.inspect(), tx)

    def test_cancel_before_transition_preserves_original_policy(self):
        self.journal.reserve(self.tx)
        tx=self.journal.confirm_cancel(self.tx, self.binding, **self.observe('skin.estuary'))
        self.assertEqual(tx.skin_approval.phase, CANCELLED)
        self.assertEqual(tx.status_code, 'SKIN_CANCELLED_NOT_APPLIED')
        self.assertFalse(tx.updater_guard_required)
        self.assertEqual(self.policy.calls, [])
        self.assertEqual(self.store.inspect(), tx)  # terminal evidence retained

    def test_previous_version_is_required_typed_and_part_of_durable_binding(self):
        self.journal.reserve(self.tx)
        self.assertEqual(self.store.inspect().skin_approval.binding.previous_skin_version, '5.0.0')
        self.assertNotEqual(self.binding.fingerprint,
                            replace(self.binding, previous_skin_version='5.0.1').fingerprint)
        before = self.store.transaction_path.read_bytes()
        for version in (None, '', 'unknown', '5.x', '5.0?', ' 5.0.0', '5.0.0 ',
                        '５.０.０', 5, True, '5'*65):
            with self.subTest(version=version), self.assertRaises(ValueError):
                replace(self.binding, previous_skin_version=version)
        raw = self.tx.to_dict()
        del raw['skin_approval']['binding']['previous_skin_version']
        with self.assertRaises(Exception):
            FrozenInstallTransaction.from_dict(raw)
        self.assertEqual(self.store.transaction_path.read_bytes(), before)

    def test_pretransition_cancel_checks_truthful_previous_identity_on_both_steps(self):
        self.journal.reserve(self.tx)
        AddonUpdateGuard(self.policy).engage_with_original(self.tx.original_update_policy)
        tx = self.journal.request_cancel(self.tx, self.binding, **self.observe(self.binding.previous_skin))
        self.assertFalse(tx.skin_approval.transition_witness)
        AddonUpdateGuard(self.policy).restore_original(tx.original_update_policy)
        done = self.journal.confirm_cancel(tx, self.binding, **self.observe(self.binding.previous_skin))
        self.assertEqual(done.status_code, 'SKIN_CANCELLED_NOT_APPLIED')
        self.assertEqual(self.store.inspect(), done)
        self.assertEqual(done.skin_approval.binding.previous_applied, self.binding.previous_applied)

    def test_pretransition_cancel_refuses_false_unknown_and_incompatible_observations(self):
        self.journal.reserve(self.tx)
        invalid = [('observed_version', v) for v in ('3.3.12', '5.0.1', '', None, 'unknown', 5)]
        invalid += [('observed_skin', self.binding.skin_id), ('stable', False), ('stable', None)]
        # Both direct cancellation and intent reservation use the same observation contract.
        for operation in ('request_cancel', 'confirm_cancel'):
            self.policy.policy = Policy.NEVER_CHECK if operation == 'request_cancel' else Policy.AUTOMATIC
            before = self.store.transaction_path.read_bytes()
            before_calls = list(self.policy.calls)
            for field, value in invalid:
                args = self.observe(self.binding.previous_skin)
                args[field] = value
                with self.subTest(operation=operation, field=field, value=value):
                    with self.assertRaises(FrozenInstallStateConflict):
                        getattr(self.journal, operation)(self.tx, self.binding, **args)
                    self.assertEqual(self.store.transaction_path.read_bytes(), before)
                    self.assertEqual(self.policy.calls, before_calls)

    def test_pending_cancel_rejects_previous_version_for_target_and_retains_witness(self):
        tx = self.pending()
        for operation in ('request_cancel', 'confirm_cancel'):
            if operation == 'confirm_cancel':
                tx = self.journal.request_cancel(tx, self.binding, **self.observe())
                AddonUpdateGuard(self.policy).restore_original(tx.original_update_policy)
            before = self.store.transaction_path.read_bytes()
            args = self.observe()
            args['observed_version'] = self.binding.previous_skin_version
            with self.subTest(operation=operation), self.assertRaises(FrozenInstallStateConflict):
                getattr(self.journal, operation)(tx, self.binding, **args)
            self.assertEqual(self.store.transaction_path.read_bytes(), before)
        done = self.journal.confirm_cancel(tx, self.binding, **self.observe())
        self.assertEqual(done.status_code, 'SKIN_CANCELLED_NOT_FULLY_APPLIED')
        self.assertEqual(self.store.inspect(), done)
        self.assertEqual(done.skin_approval.transition_witness, '1'*64)

    def test_cancel_after_verified_transition_no_rollback_or_early_release(self):
        tx=self.pending()
        tx=self.journal.request_cancel(tx, self.binding, **self.observe())
        with self.assertRaises(FrozenInstallStateConflict):
            self.journal.confirm_cancel(tx, self.binding, **self.observe())
        self.assertEqual(self.store.inspect(), tx)
        AddonUpdateGuard(self.policy).restore_original(tx.original_update_policy)
        done=self.journal.confirm_cancel(tx, self.binding, **self.observe())
        self.assertEqual(done.skin_approval.phase, CANCELLED)
        self.assertEqual(done.status_code, 'SKIN_CANCELLED_NOT_FULLY_APPLIED')
        self.assertEqual(done.skin_approval.transition_witness, '1'*64)
        self.assertEqual(done.skin_approval.binding.previous_applied,self.binding.previous_applied)
        with self.assertRaises(FrozenInstallStateConflict): self.store.clear()

    def test_uncertain_transition_retains_quarantine_and_evidence(self):
        tx=self.begin()
        with self.assertRaises(FrozenInstallStateConflict):
            self.journal.request_cancel(tx,self.binding,**self.observe())
        attention=self.journal.attention(tx,self.binding)
        self.assertEqual(attention.phase,P.NEEDS_ATTENTION)
        self.assertTrue(attention.updater_guard_required)
        self.assertEqual(self.policy.policy,Policy.NEVER_CHECK)
        self.assertEqual(self.store.inspect(),attention)

    def test_generic_transition_clear_and_competing_owner_refused(self):
        tx=self.pending()
        with self.assertRaises(FrozenInstallStateConflict): self.store.create(self.tx)
        for phase in (P.CONFIGURING,P.AWAITING_RESTART,P.COMPLETE,P.PUBLICATION_PENDING):
            with self.subTest(phase=phase),self.assertRaises(FrozenInstallStateConflict):
                self.store.transition_expected(transaction_id=tx.transaction_id,expected_phase=tx.phase,new_phase=phase)
        with self.assertRaises(FrozenInstallStateConflict):
            self.store.clear_expected(transaction_id=tx.transaction_id,expected_phase=tx.phase)
        self.assertEqual(self.store.inspect(),tx)

    def test_startup_and_existing_coordinator_do_not_execute_protocol(self):
        tx=self.pending();runner=Mock(side_effect=AssertionError('configuration forbidden'))
        from resources.lib.frozen_install import ensure_frozen_install_guard
        precondition=ensure_frozen_install_guard(store=self.store,policy_backend=self.policy)
        self.assertFalse(precondition.allowed)
        self.assertEqual(precondition.code,'FROZEN_NEEDS_ATTENTION')
        with patch('resources.lib.frozen_install.recover_applied_publication',side_effect=AssertionError('publication forbidden')):
            result=run_frozen_install_startup(bm020_status=None,store=self.store,policy_backend=self.policy,configuration_runner=runner)
            self.assertEqual(result.code,'SKIN_APPROVAL_PROTOCOL_PENDING')
            coordinator=FrozenInstallCoordinator(store=self.store,artifact_store=Mock(),policy_backend=self.policy,
                installer=Mock(),configuration_runner=runner)
            self.assertEqual(coordinator.install_target(tx.library_target).code,'SKIN_APPROVAL_PROTOCOL_PENDING')
            self.assertEqual(coordinator.resume_after_restart().code,'SKIN_APPROVAL_PROTOCOL_PENDING')
            self.assertEqual(coordinator.abandon().code,'SKIN_APPROVAL_EXPLICIT_CANCELLATION_REQUIRED')
        runner.assert_not_called()
        self.assertEqual(self.store.inspect(),tx)

    def test_write_failure_does_not_authorize_transition(self):
        tx=self.begin()
        with patch.object(self.store,'_write_unlocked',side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                self.journal.confirm_transition(tx,self.binding,**self.observe(),witness='1'*64)
        self.assertEqual(self.store.inspect(),tx)

    def test_legacy_record_preserved_and_protocol_schema_not_inferred(self):
        legacy=replace(self.tx,skin_approval=None,phase=P.PREPARING)
        raw=legacy.to_dict();self.assertEqual(raw['schema_version'],4)
        self.assertNotIn('skin_approval',raw)
        self.assertEqual(FrozenInstallTransaction.from_dict(raw).to_dict(),raw)
        raw['phase']=AWAITING
        with self.assertRaises(Exception):FrozenInstallTransaction.from_dict(raw)
        raw=self.tx.to_dict();raw['schema_version']=4
        with self.assertRaises(Exception):FrozenInstallTransaction.from_dict(raw)

    def test_unknown_fields_and_private_payload_refused(self):
        raw=self.tx.skin_approval.to_dict();raw['private_values']={'token':'synthetic'}
        with self.assertRaises(ValueError):SkinApprovalState.from_dict(raw)
        for field,value in [('private_overlay_id','synthetic'),('activation_hold_ids',('script.other',)),
                ('restart_transaction_id',SESSION_A),('configuration_manifest_path','/other')]:
            with self.subTest(field=field),self.assertRaises(ValueError):replace(self.tx,**{field:value})
        self.journal.reserve(self.tx)
        encoded=self.store.transaction_path.read_text()
        self.assertNotIn('private_values',encoded)
        self.assertNotIn('token',encoded)
        self.assertFalse((self.root/'state'/'install_resolutions').exists())
        self.assertFalse((self.root/'library'/'applied.json').exists())

    def test_restore_failure_retains_cancel_intent_and_owner(self):
        tx=self.pending()
        tx=self.journal.request_cancel(tx,self.binding,**self.observe())
        with patch.object(self.policy,'set_policy',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(Exception):AddonUpdateGuard(self.policy).restore_original(tx.original_update_policy)
        self.assertEqual(self.store.inspect(),tx)
        self.assertEqual(self.policy.policy,Policy.NEVER_CHECK)
        self.assertTrue(tx.updater_guard_required)

    def test_startup_unknown_transition_and_broken_quarantine_never_continue(self):
        tx=self.begin()
        runner=Mock(side_effect=AssertionError('no auto configuration'))
        self.policy.policy=Policy.AUTOMATIC
        result=run_frozen_install_startup(bm020_status=None,store=self.store,
            policy_backend=self.policy,configuration_runner=runner)
        self.assertEqual(result.outcome,'needs_attention')
        self.assertEqual(result.code,'SKIN_APPROVAL_PROTECTION_UNVERIFIED')
        runner.assert_not_called()
        self.assertEqual(self.store.inspect(),tx)

    def test_protocol_cannot_start_at_pending_or_erase_its_schema(self):
        tx=self.pending()
        self.store.transaction_path.unlink()  # isolated test fixture only
        with self.assertRaises(FrozenInstallStateConflict):self.store.create(tx)
        raw=tx.to_dict();raw.pop('skin_approval')
        with self.assertRaises(Exception):FrozenInstallTransaction.from_dict(raw)

    def test_ambiguous_postwrite_failure_retains_new_owner_and_refuses_replay(self):
        tx=self.begin()
        write=self.store._write_unlocked
        def committed_then_failed(updated):
            write(updated)
            raise OSError('synthetic post-write ambiguity')
        with patch.object(self.store,'_write_unlocked',side_effect=committed_then_failed):
            with self.assertRaises(OSError):
                self.journal.confirm_transition(tx,self.binding,**self.observe(),witness='1'*64)
        observed=self.store.inspect()
        self.assertEqual(observed.skin_approval.phase,AWAITING)
        self.assertEqual(observed.skin_approval.revision,2)
        with self.assertRaises(FrozenInstallStateConflict):
            self.journal.confirm_transition(tx,self.binding,**self.observe(),witness='1'*64)

    def test_all_legacy_schemas_keep_their_meaning(self):
        legacy=replace(self.tx,skin_approval=None,phase=P.PREPARING,
                       library_target=None,manifest_path='/synthetic/frozen.json')
        for schema in (1,2,3,4):
            raw=legacy.to_dict();raw['schema_version']=schema
            with self.subTest(schema=schema):
                parsed=FrozenInstallTransaction.from_dict(raw)
                self.assertIsNone(parsed.skin_approval)
                self.assertEqual(parsed.phase,P.PREPARING)

    def test_startup_corrupt_records_retain_legacy_needs_attention_result(self):
        for name, payload in (
                ('invalid_json', '{not json'),
                ('directory', None),
                ('schema_99', json.dumps({'schema_version': 99}))):
            with self.subTest(record=name):
                store = FrozenInstallStore(self.root / name)
                if payload is None:
                    store.transaction_path.mkdir()
                else:
                    store.transaction_path.write_text(payload)
                runner = Mock(side_effect=AssertionError('configuration forbidden'))
                before_calls = list(self.policy.calls)
                result = run_frozen_install_startup(bm020_status=None, store=store,
                    policy_backend=self.policy, configuration_runner=runner)
                self.assertEqual(result.outcome, 'needs_attention')
                self.assertEqual(result.code, 'APPLIED_ASSOCIATION_PERSISTENCE_FAILED')
                self.assertEqual(result.message, 'completed association publication requires recovery')
                runner.assert_not_called()
                self.assertEqual(self.policy.calls, before_calls)
                if payload is None:
                    self.assertTrue(store.transaction_path.is_dir())
                    self.assertEqual(list(store.transaction_path.iterdir()), [])
                else:
                    self.assertEqual(store.transaction_path.read_text(), payload)

    def test_startup_absent_record_control_is_unchanged(self):
        runner = Mock(side_effect=AssertionError('configuration forbidden'))
        self.assertIsNone(run_frozen_install_startup(bm020_status=None, store=self.store,
            policy_backend=self.policy, configuration_runner=runner))
        runner.assert_not_called()
        self.assertIsNone(self.store.inspect())
        self.assertEqual(self.policy.calls, [])
