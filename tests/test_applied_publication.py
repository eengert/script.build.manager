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
            owner, method = FrozenInstallStore, "_clear_publication_expected"
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
                pending = self.library.publication_journal()
                self.assertEqual(pending.previous, prior)
                self.assertEqual(self.library.current_applied_association(), pending.candidate if boundary == "A" else prior)
                self.assertIsNotNone(self.x.store.inspect())
                self.library.select(target.source.entry_id, "other")
                before = self.snapshot()
                with patch.object(lib, "_atomic", wraps=lib._atomic) as writes:
                    result = self.recover()
                self.assertEqual(sum(call.args[1] == "applied.json" for call in writes.call_args_list),
                                 0 if boundary == "A" else 1)
                self.assert_complete(target, result)
                self.assertEqual(before, self.snapshot())
                committed = (Path(self.library.root) / "applied.json").read_bytes()
                self.assertEqual(self.recover().outcome, "complete")
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
                self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
                self.assertEqual(self.library.pending_publication() is not None, not after)
                self.assertEqual(self.library.current_applied_association(), self.library.publication_journal().candidate if after else prior)
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

    def test_acknowledgement_interruption_before_and_after_terminal_transition(self):
        for after in (False, True):
            with self.subTest(after=after):
                if after: self.setUp()
                prior = self.x.seed_prior_association(); target = self.x.target()
                original = BuildLibrary._acknowledge_publication
                def interrupt(fd, journal):
                    if after: original(fd, journal)
                    raise ProcessInterrupted()
                with patch.object(BuildLibrary, "_acknowledge_publication", side_effect=interrupt), self.assertRaises(ProcessInterrupted):
                    self.install(target)
                if after:
                    self.assertIsNotNone(self.library.pending_publication())
                    self.assertEqual(self.library.publication_journal().state, "acknowledged")
                    self.assertEqual(self.library.current_applied_association(), prior)
                    self.assertEqual(self.recover().outcome, "complete")
                else:
                    self.assertEqual(self.library.current_applied_association(), prior)
                    self.assert_complete(target, self.recover())

    def test_terminal_cleanup_unlink_fsync_ambiguity_keeps_authority(self):
        target = self.x.target()
        result = self.install(target)
        self.assert_complete(target, result)
        journal = self.library.publication_journal()
        original = lib.os.fsync
        def fail_after_unlink(fd):
            if not (Path(self.library.root) / "applied-publication.json").exists():
                raise OSError("post unlink fsync")
            return original(fd)
        with patch.object(lib.os, "fsync", side_effect=fail_after_unlink):
            self.assertFalse(self.library._cleanup_acknowledged_publication(journal, resolution_store=self.x.store))
        self.assertEqual(self.library.current_applied_association(), journal.candidate)
        self.assertIsNone(self.library.pending_publication())
        # Simulate the last durable terminal journal reappearing after crash.
        (Path(self.library.root) / "applied-publication.json").write_text(json.dumps(journal.to_dict()))
        self.assertEqual(self.library.current_applied_association(), journal.candidate)
        self.assert_complete(target, self.recover())

    def test_clear_post_unlink_failure_reconciles_actual_state(self):
        target = self.x.target(); original = FrozenInstallStore._clear_publication_expected
        def ambiguous(store, **kwargs):
            original(store, **kwargs)
            raise OSError("post clear fsync")
        with patch.object(FrozenInstallStore, "_clear_publication_expected", new=ambiguous):
            result = self.install(target)
        self.assert_complete(target, result)

    def test_intent_write_before_and_after_replacement_remains_recoverable(self):
        for after in (False, True):
            with self.subTest(after=after):
                if after: self.setUp()
                prior = self.x.seed_prior_association(); target = self.x.target()
                original = lib._atomic
                def fail(fd, name, data):
                    if name == "applied-publication.json" and json.loads(data)["state"] == "pending":
                        if after: original(fd, name, data)
                        raise OSError("intent failure")
                    original(fd, name, data)
                with patch.object(lib, "_atomic", side_effect=fail):
                    result = self.install(target)
                self.assertEqual(result.outcome, "needs_attention")
                self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
                self.assertEqual(self.library.current_applied_association(), prior)
                before = self.snapshot()
                self.assert_complete(target, self.recover())
                self.assertEqual(before, self.snapshot())

    def test_active_transaction_must_match_intent_before_cleanup(self):
        prior, target = self.staged("B")
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
        with patch.object(BuildLibrary, "_create_applied_publication", side_effect=OSError("intent unavailable")):
            self.assertEqual(self.install(target).outcome, "needs_attention")
        from resources.lib.startup import run_startup
        with patch("resources.lib.startup.get_current_kodi_session_id", return_value="11111111-1111-4111-8111-111111111111"):
            status = run_startup(store=self.x.restart_store,
                frozen_precondition=lambda: ensure_frozen_install_guard(store=self.x.store, policy_backend=self.x.policy))
        self.assertEqual(status.classification.value, "needs_attention")
        self.assertEqual(status.code, "APPLIED_PUBLICATION_PENDING")
        self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
        before = self.snapshot()
        self.assert_complete(target, self.recover())
        self.assertEqual(before, self.snapshot())

    def test_change_after_materialization_keeps_ACK_but_invalid_source_fails_closed(self):
        prior = self.x.seed_prior_association(); target = self.x.target()
        envelope = self.x.fixture.envelope(target.source.entry_id)
        saved = envelope.read_bytes(); original = lib._atomic
        def change_after_write(fd, name, data):
            original(fd, name, data)
            if name == "applied.json": envelope.unlink()
        with patch.object(lib, "_atomic", side_effect=change_after_write):
            result = self.install(target)
        self.assertEqual(result.outcome, "needs_attention")
        self.assertIsNone(self.library.current_applied_association())
        from resources.lib.build_library import LibraryError
        with self.assertRaises(LibraryError): self.library.pending_publication()
        envelope.write_bytes(saved)
        self.assert_complete(target, self.recover())

    def test_durability_failure_before_clear_retains_both_owners(self):
        prior, target = self.staged("B")
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
        for outcome, classification in (("complete", "no_transaction"), ("superseded", "no_transaction"), ("needs_attention", "needs_attention")):
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


