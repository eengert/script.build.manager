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
from tools import bm_practical_preservation_comparator as comparator


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

    def test_native_nested_gui_projection_uses_unchanged_bridge(self):
        path = self.path(self.root, 2)
        path.write_text(semantic.PreservationTests.native_gui(self))
        before = path.read_bytes()
        self.begin()
        path.write_bytes(before.replace(b'<fvolumelevel>'+semantic.SECRET.encode()+b'</fvolumelevel>',
                                        b'<fvolumelevel>changed</fvolumelevel>'))
        result = self.safe(self.session.finish())
        self.assertEqual(result['scope_result'], 'CHANGED_OR_MISSING')
        self.assertEqual([r['status'] for r in result['files']],
                         ['PRESERVED', 'PRESERVED', 'CHANGED_OR_MISSING', 'PRESERVED', 'PRESERVED'])
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

    def gui(self, uptime, level='1'):
        # Kodi 21.3 native shape: general/systemtotaluptime plus one general setting.
        self.path(self.root, 2).write_text(
            '<settings version="2"><general><systemtotaluptime>' + uptime + '</systemtotaluptime>'
            '<settinglevel>' + level + '</settinglevel></general><viewstates><musicfiles>'
            '<viewmode>50</viewmode></musicfiles></viewstates></settings>')

    def estuary(self, flag):
        self.path(self.root, 3).write_text('<settings><setting id="flag" type="bool">' + flag + '</setting>'
                                           '<setting id="private.label" type="string">' + semantic.SECRET
                                           + '</setting></settings>')

    def projections(self):
        read = [(self.root / name).read_bytes() for name in w.FILES]
        return [w.database_projection(read[0], 0), w.database_projection(read[1], 1)] + [
            w.xml_projection(read[i], i) for i in (2, 3, 4)]

    def practical(self, result):
        practical = result['practical']
        self.assertEqual(set(practical), {'schema', 'classification', 'files', 'verdict', 'qualification'})
        self.assertEqual(practical['verdict'], 'NOT_DECIDED')
        self.assertEqual([row['file'] for row in practical['files']], list(w.FILES))
        return practical

    def test_practical_classification_is_exact_for_all_five_unchanged_projections(self):
        self.begin()
        result = self.safe(self.session.finish())
        self.assertEqual(result['scope_result'], 'PRESERVED')
        practical = self.practical(result)
        self.assertEqual(practical['classification'], 'EXACT')
        self.assertEqual([row['classification'] for row in practical['files']], ['EXACT'] * 5)
        self.assertEqual([row['maintenance'] for row in practical['files']], [[]] * 5)

    def test_uptime_only_change_is_strict_changed_and_practical_maintenance_only(self):
        self.gui('10')
        self.begin()
        self.gui('11')
        result = self.safe(self.session.finish())
        self.assertEqual([row['status'] for row in result['files']],
                         ['PRESERVED', 'PRESERVED', 'CHANGED_OR_MISSING', 'PRESERVED', 'PRESERVED'])
        practical = self.practical(result)
        self.assertEqual(practical['files'][2], {'file': w.FILES[2], 'classification': 'MAINTENANCE_ONLY',
                                                 'maintenance': [['M1_UPTIME', 1]], 'meaningful_count': 0})
        self.assertEqual(practical['classification'], 'MAINTENANCE_ONLY')
        self.assertEqual({row['classification'] for i, row in enumerate(practical['files']) if i != 2},
                         {'EXACT'})

    def test_texture_maintenance_is_strict_changed_and_practical_maintenance_only(self):
        self.begin()
        with sqlite3.connect(self.path(self.root, 1)) as db:
            db.execute('UPDATE sizes SET usecount=usecount+1, lastusetime=?', ('synthetic-later',))
            db.execute('UPDATE texture SET lasthashcheck=?', ('synthetic-later',))
        result = self.safe(self.session.finish())
        self.assertEqual(result['files'][1]['status'], 'CHANGED_OR_MISSING')
        practical = self.practical(result)
        self.assertEqual(practical['files'][1]['classification'], 'MAINTENANCE_ONLY')
        self.assertEqual(practical['files'][1]['maintenance'], [
            ['M2_SIZES_LASTUSETIME', 1], ['M2_SIZES_USECOUNT', 1], ['M2_TEXTURE_LASTHASHCHECK', 1]])
        self.assertEqual(practical['classification'], 'MAINTENANCE_ONLY')

    def test_cache_row_creation_and_eviction_with_their_sizes_are_maintenance_only(self):
        self.begin()
        with sqlite3.connect(self.path(self.root, 1)) as db:
            db.execute('INSERT INTO texture VALUES (2, ?, ?, ?, NULL)',
                       ('synthetic-new', 'synthetic-cached', 'synthetic-hash'))
            db.execute('INSERT INTO sizes VALUES (2, 32, 32, 32, 0, NULL)')
            db.execute('DELETE FROM texture WHERE id=1')  # The schema trigger removes its sizes row.
        result = self.safe(self.session.finish())
        practical = self.practical(result)
        self.assertEqual(practical['files'][1]['maintenance'], [
            ['M2_CACHE_ROW_CREATE', 1], ['M2_CACHE_ROW_EVICT', 1],
            ['M2_CACHE_SIZES_CREATE', 1], ['M2_CACHE_SIZES_EVICT', 1]])
        self.assertEqual(practical['files'][1]['classification'], 'MAINTENANCE_ONLY')

    def test_meaningful_setting_change_is_practical_meaningful(self):
        self.begin()
        self.estuary('false')
        result = self.safe(self.session.finish())
        self.assertEqual(result['files'][3]['status'], 'CHANGED_OR_MISSING')
        practical = self.practical(result)
        self.assertEqual(practical['files'][3], {'file': w.FILES[3], 'classification': 'MEANINGFUL',
                                                 'maintenance': [], 'meaningful_count': 1})
        self.assertEqual(practical['classification'], 'MEANINGFUL')

    def test_combined_maintenance_and_meaningful_changes_are_never_maintenance_only(self):
        # Same file: uptime maintenance plus a meaningful setting leaf.
        self.gui('10')
        self.begin()
        self.gui('11', level='2')
        practical = self.practical(self.safe(self.session.finish()))
        self.assertEqual(practical['files'][2], {'file': w.FILES[2], 'classification': 'MEANINGFUL',
                                                 'maintenance': [], 'meaningful_count': 1})
        self.assertEqual(practical['classification'], 'MEANINGFUL')
        # Different files: maintenance in one and a meaningful estuary setting in another.
        self.session = self.new_session()
        self.gui('10')
        self.begin()
        self.gui('11')
        self.estuary('false')
        practical = self.practical(self.safe(self.session.finish()))
        self.assertEqual(practical['files'][2]['classification'], 'MAINTENANCE_ONLY')
        self.assertEqual(practical['files'][3]['classification'], 'MEANINGFUL')
        self.assertEqual(practical['classification'], 'MEANINGFUL')

    def test_comparator_rejection_is_inconclusive_for_its_file_and_never_pass(self):
        # Malformed uptime is identical on both sides: strict PRESERVED, practical INCONCLUSIVE.
        self.gui('010')
        self.begin()
        result = self.safe(self.session.finish())
        self.assertEqual(result['scope_result'], 'PRESERVED')
        practical = self.practical(result)
        self.assertEqual(practical['files'][2]['classification'], 'INCONCLUSIVE')
        self.assertEqual(practical['classification'], 'INCONCLUSIVE')

    def test_rejection_detail_never_reaches_the_result(self):
        self.begin()
        rejected = comparator.ComparatorRejected(semantic.SECRET, 'unexpected_schema')
        with mock.patch.object(comparator, 'compare_file', side_effect=rejected):
            result = self.safe(self.session.finish())
        practical = self.practical(result)
        self.assertEqual([row['classification'] for row in practical['files']], ['INCONCLUSIVE'] * 5)
        self.assertEqual(practical['classification'], 'INCONCLUSIVE')
        self.assertEqual(result['scope_result'], 'PRESERVED')

    def test_failed_after_acquisition_carries_no_practical_block(self):
        self.begin()
        with mock.patch.object(w, 'read_copy', side_effect=OSError(semantic.SECRET)):
            result = self.refused('after')
        self.assertNotIn('practical', result)

    def test_practical_classification_reads_and_writes_nothing(self):
        before, after = self.projections(), self.projections()
        with mock.patch('builtins.open', side_effect=AssertionError('io')), \
             mock.patch('os.open', side_effect=AssertionError('io')), \
             mock.patch('os.write', side_effect=AssertionError('io')), \
             mock.patch('tempfile.TemporaryDirectory', side_effect=AssertionError('io')):
            practical = bridge._practical(before, after)
        self.assertEqual(practical['classification'], 'EXACT')
        self.assertEqual(before, self.projections())

    def test_practical_path_keeps_single_finish_and_closed_session(self):
        self.begin()
        self.practical(self.safe(self.session.finish()))
        self.assertIsNone(self.session._before)
        again = self.safe(self.session.finish())
        self.assertEqual(again['acquisition'], 'REFUSED')
        self.assertNotIn('practical', again)

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

    # --- D-032 clarification of 2026-11-19: whole-file Addons33 byte identity ---------------

    BYTES_KEYS = {'schema', 'scope', 'status'}

    def addons_bytes(self):
        return self.path(self.root, 0).read_bytes()

    def finished(self):
        result = self.safe(self.session.finish())
        self.assertEqual(result['acquisition'], 'ACQUIRED')
        return result

    def byte_status(self, result):
        block = result['addons33_bytes']
        self.assertEqual(set(block), self.BYTES_KEYS)
        self.assertEqual(block['schema'], 'bm-a15-addons33-bytes/1')
        self.assertEqual(block['scope'], 'addons33_file_bytes')
        return block['status']

    def assertNoFingerprintOrPrivateValue(self, result, *raws):
        encoded = json.dumps(result)
        for raw in raws:
            digest = hashlib.sha256(raw).digest()
            for text in (digest.hex(), digest.hex().upper(), str(len(raw)), repr(digest)):
                if text.isdigit():
                    # A length may coincide with a count; it must never appear as a field value.
                    self.assertNotIn('"length"', encoded)
                    self.assertNotIn('"size"', encoded)
                else:
                    self.assertNotIn(text, encoded)
        self.assertNotIn(semantic.SECRET, encoded)
        self.assertNotIn('sha256', encoded)
        self.assertNotIn('digest', encoded)

    def test_identical_bytes_are_reported_and_leave_the_strict_result_unchanged(self):
        raw = self.addons_bytes()
        self.begin()
        result = self.finished()
        self.assertEqual(self.byte_status(result), 'BYTES_IDENTICAL')
        self.assertEqual(result['scope_result'], 'PRESERVED')
        self.assertEqual([r['status'] for r in result['files']], ['PRESERVED'] * 5)
        self.assertNoFingerprintOrPrivateValue(result, raw)
        self.assertEqual(raw, self.addons_bytes())

    def test_the_sibling_block_is_the_only_strict_addition(self):
        self.begin()
        result = self.finished()
        strict = bridge._result('after', 'ACQUIRED', 'scoped_comparison', ['PRESERVED'] * 5,
                                result['practical'], result['addons33_bytes'])
        self.assertEqual(result, strict)
        without = {k: v for k, v in result.items() if k not in ('practical', 'addons33_bytes')}
        self.assertEqual(without, bridge._result('after', 'ACQUIRED', 'scoped_comparison', ['PRESERVED'] * 5))
        self.assertEqual(set(result) - set(without), {'practical', 'addons33_bytes'})

    def test_same_length_changed_content_is_different_bytes_with_an_agreeing_projection(self):
        before = self.addons_bytes()
        self.begin()
        with sqlite3.connect(self.path(self.root, 0)) as db:
            db.execute("UPDATE installed SET lastUsed='Z' || substr(lastUsed, 2)")
        after = self.addons_bytes()
        self.assertEqual(len(before), len(after))
        self.assertNotEqual(before, after)
        result = self.finished()
        self.assertEqual(self.byte_status(result), 'BYTES_DIFFERENT')
        # The identity/enabled projection is unchanged: strict N6 still says PRESERVED.
        self.assertEqual(result['files'][0]['status'], 'PRESERVED')
        self.assertEqual(result['scope_result'], 'PRESERVED')
        self.assertEqual(result['practical']['files'][0]['classification'], 'EXACT')
        self.assertNoFingerprintOrPrivateValue(result, before, after)

    def test_different_length_is_different_bytes(self):
        before = self.addons_bytes()
        self.begin()
        with sqlite3.connect(self.path(self.root, 0)) as db:
            db.execute('CREATE TABLE unrelated (note TEXT)')
            db.executemany('INSERT INTO unrelated VALUES (?)', [('x' * 900,)] * 40)
        after = self.addons_bytes()
        self.assertNotEqual(len(before), len(after))
        result = self.finished()
        self.assertEqual(self.byte_status(result), 'BYTES_DIFFERENT')
        self.assertEqual(result['files'][0]['status'], 'PRESERVED')
        self.assertNoFingerprintOrPrivateValue(result, before, after)

    def test_sqlite_header_counter_change_alone_is_different_bytes(self):
        path = self.path(self.root, 0)
        self.begin()
        raw = bytearray(path.read_bytes())
        counter = int.from_bytes(raw[24:28], 'big') + 1
        raw[24:28] = raw[92:96] = counter.to_bytes(4, 'big')
        path.write_bytes(bytes(raw))
        result = self.finished()
        self.assertEqual(self.byte_status(result), 'BYTES_DIFFERENT')
        self.assertEqual(result['files'][0]['status'], 'PRESERVED')

    def test_same_digest_requires_the_same_length_and_a_different_digest_is_different(self):
        digest = bytes(range(32))
        other = bytes(range(1, 33))
        self.assertEqual(bridge._addons33_bytes((digest, 5), (digest, 5))['status'], 'BYTES_IDENTICAL')
        self.assertEqual(bridge._addons33_bytes((digest, 5), (digest, 6))['status'], 'BYTES_DIFFERENT')
        self.assertEqual(bridge._addons33_bytes((digest, 5), (other, 5))['status'], 'BYTES_DIFFERENT')

    def test_missing_or_malformed_fingerprints_are_unverified_never_identical(self):
        digest = bytes(32)
        good = (digest, 4)
        bad = (None, (), [], (digest,), (digest, 4, 1), (digest, True), (digest, -1), (digest, '4'),
               (digest[:31], 4), (bytearray(digest), 4), (digest.hex(), 4), 'x', 4, {})
        self.assertEqual(bridge._addons33_bytes(None, None)['status'], 'UNVERIFIED')
        for value in bad:
            with self.subTest(value=repr(value)):
                self.assertEqual(bridge._addons33_bytes(value, good)['status'], 'UNVERIFIED')
                self.assertEqual(bridge._addons33_bytes(good, value)['status'], 'UNVERIFIED')
                self.assertEqual(bridge._addons33_bytes(value, value)['status'], 'UNVERIFIED')

    def test_missing_addons33_at_begin_refuses_and_holds_no_fingerprint(self):
        self.path(self.root, 0).unlink()
        result = self.refused()
        self.assertEqual(result['reason'], 'missing_input')
        self.assertNotIn('addons33_bytes', result)
        self.assertIsNone(self.session._fingerprint)

    def test_missing_addons33_at_finish_is_unverified(self):
        self.begin()
        self.path(self.root, 0).unlink()
        result = self.finished()
        self.assertEqual(self.byte_status(result), 'UNVERIFIED')
        self.assertEqual(result['files'][0]['status'], 'CHANGED_OR_MISSING')
        self.assertEqual(result['practical']['files'][0]['classification'], 'INCONCLUSIVE')

    def test_database_sidecar_or_wal_header_at_finish_refuses_with_no_byte_status(self):
        for suffix in ('-wal', '-shm', '-journal'):
            with self.subTest(suffix=suffix):
                self.session = self.new_session(); self.begin()
                sidecar = Path(str(self.path(self.root, 0)) + suffix); sidecar.touch()
                result = self.refused('after')
                self.assertEqual(result['reason'], 'sqlite_sidecar_uncertain')
                self.assertNotIn('addons33_bytes', result)
                self.assertIsNone(self.session._fingerprint)
                sidecar.unlink()
        self.session = self.new_session(); self.begin()
        path = self.path(self.root, 0); raw = bytearray(path.read_bytes()); raw[18:20] = b'\x02\x02'
        path.write_bytes(raw)
        result = self.refused('after')
        self.assertEqual(result['reason'], 'sqlite_wal_mode_uncertain')
        self.assertNotIn('addons33_bytes', result)

    def test_sidecar_or_wal_header_at_begin_refuses_and_holds_no_fingerprint(self):
        sidecar = Path(str(self.path(self.root, 0)) + '-journal'); sidecar.touch()
        self.assertEqual(self.refused()['reason'], 'sqlite_sidecar_uncertain')
        self.assertIsNone(self.session._fingerprint)
        sidecar.unlink()
        self.session = self.new_session()
        path = self.path(self.root, 0); raw = bytearray(path.read_bytes()); raw[18:20] = b'\x02\x02'
        path.write_bytes(raw)
        self.assertEqual(self.refused()['reason'], 'sqlite_wal_mode_uncertain')
        self.assertIsNone(self.session._fingerprint)

    def test_addons33_changing_during_capture_refuses_at_both_boundaries(self):
        original = w.database_projection
        def changing(raw, kind):
            value = original(raw, kind)
            if kind == 0:
                with sqlite3.connect(self.path(self.root, 0)) as db:
                    db.execute("UPDATE installed SET lastUsed='moving'")
            return value
        with mock.patch.object(w, 'database_projection', side_effect=changing):
            result = self.refused()
        self.assertEqual(result['reason'], 'input_changed')
        self.assertIsNone(self.session._fingerprint)
        self.session = self.new_session()
        with sqlite3.connect(self.path(self.root, 0)) as db:
            db.execute("UPDATE installed SET lastUsed=?", (semantic.SECRET,))
        self.begin()
        with mock.patch.object(w, 'database_projection', side_effect=changing):
            result = self.refused('after')
        self.assertEqual(result['reason'], 'input_changed')
        self.assertNotIn('addons33_bytes', result)
        self.assertIsNone(self.session._fingerprint)

    def test_interrupted_acquisition_clears_the_fingerprint_and_cannot_retry(self):
        with mock.patch.object(w, 'read_copy', side_effect=KeyboardInterrupt):
            result = self.refused()
        self.assertNotIn('addons33_bytes', result)
        self.assertIsNone(self.session._fingerprint)
        self.session = self.new_session(); self.begin()
        self.assertIsNotNone(self.session._fingerprint)
        with mock.patch.object(w, 'read_copy', side_effect=KeyboardInterrupt):
            result = self.refused('after')
        self.assertNotIn('addons33_bytes', result)
        self.assertIsNone(self.session._fingerprint)
        with mock.patch.object(w, 'read_copy', side_effect=AssertionError('no retry')):
            self.refused('after')

    def test_interruption_while_fingerprinting_clears_everything(self):
        with mock.patch.object(bridge, '_fingerprint', side_effect=KeyboardInterrupt):
            result = self.refused()
        self.assertNotIn('addons33_bytes', result)
        self.assertIsNone(self.session._fingerprint)
        self.session = self.new_session(); self.begin()
        with mock.patch.object(bridge, '_fingerprint', side_effect=KeyboardInterrupt):
            result = self.refused('after')
        self.assertNotIn('addons33_bytes', result)
        self.assertIsNone(self.session._fingerprint)

    def test_failure_while_comparing_fingerprints_returns_no_block_and_clears_state(self):
        self.begin()
        with mock.patch.object(bridge, '_addons33_bytes', side_effect=RuntimeError(semantic.SECRET)):
            result = self.refused('after')
        self.assertNotIn('addons33_bytes', result)
        self.assertNotIn('practical', result)
        self.assertIsNone(self.session._fingerprint)

    def test_private_fingerprint_is_held_only_between_begin_and_finish(self):
        raw = self.addons_bytes()
        self.assertIsNone(self.session._fingerprint)
        self.begin()
        held = self.session._fingerprint
        self.assertEqual(held, (hashlib.sha256(raw).digest(), len(raw)))
        # No raw copy is retained: no slot holds the database bytes or anything of their size.
        for name in bridge.AcquisitionSession.__slots__:
            value = getattr(self.session, name)
            self.assertFalse(type(value) in (bytes, bytearray) and len(value) > 32, name)
            self.assertNotIn(raw, [value] if isinstance(value, bytes) else [])
        self.assertNotIn(repr(held[0]), repr(self.session))
        self.assertNotIn(held[0].hex(), repr(self.session))
        self.session.finish()
        self.assertIsNone(self.session._fingerprint)
        self.assertIsNone(self.session._before)

    def test_close_and_context_exit_clear_the_fingerprint(self):
        self.begin()
        self.assertIsNotNone(self.session._fingerprint)
        self.session.close()
        self.assertIsNone(self.session._fingerprint)
        self.session = self.new_session()
        with self.session:
            self.begin()
            self.assertIsNotNone(self.session._fingerprint)
        self.assertIsNone(self.session._fingerprint)
        self.assertEqual(self.refused('after')['reason'], 'session_closed')

    def test_a_second_finish_or_begin_cannot_rebuild_lost_evidence(self):
        self.begin()
        self.finished()
        again = self.safe(self.session.finish())
        self.assertEqual(again['reason'], 'session_closed')
        self.assertNotIn('addons33_bytes', again)
        again = self.safe(self.session.begin())
        self.assertEqual(again['reason'], 'session_closed')
        self.assertIsNone(self.session._fingerprint)

    def test_byte_witness_reads_nothing_beyond_the_fixed_five_sources(self):
        reader = w.read_copy
        calls = []
        def fixed(root, relative, limit):
            calls.append(relative)
            return reader(root, relative, limit)
        with mock.patch.object(w, 'read_copy', side_effect=fixed):
            self.begin(); self.finished()
        self.assertEqual(set(calls), set(w.FILES))
        # Each boundary reads each source twice (capture and stability pass), as before.
        self.assertEqual(len(calls), 20)

    def test_no_practical_pass_or_fail_or_maintenance_class_is_emitted_for_addons33(self):
        for change in (None, 'content', 'length'):
            with self.subTest(change=change):
                self.session = self.new_session(); self.begin()
                if change == 'content':
                    with sqlite3.connect(self.path(self.root, 0)) as db:
                        db.execute("UPDATE installed SET lastUsed='Y' || substr(lastUsed, 2)")
                elif change == 'length':
                    with sqlite3.connect(self.path(self.root, 0)) as db:
                        db.execute('CREATE TABLE IF NOT EXISTS unrelated (note TEXT)')
                        db.executemany('INSERT INTO unrelated VALUES (?)', [('y' * 900,)] * 10)
                result = self.finished()
                encoded = json.dumps(result)
                self.assertNotIn('PASS', encoded)
                self.assertNotIn('FAIL', encoded)
                self.assertEqual(result['practical']['verdict'], 'NOT_DECIDED')
                self.assertEqual(result['practical']['files'][0]['maintenance'], [])
                self.assertIn(self.byte_status(result), ('BYTES_IDENTICAL', 'BYTES_DIFFERENT'))

    def test_enabled_state_change_is_strict_changed_and_never_identical_bytes(self):
        self.begin()
        with sqlite3.connect(self.path(self.root, 0)) as db:
            db.execute('UPDATE installed SET enabled=0')
        result = self.finished()
        self.assertEqual(result['files'][0]['status'], 'CHANGED_OR_MISSING')
        self.assertEqual(self.byte_status(result), 'BYTES_DIFFERENT')

    def test_other_protected_files_do_not_affect_the_addons33_byte_status(self):
        self.begin()
        self.path(self.root, 4).write_text('<settings><setting id="layout" value="changed"/></settings>')
        result = self.finished()
        self.assertEqual(self.byte_status(result), 'BYTES_IDENTICAL')
        self.assertEqual(result['files'][4]['status'], 'CHANGED_OR_MISSING')
        self.assertEqual(result['scope_result'], 'CHANGED_OR_MISSING')
