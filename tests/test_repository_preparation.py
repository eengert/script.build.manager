"""Offline pre-Apply preparation -> fresh review -> exact library execution."""
from dataclasses import replace
import io
import json
from unittest.mock import patch
import unittest
import zipfile

from resources.lib import repository_preparation as prep
from resources.lib.build_library import LibraryInstallTarget, LibrarySource
from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
from resources.lib.frozen_install import FrozenInstallStore, FrozenInstallTransaction
from resources.lib.frozen_resolution import (
    FrozenInstallResolutionManifest, InstallResolution, ResolutionChoice, ResolutionState,
)
from resources.lib.plan import PlanTarget, ReadOnlyArtifactStore
from resources.lib.plan_model import DecisionChoice, PlanState, ReviewFreshness, IdentityComponent
from resources.lib.transaction import TransactionStore
from resources.lib.resolver import resolve_manifest
from tests import test_library_install as library_install_fixture
from tests.test_library_install import forbidden
from tests.test_plan import PlanHarness, REPOSITORY, LATE_DEPENDENCY, REDLIGHT_ADDON_ID
from tests.test_frozen_install import _zip, SESSION_B
from tests.test_status import DEMO, SECRET

INDEX_URL = 'http://127.0.0.1:9999/addons.xml'


def rewrite_xml(data, change):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(output, 'w') as result:
        for name in original.namelist():
            content = original.read(name)
            result.writestr(name, change(content) if name.endswith('/addon.xml') else content)
    return output.getvalue()


