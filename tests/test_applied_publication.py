"""Offline crash boundaries and exact applied-resolution continuity."""
from dataclasses import replace
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from resources.lib import build_library as lib
from resources.lib.build_library import BuildLibrary, LibraryInstallTarget, LibrarySource
from resources.lib.config import ConfigurationInspector, ReadOnlyConfigurationBackend
from resources.lib.frozen import AddonCaptureNode, ProvenanceStatus
from resources.lib.frozen_install import (FrozenInstallStore, FrozenInstallPhase,
    run_frozen_install_startup,
    ensure_frozen_install_guard)
from resources.lib.frozen_resolution import (ResolutionChoice, InstallResolution,
    resolved_software_fingerprint)
from resources.lib.plan import BuildPlanService
from resources.lib.resolver import resolve_manifest
from resources.lib.status import BuildStatusService
from tests import test_library_install as install_fixture
from tests.test_library_install import forbidden
from tests.test_plan import PlanHarness, ReadOnlyArtifactStore
from tests.test_frozen_install import _zip


class ProcessInterrupted(BaseException):
    """Bypass Exception handling, just as process death bypasses finalizers."""


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.x = install_fixture.LibraryInstallTests()
        self.x.setUp()
        self.addCleanup(self.x.doCleanups)
        self.library = self.x.fixture.library

    def snapshot(self):
        x = self.x
        return (dict(x.backend.installed), list(x.backend.install_calls),
                list(x.config.mutations), list(x.policy.calls))

    def install(self, target, **kwargs):
        with self.x.isolated():
            return self.x.coordinator().install_target(target, interactive=False, **kwargs)

    def recover(self):
        # Fresh durable owner, no installer/configuration runner or session needed.
        return run_frozen_install_startup(
            bm020_status=SimpleNamespace(resume_result=None),
            store=FrozenInstallStore(self.x.store.root), policy_backend=self.x.policy,
            installer=SimpleNamespace(install_exact=forbidden), configuration_runner=forbidden)

    def assert_complete(self, target, result):
        self.assertEqual(result.outcome, "complete", result)
        self.assertIsNone(self.library.pending_publication())
        self.assertIsNone(self.x.store.inspect())
        applied = self.library.current_applied_association()
        self.assertEqual((applied.entry_id, applied.device_profile_id),
                         (target.source.entry_id, target.device_profile_id))
        self.assertEqual(applied.resolution_fingerprint, result.resolution_manifest.resolution_fingerprint)

    def staged(self, boundary="B", prior=True):
        previous = self.x.seed_prior_association() if prior else None
        target = self.x.target()
        if boundary == "A":
            owner, method = FrozenInstallStore, "clear_expected"
        elif boundary == "B":
            owner, method = BuildLibrary, "_record_applied_completion"
        else:
            owner, method = BuildLibrary, "_acknowledge_publication"
        with patch.object(owner, method, side_effect=ProcessInterrupted), self.assertRaises(ProcessInterrupted):
            self.install(target)
        return previous, target

    def test_crash_boundaries_A_B_C_fresh_owner_no_install_mutation(self):
        for boundary in ("A", "B", "C"):
            with self.subTest(boundary=boundary):
                if boundary != "A": self.setUp()
                prior, target = self.staged(boundary)
                pending = self.library.pending_publication()
                self.assertIsNotNone(pending)
                self.assertEqual(pending.previous, prior)
                self.assertEqual(self.library.current_applied_association(), prior)
                self.assertEqual(self.x.store.inspect() is not None, boundary == "A")
                self.library.select(target.source.entry_id, "other")
                before = self.snapshot()
                with patch.object(lib, "_atomic", wraps=lib._atomic) as writes:
                    result = self.recover()
                self.assertEqual(sum(call.args[1] == "applied.json" for call in writes.call_args_list),
                                 0 if boundary == "C" else 1)
                self.assert_complete(target, result)
                self.assertEqual(before, self.snapshot())
                committed = (Path(self.library.root) / "applied.json").read_bytes()
                self.assertIsNone(self.recover())
                self.assertEqual(committed, (Path(self.library.root) / "applied.json").read_bytes())
                # A stale concurrent owner also acknowledges idempotently.
                self.library._record_applied_completion(pending, resolution_store=self.x.store)
                self.assertEqual(committed, (Path(self.library.root) / "applied.json").read_bytes())

    def test_write_failure_before_and_after_applied_replacement_masks_candidate(self):
        for after in (False, True):
            with self.subTest(after=after):
                if after: self.setUp()
                prior = self.x.seed_prior_association(); target = self.x.target()
                original = lib._atomic
                def fail(fd, name, data):
                    if name == "applied.json":
                        if after: original(fd, name, data)
                        raise OSError("injected write boundary")
                    return original(fd, name, data)
                with patch.object(lib, "_atomic", side_effect=fail):
                    result = self.install(target)
                self.assertEqual(result.outcome, "needs_attention")
                self.assertIsNone(self.x.store.inspect())
                self.assertIsNotNone(self.library.pending_publication())
                self.assertEqual(self.library.current_applied_association(), prior)
                visible = json.loads((Path(self.library.root) / "applied.json").read_text())
                self.assertEqual(visible["entry_id"], target.source.entry_id if after else prior.entry_id)
                before = self.snapshot()
                self.assert_complete(target, self.recover())
                self.assertEqual(before, self.snapshot())

    def test_pending_without_previous_masks_even_replaced_candidate(self):
        _, target = self.staged("C", prior=False)
        self.assertIsNone(self.library.current_applied_association())
        self.assertIsNone(self.library.associated_status_target())
        self.assertIsNone(self.library.associated_plan_target())
        self.assert_complete(target, self.recover())

    def test_acknowledgement_interruption_before_and_after_unlink(self):
        for after in (False, True):
            with self.subTest(after=after):
                if after: self.setUp()
                prior = self.x.seed_prior_association(); target = self.x.target()
                original = BuildLibrary._acknowledge_publication
                def interrupt(fd):
                    if after: original(fd)
                    raise ProcessInterrupted()
                with patch.object(BuildLibrary, "_acknowledge_publication", side_effect=interrupt), self.assertRaises(ProcessInterrupted):
                    self.install(target)
                if after:
                    self.assertIsNone(self.library.pending_publication())
                    self.assertEqual(self.library.current_applied_association().entry_id, target.source.entry_id)
                    self.assertIsNone(self.recover())
                else:
                    self.assertEqual(self.library.current_applied_association(), prior)
                    self.assert_complete(target, self.recover())

    def test_post_unlink_fsync_exception_reports_complete_no_dangling_attention(self):
        target = self.x.target()
        def ambiguous(fd):
            os.unlink("applied-publication.json", dir_fd=fd)
            raise OSError("post unlink fsync")
        with patch.object(BuildLibrary, "_acknowledge_publication", side_effect=ambiguous):
            result = self.install(target)
        self.assert_complete(target, result)

    def test_clear_post_unlink_failure_reconciles_actual_state(self):
        target = self.x.target(); original = FrozenInstallStore.clear_expected
        def ambiguous(store, **kwargs):
            original(store, **kwargs)
            raise OSError("post clear fsync")
        with patch.object(FrozenInstallStore, "clear_expected", new=ambiguous):
            result = self.install(target)
        self.assert_complete(target, result)

    def test_intent_write_before_and_after_replacement_remains_recoverable(self):
        for after in (False, True):
            with self.subTest(after=after):
                if after: self.setUp()
                prior = self.x.seed_prior_association(); target = self.x.target()
                original = lib._atomic
                def fail(fd, name, data):
                    if name == "applied-publication.json":
                        if after: original(fd, name, data)
                        raise OSError("intent failure")
                    original(fd, name, data)
                with patch.object(lib, "_atomic", side_effect=fail):
                    result = self.install(target)
                self.assertEqual(result.outcome, "needs_attention")
                self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.COMPLETE)
                self.assertEqual(self.library.current_applied_association(), prior)
                before = self.snapshot()
                self.assert_complete(target, self.recover())
                self.assertEqual(before, self.snapshot())

    def test_active_transaction_must_match_intent_before_cleanup(self):
        prior, target = self.staged("A")
        original = self.x.store.transaction_path.read_bytes()
        raw = json.loads(original); raw["transaction_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        self.x.store.transaction_path.write_text(json.dumps(raw))
        result = self.recover()
        self.assertEqual(result.outcome, "needs_attention")
        self.assertIsNotNone(self.x.store.inspect())
        self.assertEqual(self.library.current_applied_association(), prior)
        self.assertIsNotNone(self.library.pending_publication())
        self.x.store.transaction_path.write_bytes(original)
        self.assert_complete(target, self.recover())

    def test_changed_removed_source_profile_and_resolution_leave_pending_attention(self):
        for mode in ("missing_entry", "changed_entry", "removed_profile", "missing_resolution", "corrupt_resolution"):
            with self.subTest(mode=mode):
                if mode != "missing_entry": self.setUp()
                prior, target = self.staged()
                pending = self.library.pending_publication()
                path = self.x.fixture.envelope(target.source.entry_id)
                if "resolution" in mode: path = self.x.store.resolution_path(pending.candidate.resolution_fingerprint)
                saved = path.read_bytes()
                if mode.startswith("missing"): path.unlink()
                elif mode == "corrupt_resolution": path.write_text("{")
                else:
                    raw = json.loads(saved)
                    if mode == "changed_entry": raw["manifest"]["build"]["name"] = "Changed"
                    else: del raw["manifest"]["device_profiles"]["desk"]
                    path.write_text(json.dumps(raw))
                before = self.snapshot()
                self.assertEqual(self.recover().outcome, "needs_attention")
                self.assertEqual(self.library.pending_publication(), pending)
                self.assertEqual(self.library.current_applied_association(), prior)
                self.assertEqual(before, self.snapshot())
                path.write_bytes(saved)
                self.assert_complete(target, self.recover())

    def test_pending_blocks_install_and_is_nonidle_for_startup_status_plan(self):
        prior, target = self.staged()
        before = self.snapshot()
        result = self.install(target)
        self.assertEqual(result.code, "APPLIED_PUBLICATION_PENDING")
        self.assertEqual(before, self.snapshot())
        guard = ensure_frozen_install_guard(store=self.x.store, policy_backend=self.x.policy)
        self.assertFalse(guard.allowed); self.assertEqual(guard.code, "APPLIED_PUBLICATION_PENDING")
        h = PlanHarness(self, with_private=False, with_resource=False)
        owners = h.owners(publication_snapshot=self.library.pending_publication)
        status = BuildStatusService(owners).check()
        self.assertEqual(status.operation.kind.value, "needs_attention")
        self.assertEqual(status.operation.status_code, "APPLIED_PUBLICATION_PENDING")
        self.assertEqual(status.overall.value, "needs_attention")
        self.assertEqual(self.library.current_applied_association(), prior)
        self.assert_complete(target, self.recover())

    def test_malformed_pending_is_attention_and_masks_unacknowledged_bytes(self):
        prior, target = self.staged("C")
        path = Path(self.library.root) / "applied-publication.json"
        saved = path.read_bytes()
        for data in (b"{", b"null", b"x" * (lib.STATE_LIMIT + 1)):
            path.write_bytes(data)
            self.assertIsNone(self.library.current_applied_association())
            self.assertEqual(self.recover().outcome, "needs_attention")
            before = self.snapshot()
            self.assertNotEqual(self.install(target).outcome, "complete")
            self.assertEqual(before, self.snapshot())
        path.write_bytes(saved)
        self.assertEqual(self.library.current_applied_association(), prior)
        self.assert_complete(target, self.recover())

    def test_actual_fresh_process_recovers_without_runtime_or_selection(self):
        prior, target = self.staged("B")
        self.library.select(prior.entry_id, "other")
        before = self.snapshot()
        script = '''import sys
from pathlib import Path
from resources.lib.build_library import BuildLibrary, isolated_library_install_authority
from resources.lib.frozen_install import FrozenInstallStore, recover_applied_publication
library = BuildLibrary(sys.argv[1])
with isolated_library_install_authority(library):
    result = recover_applied_publication(store=FrozenInstallStore(Path(sys.argv[2])), library=library)
    assert result.outcome == "complete", result.code
'''
        result = subprocess.run([sys.executable, "-c", script, self.library.root, str(self.x.store.root)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertIsNone(self.library.pending_publication())
        self.assertEqual(self.library.current_applied_association().entry_id, target.source.entry_id)

    def services(self):
        x = self.x
        h = PlanHarness(self, with_private=False, with_resource=False)
        owners = h.owners(resolver=resolve_manifest, inspector=x.manager().owners.inspector,
            dependency_resolver=x.manager().owners.dependency_resolver,
            configuration_inspector=ConfigurationInspector(ReadOnlyConfigurationBackend(x.config)))
        return (BuildStatusService(owners), BuildPlanService(h.plan_owners(
            status=owners, artifact_store=ReadOnlyArtifactStore(x.artifacts.root),
            addon_details=lambda a: x.backend.installed.get(a))))

    def test_completed_skip_is_current_and_no_changes_with_accepted_skip(self):
        missing = self.x.with_missing_addon(); target = self.x.target()
        result = self.install(target, resolution_choices={missing: ResolutionChoice.SKIP})
        self.assert_complete(target, result)
        self.library.select(target.source.entry_id, "other")
        status_service, plan_service = self.services()
        status = status_service.check(self.library.associated_status_target())
        plan = plan_service.preview(self.library.associated_plan_target())
        self.assertEqual(status.overall.value, "current")
        self.assertEqual(plan.state.value, "no_changes")
        row = next(r for r in plan.software if r.addon_id == missing)
        self.assertEqual(row.action.value, "accepted_skip")
        # Before correction, omission of this completed resolution reproduced
        # changes_needed / decision_required for the same target/state.
        unbound_status = replace(self.library.associated_status_target(), install_resolution=None)
        unbound_plan = replace(self.library.associated_plan_target(), install_resolution=None)
        self.assertEqual(status_service.check(unbound_status).overall.value, "changes_needed")
        self.assertEqual(plan_service.preview(unbound_plan).state.value, "decision_required")

    def test_missing_corrupt_or_mismatched_committed_resolution_never_degrades(self):
        target = self.x.target(); result = self.install(target)
        self.assert_complete(target, result)
        path = self.x.store.resolution_path(result.resolution_manifest.resolution_fingerprint)
        original = path.read_bytes()
        wrong = replace(result.resolution_manifest, build_id="another-build")
        applied_path = Path(self.library.root) / "applied.json"
        applied_original = applied_path.read_bytes()
        for mode in ("missing", "corrupt", "different_content", "wrong_build"):
            with self.subTest(mode=mode):
                path.write_bytes(original); applied_path.write_bytes(applied_original)
                if mode == "missing": path.unlink()
                elif mode == "corrupt": path.write_text("{")
                elif mode == "different_content": path.write_text(json.dumps(wrong.to_dict()))
                else:
                    path.write_text(json.dumps(replace(result.resolution_manifest,
                        install_plan_fingerprint="a" * 64).to_dict()))
                self.assertIsNone(self.library.associated_status_target())
                self.assertIsNone(self.library.associated_plan_target())
        path.write_bytes(original); applied_path.write_bytes(applied_original)
        self.assertEqual(self.library.associated_status_target().install_resolution, result.resolution_manifest)

    def test_schema_one_applied_fails_closed_without_migration(self):
        target = self.x.target()
        (Path(self.library.root) / "applied.json").write_text(json.dumps({
            "schema_version": 1, "entry_id": target.source.entry_id, "device_profile_id": "desk"}))
        with patch.object(FrozenInstallStore, "load_resolution_manifest", side_effect=forbidden):
            self.assertIsNone(self.library.current_applied_association())
            self.assertIsNone(self.library.associated_status_target())

    def repository_target(self):
        x = self.x
        missing = x.with_missing_addon()
        repo = "repository.demo"
        metadata = x.artifacts.import_zip(_zip(repo, "1.0.0", repository=True),
                                          expected_addon_id=repo, expected_version="1.0.0")
        x.fixture.frozen = replace(x.fixture.frozen, addons=x.fixture.frozen.addons + (
            AddonCaptureNode(repo, "1.0.0", "xbmc.addon.repository", True,
                             ProvenanceStatus.VERIFIED_REPOSITORY, artifact=metadata),))
        x.fixture.raw["addons"].append({"addon_id": repo, "state": "enabled"})
        x.fixture.raw["device_profiles"]["desk"]["frozen_install_policies"][0]["repository_id"] = repo
        x.fixture.write_sources()
        x.backend.repository_packages[(repo, missing)] = ("2.0.0", _zip(missing, "2.0.0"))
        return missing, x.target()

    def test_repository_current_and_two_compatible_resolutions_are_not_confused(self):
        missing, target = self.repository_target()
        from resources.lib.repository_preparation import RepositoryPreparationService
        from resources.lib.plan_model import DecisionChoice
        plan_target = replace(self.library.plan_target(target.source.entry_id, "desk"),
                              choices=((missing, DecisionChoice.INSTALL_CURRENT),))
        def download(url, **kwargs):
            if url == "http://127.0.0.1:9999/addons.xml":
                return ('<addons><addon id="%s" version="2.0.0"/></addons>' % missing).encode()
            self.assertEqual(url, "http://127.0.0.1:9999/%s/2.0.0/%s-2.0.0.zip" % (missing, missing))
            return _zip(missing, "2.0.0")
        prepared = RepositoryPreparationService(self.x.artifacts, download=download).prepare(plan_target)
        self.assertEqual(prepared.code.value, "ready")
        result = self.install(target, resolution_choices={missing: ResolutionChoice.INSTALL_CURRENT},
                              prepared_resolution=prepared.prepared)
        self.assert_complete(target, result)
        row = next(r for r in result.resolution_manifest.records if r.addon_id == missing)
        self.assertEqual(row.resolution, InstallResolution.REPOSITORY_CURRENT)
        self.assertEqual((row.captured_version, row.resolved_version), ("1.0.0", "2.0.0"))
        status_service, plan_service = self.services()
        self.assertEqual(status_service.check(self.library.associated_status_target()).overall.value, "current")
        plan = plan_service.preview(self.library.associated_plan_target())
        self.assertEqual(plan.state.value, "no_changes")
        self.assertEqual(next(r for r in plan.software if r.addon_id == missing).version, "2.0.0")
        third = self.x.artifacts.import_zip(_zip(missing, "3.0.0"),
                                           expected_addon_id=missing, expected_version="3.0.0")
        records = tuple(replace(r, resolved_version="3.0.0", artifact_sha256=third.sha256,
                               artifact_size=third.size) if r.addon_id == missing else r
                        for r in result.resolution_manifest.records)
        frozen = target.load()[1]
        other = replace(result.resolution_manifest, records=records,
                        resulting_software_fingerprint=resolved_software_fingerprint(frozen, records))
        from resources.lib.build_identity import bind_resolutions
        desired = resolve_manifest(target.load()[0], target.device_profile_id)
        bind_resolutions(desired.build.id, frozen, other, policies=desired.frozen_install_policies)
        self.x.store.save_resolution_manifest(other)
        self.assertNotEqual(other.resolution_fingerprint, result.resolution_manifest.resolution_fingerprint)
        self.library.select(target.source.entry_id, "other")
        self.assertEqual(self.library.associated_status_target().install_resolution, result.resolution_manifest)
        self.assertEqual(self.library.associated_plan_target().install_resolution, result.resolution_manifest)
        self.assertEqual(status_service.check(self.library.associated_status_target()).overall.value, "current")
        self.assertEqual(plan_service.preview(self.library.associated_plan_target()).state.value, "no_changes")
        self.assertEqual(status_service.check(replace(self.library.associated_status_target(),
            install_resolution=other)).overall.value, "changes_needed")

    def test_unbindable_pending_resolution_keeps_prior_and_pending(self):
        prior, target = self.staged()
        pending = self.library.pending_publication()
        path = self.x.store.resolution_path(pending.candidate.resolution_fingerprint)
        original = path.read_bytes()
        good = self.x.store.load_resolution_manifest(pending.candidate.resolution_fingerprint)
        for field, value in (("build_id", "another-build"),
                             ("source_software_fingerprint", "a" * 64),
                             ("install_plan_fingerprint", "b" * 64),
                             ("resulting_software_fingerprint", "c" * 64)):
            with self.subTest(field=field):
                path.write_text(json.dumps(replace(good, **{field: value}).to_dict()))
                before = self.snapshot()
                self.assertEqual(self.recover().outcome, "needs_attention")
                self.assertEqual(before, self.snapshot())
                self.assertEqual(self.library.current_applied_association(), prior)
                self.assertEqual(self.library.pending_publication(), pending)
        path.write_bytes(original)
        self.assert_complete(target, self.recover())

    def test_resolution_symlink_and_pending_symlink_fail_closed(self):
        prior, target = self.staged()
        pending = self.library.pending_publication()
        resolution_path = self.x.store.resolution_path(pending.candidate.resolution_fingerprint)
        intent_path = Path(self.library.root) / "applied-publication.json"
        for path in (resolution_path, intent_path):
            with self.subTest(kind=path.name):
                original = path.read_bytes()
                external = self.x.base / "external-state"
                external.write_bytes(original)
                path.unlink(); path.symlink_to(external)
                before = self.snapshot()
                self.assertEqual(self.recover().outcome, "needs_attention")
                self.assertEqual(before, self.snapshot())
                self.assertEqual(external.read_bytes(), original)
                path.unlink(); path.write_bytes(original)
        self.assertEqual(self.library.current_applied_association(), prior)
        self.assert_complete(target, self.recover())

    def test_startup_precondition_keeps_complete_identity_for_intent_retry(self):
        target = self.x.target()
        with patch.object(BuildLibrary, "_prepare_applied_publication", side_effect=OSError("intent unavailable")):
            self.assertEqual(self.install(target).outcome, "needs_attention")
        from resources.lib.startup import run_startup
        with patch("resources.lib.startup.get_current_kodi_session_id", return_value="11111111-1111-4111-8111-111111111111"):
            status = run_startup(store=self.x.restart_store,
                frozen_precondition=lambda: ensure_frozen_install_guard(store=self.x.store, policy_backend=self.x.policy))
        self.assertEqual(status.classification.value, "needs_attention")
        self.assertEqual(status.code, "APPLIED_PUBLICATION_PENDING")
        self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.COMPLETE)
        before = self.snapshot()
        self.assert_complete(target, self.recover())
        self.assertEqual(before, self.snapshot())

    def test_change_after_applied_write_before_acknowledgement_is_masked(self):
        prior = self.x.seed_prior_association(); target = self.x.target()
        envelope = self.x.fixture.envelope(target.source.entry_id)
        saved = envelope.read_bytes(); original = lib._atomic
        def change_after_write(fd, name, data):
            original(fd, name, data)
            if name == "applied.json": envelope.unlink()
        with patch.object(lib, "_atomic", side_effect=change_after_write):
            result = self.install(target)
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.library.current_applied_association(), prior)
        self.assertIsNotNone(self.library.pending_publication())
        envelope.write_bytes(saved)
        self.assert_complete(target, self.recover())

    def test_durability_failure_before_clear_retains_both_owners(self):
        prior, target = self.staged("A")
        from resources.lib import frozen_install
        before = self.snapshot()
        with patch.object(frozen_install, "_sync_publication_storage", side_effect=OSError("fsync unavailable")):
            self.assertEqual(self.recover().outcome, "needs_attention")
        self.assertIsNotNone(self.x.store.inspect())
        self.assertIsNotNone(self.library.pending_publication())
        self.assertEqual(self.library.current_applied_association(), prior)
        self.assertEqual(before, self.snapshot())
        self.assert_complete(target, self.recover())

    def test_reader_rechecks_intent_created_during_applied_read(self):
        prior, target = self.staged("C")
        pending = self.library.pending_publication()
        original = BuildLibrary._publication_at
        reads = 0
        def race(fd):
            nonlocal reads
            reads += 1
            return None if reads == 1 else original(fd)
        with patch.object(BuildLibrary, "_publication_at", side_effect=race):
            self.assertEqual(self.library.current_applied_association(), prior)
        self.assertEqual(self.library.pending_publication(), pending)
        self.assert_complete(target, self.recover())

    def test_service_reports_recovered_publication_as_idle_and_failed_as_attention(self):
        from unittest.mock import Mock
        from resources.lib.startup import StartupStatus, StartupClassification, STARTUP_CLASSIFICATION_PROPERTY
        from resources.lib.frozen_install import FrozenInstallResult
        status = StartupStatus(StartupClassification.NEEDS_ATTENTION, code="APPLIED_PUBLICATION_PENDING")
        for outcome, classification in (("complete", "no_transaction"), ("needs_attention", "needs_attention")):
            with self.subTest(outcome=outcome):
                window = Mock()
                xbmc = SimpleNamespace(log=Mock(), LOGINFO=1, LOGERROR=3)
                xbmcgui = SimpleNamespace(Window=lambda _: window)
                with patch.dict(sys.modules, {"xbmc": xbmc, "xbmcgui": xbmcgui}), \
                     patch("resources.lib.startup.run_startup", return_value=status), \
                     patch("resources.lib.frozen_install.run_frozen_install_startup",
                           return_value=FrozenInstallResult(outcome)):
                    runpy.run_path(str(Path(__file__).resolve().parents[1] / "service.py"))
                window.setProperty.assert_any_call(STARTUP_CLASSIFICATION_PROPERTY, classification)
