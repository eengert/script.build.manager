"""Synthetic fixed-target acquisitions only; never access native Kodi."""
import copy
import hashlib
import json
import pickle
import plistlib
import sqlite3
from pathlib import Path
from unittest import mock

from tests import test_bm_test_app as fixtures
from tests import test_bm_public_preservation_witness as semantic
from tools import bm_preservation_acquisition as bridge
from tools import bm_public_preservation_witness as w
from tools import bm_test_app as bm


class AcquisitionTests(fixtures.TripwireTestCase):
    def setUp(self):
        super().setUp()
        fake = fixtures.make_fake_app(self.tmp)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(bm, 'AUTHORIZED_TEST_APP', str(fake.root)).start()
        self.target = bm.TestAppTarget(fake.root, production=True)
        self.services = fixtures.make_services(self.target)
        self.root = self.target.portable_data
        semantic.PreservationTests.populate(self, self.root)
        self.manifest = {'synthetic': True}
        self.validation = mock.patch.object(bm, 'validate_manifest', side_effect=lambda value: value)
        self.verify = mock.patch.object(bm, 'verify_installed', return_value={
            'installed_equals_manifest': True, 'installed_equals_candidate': True,
            'git_binding': {'checked': True, 'ok': True}})
        self.validation.start(); self.verification = self.verify.start()
        self.session = self.new_session()
        self.addCleanup(self.session.close)

    def path(self, root, i):
        return root / w.FILES[i]

    def new_session(self):
        return bridge.AcquisitionSession(self.services, manifest=self.manifest, git_repo=self.tmp)

    def safe(self, result):
        encoded = json.dumps(result)
        for value in (semantic.SECRET, hashlib.sha256(semantic.SECRET.encode()).hexdigest(),
                      'network.password', 'private.label', str(self.root)):
            self.assertNotIn(value, encoded)
        self.assertEqual(result['complete_preservation'], 'UNVERIFIED')
        self.assertEqual(result['qualification'], 'not_qualified')
        self.assertEqual(result['maintenance_attribution'], 'UNKNOWN')
        self.assertEqual(result['writer_exclusion'], 'UNVERIFIED')
        return result

    def begin(self):
        result = self.safe(self.session.begin())
        self.assertEqual(result['acquisition'], 'ACQUIRED')
        self.assertEqual(result['scope_result'], 'UNVERIFIED')

    def refused(self, boundary='before'):
        result = self.safe(self.session.begin() if boundary == 'before' else self.session.finish())
        self.assertIn(result['acquisition'], ('REFUSED', 'FAILED'))
        self.assertEqual(result['scope_result'], 'UNVERIFIED')
        self.assertIsNone(self.session._before)
        return result

    def test_equal_and_source_bytes_unchanged_no_native_mutation(self):
        before = {name: (self.root/name).read_bytes() for name in w.FILES}
        with mock.patch.object(bm, 'run_adapter', side_effect=AssertionError('mutation')), \
             mock.patch.object(bm, 'run_stage', side_effect=AssertionError('mutation')):
            self.begin()
            self.assertEqual(self.safe(self.session.finish())['scope_result'], 'PRESERVED')
        self.assertEqual(before, {name: (self.root/name).read_bytes() for name in w.FILES})
        self.assertEqual(self.verification.call_count, 6)
        self.assertEqual(self.services.transport.requests, [])

    def test_layout_changes_are_semantically_equal(self):
        self.begin()
        path = self.path(self.root, 4)
        path.write_text('<settings>\n  <setting value="'+semantic.SECRET+'" id="layout" />\n</settings>')
        with sqlite3.connect(self.path(self.root, 1)) as db: db.execute('VACUUM')
        self.assertEqual(self.safe(self.session.finish())['scope_result'], 'PRESERVED')

    def test_only_fixed_five_sources_are_read_and_unrelated_records_unchanged(self):
        for name in ('fixture-journal.jsonl', 'bm-auto-keep-attempt-v1.json', 'applied.json',
                     'frozen_install_transaction.json', 'private-overlay-not-authorized.json'):
            (self.root/name).write_text(semantic.SECRET)
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        reader = w.read_copy
        def fixed(root, relative, limit):
            self.assertEqual(root, self.root)
            self.assertIn(relative, w.FILES)
            return reader(root, relative, limit)
        with mock.patch.object(w, 'read_copy', side_effect=fixed), \
             mock.patch.object(bm, 'run_snapshot', side_effect=AssertionError('separate witness')):
            self.begin()
            self.assertEqual(self.safe(self.session.finish())['scope_result'], 'PRESERVED')
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes()
                                 for p in self.root.rglob('*') if p.is_file()})

    def test_manifest_is_frozen_and_failed_after_acquisition_cannot_retry(self):
        self.begin()
        self.manifest['synthetic'] = False
        self.assertEqual(self.session._manifest, {'synthetic': True})
        with mock.patch.object(w, 'read_copy', side_effect=OSError(semantic.SECRET)):
            self.refused('after')
        with mock.patch.object(w, 'read_copy', side_effect=AssertionError('no retry')):
            self.refused('after')

    def test_each_xml_value_change_is_detected_without_echo(self):
        for i in (2, 3, 4):
            with self.subTest(i=i):
                self.session = self.new_session(); self.begin()
                path = self.path(self.root, i)
                path.write_text(path.read_text().replace(semantic.SECRET, semantic.SECRET+'changed'))
                result = self.safe(self.session.finish())
                self.assertEqual(result['files'][i]['status'], 'CHANGED_OR_MISSING')

    def test_addons_enabled_change_detected_but_other_fields_not_claimed(self):
        self.begin()
        with sqlite3.connect(self.path(self.root, 0)) as db:
            db.execute('UPDATE installed SET enabled=0')
        result = self.safe(self.session.finish())
        self.assertEqual(result['files'][0]['status'], 'CHANGED_OR_MISSING')
        self.assertIn('all other Addons33 content UNVERIFIED', result['files'][0]['scope'])
        self.session = self.new_session(); self.begin()
        with sqlite3.connect(self.path(self.root, 0)) as db: db.execute("UPDATE installed SET lastUsed='changed'")
        self.assertEqual(self.safe(self.session.finish())['scope_result'], 'PRESERVED')

    def test_texture_maintenance_field_change_is_not_called_harmless(self):
        self.begin()
        with sqlite3.connect(self.path(self.root, 1)) as db: db.execute('UPDATE sizes SET usecount=usecount+1')
        result = self.safe(self.session.finish())
        self.assertEqual(result['files'][1]['status'], 'CHANGED_OR_MISSING')

    def test_missing_baseline_refuses_but_missing_after_is_difference(self):
        path = self.path(self.root, 4); saved = path.read_bytes(); path.unlink()
        self.assertEqual(self.refused()['reason'], 'missing_input')
        path.write_bytes(saved); self.session = self.new_session(); self.begin(); path.unlink()
        self.assertEqual(self.safe(self.session.finish())['files'][4]['status'], 'CHANGED_OR_MISSING')

    def test_unsupported_xml_refuses_before_and_after(self):
        path = self.path(self.root, 2); saved = path.read_bytes(); path.write_text('<unknown/>')
        self.refused()
        path.write_bytes(saved); self.session = self.new_session(); self.begin(); path.write_text('<unknown/>')
        self.refused('after')

    def test_each_database_sidecar_refuses_even_empty(self):
        for i in (0, 1):
            for suffix in ('-wal', '-shm', '-journal'):
                with self.subTest(i=i, suffix=suffix):
                    path = Path(str(self.path(self.root, i))+suffix); path.touch()
                    self.session = self.new_session()
                    self.assertEqual(self.refused()['reason'], 'sqlite_sidecar_uncertain')
                    path.unlink()

    def test_wal_header_without_sidecars_refuses(self):
        path = self.path(self.root, 1); raw = bytearray(path.read_bytes()); raw[18:20] = b'\x02\x02'
        path.write_bytes(raw)
        self.assertEqual(self.refused()['reason'], 'sqlite_wal_mode_uncertain')

    def test_unsupported_database_schema_refuses(self):
        with sqlite3.connect(self.path(self.root, 1)) as db: db.execute('CREATE TABLE extra(secret TEXT)')
        self.refused()

    def test_symlink_leaf_and_ancestor_and_hardlink_refuse(self):
        path = self.path(self.root, 4); saved = path.read_bytes(); path.unlink()
        other = self.tmp/'secret'; other.write_bytes(saved); path.symlink_to(other)
        self.refused(); path.unlink(); path.hardlink_to(other)
        self.session = self.new_session(); self.refused(); path.unlink(); path.write_bytes(saved)
        parent = path.parent; renamed = parent.with_name('saved'); parent.rename(renamed); parent.symlink_to(renamed)
        self.session = self.new_session(); self.refused()

    def test_fixed_target_and_repository_required_before_any_file_read(self):
        for target, repo in ((bm.TestAppTarget.for_tests(self.target.root), self.tmp),
                             (self.target, None)):
            self.services.target = target
            self.session = bridge.AcquisitionSession(self.services, manifest=self.manifest, git_repo=repo)
            with mock.patch.object(w, 'read_copy', side_effect=AssertionError('must not read')):
                self.assertEqual(self.refused()['reason'], 'admission_refused')

    def test_foreign_or_running_process_refuses(self):
        self.services.process_lister.run_test_app(self.target)
        self.assertEqual(self.refused()['reason'], 'admission_refused')

    def test_process_failure_never_becomes_stopped(self):
        self.services.process_lister.fail = True
        self.refused()

    def test_bundle_identity_must_remain_the_same_across_boundaries(self):
        self.begin()
        data = plistlib.loads(self.target.info_plist.read_bytes())
        data['CFBundleShortVersionString'] = '21.4'
        self.target.info_plist.write_bytes(plistlib.dumps(data))
        self.assertEqual(self.refused('after')['reason'], 'admission_refused')

    def test_sidecar_or_oversized_source_after_baseline_refuses(self):
        self.begin()
        Path(str(self.path(self.root, 1))+'-journal').touch()
        self.refused('after')
        self.session = self.new_session()
        with mock.patch.object(w, 'MAX_XML', 1): self.refused()

    def test_source_mismatch_or_missing_git_check_refuses_both_boundaries(self):
        for field in ('installed_equals_candidate', 'installed_equals_manifest', 'git_binding'):
            self.session = self.new_session(); self.begin()
            original = self.verification.return_value
            changed = copy.deepcopy(original)
            changed[field] = {'checked': False, 'ok': True} if field == 'git_binding' else False
            self.verification.return_value = changed
            self.assertEqual(self.refused('after')['reason'], 'source_unverified')
            self.session = self.new_session()
            self.assertEqual(self.refused()['reason'], 'source_unverified')
            self.verification.return_value = original

    def test_source_or_process_changes_during_final_admission_refuse(self):
        self.verification.side_effect = [self.verification.return_value, RuntimeError(semantic.SECRET)]
        self.refused()
        self.verification.side_effect = None; self.session = self.new_session()
        def start_during_verification(*args, **kwargs):
            self.services.process_lister.run_test_app(self.target)
            return self.verification.return_value
        self.verification.side_effect = start_during_verification
        self.refused()

    def test_source_files_mutated_during_projection_or_final_admission_refuse(self):
        original = w.xml_projection
        def changed(raw, kind):
            value = original(raw, kind)
            self.path(self.root, 2).write_text('<settings version="2"/>')
            return value
        with mock.patch.object(w, 'xml_projection', side_effect=changed):
            self.assertEqual(self.refused()['reason'], 'input_changed')
        self.session = self.new_session()
        self.verification.side_effect = [self.verification.return_value, self.verification.return_value]
        def mutate_at_final(*args, **kwargs):
            if self.verification.call_count > 2:
                self.path(self.root, 4).write_text('<settings/>')
            return self.verification.return_value
        self.verification.side_effect = mutate_at_final
        self.refused()

    def test_private_exception_and_cleanup_uncertainty_never_echo_or_pass(self):
        for error in (RuntimeError(semantic.SECRET), OSError(semantic.SECRET),
                      w.Unverified(semantic.SECRET), bridge._Refused(semantic.SECRET)):
            self.session = self.new_session()
            with mock.patch.object(w, 'database_projection', side_effect=error): self.refused()

    def test_connection_close_and_scratch_cleanup_failures_refuse(self):
        connect = sqlite3.connect
        class Connection:
            def __init__(self, *args, **kwargs): self.value = connect(*args, **kwargs)
            def __getattr__(self, name): return getattr(self.value, name)
            def close(self):
                self.value.close()
                raise sqlite3.OperationalError(semantic.SECRET)
        with mock.patch.object(w.sqlite3, 'connect', Connection): self.refused()
        self.session = self.new_session()
        original_unlink = Path.unlink
        def unlink_failure(path, *args, **kwargs):
            if path.name == 'copy.db':
                original_unlink(path, *args, **kwargs)
                raise OSError(semantic.SECRET)
            return original_unlink(path, *args, **kwargs)
        with mock.patch.object(Path, 'unlink', unlink_failure): self.refused()

    def test_no_persistence_copy_or_retry_and_context_discards_baseline(self):
        with self.session:
            self.begin()
            for operation in (pickle.dumps, copy.copy, copy.deepcopy):
                with self.assertRaises(TypeError): operation(self.session)
            self.assertNotIn(semantic.SECRET, repr(self.session))
        self.refused('after')
        self.session = self.new_session(); self.begin()
        self.session.finish()
        with mock.patch.object(w, 'read_copy', side_effect=AssertionError('no retry')):
            self.refused('after'); self.refused()

    def test_real_git_bound_installed_verification_and_tamper_refusal(self):
        self.validation.stop(); self.verify.stop()
        repo, commit = fixtures.build_candidate_repo(self.tmp)
        evidence = self.tmp/'stage-evidence'; evidence.mkdir()
        result = bm.run_stage(self.services, candidate_id=commit,
                              config={'adapter':dict(fixtures.ADAPTER_VALUES),'rpc':{}},
                              repo=repo, evidence_dir=evidence, dry_run=False)
        self.assertTrue(result['ok'])
        manifest, unused = bm.load_manifest(result['evidence']['manifest_path'], self.services)
        self.session = bridge.AcquisitionSession(self.services, manifest=manifest, git_repo=repo)
        self.begin()
        path = self.target.addon_dir(bm.BUILD_MANAGER_ID)/'default.py'
        path.write_text(path.read_text()+'\n# synthetic tamper\n')
        self.assertEqual(self.refused('after')['reason'], 'source_unverified')