class RepositoryPreparationTests(unittest.TestCase):
    def setUp(self):
        self.f = library_install_fixture.LibraryInstallTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.store = self.f.artifacts
        self.raw = self.f.fixture.raw
        self.raw['device_profiles']['desk']['frozen_install_policies'] = [
            {'addon_id': DEMO, 'policy': 'exact_first_with_repository_fallback_or_skip', 'repository_id': REPOSITORY}]
        self.nodes = list(self.f.fixture.frozen.addons)
        self.store.artifact_path(self.nodes[0].artifact.sha256).unlink()
        repo = self.store.import_zip(_zip(REPOSITORY, '1.0.0', repository=True),
                                     expected_addon_id=REPOSITORY, expected_version='1.0.0')
        self.nodes.append(AddonCaptureNode(REPOSITORY, '1.0.0', 'xbmc.addon.repository', True,
                                          ProvenanceStatus.VERIFIED_REPOSITORY, artifact=repo))
        late = self.store.import_zip(_zip(LATE_DEPENDENCY, '3.0.0'),
                                     expected_addon_id=LATE_DEPENDENCY, expected_version='3.0.0')
        self.nodes.append(AddonCaptureNode(LATE_DEPENDENCY, '3.0.0', 'xbmc.python.module', True,
                                          ProvenanceStatus.UNKNOWN, artifact=late))
        self.package = _zip(DEMO, '2.0.0', requires=((LATE_DEPENDENCY, '3.0.0'),))
        self.index = f'<addons><addon id="{DEMO}" version="2.0.0"/></addons>'.encode()
        self.downloads = []

    def target(self):
        self.f.fixture.frozen = replace(self.f.fixture.frozen, addons=tuple(self.nodes))
        self.f.fixture.write_sources()
        install_target = self.f.target()
        self.install_target = install_target
        return PlanTarget('/unused-build', 'desk', '/unused-frozen',
                          library_source=install_target.source,
                          choices=((DEMO, DecisionChoice.INSTALL_CURRENT),))

    def download(self, url, *, max_bytes, timeout):
        self.downloads.append((url, max_bytes, timeout))
        if url == INDEX_URL:
            return self.index
        self.assertEqual(url, f'http://127.0.0.1:9999/{DEMO}/2.0.0/{DEMO}-2.0.0.zip')
        return self.package

    def prepare(self, target):
        # These owners must remain unreachable in BOTH successful and failed preparation.
        with patch.object(self.f.backend, 'install_exact', side_effect=forbidden), \
             patch.object(self.f.backend, 'set_addon_enabled', side_effect=forbidden), \
             patch.object(self.f.backend, 'resolve_repository_current', side_effect=forbidden), \
             patch.object(self.f.policy, 'set_policy', side_effect=forbidden), \
             patch.object(FrozenInstallStore, 'create', side_effect=forbidden), \
             patch.object(TransactionStore, 'create', side_effect=forbidden):
            result = prep.RepositoryPreparationService(self.store, download=self.download).prepare(target)
        self.f.assert_no_mutation()
        self.assertIsNone(self.f.restart_store.inspect())
        return result

    def prepared(self):
        target = self.target()
        result = self.prepare(target)
        self.assertEqual(result.code, prep.PreparationCode.READY, result)
        return replace(target, prepared_resolution=result.prepared)

    def harness(self):
        h = PlanHarness(self, with_private=False, with_resource=False)
        del h.kodi.addons[DEMO]
        h.deps.installed.pop(DEMO, None)
        return h

    def preview(self, h, target):
        # Existing read-only tripwires prohibit downloads, store creation/import, and mutations.
        with h.instrumented():
            plan = h.plan_service(status=h.owners(resolver=resolve_manifest),
                                  artifact_store=ReadOnlyArtifactStore(self.store.root)).preview(target)
        h.assert_untouched()
        return plan

    def validate(self, h, target, review):
        with h.instrumented():
            check = h.plan_service(status=h.owners(resolver=resolve_manifest),
                                  artifact_store=ReadOnlyArtifactStore(self.store.root)).validate(target, review)
        h.assert_untouched()
        return check

    def apply(self, target, **kwargs):
        with self.f.isolated(), patch.object(self.f.backend, 'resolve_repository_current', side_effect=forbidden):
            return self.f.coordinator(**kwargs).install_target(
                LibraryInstallTarget.from_plan_target(target), prepared_resolution=target.prepared_resolution,
                resolution_choices={a: ResolutionChoice(c.value) for a, c in target.choices})

    def test_encoded_dtd_index_fails_closed(self):
        target = self.target()
        for encoding in ('utf-8', 'utf-16', 'utf-16le', 'utf-16be'):
            with self.subTest(encoding=encoding):
                self.index = ('<!DOCTYPE addons [<!ENTITY version "2.0.0">]>'
                              f'<addons><addon id="{DEMO}" version="&version;"/></addons>').encode(encoding)
                result = self.prepare(target)
                self.assertEqual(result.code, prep.PreparationCode.INDEX_INVALID)
                self.assertIsNone(result.prepared)

    def test_encoded_ordinary_index_declaration_prepares_exact_identity(self):
        target = self.target()
        for encoding in ('utf-8', 'utf-16', 'utf-16le', 'utf-16be'):
            declaration = 'UTF-16' if encoding.startswith('utf-16') else 'UTF-8'
            with self.subTest(encoding=encoding):
                self.index = (f'<?xml version="1.0" encoding="{declaration}"?>'
                              f'<addons><addon id="{DEMO}" version="2.0.0"/></addons>').encode(encoding)
                result = self.prepare(target)
                self.assertEqual(result.code, prep.PreparationCode.READY)
                record, = result.prepared.records
                self.assertEqual((record.addon_id, record.resolved_version), (DEMO, '2.0.0'))
                self.assertEqual(self.store.read_bytes(record.artifact_sha256), self.package)

    def test_final_boundary_artifact_corruption_fails_before_mutation(self):
        target = self.prepared()
        h = self.harness()
        review = self.preview(h, target).review
        self.assertEqual(self.validate(h, target, review).freshness, ReviewFreshness.CURRENT)
        dependency = next(n for n in self.nodes if n.addon_id == LATE_DEPENDENCY)
        for digest in (dependency.artifact.sha256, target.prepared_resolution.records[0].artifact_sha256):
            with self.subTest(digest=digest):
                path = self.store.artifact_path(digest)
                original_bytes = path.read_bytes()
                original_load = LibraryInstallTarget.load
                calls = []
                def load(bound):
                    value = original_load(bound)
                    calls.append(bound)
                    if len(calls) == 3:
                        path.write_bytes(b'corrupt')
                    return value
                with patch.object(LibraryInstallTarget, 'load', load), \
                     patch.object(self.f.backend, 'install_exact', side_effect=forbidden), \
                     patch.object(self.f.backend, 'set_addon_enabled', side_effect=forbidden), \
                     patch.object(self.f.policy, 'set_policy', side_effect=forbidden), \
                     patch.object(self.f.store, 'create', side_effect=forbidden):
                    result = self.apply(target)
                path.write_bytes(original_bytes)
                self.assertEqual(len(calls), 3)
                self.assertEqual(result.outcome, 'failed', result)
                self.assertIsNone(self.f.store.inspect())
                self.f.assert_no_mutation()
                self.assertEqual(len(self.downloads), 2)
        self.package = b'remote changed'
        self.assertEqual(self.apply(target).outcome, 'complete')
        self.assertEqual(len(self.downloads), 2)

    def test_unprepared_choice_has_no_review(self):
        target = self.target()
        plan = self.preview(self.harness(), target)
        self.assertEqual(plan.state, PlanState.RESOLUTION_REQUIRED, plan.to_safe_dict())
        self.assertIsNone(plan.review)
        self.assertEqual(next(r for r in plan.software if r.addon_id == DEMO).version, '')
        self.assertEqual(self.downloads, [])
        result = self.apply(target)
        self.assertEqual(result.code, 'PREPARATION_REQUIRED')
        self.f.assert_no_mutation()

    def test_prepare_uses_captured_authority_without_installed_repository_and_imports_exact_zip(self):
        target = self.prepared()
        self.assertEqual(self.downloads, [(INDEX_URL, prep.INDEX_LIMIT, 30.0),
            (f'http://127.0.0.1:9999/{DEMO}/2.0.0/{DEMO}-2.0.0.zip', prep.PACKAGE_LIMIT, 30.0)])
        p = target.prepared_resolution
        self.assertEqual(prep.PreparedRepositoryResolution.from_dict(p.to_dict()), p)
        r, = p.records
        self.assertEqual((r.repository_id, r.resolved_version, r.captured_version, r.state),
                         (REPOSITORY, '2.0.0', '1.0.0', ResolutionState.RESOLVED))
        self.assertEqual(r.artifact_size, len(self.package))
        self.assertEqual(self.store.read_bytes(r.artifact_sha256), self.package)
        self.assertEqual(p.build_id, 'demo')
        self.assertEqual(p.device_profile_id, 'desk')
        # A preparation cannot be parsed as a completed install outcome.
        with self.assertRaises(Exception): FrozenInstallResolutionManifest.from_dict(p.to_dict())

    def test_fresh_review_binds_package_and_dependencies_and_apply_never_refetches(self):
        target = self.prepared()
        h = self.harness()
        plan = self.preview(h, target)
        self.assertEqual(plan.state, PlanState.CHANGES_READY, plan.to_safe_dict())
        self.assertIsNotNone(plan.review)
        self.assertEqual(next(r for r in plan.software if r.addon_id == DEMO).version, '2.0.0')
        order = [r.addon_id for r in plan.software]
        self.assertLess(order.index(LATE_DEPENDENCY), order.index(DEMO))
        self.assertEqual(self.validate(h, target, plan.review).freshness, ReviewFreshness.CURRENT)
        self.package = _zip(DEMO, '9.0.0')  # remote current changes after approval
        result = self.apply(target)
        self.assertEqual(result.outcome, 'complete', (result.code, result.message))
        self.assertEqual(self.f.backend.installed[DEMO].version, '2.0.0')
        self.assertEqual(len(self.downloads), 2)
        r = next(r for r in result.resolution_manifest.records if r.addon_id == DEMO)
        self.assertEqual(r.artifact_sha256, target.prepared_resolution.records[0].artifact_sha256)
        self.assertEqual(r.state, ResolutionState.INSTALLED)

    def test_review_stales_on_new_package_version_digest_size_and_dependencies(self):
        target = self.prepared(); h = self.harness()
        review = self.preview(h, target).review
        for version, requires in [('2.0.0', ()), ('3.0.0', ((LATE_DEPENDENCY, '1.0.0'),))]:
            data = _zip(DEMO, version, requires=requires)
            m = self.store.import_zip(data, expected_addon_id=DEMO, expected_version=version)
            r = replace(target.prepared_resolution.records[0], resolved_version=version,
                        artifact_sha256=m.sha256, artifact_size=m.size)
            changed = replace(target, prepared_resolution=replace(target.prepared_resolution, records=(r,)))
            plan = self.preview(h, changed)
            self.assertEqual(plan.state, PlanState.CHANGES_READY, plan.to_safe_dict())
            self.assertNotEqual(review.digest, plan.review.digest)
            check = self.validate(h, changed, review)
            self.assertEqual(check.freshness, ReviewFreshness.STALE)
            self.assertIn(IdentityComponent.POLICY, check.changed)

    def test_binding_mismatches_fail_before_any_mutation(self):
        target = self.prepared(); h = self.harness(); review = self.preview(h, target).review
        p = target.prepared_resolution
        alterations = dict(source_identity='a'*64, device_profile_id='other', build_id='different',
                           source_software_fingerprint='b'*64, install_plan_fingerprint='c'*64,
                           build_fingerprint='d'*64)
        for key, value in alterations.items():
            with self.subTest(key=key):
                changed = replace(target, prepared_resolution=replace(p, **{key: value}))
                self.assertIsNone(self.preview(h, changed).review)
                self.assertNotEqual(self.validate(h, changed, review).freshness, ReviewFreshness.CURRENT)
                self.assertEqual(self.apply(changed).outcome, 'failed')
                self.f.assert_no_mutation()

    def test_artifact_corruption_missing_and_metadata_mismatch_fail_closed(self):
        target = self.prepared(); h = self.harness(); review = self.preview(h, target).review
        r, = target.prepared_resolution.records
        path = self.store.artifact_path(r.artifact_sha256); original = path.read_bytes()
        for payload in (None, b'corrupt'):
            if payload is None: path.unlink()
            else: path.write_bytes(payload)
            self.assertIsNone(self.preview(h, target).review)
            self.assertNotEqual(self.validate(h, target, review).freshness, ReviewFreshness.CURRENT)
            self.assertEqual(self.apply(target).outcome, 'failed')
            self.f.assert_no_mutation(); path.write_bytes(original)
        changed = replace(target, prepared_resolution=replace(target.prepared_resolution,
                          records=(replace(r, artifact_size=r.artifact_size + 1),)))
        self.assertIsNone(self.preview(h, changed).review)
        self.assertEqual(self.apply(changed).outcome, 'failed'); self.f.assert_no_mutation()

    def test_repository_mismatch_and_choice_change_reject_preparation(self):
        target = self.prepared(); r, = target.prepared_resolution.records
        changed = replace(target, prepared_resolution=replace(target.prepared_resolution,
                          records=(replace(r, repository_id='repository.other'),)))
        self.assertIsNone(self.preview(self.harness(), changed).review)
        self.assertEqual(self.apply(changed).outcome, 'failed'); self.f.assert_no_mutation()
        changed = target.with_choice(DEMO, DecisionChoice.SKIP)
        self.assertIsNone(self.preview(self.harness(), changed).review)
        self.assertEqual(self.apply(changed).outcome, 'failed'); self.f.assert_no_mutation()

    def test_captured_repository_missing_cannot_substitute_installed_repo(self):
        target = self.target()
        repo = next(n for n in self.nodes if n.addon_id == REPOSITORY)
        self.store.artifact_path(repo.artifact.sha256).unlink()
        result = self.prepare(target)
        self.assertNotEqual(result.code, prep.PreparationCode.READY)
        self.assertEqual(self.downloads, [])

    def test_invalid_index_versions_and_packages_fail_without_transactions_or_leaks(self):
        target = self.target()
        for index, package in [
            (b'<addons/>', self.package), (b'broken', self.package),
            (f'<addons><addon id="{DEMO}" version="../secret"/></addons>'.encode(), self.package),
            (self.index, b'invalid zip'), (self.index, _zip(DEMO, 'wrong')),
            (self.index, _zip('plugin.video.other', '2.0.0')),
            (b'<!DOCTYPE x [<!ENTITY private "'+SECRET.encode()+b'">]><addons/>', self.package),
        ]:
            with self.subTest(index=index[:20]):
                self.index, self.package = index, package
                result = self.prepare(target)
                self.assertIsNone(result.prepared)
                safe = json.dumps(result.to_safe_dict()) + repr(result)
                self.assertNotIn(SECRET, safe); self.assertNotIn(str(self.store.root), safe)
                self.assertNotIn('http', safe)

    def test_incompatible_dependencies_uncaptured_newer_or_skipped_fail_before_import(self):
        target = self.target()
        for requires in [(('script.module.uncaptured', '1.0.0'),), ((LATE_DEPENDENCY, '4.0.0'),)]:
            self.package = _zip(DEMO, '2.0.0', requires=requires)
            with patch.object(self.store, 'import_zip', side_effect=forbidden):
                self.assertEqual(self.prepare(target).code, prep.PreparationCode.INCOMPATIBLE)

    def test_import_failure_is_safe_and_typed(self):
        target = self.target()
        with patch.object(self.store, 'import_zip', side_effect=OSError(SECRET)):
            result = self.prepare(target)
        self.assertEqual(result.code, prep.PreparationCode.IMPORT_FAILED)
        self.assertNotIn(SECRET, repr(result))

    def test_skip_still_reviewable_without_fetch(self):
        target = self.target().with_choice(DEMO, DecisionChoice.SKIP)
        plan = self.preview(self.harness(), target)
        self.assertEqual(plan.state, PlanState.CHANGES_READY, plan.to_safe_dict())
        self.assertIsNotNone(plan.review); self.assertEqual(self.downloads, [])

    def test_resume_restores_exact_prepared_resolution_without_network(self):
        target = self.prepared()
        from resources.lib.restart_coordinator import RestartCoordinator, RestartCapabilityResolver
        from resources.lib.resume import ResumeCoordinator
        from tests.test_frozen_install import SESSION_A
        restart = RestartCoordinator(self.f.manager(restart=True), store=self.f.restart_store,
                                     session_id_provider=lambda: SESSION_A,
                                     capability_resolver=RestartCapabilityResolver(platform_id='macos'))
        result = self.apply(target, runner=restart.reconcile)
        self.assertEqual(result.outcome, 'awaiting_restart', (result.code, result.message))
        persisted = self.f.store.inspect()
        roundtrip = FrozenInstallTransaction.from_dict(persisted.to_dict())
        self.assertEqual(roundtrip.resolution_records, persisted.resolution_records)
        record = next(r for r in persisted.resolution_records if r.addon_id == DEMO)
        self.assertEqual(record.artifact_sha256, target.prepared_resolution.records[0].artifact_sha256)
        with self.f.isolated(), patch.object(self.f.backend, 'resolve_repository_current', side_effect=forbidden):
            restart_tx = self.f.restart_store.inspect()
            resumed = ResumeCoordinator(self.f.manager(), store=self.f.restart_store,
                                        session_id_provider=lambda: SESSION_B).resume(restart_tx)
            self.assertTrue(resumed.succeeded, resumed)
            result = self.f.coordinator(session=SESSION_B).resume_after_restart(bm020_result=resumed)
        self.assertEqual(result.outcome, 'complete', (result.code, result.message))
        self.assertEqual(self.f.backend.installed[DEMO].version, '2.0.0')
        self.assertEqual(len(self.downloads), 2)

    def test_prepared_incompatible_dependency_zip_blocks_preview_and_apply(self):
        target = self.prepared(); h = self.harness()
        review = self.preview(h, target).review
        data = _zip(DEMO, '2.0.0', requires=(('script.module.uncaptured', '1.0.0'),))
        m = self.store.import_zip(data, expected_addon_id=DEMO, expected_version='2.0.0')
        r = replace(target.prepared_resolution.records[0], artifact_sha256=m.sha256, artifact_size=m.size)
        target = replace(target, prepared_resolution=replace(target.prepared_resolution, records=(r,)))
        self.assertEqual(self.preview(h, target).state, PlanState.BLOCKED)
        self.assertNotEqual(self.validate(h, target, review).freshness, ReviewFreshness.CURRENT)
        self.assertEqual(self.apply(target).outcome, 'failed'); self.f.assert_no_mutation()

    def test_skipped_dependency_blocks_preparation_before_import(self):
        late = next(n for n in self.nodes if n.addon_id == LATE_DEPENDENCY)
        self.store.artifact_path(late.artifact.sha256).unlink()
        self.raw['device_profiles']['desk']['frozen_install_policies'].append(
            {'addon_id': LATE_DEPENDENCY, 'policy': 'exact_first_with_repository_fallback_or_skip'})
        target = self.target().with_choice(LATE_DEPENDENCY, DecisionChoice.SKIP)
        with patch.object(self.store, 'import_zip', side_effect=forbidden):
            self.assertEqual(self.prepare(target).code, prep.PreparationCode.INCOMPATIBLE)

    def test_held_resource_blocks_preparation_and_forged_prepared_review_before_apply(self):
        from tests.test_status import redlight_resource_declaration
        owner = self.store.import_zip(_zip(REDLIGHT_ADDON_ID, '2.6.8'),
                                     expected_addon_id=REDLIGHT_ADDON_ID, expected_version='2.6.8')
        self.nodes.append(AddonCaptureNode(REDLIGHT_ADDON_ID, '2.6.8', 'xbmc.python.pluginsource',
                                          True, ProvenanceStatus.UNKNOWN, artifact=owner))
        self.raw['config']['structured_private_resources'] = [redlight_resource_declaration().safe_dict()]
        target = self.target()
        with patch.object(self.store, 'import_zip', side_effect=forbidden):
            self.assertEqual(self.prepare(target).code, prep.PreparationCode.INCOMPATIBLE)
        # A serialized identity is never a bypass of the Plan/install held-resource checks.
        public, frozen, loader = self.install_target.load()
        desired = resolve_manifest(public, 'desk')
        m = self.store.import_zip(self.package, expected_addon_id=DEMO, expected_version='2.0.0')
        from resources.lib.frozen_resolution import InstallResolutionRecord
        record = InstallResolutionRecord(DEMO, '1.0.0', InstallResolution.REPOSITORY_CURRENT,
                                         ResolutionState.RESOLVED, True, REPOSITORY, '2.0.0', m.sha256, m.size)
        p = prep.PreparedRepositoryResolution(**prep._binding(target.library_source, 'desk', desired,
                                                               frozen, loader), records=(record,))
        target = replace(target, prepared_resolution=p)
        self.assertEqual(self.preview(self.harness(), target).state, PlanState.BLOCKED)
        self.assertEqual(self.apply(target).outcome, 'failed'); self.f.assert_no_mutation()

    def test_private_setting_ownership_blocks_repository_fallback(self):
        self.raw['config']['private_settings'] = [
            {'addon_id': DEMO, 'key': 'api_token', 'type': 'string', 'required': True, 'sensitivity': 'token'}]
        target = self.target()
        self.assertEqual(self.prepare(target).code, prep.PreparationCode.INCOMPATIBLE)

    def test_exact_only_policy_cannot_prepare_or_fetch(self):
        self.raw['device_profiles']['desk']['frozen_install_policies'] = []
        target = self.target()
        self.assertNotEqual(self.prepare(target).code, prep.PreparationCode.READY)
        self.assertEqual(self.downloads, [])

    def test_actual_other_source_or_profile_cannot_use_prepared_resolution(self):
        target = self.prepared()
        for changed in [replace(target, device_profile_id='other'),
                        replace(target, library_source=LibrarySource(target.library_source.root, 'unknown'))]:
            self.assertIsNone(self.preview(self.harness(), changed).review)
            try:
                result = self.apply(changed)
            except Exception:
                pass  # LibraryInstallTarget itself can reject a nonexistent entry before install.
            else:
                self.assertEqual(result.outcome, 'failed')
            self.f.assert_no_mutation()

    def test_source_changes_during_network_fetch_cannot_produce_prepared_identity(self):
        target = self.target()
        envelope = self.f.fixture.envelope(target.library_source.entry_id)
        original = self.download
        def changed(url, **kwargs):
            data = original(url, **kwargs)
            envelope.write_bytes(b'corrupt')
            return data
        self.download = changed
        self.assertEqual(self.prepare(target).code, prep.PreparationCode.TARGET_INVALID)

    def test_serialized_preparation_rejects_unknown_fields_invalid_versions_and_terminal_state(self):
        target = self.prepared(); p = target.prepared_resolution
        for field, value in [('resolved_version', '../unsafe'), ('state', 'installed'), ('desired_enabled', 1)]:
            raw = p.to_dict(); raw['records'][0][field] = value
            with self.assertRaises(prep.PreparationError): prep.PreparedRepositoryResolution.from_dict(raw)
        raw = p.to_dict(); raw['url'] = 'https://user:secret@example.org/'
        with self.assertRaises(prep.PreparationError): prep.PreparedRepositoryResolution.from_dict(raw)