class PublicationAuthorityTests(unittest.TestCase):
    """Deterministic authority races and actual acknowledgement barriers."""
    setUp = PublicationTests.setUp
    snapshot = PublicationTests.snapshot
    install = PublicationTests.install
    recover = PublicationTests.recover
    staged = PublicationTests.staged
    assert_complete = PublicationTests.assert_complete

    def next_target(self, version):
        x = self.x
        x.fixture.raw["build"]["version"] = version
        (x.fixture.packages / "shared").mkdir(parents=True, exist_ok=True)
        x.fixture.write_sources()
        return x.target()

    def stale_race(self, *, newer, cleanup=False):
        from resources.lib import frozen_install
        previous, b = self.staged("B")
        original = frozen_install._sync_publication_storage
        state = {}
        def paused_owner(store):
            if not state:
                # R1 already observed B. Run R2 and (optionally) Install C
                # before letting R1 continue; no sleeps or scheduler timing.
                with patch.object(frozen_install, "_sync_publication_storage", new=original):
                    state["r2"] = self.recover()
                    self.assert_complete(b, state["r2"])
                    if newer:
                        c = self.next_target("3.0.0")
                        state["c"] = c
                        state["install_c"] = self.install(c)
                        self.assert_complete(c, state["install_c"])
                    if cleanup:
                        self.assertTrue(self.library._cleanup_acknowledged_publication(
                            self.library.publication_journal(), resolution_store=self.x.store))
                    state["authority"] = self.library.current_applied_association()
                    state["applied"] = (Path(self.library.root) / "applied.json").read_bytes()
                    state["mutations"] = self.snapshot()
            return original(store)
        with patch.object(frozen_install, "_sync_publication_storage", side_effect=paused_owner):
            state["r1"] = self.recover()
        state["b"] = b
        return state

    def test_stale_B_recovery_cannot_resurrect_after_newer_C_install(self):
        state = self.stale_race(newer=True)
        self.assertTrue(state["r1"].succeeded, state["r1"])
        self.assertEqual(self.library.current_applied_association(), state["authority"])
        self.assertEqual((Path(self.library.root) / "applied.json").read_bytes(), state["applied"])
        self.assertIsNone(self.library.pending_publication())
        self.assertEqual(self.snapshot(), state["mutations"])
        self.recover()
        self.assertEqual(self.library.current_applied_association(), state["authority"])

    def test_actual_ack_directory_fsync_failure_cannot_return_complete(self):
        import stat
        _, target = self.staged("B")
        original = lib.os.fsync
        failures = []
        def fail_ack(fd):
            # Fail the actual directory fsync immediately after ACK replaces
            # PENDING. Visibility of ACK must not turn this error into complete.
            journal = self.library.publication_journal()
            if (stat.S_ISDIR(os.fstat(fd).st_mode) and journal is not None
                    and journal.state == "acknowledged"
                    and journal.candidate.entry_id == target.source.entry_id):
                failures.append(True)
                raise OSError("injected actual acknowledgement directory fsync failure")
            return original(fd)
        before = self.snapshot()
        with patch.object(lib.os, "fsync", side_effect=fail_ack):
            result = self.recover()
            self.assertEqual(self.recover().outcome, "needs_attention")
            self.assertEqual(self.recover().outcome, "needs_attention")
        self.assertTrue(failures, "actual acknowledgement durability barrier was not reached")
        self.assertNotEqual(result.outcome, "complete")
        self.assertEqual(self.library.publication_journal().state, "acknowledged")
        self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
        self.assert_complete(target, self.recover())
        self.assert_complete(target, self.recover())
        self.assertEqual(self.snapshot(), before)

    def test_two_recoveries_same_candidate_and_transition_beneath_stale_owner(self):
        for cleanup in (False, True):
            with self.subTest(cleanup=cleanup):
                if cleanup: self.setUp()
                state = self.stale_race(newer=False, cleanup=cleanup)
                self.assertEqual(state["r1"].outcome, "complete")
                self.assertEqual(self.library.current_applied_association(), state["authority"])
                self.assertEqual((Path(self.library.root) / "applied.json").read_bytes(), state["applied"])
                self.assertIsNone(self.library.pending_publication())
                self.assertEqual(self.snapshot(), state["mutations"])

    def test_stale_recovery_after_C_terminal_cleanup_never_creates(self):
        state = self.stale_race(newer=True, cleanup=True)
        self.assertEqual(state["r1"].outcome, "superseded")
        self.assertIsNone(self.library.publication_journal())
        self.assertIsNone(self.recover())
        self.assertEqual(self.library.current_applied_association(), state["authority"])
        self.assertEqual((Path(self.library.root) / "applied.json").read_bytes(), state["applied"])
        self.assertEqual(self.snapshot(), state["mutations"])

    def test_stale_validation_and_record_cannot_write_or_load_obsolete_source(self):
        _, b = self.staged("B")
        observed = self.library.publication_journal()
        self.assert_complete(b, self.recover())
        c = self.next_target("3.0.0")
        self.assert_complete(c, self.install(c))
        self.x.fixture.envelope(b.source.entry_id).unlink()
        authority = self.library.current_applied_association()
        saved = (Path(self.library.root) / "applied.json").read_bytes()
        with patch.object(lib, "_atomic", side_effect=AssertionError("stale write")):
            self.assertEqual(self.library._validate_applied_publication(observed,
                resolution_store=self.x.store)[0], "superseded")
            self.assertEqual(self.library._record_applied_completion(observed,
                resolution_store=self.x.store), "superseded")
        self.assertEqual(self.library.current_applied_association(), authority)
        self.assertEqual((Path(self.library.root) / "applied.json").read_bytes(), saved)

    def test_stale_owner_defers_to_other_pending_without_changing_it(self):
        from resources.lib.frozen_install import recover_applied_publication
        _, b = self.staged("B")
        observed = self.library.publication_journal()
        self.assert_complete(b, self.recover())
        c = self.next_target("3.0.0")
        with patch.object(BuildLibrary, "_record_applied_completion", side_effect=ProcessInterrupted), self.assertRaises(ProcessInterrupted):
            self.install(c)
        pending = self.library.pending_publication()
        before = self.snapshot()
        saved = (Path(self.library.root) / "applied.json").read_bytes()
        result = recover_applied_publication(store=self.x.store, library=self.library,
            policy_backend=self.x.policy, publication=observed)
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(self.library.pending_publication(), pending)
        self.assertEqual((Path(self.library.root) / "applied.json").read_bytes(), saved)
        self.assert_complete(c, self.recover())
        self.assertEqual(before, self.snapshot())

    def test_initial_creation_rejects_old_memory_after_durable_owner_gone_or_changed(self):
        from resources.lib.build_library import LibraryConflict
        self.staged("A")
        transaction = self.x.store.inspect()
        journal = self.library.publication_journal()
        self.library._record_applied_completion(self.library.publication_journal(), resolution_store=self.x.store)
        self.x.store._clear_publication_expected(transaction_id=transaction.transaction_id,
            publication=self.library.publication_journal())
        for changed in (False, True):
            with self.subTest(changed=changed):
                if changed:
                    self.x.store.create(replace(transaction,
                        transaction_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
                with self.assertRaises(LibraryConflict):
                    self.library._create_applied_publication(transaction, resolution_store=self.x.store)
                self.assertTrue(self.library.publication_journal().same_identity(journal))

    def test_two_creation_identities_cannot_steal_existing_pending(self):
        from resources.lib.build_library import LibraryConflict
        self.staged("B")
        transaction = self.x.store.inspect()
        pending = self.library.pending_publication()
        self.library._record_applied_completion(self.library.publication_journal(), resolution_store=self.x.store)
        self.x.store._clear_publication_expected(transaction_id=transaction.transaction_id,
            publication=self.library.publication_journal())
        other = replace(transaction, transaction_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.x.store.create(other)
        (Path(self.library.root) / "applied-publication.json").write_text(json.dumps(pending.to_dict()))
        for attempted in (other, transaction):
            with self.assertRaises(LibraryConflict):
                self.library._create_applied_publication(attempted, resolution_store=self.x.store)
            self.assertEqual(self.library.pending_publication(), pending)
        self.assertEqual(self.x.store.inspect(), other)

    def test_fence_preserves_owner_during_journal_write(self):
        target = self.x.target()
        with patch.object(BuildLibrary, "_create_applied_publication", side_effect=ProcessInterrupted), self.assertRaises(ProcessInterrupted):
            self.install(target)
        transaction = self.x.store.inspect()
        original = lib._atomic
        def attempt_clear(fd, name, data):
            from resources.lib.frozen_install import FrozenInstallStateConflict
            with self.assertRaises(FrozenInstallStateConflict): self.x.store.clear()
            with self.assertRaises(FrozenInstallStateConflict):
                self.x.store.clear_expected(transaction_id=transaction.transaction_id,
                    expected_phase=transaction.phase)
            return original(fd, name, data)
        with patch.object(lib, "_atomic", side_effect=attempt_clear):
            self.library._create_applied_publication(transaction, resolution_store=self.x.store)
        self.assertEqual(self.x.store.inspect(), transaction)
        self.assert_complete(target, self.recover())

    def test_real_pending_directory_barrier_failure_keeps_COMPLETE_and_masks_candidate(self):
        import stat
        previous = self.x.seed_prior_association()
        target = self.x.target()
        original = lib.os.fsync
        failures = []
        def fail_pending(fd):
            journal = self.library.publication_journal()
            if (stat.S_ISDIR(os.fstat(fd).st_mode) and journal is not None
                    and journal.state == "pending" and journal.candidate.entry_id == target.source.entry_id):
                failures.append(True)
                raise OSError("actual pending directory barrier")
            return original(fd)
        with patch.object(lib.os, "fsync", side_effect=fail_pending):
            self.assertEqual(self.install(target).outcome, "needs_attention")
        self.assertTrue(failures)
        self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
        self.assertEqual(self.library.current_applied_association(), previous)
        self.assertIsNotNone(self.library.pending_publication())
        before = self.snapshot()
        self.assert_complete(target, self.recover())
        self.assert_complete(target, self.recover())
        self.assertEqual(self.snapshot(), before)

    def test_ACK_replace_failure_retains_pending_then_recovery_finishes_without_replay(self):
        previous, target = self.staged("B")
        original = lib.os.replace
        def fail_ACK(source, destination, **kwargs):
            if destination == "applied-publication.json":
                raise OSError("ACK replacement failed")
            return original(source, destination, **kwargs)
        before = self.snapshot()
        with patch.object(lib.os, "replace", side_effect=fail_ACK):
            self.assertEqual(self.recover().outcome, "needs_attention")
            self.assertEqual(self.recover().outcome, "needs_attention")
        self.assertEqual(self.library.current_applied_association(), previous)
        self.assertIsNotNone(self.library.pending_publication())
        self.assert_complete(target, self.recover())
        self.assertEqual(self.snapshot(), before)

    def test_terminal_cleanup_failure_before_unlink_and_repeated_GC_are_harmless(self):
        target = self.x.target()
        self.assert_complete(target, self.install(target))
        journal = self.library.publication_journal()
        before = self.snapshot()
        with patch.object(lib.os, "unlink", side_effect=OSError("GC failed")):
            self.assertFalse(self.library._cleanup_acknowledged_publication(journal, resolution_store=self.x.store))
        self.assertIsNone(self.library.pending_publication())
        self.assertEqual(self.library.current_applied_association(), journal.candidate)
        self.assert_complete(target, self.recover())
        self.assertTrue(self.library._cleanup_acknowledged_publication(journal, resolution_store=self.x.store))
        self.assertFalse(self.library._cleanup_acknowledged_publication(journal, resolution_store=self.x.store))
        self.assertEqual(self.snapshot(), before)

    def test_terminal_inspection_never_writes_fsyncs_creates_or_cleans(self):
        target = self.x.target()
        self.assert_complete(target, self.install(target))
        before = {str(p): p.read_bytes() for p in Path(self.x.fixture.root).rglob("*") if p.is_file()}
        with patch.object(BuildLibrary, "_writer", side_effect=AssertionError("read writer")), \
             patch.object(lib.os, "fsync", side_effect=AssertionError("read fsync")), \
             patch.object(lib, "_atomic", side_effect=AssertionError("read mutation")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("read mkdir")):
            self.assertIsNone(self.library.pending_publication())
            self.assertIsNotNone(self.library.associated_status_target())
            self.assertIsNotNone(self.library.associated_plan_target())
        self.assertEqual(before, {str(p): p.read_bytes() for p in Path(self.x.fixture.root).rglob("*") if p.is_file()})

    def test_contradictory_or_unknown_terminal_journal_fails_closed(self):
        from resources.lib.build_library import LibraryError
        target = self.x.target()
        self.assert_complete(target, self.install(target))
        path = Path(self.library.root) / "applied-publication.json"
        raw = json.loads(path.read_text())
        for state in ("unknown", "acknowledged"):
            changed = dict(raw, state=state)
            if state == "acknowledged":
                changed["candidate"] = dict(raw["candidate"], device_profile_id="other")
            path.write_text(json.dumps(changed))
            self.assertIsNone(self.library.current_applied_association())
            with self.assertRaises(LibraryError): self.library.pending_publication()
            self.assertEqual(self.recover().outcome, "needs_attention")
        path.write_text(json.dumps(raw))
        self.assert_complete(target, self.recover())

    def test_retained_terminal_does_not_intercept_new_COMPLETE_restart_owner(self):
        b = self.x.target()
        self.assert_complete(b, self.install(b))
        c = self.next_target("3.0.0")
        with patch.object(BuildLibrary, "_create_applied_publication", side_effect=ProcessInterrupted), self.assertRaises(ProcessInterrupted):
            self.install(c)
        self.assertEqual(self.library.publication_journal().candidate.entry_id, b.source.entry_id)
        self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
        before = self.snapshot()
        self.assert_complete(c, self.recover())
        self.assert_complete(c, self.recover())
        self.assertEqual(self.snapshot(), before)

    def test_initial_old_COMPLETE_cannot_create_after_newer_normal_install(self):
        from resources.lib.build_library import LibraryConflict
        _, b = self.staged("A")
        old = self.x.store.inspect()
        self.assert_complete(b, self.recover())
        c = self.next_target("3.0.0")
        self.assert_complete(c, self.install(c))
        journal = self.library.publication_journal()
        with self.assertRaises(LibraryConflict):
            self.library._create_applied_publication(old, resolution_store=self.x.store)
        self.assertEqual(self.library.publication_journal(), journal)
        self.assertEqual(self.library.current_applied_association(), journal.candidate)

    def test_owner_revalidated_before_replace_without_nested_frozen_lock(self):
        from resources.lib.build_library import LibraryConflict
        previous = self.x.seed_prior_association()
        preceding = self.library.publication_journal()
        target = self.x.target()
        with patch.object(BuildLibrary, "_create_applied_publication", side_effect=ProcessInterrupted), self.assertRaises(ProcessInterrupted):
            self.install(target)
        transaction = self.x.store.inspect()
        original = BuildLibrary.current_applied_association
        def owner_disappears(library, **kwargs):
            applied = original(library, **kwargs)
            self.x.store.transaction_path.unlink()
            return applied
        with patch.object(BuildLibrary, "current_applied_association", new=owner_disappears), \
             patch.object(lib, "_atomic", side_effect=AssertionError("obsolete creation")), \
             self.assertRaises(LibraryConflict):
            self.library._create_applied_publication(transaction, resolution_store=self.x.store)
        self.assertEqual(self.library.publication_journal(), preceding)
        self.assertEqual(self.library.current_applied_association(), previous)

    def test_restart_restores_last_durable_PENDING_after_ambiguous_ACK(self):
        import stat
        previous, target = self.staged("B")
        path = Path(self.library.root) / "applied-publication.json"
        pending_bytes = path.read_bytes()
        original = lib.os.fsync
        def failed_barrier(fd):
            journal = self.library.publication_journal()
            if stat.S_ISDIR(os.fstat(fd).st_mode) and journal.state == "acknowledged":
                raise OSError("ACK durability unknown")
            return original(fd)
        before = self.snapshot()
        with patch.object(lib.os, "fsync", side_effect=failed_barrier):
            self.assertEqual(self.recover().outcome, "needs_attention")
        # Crash model: the failed replacement barrier restores last durable PENDING.
        path.write_bytes(pending_bytes)
        self.assertEqual(self.library.current_applied_association(), previous)
        self.assertIsNotNone(self.library.pending_publication())
        self.assert_complete(target, self.recover())
        self.assert_complete(target, self.recover())
        self.assertEqual(self.snapshot(), before)

    def test_schema1_publication_remains_PENDING_and_recovers(self):
        previous, target = self.staged("B")
        path = Path(self.library.root) / "applied-publication.json"
        raw = json.loads(path.read_text()); raw["schema_version"] = 1; raw.pop("state")
        path.write_text(json.dumps(raw))
        self.assertEqual(self.library.pending_publication().state, "pending")
        self.assertEqual(self.library.current_applied_association(), previous)
        before = self.snapshot()
        self.assert_complete(target, self.recover())
        self.assertEqual(self.library.publication_journal().state, "acknowledged")
        self.assertEqual(self.snapshot(), before)

class PublicationFenceTests(unittest.TestCase):
    def setUp(self):
        PublicationTests.setUp(self)
        self._status = self.services()[0]
    snapshot = PublicationTests.snapshot
    install = PublicationTests.install
    recover = PublicationTests.recover
    staged = PublicationTests.staged
    assert_complete = PublicationTests.assert_complete
    services = PublicationTests.services

    def test_supported_abandon_cannot_remove_owner_before_pending_atomic_failure(self):
        import stat
        previous = self.x.seed_prior_association()
        target = self.x.target()
        original_atomic = lib._atomic
        original_fsync = lib.os.fsync
        outcomes = []
        def interleave(fd, name, data):
            if name == "applied-publication.json" and json.loads(data)["state"] == "pending":
                outcomes.append(self.x.coordinator().abandon())
            return original_atomic(fd, name, data)
        def fail_pending(fd):
            journal = self.library.publication_journal()
            if stat.S_ISDIR(os.fstat(fd).st_mode) and journal is not None and journal.state == "pending":
                raise OSError("actual pending directory barrier failure")
            return original_fsync(fd)
        with patch.object(lib, "_atomic", side_effect=interleave), patch.object(lib.os, "fsync", side_effect=fail_pending):
            result = self.install(target)
        before = self.snapshot()
        recovered = self.recover()
        self.assertEqual(outcomes[0].outcome, "needs_attention")
        self.assertEqual(result.outcome, "needs_attention")
        self.assert_complete(target, recovered)
        self.assertEqual(self.snapshot(), before)

    def test_failed_ACK_barrier_keeps_previous_nonidle_and_blocks_install(self):
        import stat
        previous, target = self.staged("B")
        original = lib.os.fsync
        def fail_ACK(fd):
            journal = self.library.publication_journal()
            if stat.S_ISDIR(os.fstat(fd).st_mode) and journal is not None and journal.state == "acknowledged":
                raise OSError("actual ACK directory barrier failure")
            return original(fd)
        before = self.snapshot()
        with patch.object(lib.os, "fsync", side_effect=fail_ACK):
            self.assertEqual(self.recover().outcome, "needs_attention")
            self.assertEqual(self.recover().outcome, "needs_attention")
            self.assertEqual(self.library.current_applied_association(), previous)
            self.assertIsNotNone(self.library.pending_publication())
            self.assertFalse(ensure_frozen_install_guard(store=self.x.store, policy_backend=self.x.policy).allowed)
            self.assert_public_state(previous, unresolved=True)
            self.assertFalse(self.install(target).succeeded)
        self.assert_complete(target, self.recover())
        self.assert_public_state(self.library.publication_journal().candidate, unresolved=False)
        self.assertEqual(self.snapshot(), before)

    def assert_public_state(self, expected, *, unresolved):
        from resources.lib.status_model import OperationKind
        status = self._status
        status = BuildStatusService(replace(status._o,
            publication_snapshot=self.library.pending_publication,
            frozen_snapshot=lambda: FrozenInstallStore.read_snapshot(self.x.store.root),
            restart_snapshot=lambda: None))
        result = status.check(self.library.associated_status_target())
        self.assertEqual(self.library.current_applied_association(), expected)
        self.assertEqual(result.operation.kind is OperationKind.NEEDS_ATTENTION, unresolved)
        self.assertEqual(ensure_frozen_install_guard(store=self.x.store,
            policy_backend=self.x.policy).allowed, not unresolved)

    def fresh_process(self):
        script = """import sys
from pathlib import Path
from types import SimpleNamespace
from resources.lib.build_library import BuildLibrary, isolated_library_install_authority
from resources.lib.frozen_install import FrozenInstallStore, recover_applied_publication
store = FrozenInstallStore(Path(sys.argv[2]))
library = BuildLibrary(sys.argv[1])
with isolated_library_install_authority(library):
    tx = store.inspect()
    policy = SimpleNamespace(get_policy=lambda: tx.original_update_policy if tx else None)
    result = recover_applied_publication(store=store, library=library, policy_backend=policy)
    assert result.succeeded, result
"""
        result = subprocess.run([sys.executable, "-c", script, self.library.root, str(self.x.store.root)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def fence_without_journal(self):
        previous = self.x.seed_prior_association()
        target = self.x.target()
        with patch.object(BuildLibrary, "_create_applied_publication", side_effect=ProcessInterrupted), self.assertRaises(ProcessInterrupted):
            self.install(target)
        self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
        return previous, target

    def test_abandon_wins_COMPLETE_before_fence_no_B_journal(self):
        previous = self.x.seed_prior_association()
        target = self.x.target()
        original = FrozenInstallStore.transition_expected
        abandoned = []
        def race(store, **kwargs):
            if kwargs["new_phase"] is FrozenInstallPhase.PUBLICATION_PENDING:
                abandoned.append(self.x.coordinator().abandon())
            return original(store, **kwargs)
        with patch.object(FrozenInstallStore, "transition_expected", new=race):
            self.assertEqual(self.install(target).outcome, "needs_attention")
        self.assertEqual(abandoned[0].outcome, "complete")
        self.assertIsNone(self.x.store.inspect())
        self.assertEqual(self.library.current_applied_association(), previous)
        self.assertNotEqual(self.library.publication_journal().candidate.entry_id, target.source.entry_id)
        self.recover()
        self.assertEqual(self.library.current_applied_association(), previous)

    def test_fence_crash_before_journal_refuses_all_supported_discard_and_new_install(self):
        from resources.lib.frozen_install import FrozenInstallStateConflict
        previous, target = self.fence_without_journal()
        transaction = self.x.store.inspect()
        before = self.snapshot()
        self.assertEqual(self.x.coordinator().abandon(acknowledge_restore_failure=True).outcome, "needs_attention")
        for action in (lambda: self.x.store.clear(),
                lambda: self.x.store.clear_expected(transaction_id=transaction.transaction_id, expected_phase=transaction.phase),
                lambda: self.x.store.transition_expected(transaction_id=transaction.transaction_id,
                    expected_phase=transaction.phase, new_phase=FrozenInstallPhase.NEEDS_ATTENTION),
                lambda: self.x.store.create(replace(transaction, transaction_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")),
                lambda: self.x.store._clear_publication_expected(transaction_id=transaction.transaction_id,
                    publication=self.library.publication_journal())):
            with self.assertRaises(FrozenInstallStateConflict): action()
        self.assertFalse(self.install(target).succeeded)
        self.assertEqual(self.x.store.inspect(), transaction)
        self.assert_public_state(previous, unresolved=True)
        self.assertEqual(self.snapshot(), before)
        self.fresh_process()
        self.assertIsNone(self.x.store.inspect())
        candidate = self.library.publication_journal().candidate
        self.assert_public_state(candidate, unresolved=False)
        self.assert_complete(target, self.recover())
        self.assertEqual(self.snapshot(), before)

    def test_legacy_COMPLETE_must_fence_before_initial_journal(self):
        previous, target = self.fence_without_journal()
        transaction = self.x.store.inspect()
        # Explicit legacy persisted-state fixture, not a product transition.
        self.x.store.transaction_path.write_text(json.dumps(replace(transaction, phase=FrozenInstallPhase.COMPLETE).to_dict()))
        phases = []
        original = BuildLibrary._create_applied_publication
        def observe(library, owner, **kwargs):
            phases.append(self.x.store.inspect().phase)
            return original(library, owner, **kwargs)
        before = self.snapshot()
        with patch.object(BuildLibrary, "_create_applied_publication", new=observe):
            self.assert_complete(target, self.recover())
        self.assertEqual(phases, [FrozenInstallPhase.PUBLICATION_PENDING])
        self.assertEqual(self.snapshot(), before)

    def test_fenced_pending_replacement_failure_before_visibility_fresh_process(self):
        previous = self.x.seed_prior_association()
        target = self.x.target()
        original = lib.os.replace
        def fail(source, destination, **kwargs):
            if destination == "applied-publication.json": raise OSError("pending replace")
            return original(source, destination, **kwargs)
        with patch.object(lib.os, "replace", side_effect=fail):
            self.assertEqual(self.install(target).outcome, "needs_attention")
        self.assertEqual(self.x.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
        self.assert_public_state(previous, unresolved=True)
        before = self.snapshot()
        self.fresh_process()
        self.assert_public_state(self.library.publication_journal().candidate, unresolved=False)
        self.assertEqual(self.snapshot(), before)

    def test_ACK_first_crash_and_applied_failures_recover_without_replay(self):
        import stat
        for stage in ("before_applied", "replace", "directory_fsync", "terminal"):
            with self.subTest(stage=stage):
                if stage != "before_applied": self.setUp()
                previous, target = self.staged("B")
                journal_path = Path(self.library.root) / "applied-publication.json"
                old_applied = (Path(self.library.root) / "applied.json").read_bytes()
                before = self.snapshot()
                if stage == "before_applied":
                    original = BuildLibrary._acknowledge_publication
                    def crash(fd, journal):
                        original(fd, journal)
                        self.assertEqual((Path(self.library.root) / "applied.json").read_bytes(), old_applied)
                        raise ProcessInterrupted()
                    with patch.object(BuildLibrary, "_acknowledge_publication", side_effect=crash), self.assertRaises(ProcessInterrupted):
                        self.recover()
                elif stage == "replace":
                    original = lib.os.replace
                    def fail(source, destination, **kwargs):
                        if destination == "applied.json": raise OSError("applied replace")
                        return original(source, destination, **kwargs)
                    with patch.object(lib.os, "replace", side_effect=fail):
                        self.assertEqual(self.recover().outcome, "needs_attention")
                        self.assertEqual(self.recover().outcome, "needs_attention")
                elif stage == "directory_fsync":
                    original = lib.os.fsync
                    def fail(fd):
                        if (stat.S_ISDIR(os.fstat(fd).st_mode)
                                and self.library.current_applied_association() != previous):
                            raise OSError("applied materialization barrier")
                        return original(fd)
                    with patch.object(lib.os, "fsync", side_effect=fail):
                        self.assertEqual(self.recover().outcome, "needs_attention")
                else:
                    self.assert_complete(target, self.recover())
                self.assertEqual(json.loads(journal_path.read_text())["state"], "acknowledged")
                candidate = self.library.publication_journal().candidate
                self.assert_public_state(candidate if stage in ("directory_fsync", "terminal") else previous,
                    unresolved=stage != "terminal")
                self.assertEqual(self.snapshot(), before)
                self.fresh_process()
                self.assert_public_state(candidate, unresolved=False)
                self.assert_complete(target, self.recover())
                self.assertEqual(self.snapshot(), before)

    def test_status_ambiguous_ACK_is_creation_free(self):
        previous, target = self.staged("B")
        original = BuildLibrary._acknowledge_publication
        def crash(fd, journal):
            original(fd, journal)
            raise ProcessInterrupted()
        with patch.object(BuildLibrary, "_acknowledge_publication", side_effect=crash), self.assertRaises(ProcessInterrupted):
            self.recover()
        root = self.x.fixture.base
        before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        from resources.lib.status_model import OperationKind
        status = self._status
        status = BuildStatusService(replace(status._o, publication_snapshot=self.library.pending_publication,
            frozen_snapshot=lambda: FrozenInstallStore.read_snapshot(self.x.store.root), restart_snapshot=lambda: None))
        with patch.object(lib.os, "fsync", side_effect=forbidden), \
             patch.object(BuildLibrary, "_writer", side_effect=forbidden), \
             patch.object(Path, "mkdir", side_effect=forbidden):
            result = status.check(self.library.associated_status_target())
            self.assertEqual(result.operation.kind, OperationKind.NEEDS_ATTENTION)
            self.assertEqual(self.library.current_applied_association(), previous)
            self.assertIsNotNone(self.library.pending_publication())
        self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()})
        self.assert_complete(target, self.recover())

    def test_visible_fence_after_failed_store_barrier_must_be_confirmed_before_journal(self):
        previous = self.x.seed_prior_association()
        target = self.x.target()
        import stat
        original = os.fsync
        identity = os.stat(self.x.store.root)
        def fail_fence(fd):
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                owner = FrozenInstallStore.read_snapshot(self.x.store.root)
                if owner is not None and owner.phase is FrozenInstallPhase.PUBLICATION_PENDING:
                    raise OSError("fence directory ambiguity")
            return original(fd)
        with patch.object(os, "fsync", side_effect=fail_fence):
            self.assertEqual(self.install(target).outcome, "needs_attention")
            self.assertEqual(self.recover().outcome, "needs_attention")
            self.assertNotEqual(self.library.publication_journal().candidate.entry_id, target.source.entry_id)
            self.assert_public_state(previous, unresolved=True)
        before = self.snapshot()
        self.fresh_process()
        self.assert_complete(target, self.recover())
        self.assertEqual(self.snapshot(), before)

    def test_legacy_PENDING_candidate_is_masked_before_ambiguous_ACK(self):
        import stat
        for prior in (True, False):
            with self.subTest(prior=prior):
                if not prior: self.setUp()
                previous, target = self.staged("B", prior=prior)
                journal = self.library.publication_journal()
                # Earlier product ordering could leave masked candidate bytes.
                (Path(self.library.root) / "applied.json").write_text(json.dumps(journal.candidate.to_dict()))
                original = lib.os.fsync
                def fail(fd):
                    if stat.S_ISDIR(os.fstat(fd).st_mode) and self.library.publication_journal().state == "acknowledged":
                        raise OSError("ACK barrier")
                    return original(fd)
                before = self.snapshot()
                with patch.object(lib.os, "fsync", side_effect=fail):
                    self.assertEqual(self.recover().outcome, "needs_attention")
                    self.assert_public_state(previous, unresolved=True)
                    self.assertEqual(self.recover().outcome, "needs_attention")
                self.fresh_process()
                self.assert_complete(target, self.recover())
                self.assertEqual(self.snapshot(), before)

    def test_publication_persistence_locks_are_never_nested(self):
        from contextlib import contextmanager
        original_writer = BuildLibrary._writer
        original_locked = FrozenInstallStore.locked
        active = {"library": False, "frozen": False}
        @contextmanager
        def writer(library):
            self.assertFalse(active["frozen"])
            with original_writer(library) as fd:
                active["library"] = True
                try: yield fd
                finally: active["library"] = False
        @contextmanager
        def locked(store):
            self.assertFalse(active["library"])
            with original_locked(store) as value:
                active["frozen"] = True
                try: yield value
                finally: active["frozen"] = False
        target = self.x.target()
        with patch.object(BuildLibrary, "_writer", new=writer), patch.object(FrozenInstallStore, "locked", new=locked):
            self.assert_complete(target, self.install(target))
            self.assert_complete(target, self.recover())

class StrictFenceConfirmationTests(unittest.TestCase):
    setUp = PublicationFenceTests.setUp
    services = PublicationTests.services
    snapshot = PublicationTests.snapshot
    install = PublicationTests.install
    recover = PublicationTests.recover
    assert_complete = PublicationTests.assert_complete
    fence_without_journal = PublicationFenceTests.fence_without_journal
    fresh_process = PublicationFenceTests.fresh_process

    def frozen_barrier_failure(self, mode, *, fenced_only=False):
        import errno
        import stat
        original_open = os.open
        original_fsync = os.fsync
        root = self.x.store.root
        identity = os.stat(root)
        def failed_open(path, flags, *args, **kwargs):
            if mode == "open" and os.fspath(path) == str(root):
                raise OSError(errno.EACCES, "injected frozen directory open failure")
            return original_open(path, flags, *args, **kwargs)
        def failed_fsync(fd):
            info = os.fstat(fd)
            if (mode != "open" and stat.S_ISDIR(info.st_mode)
                    and (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino)
                    and (not fenced_only or FrozenInstallStore.read_snapshot(root).phase is FrozenInstallPhase.PUBLICATION_PENDING)):
                raise OSError(getattr(errno, mode), "injected frozen directory fsync failure")
            return original_fsync(fd)
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(os, "open", side_effect=failed_open))
        stack.enter_context(patch.object(os, "fsync", side_effect=failed_fsync))
        return stack

    def test_confirmation_and_creation_reject_all_directory_errors(self):
        from resources.lib.frozen_install import FrozenInstallPersistenceError
        from resources.lib.build_library import LibraryConflict
        for mode in ("open", "EINVAL", "ENOTSUP", "EIO"):
            with self.subTest(mode=mode):
                if mode != "open": self.setUp()
                previous, target = self.fence_without_journal()
                expected = self.x.store.inspect()
                journal = self.library.publication_journal()
                applied = (Path(self.library.root) / "applied.json").read_bytes()
                before = self.snapshot()
                with self.frozen_barrier_failure(mode):
                    with self.assertRaises(FrozenInstallPersistenceError):
                        self.x.store._confirm_publication_owner(expected)
                    with self.assertRaises(LibraryConflict):
                        self.library._create_applied_publication(expected, resolution_store=self.x.store)
                    self.assertEqual(self.recover().outcome, "needs_attention")
                    self.assertEqual(self.recover().outcome, "needs_attention")
                self.assertEqual(self.library.publication_journal(), journal)
                self.assertEqual((Path(self.library.root) / "applied.json").read_bytes(), applied)
                self.assertEqual(self.x.store.inspect(), expected)
                self.assertEqual(self.snapshot(), before)
                self.fresh_process()
                self.assert_complete(target, self.recover())
                self.assertEqual(self.snapshot(), before)

    def test_ENOTSUP_crash_restored_COMPLETE_abandon_cannot_leave_B_authority(self):
        previous = self.x.seed_prior_association()
        target = self.x.target()
        original_transition = FrozenInstallStore.transition_expected
        durable_complete = []
        def remember(store, **kwargs):
            if kwargs["new_phase"] is FrozenInstallPhase.PUBLICATION_PENDING:
                durable_complete.append(store.transaction_path.read_bytes())
            return original_transition(store, **kwargs)
        # Legacy transition can tolerate ENOTSUP, but confirmation must not.
        with patch.object(FrozenInstallStore, "transition_expected", new=remember), self.frozen_barrier_failure("ENOTSUP", fenced_only=True):
            result = self.install(target)
        self.assertEqual(result.outcome, "needs_attention")
        visible = self.x.store.inspect()
        b_journal = self.library.publication_journal().candidate.entry_id == target.source.entry_id
        self.assertEqual(visible.phase, FrozenInstallPhase.PUBLICATION_PENDING)
        self.x.store.transaction_path.write_bytes(durable_complete[0])
        abandoned = self.x.coordinator().abandon()
        self.assertEqual(abandoned.outcome, "complete")
        self.assertIsNone(self.x.store.inspect())
        before = self.snapshot()
        self.recover()
        published_b = self.library.current_applied_association().entry_id == target.source.entry_id
        print("ENOTSUP crash probe:", result.outcome, "B journal:", b_journal,
              "visible phase:", visible.phase.value, "abandon:", abandoned.outcome,
              "B published:", published_b)
        self.assertFalse(b_journal)
        self.assertFalse(published_b)
        self.assertEqual(self.library.current_applied_association(), previous)
        self.assertEqual(self.snapshot(), before)

    def test_successful_strict_confirmation_precedes_journal_creation(self):
        import stat
        _, target = self.fence_without_journal()
        owner = self.x.store.inspect()
        identity = os.stat(self.x.store.root)
        original = os.fsync
        barriers = []
        original_atomic = lib._atomic
        def sync(fd):
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                barriers.append(True)
            return original(fd)
        def write(fd, name, data):
            if name == "applied-publication.json": self.assertTrue(barriers)
            return original_atomic(fd, name, data)
        with patch.object(os, "fsync", side_effect=sync), patch.object(lib, "_atomic", side_effect=write):
            self.assertEqual(self.x.store._confirm_publication_owner(owner), owner)
            journal = self.library._create_applied_publication(owner, resolution_store=self.x.store)
        self.assertEqual(journal.transaction_id, owner.transaction_id)
        self.assert_complete(target, self.recover())

    def test_mismatch_and_wrong_phase_reject_before_barrier_or_journal(self):
        from resources.lib.frozen_install import FrozenInstallStateConflict
        from resources.lib.build_library import LibraryConflict
        _, target = self.fence_without_journal()
        owner = self.x.store.inspect()
        journal = self.library.publication_journal()
        for wrong_phase in (False, True):
            with self.subTest(wrong_phase=wrong_phase):
                if wrong_phase:
                    owner = replace(owner, phase=FrozenInstallPhase.COMPLETE)
                    self.x.store.transaction_path.write_text(json.dumps(owner.to_dict()))
                    expected = owner
                else:
                    expected = replace(owner, transaction_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
                with patch.object(os, "fsync", side_effect=AssertionError("unowned barrier")):
                    with self.assertRaises(FrozenInstallStateConflict):
                        self.x.store._confirm_publication_owner(expected)
                    with self.assertRaises(LibraryConflict):
                        self.library._create_applied_publication(expected, resolution_store=self.x.store)
                self.assertEqual(self.library.publication_journal(), journal)
        self.assert_complete(target, self.recover())

    def test_legacy_directory_helper_keeps_compatibility_semantics(self):
        for mode in ("open", "EINVAL", "ENOTSUP"):
            with self.subTest(mode=mode), self.frozen_barrier_failure(mode):
                self.x.store._fsync_directory()