class CapturedRepositoryMetadataTests(unittest.TestCase):
    def test_parser_rejects_encoded_dtd_and_accepts_ordinary_declarations(self):
        for encoding in ('utf-8', 'utf-16', 'utf-16le', 'utf-16be', 'iso-8859-1'):
            declaration = 'UTF-16' if encoding.startswith('utf-16') else encoding
            prefix = f'<?xml version="1.0" encoding="{declaration}"?>'
            with self.subTest(encoding=encoding):
                normal = (prefix + '<addons><addon version="2.0.0"/></addons>').encode(encoding)
                self.assertEqual(prep._xml(normal).find('addon').get('version'), '2.0.0')
                for subset in ('', '[<!ENTITY value "ENTITY_SENTINEL">]'):
                    hostile = (prefix + '<!DOCTYPE addons ' + subset +
                               '><addons>&value;</addons>').encode(encoding)
                    with self.assertRaises(ValueError): prep._xml(hostile)
        # ElementTree does not support UTF-32 here; it must still fail closed.
        for encoding in ('utf-32', 'utf-32le', 'utf-32be'):
            with self.assertRaises(Exception):
                prep._xml('<!DOCTYPE addons [<!ENTITY x "sentinel">]><addons>&x;</addons>'.encode(encoding))

    def test_encoded_captured_repository_dtd_never_supplies_url_or_package(self):
        original = _zip(REPOSITORY, '1.0.0', repository=True)
        for encoding in ('utf-8', 'utf-16', 'utf-16le', 'utf-16be'):
            def change(xml):
                text = xml.decode().replace(INDEX_URL, '&url;')
                return ('<!DOCTYPE addon [<!ENTITY url "' + INDEX_URL + '">]>' + text).encode(encoding)
            with self.subTest(encoding=encoding), self.assertRaises(prep.PreparationError) as error:
                prep._fetch_package(rewrite_xml(original, change), REPOSITORY, DEMO, forbidden)
            self.assertEqual(error.exception.code, prep.PreparationCode.METADATA_UNSUPPORTED)
            self.assertNotIn(INDEX_URL, str(error.exception))

    def test_unsafe_and_unsupported_metadata_does_not_download(self):
        original = _zip(REPOSITORY, '1.0.0', repository=True)
        for changed in [
            lambda x: x.replace(b'http://127.0.0.1:9999/addons.xml', b'file:///private/secret'),
            lambda x: x.replace(b'http://127.0.0.1:9999/addons.xml', b'https://user:secret@example.org/index'),
            lambda x: x.replace(b'zip="true"', b'zip="false"'),
            lambda x: x.replace(b'<dir>', b'<dir minversion="21">'),
            lambda x: x.replace(b'</dir>', b'</dir><dir/>'),
        ]:
            with self.subTest(changed=changed), self.assertRaises(prep.PreparationError) as error:
                prep._fetch_package(rewrite_xml(original, changed), REPOSITORY, DEMO, forbidden)
            self.assertEqual(error.exception.code, prep.PreparationCode.METADATA_UNSUPPORTED)
            self.assertNotIn('secret', str(error.exception))

    def test_bounds_enforced_even_if_downloader_violates_contract(self):
        repo = _zip(REPOSITORY, '1.0.0', repository=True)
        with self.assertRaises(prep.PreparationError):
            prep._fetch_package(repo, REPOSITORY, DEMO, lambda *a, **k: b'x'*(prep.INDEX_LIMIT+1))

    def test_package_download_bound_is_checked(self):
        repo = _zip(REPOSITORY, '1.0.0', repository=True)
        def download(url, **kwargs):
            return (f'<addons><addon id="{DEMO}" version="2.0.0"/></addons>'.encode()
                    if url == INDEX_URL else b'x'*21)
        with patch.object(prep, 'PACKAGE_LIMIT', 20), self.assertRaises(prep.PreparationError):
            prep._fetch_package(repo, REPOSITORY, DEMO, download)

    def test_production_downloader_enforces_stream_bound_and_redirect_policy(self):
        from resources.lib import repository
        from unittest.mock import Mock
        response = io.BytesIO(b'x'*21)
        opener = Mock(); opener.open.return_value = response
        with patch.object(repository, '_build_safe_opener', return_value=opener):
            with self.assertRaises(repository.RepositoryInstallError):
                repository._download_artifact('https://example.org/index', max_bytes=20, timeout=30.0)
        opener.open.assert_called_once_with('https://example.org/index', timeout=30.0)
        handler = repository._SafeRedirectHandler()
        for url in ['file:///private/data', 'https://user:secret@example.org/index']:
            with self.assertRaises(repository.RepositoryInstallError):
                handler.redirect_request(None, None, 302, '', {}, url)
