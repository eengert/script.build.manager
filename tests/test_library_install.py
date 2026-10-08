"""Offline durable library -> frozen/configuration/restart ownership tests."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from resources.lib.artifacts import ArtifactStore
from resources.lib.build_library import LibraryInstallTarget, LibrarySource, LibraryError, isolated_library_install_authority
from resources.lib.build_manager import BuildManager, BuildManagerOwners, ReconcileRequest
from resources.lib.config import ConfigPackageLoader, ConfigurationManager
from resources.lib.dependencies import DependencyClosure
from resources.lib.frozen import AddonCaptureNode, CaptureStatus, ProvenanceStatus
from resources.lib.frozen_install import (
    FrozenInstallCoordinator, FrozenInstallStore, FrozenInstallTransaction,
    FrozenInstallPhase, FrozenLifecycleStage, InMemoryFrozenArtifactBackend,
    load_transaction_manifest, ensure_frozen_resume_registry_ready,
)
from resources.lib.frozen_resolution import ResolutionChoice, InstallResolution
from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.private_overlay import PrivateOverlayMetadata
from resources.lib.redlight_resource import redlight_declaration
from resources.lib.resolver import resolve_manifest
from resources.lib.restart import RestartRequirement
from resources.lib.restart_coordinator import RestartCoordinator, RestartCapabilityResolver
from resources.lib.resume import ResumeCoordinator
from resources.lib.transaction import TransactionStore, RestartTransaction, TransactionCorrupt
from resources.lib.update_guard import AddonUpdatePolicy
from tests import test_build_library as library_fixture
from tests.test_config import FakeConfigurationBackend
from tests.test_frozen_install import FakePolicy, InMemoryRegistryBackend, SESSION_A, SESSION_B, _zip
from tests.test_status import DEMO, SECRET, DB_SECRET


def forbidden(*args, **kwargs):
    raise AssertionError("standalone/global loader must not be used")


class LibraryInstallTests(unittest.TestCase):
    def setUp(self):
        self.fixture = library_fixture.LibraryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        authority = isolated_library_install_authority(self.fixture.library)
        authority.__enter__()
        self.addCleanup(authority.__exit__, None, None, None)
        self.base = self.fixture.base
        self.artifacts = ArtifactStore(self.base / "artifacts")
        self.store = FrozenInstallStore(self.fixture.root.parent)
        self.restart_store = TransactionStore(str(self.base / "restart-state"))
        self.policy = FakePolicy(AddonUpdatePolicy.NOTIFY_ONLY)
        self.backend = InMemoryFrozenArtifactBackend()
        self.config = FakeConfigurationBackend(settings={(DEMO, "quality"): "low"})
        metadata = self.artifacts.import_zip(_zip(DEMO, "1.0.0"),
                                             expected_addon_id=DEMO, expected_version="1.0.0")
        self.fixture.frozen = replace(self.fixture.frozen, addons=(
            AddonCaptureNode(DEMO, "1.0.0", "xbmc.python.pluginsource", True,
                             ProvenanceStatus.UNKNOWN, artifact=metadata),))
        self.fixture.raw.pop("private_overlay")
        self.fixture.write_sources()

    def seed_prior_association(self):
        version = self.fixture.raw["build"]["version"]
        self.fixture.raw["build"]["version"] = "0.9.0"
        frozen = self.fixture.frozen
        self.fixture.frozen = replace(frozen, addons=())
        self.fixture.write_sources(); prior = self.fixture.register()
        self.fixture.record_applied(prior, "other")
        self.fixture.frozen = frozen
        self.fixture.raw["build"]["version"] = version
        self.fixture.write_sources()
        return self.fixture.library.current_applied_association()

    def assert_associated(self, target):
        applied = self.fixture.library.current_applied_association()
        self.assertEqual((applied.entry_id, applied.device_profile_id),
                         (target.source.entry_id, target.device_profile_id))

    def test_successful_A_selection_B_then_successful_B(self):
        a = self.fixture.register()
        target_a = LibraryInstallTarget(LibrarySource(str(self.fixture.root), a.entry_id), "desk")
        self.fixture.library.select(a.entry_id, "desk")
        with self.isolated():
            first = self.coordinator().install_target(target_a, interactive=False)
        self.assertEqual(first.outcome, "complete"); self.assert_associated(target_a)
        self.fixture.raw["build"]["version"] = "2.0.0"
        self.fixture.descriptor["settings"][0]["value"] = "second"
        self.fixture.write_sources(); b = self.fixture.register()
        self.fixture.library.select(b.entry_id, "other")
        self.assert_associated(target_a)
        target_b = LibraryInstallTarget(LibrarySource(str(self.fixture.root), b.entry_id), "other")
        with self.isolated():
            second = self.coordinator().install_target(target_b, interactive=False)
        self.assertEqual(second.outcome, "complete"); self.assert_associated(target_b)

    def test_missing_choices_cancel_and_resolution_preserve_prior(self):
        prior = self.seed_prior_association()
        missing = self.with_missing_addon(); target = self.target()
        before = (self.fixture.root / "applied.json").read_bytes()
        for choices, outcome in (({}, "user_resolution_required"),
                                 ({missing: ResolutionChoice.CANCEL}, "cancelled")):
            with self.subTest(outcome=outcome), self.isolated():
                result = self.coordinator().install_target(target, interactive=False, resolution_choices=choices)
                self.assertEqual(result.outcome, outcome)
                self.assertEqual(self.fixture.library.current_applied_association(), prior)
                self.assertEqual((self.fixture.root / "applied.json").read_bytes(), before)
        with self.isolated():
            result = self.coordinator().install_target(target, interactive=False,
                                                       resolution_choices={missing: ResolutionChoice.SKIP})
        self.assertEqual(result.outcome, "complete"); self.assert_associated(target)

    def test_terminal_cleanup_failures_preserve_prior(self):
        for stage in ("resolution", "updater", "clear", "association"):
            with self.subTest(stage=stage):
                if stage != "resolution": self.setUp()
                prior = self.seed_prior_association(); target = self.target()
                before = (self.fixture.root / "applied.json").read_bytes()
                coordinator = self.coordinator()
                if stage == "resolution": owner, method = coordinator.store, "save_resolution_manifest"
                elif stage == "updater": owner, method = self.policy, "set_policy"
                elif stage == "clear": owner, method = coordinator.store, "_clear_publication_expected"
                else:
                    from resources.lib.build_library import BuildLibrary
                    owner, method = BuildLibrary, "_record_applied_completion"
                if stage == "updater":
                    original = self.policy.set_policy
                    def fail_restore(policy):
                        if policy == AddonUpdatePolicy.NOTIFY_ONLY: raise OSError("restore failure")
                        return original(policy)
                    effect = fail_restore
                else: effect = OSError("write failure")
                with self.isolated(), patch.object(owner, method, side_effect=effect):
                    result = coordinator.install_target(target, interactive=False)
                self.assertEqual(result.outcome, "needs_attention", (result.code, result.message))
                if stage == "clear":
                    self.assertEqual(self.fixture.library.current_applied_association().entry_id, target.source.entry_id)
                    self.assertEqual(self.store.inspect().phase, FrozenInstallPhase.PUBLICATION_PENDING)
                else:
                    self.assertEqual(self.fixture.library.current_applied_association(), prior)
                    self.assertEqual((self.fixture.root / "applied.json").read_bytes(), before)

    def target(self):
        entry = self.fixture.register()
        self.fixture.library.select(entry.entry_id, "desk")
        result = LibraryInstallTarget.from_plan_target(self.fixture.library.selected_plan_target())
        # The only remaining package material is owned by the library envelope.
        shutil.rmtree(self.fixture.source)
        return result

    def manager(self, restart=False):
        backend = self.backend
        inspector = SimpleNamespace(inspect=lambda: KodiState(
            "macos", "21.0", "", tuple(InstalledAddon(x.addon_id, x.enabled, x.version)
                                        for x in backend.installed.values())))
        config_owner = ConfigurationManager(self.config)
        if restart:
            # Preserve real apply/verification; model an owner requesting restart
            # only for a changed operation, as required by the restart contract.
            owner = config_owner
            def apply(effective):
                result = owner.apply(effective)
                return replace(result, results=tuple(replace(
                    row, restart_requirement=RestartRequirement.KODI_RESTART
                ) for row in result.results))
            config_owner = SimpleNamespace(apply=apply)
        return BuildManager(BuildManagerOwners(
            inspector=inspector, manifest_loader=forbidden, resolver=resolve_manifest,
            dependency_resolver=SimpleNamespace(resolve_closure=lambda roots, **kwargs:
                                               DependencyClosure(tuple(roots), ())),
            repository_manager=SimpleNamespace(install=forbidden),
            dependency_installer=SimpleNamespace(install=forbidden),
            addon_state_reconciler=SimpleNamespace(reconcile=forbidden),
            skin_activator=SimpleNamespace(activate=forbidden),
            config_loader=ConfigPackageLoader(str(self.base / "empty-global-packages")),
            config_manager=config_owner, frozen_manifest_loader=forbidden,
        ))

    def coordinator(self, runner=None, session=SESSION_A, **kwargs):
        return FrozenInstallCoordinator(
            store=FrozenInstallStore(self.store.root),
            artifact_store=ArtifactStore(self.artifacts.root),
            policy_backend=self.policy, installer=self.backend,
            session_id_provider=lambda: session, manifest_loader=forbidden,
            configuration_runner=runner or self.manager().reconcile,
            registry_backend=InMemoryRegistryBackend(self.backend), **kwargs)

    def isolated(self):
        # All transaction inspection is rooted in the disposable fixture.
        return patch("resources.lib.frozen_install.FrozenInstallStore", return_value=self.store)

    def assert_no_mutation(self):
        self.assertEqual(self.backend.installed, {})
        self.assertEqual(self.policy.calls, [])
        self.assertEqual(self.config.mutations, [])
        self.assertIsNone(self.store.inspect())

    def test_source_load_and_real_configuration_use_only_owned_packages(self):
        target = self.target()
        public, frozen, loader = target.load()
        self.assertEqual(frozen.fingerprint(), self.fixture.frozen.fingerprint())
        desired = resolve_manifest(public, "desk")
        self.assertEqual(loader.resolve(desired.config).files[0].content, self.fixture.asset)
        with self.assertRaises(Exception):
            ConfigPackageLoader(str(self.base / "empty-global-packages")).resolve(desired.config)
        coordinator = self.coordinator()
        with self.isolated():
            result = coordinator.install_target(target, interactive=False)
        self.assertEqual(result.outcome, "complete", (result.code, result.message))
        self.assert_associated(target)
        self.assertEqual(self.config.settings[(DEMO, "quality")], "high")
        self.assertEqual(self.config.files["userdata/keymaps/demo.xml"], self.fixture.asset)
        self.assertIsNone(self.store.inspect())
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NOTIFY_ONLY)

    def test_default_library_configuration_composition_does_not_change_standalone_runner(self):
        target = self.target()
        coordinator = self.coordinator()
        coordinator.configuration_runner = None
        runtime_owner = SimpleNamespace(reconcile=self.manager().reconcile)
        with self.isolated(), patch("resources.lib.restart_coordinator.RestartCoordinator", return_value=runtime_owner) as factory:
            result = coordinator.install_target(target)
        self.assertEqual(result.outcome, "complete", (result.code, result.message))
        factory.assert_called_once_with()
        self.assertIsNone(coordinator.configuration_runner)

    def test_selection_changes_do_not_redirect_target_or_profile(self):
        target = self.target()
        self.fixture.library.select(target.source.entry_id, "other")
        # Clearing selection and corrupting its file cannot redirect execution.
        self.fixture.library.clear_selection()
        (self.fixture.root / "selection.json").write_text("invalid")
        with self.isolated():
            result = self.coordinator().install_target(target, interactive=False)
        self.assertEqual(result.outcome, "complete")
        self.assertEqual(target.device_profile_id, "desk")

    def test_selecting_another_entry_with_identical_software_does_not_redirect_configuration(self):
        entry = self.fixture.register()
        self.fixture.library.select(entry.entry_id, "desk")
        target = LibraryInstallTarget.from_plan_target(self.fixture.library.selected_plan_target())
        self.fixture.raw["build"]["version"] = "2.0.0"
        self.fixture.descriptor["settings"][0]["value"] = "second"
        self.fixture.write_sources()
        other = self.fixture.register()
        self.fixture.library.select(other.entry_id, "other")
        self.assertNotEqual(entry.entry_id, other.entry_id)
        self.assertEqual(target.load()[1].fingerprint(), LibrarySource(str(self.fixture.root), other.entry_id).load()[1].fingerprint())
        shutil.rmtree(self.fixture.source)
        with self.isolated():
            result = self.coordinator().install_target(target, interactive=False)
        self.assertEqual(result.outcome, "complete", (result.code, result.message))
        self.assert_associated(target)
        self.assertEqual(self.config.settings[(DEMO, "quality")], "high")

    def test_plan_review_binds_registered_source_even_with_identical_effective_content(self):
        from resources.lib.plan import BuildPlanService
        from resources.lib.plan_model import IdentityComponent
        from tests.test_plan import PlanHarness
        self.fixture.frozen = replace(self.fixture.frozen, addons=())
        self.fixture.descriptor["settings"][0]["value"] = "review-change"
        self.fixture.write_sources()
        target = self.target()
        plan_target = self.fixture.library.selected_plan_target()
        duplicate_root = self.base / "duplicate-library"
        shutil.copytree(self.fixture.root, duplicate_root)
        other = replace(plan_target, library_source=LibrarySource(str(duplicate_root), target.source.entry_id))
        harness = PlanHarness(self, with_private=False, with_resource=False)
        service = BuildPlanService(harness.plan_owners(status=harness.owners(resolver=resolve_manifest)))
        with harness.instrumented():
            first = service.preview(plan_target)
            self.assertIsNotNone(first.review)
            check = service.validate(other, first.review)
        self.assertFalse(check.is_current)
        self.assertIn(IdentityComponent.BUILD, check.changed)
        harness.assert_untouched()

    def test_initial_missing_corrupt_unregistered_and_metadata_mismatch_fail_closed(self):
        target = self.target()
        envelope = self.fixture.envelope(target.source.entry_id)
        saved = envelope.read_bytes()
        registry = self.fixture.root / "registry.json"
        index = registry.read_bytes()
        for mode in ("missing", "corrupt", "changed", "unregistered", "metadata"):
            with self.subTest(mode=mode):
                envelope.write_bytes(saved); registry.write_bytes(index)
                if mode == "missing": envelope.unlink()
                elif mode == "corrupt": envelope.write_text("invalid")
                elif mode == "changed":
                    bundle = json.loads(saved)
                    bundle["packages"]["shared"]["descriptor"]["settings"][0]["value"] = "changed"
                    envelope.write_text(json.dumps(bundle))
                else:
                    data = json.loads(index)
                    if mode == "unregistered": data["entries"].clear()
                    else: data["entries"][target.source.entry_id]["device_profiles"] = ["missing"]
                    registry.write_text(json.dumps(data))
                result = self.coordinator().install_target(target, interactive=False)
                self.assertEqual(result.outcome, "failed")
                self.assert_no_mutation()

    def test_profile_and_conflicting_path_identity_rejected(self):
        target = self.target()
        bad = replace(target, device_profile_id="missing")
        self.assertEqual(self.coordinator().install_target(bad).outcome, "failed")
        with self.assertRaises(ValueError):
            ReconcileRequest("/standalone.json", "desk", library_target=target)
        result = self.coordinator().install(self.fixture.frozen, manifest_path="/wrong.json",
                                           device_profile_id="desk", library_target=target)
        self.assertEqual(result.outcome, "failed")
        self.assert_no_mutation()

    def awaiting(self, target):
        restart = RestartCoordinator(self.manager(restart=True), store=self.restart_store,
                                     session_id_provider=lambda: SESSION_A,
                                     capability_resolver=RestartCapabilityResolver(platform_id="macos"))
        with self.isolated():
            result = self.coordinator(runner=restart.reconcile).install_target(target, interactive=False)
        self.assertEqual(result.outcome, "awaiting_restart", (result.code, result.message))
        return result

    def test_real_restart_roundtrip_new_owners_and_resolution_continuity(self):
        prior = self.seed_prior_association()
        target = self.target()
        first = self.awaiting(target)
        self.assertEqual(self.fixture.library.current_applied_association(), prior)
        raw = json.loads(self.store.transaction_path.read_text())
        self.assertEqual(raw["schema_version"], 4)
        self.assertEqual(raw["library_target"], target.to_dict())
        self.assertEqual(raw["manifest_path"], "")
        self.assertEqual(raw["configuration_manifest_path"], "")
        durable = FrozenInstallTransaction.from_dict(raw)
        restart_raw = json.loads(Path(self.restart_store.transaction_path).read_text())
        self.assertEqual(restart_raw["schema_version"], 2)
        restart_tx = RestartTransaction.from_dict(restart_raw)
        self.assertEqual(restart_tx.request.library_target, target)
        for sentinel in (SECRET, DB_SECRET, "<keymap/>", '"value": "high"'):
            self.assertNotIn(sentinel, json.dumps(raw) + json.dumps(restart_raw))
        self.fixture.library.select(target.source.entry_id, "other")
        # Fresh manager, config/package owners, stores, coordinator, session.
        with self.isolated():
            resumed = ResumeCoordinator(self.manager(), store=TransactionStore(str(self.base / "restart-state")),
                                        session_id_provider=lambda: SESSION_B).resume(restart_tx)
            self.assertTrue(resumed.succeeded, resumed)
            final = self.coordinator(session=SESSION_B).resume_after_restart(bm020_result=resumed)
        self.assertEqual(final.outcome, "complete", (final.code, final.message))
        self.assert_associated(target)
        self.assertEqual(final.resolution_manifest.records, durable.resolution_records)
        self.assertEqual(self.fixture.library.current_applied_association().resolution_fingerprint,
                         durable.resolution_fingerprint)
        self.assertEqual(self.fixture.library.associated_status_target().install_resolution,
                         final.resolution_manifest)
        self.assertEqual(final.resolution_manifest.install_plan_fingerprint, durable.install_plan_fingerprint)
        self.assertEqual(durable.library_target, first.transaction.library_target)
        self.assertIsNone(self.store.inspect())
        self.assertIsNone(self.restart_store.inspect())

    def test_changed_source_across_restart_rejected_before_configuration_or_activation(self):
        prior = self.seed_prior_association()
        target = self.target()
        self.awaiting(target)
        self.assertEqual(self.fixture.library.current_applied_association(), prior)
        restart_tx = self.restart_store.inspect()
        envelope = self.fixture.envelope(target.source.entry_id)
        bundle = json.loads(envelope.read_text())
        bundle["packages"]["shared"]["descriptor"]["settings"][0]["value"] = "changed"
        envelope.write_text(json.dumps(bundle))
        before = (dict(self.backend.installed), list(self.policy.calls), list(self.config.mutations))
        with self.isolated():
            resumed = ResumeCoordinator(self.manager(), store=self.restart_store,
                                        session_id_provider=lambda: SESSION_B).resume(restart_tx)
            final = self.coordinator(session=SESSION_B).resume_after_restart(bm020_result=resumed)
        self.assertFalse(resumed.succeeded)
        self.assertEqual(final.outcome, "needs_attention")
        self.assertEqual(self.fixture.library.current_applied_association(), prior)
        self.assertEqual(before, (self.backend.installed, self.policy.calls, self.config.mutations))
        self.assertEqual(self.store.inspect().library_target, target)

    def test_frozen_schema_legacy_modes_and_source_validation(self):
        target = self.target(); first = self.awaiting(target)
        raw = first.transaction.to_dict()
        for version in (1, 2, 3):
            legacy = {**raw, "schema_version": version, "manifest_path": "/frozen.json",
                      "configuration_manifest_path": "/public.json"}
            legacy.pop("library_target")
            if version < 3:
                for field in ("configuration_manifest_path", "lifecycle_stage", "activation_hold_ids",
                              "activation_hold_released", "lifecycle_restart_count"):
                    legacy.pop(field)
            if version == 1:
                for field in ("install_plan_fingerprint", "policies", "resolution_records",
                              "resolution_fingerprint", "resolved_software_fingerprint"):
                    legacy.pop(field)
            parsed = FrozenInstallTransaction.from_dict(legacy)
            self.assertIsNone(parsed.library_target)
            self.assertEqual(load_transaction_manifest(parsed, lambda path: path), "/frozen.json")
        for change in ({"mode": "path"}, {"entry_id": "../escape"}, {"device_profile_id": "other"},
                       {"root": "relative"}, {"payload": SECRET}):
            invalid = {**raw, "library_target": {**target.to_dict(), **change}}
            with self.assertRaises(Exception): FrozenInstallTransaction.from_dict(invalid)
        invalid = dict(raw); invalid.pop("library_target")
        with self.assertRaises(Exception): FrozenInstallTransaction.from_dict(invalid)
        invalid = {**raw, "schema_version": 3}
        with self.assertRaises(Exception): FrozenInstallTransaction.from_dict(invalid)
        restart_raw = self.restart_store.inspect().to_dict()
        restart_raw["request"]["library_target"]["entry_id"] = "../escape"
        with self.assertRaises(TransactionCorrupt): RestartTransaction.from_dict(restart_raw)

    def with_missing_addon(self):
        missing = "plugin.video.missing"
        self.fixture.frozen = replace(self.fixture.frozen, addons=self.fixture.frozen.addons + (
            AddonCaptureNode(missing, "1.0.0", "xbmc.python.pluginsource", True,
                             ProvenanceStatus.UNKNOWN, status=CaptureStatus.INCOMPLETE_ARTIFACT),))
        self.fixture.raw["addons"].append({"addon_id": missing, "state": "enabled"})
        self.fixture.raw["device_profiles"]["desk"]["frozen_install_policies"] = [
            {"addon_id": missing, "policy": "exact_first_with_repository_fallback_or_skip"}]
        self.fixture.write_sources()
        return missing

    def test_approved_skip_choices_and_policies_survive_restart_without_reprompt(self):
        missing = self.with_missing_addon()
        target = self.target()
        restart = RestartCoordinator(self.manager(restart=True), store=self.restart_store,
                                     session_id_provider=lambda: SESSION_A,
                                     capability_resolver=RestartCapabilityResolver(platform_id="macos"))
        with self.isolated():
            first = self.coordinator(runner=restart.reconcile, resolution_decider=forbidden).install_target(
                target, interactive=False, resolution_choices={missing: ResolutionChoice.SKIP})
        self.assertEqual(first.outcome, "awaiting_restart", (first.code, first.message))
        durable = FrozenInstallTransaction.from_dict(json.loads(self.store.transaction_path.read_text()))
        self.assertEqual(durable.policies[0].addon_id, missing)
        self.assertEqual(next(row for row in durable.resolution_records if row.addon_id == missing).resolution,
                         InstallResolution.SKIPPED)
        with self.isolated():
            resumed = ResumeCoordinator(self.manager(), store=self.restart_store,
                                        session_id_provider=lambda: SESSION_B).resume(self.restart_store.inspect())
            final = self.coordinator(session=SESSION_B, resolution_decider=forbidden).resume_after_restart(bm020_result=resumed)
        self.assertTrue(resumed.succeeded, resumed)
        self.assertEqual(final.outcome, "complete", (final.code, final.message))
        self.assert_associated(target)
        self.assertEqual(final.resolution_manifest.records, durable.resolution_records)
        self.assertEqual(self.fixture.library.current_applied_association().resolution_fingerprint,
                         durable.resolution_fingerprint)
        self.assertEqual(self.fixture.library.associated_status_target().install_resolution,
                         final.resolution_manifest)
        self.assertNotIn(missing, self.backend.installed)

    def test_revalidation_after_resolution_before_first_mutation(self):
        missing = self.with_missing_addon()
        target = self.target()
        def choose(prompt):
            self.fixture.envelope(target.source.entry_id).unlink()
            return ResolutionChoice.SKIP
        result = self.coordinator(resolution_decider=choose).install_target(target, interactive=True)
        self.assertEqual(result.outcome, "failed")
        self.assert_no_mutation()

    def test_missing_entry_and_frozen_identity_mismatch_on_resume(self):
        target = self.target(); first = self.awaiting(target)
        raw = first.transaction.to_dict()
        mismatch = FrozenInstallTransaction.from_dict({**raw, "manifest_fingerprint": "a" * 64})
        with self.assertRaises(Exception): load_transaction_manifest(mismatch, forbidden)
        self.fixture.envelope(target.source.entry_id).unlink()
        before = (dict(self.backend.installed), list(self.policy.calls), list(self.config.mutations))
        result = self.coordinator(session=SESSION_B).resume_after_restart()
        self.assertEqual(result.outcome, "needs_attention")
        self.assertEqual(before, (self.backend.installed, self.policy.calls, self.config.mutations))

    def test_held_configuration_boundaries_reopen_real_library_loaders(self):
        # Public declarations only; private resource execution stays an injected
        # owner as in existing held lifecycle tests. No SQLite/runtime access.
        self.fixture.raw["private_overlay"] = {"type": "local_file", "overlay_id": "held", "required": True}
        declaration = replace(redlight_declaration(), owner_addon_id=DEMO, supported_versions=("1.0.0",))
        self.fixture.raw["config"]["structured_private_resources"] = [declaration.safe_dict()]
        self.fixture.write_sources()
        target = self.target()
        meta = PrivateOverlayMetadata("held", "sha256:" + "3" * 64, True, True)
        provider = lambda profile, fingerprint: (meta.overlay_id, meta.fingerprint, meta.required)
        requests = []
        def runner(request):
            requests.append(request)
            public, _, loader = request.library_target.load()
            effective = loader.resolve(resolve_manifest(public, request.device_profile_id).config)
            self.assertTrue(ConfigurationManager(self.config).apply(effective).all_applied)
            return SimpleNamespace(outcome="manual_restart_required", private_overlay=meta,
                                   transaction=SimpleNamespace(transaction_id="33333333-3333-4333-8333-333333333333"))
        first = self.coordinator(runner=runner, private_overlay_metadata_provider=provider).install_target(target, interactive=False)
        self.assertEqual(first.outcome, "awaiting_restart", (first.code, first.message))
        self.assertEqual(first.transaction.lifecycle_stage, FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART)
        self.assertEqual(requests, [])
        self.assertFalse(self.backend.installed[DEMO].enabled)
        second = self.coordinator(runner=runner, session=SESSION_B,
                                  private_overlay_metadata_provider=provider).resume_after_restart()
        self.assertEqual(second.outcome, "awaiting_restart", (second.code, second.message))
        self.assertEqual(second.transaction.lifecycle_stage, FrozenLifecycleStage.CONFIGURATION_AWAITING_RESTART)
        durable = FrozenInstallTransaction.from_dict(json.loads(self.store.transaction_path.read_text()))
        self.assertEqual(durable.library_target, target)
        self.assertEqual(requests[0].library_target, target)
        request = requests[0]
        preview = SimpleNamespace(request=request, success=True, private_overlay=meta)
        readiness = ensure_frozen_resume_registry_ready(
            SimpleNamespace(request=request), preview, "44444444-4444-4444-8444-444444444444",
            store=self.store, artifact_store=ArtifactStore(self.artifacts.root), policy_backend=self.policy,
            registry_backend=InMemoryRegistryBackend(self.backend), manifest_loader=forbidden,
            coordinator_factory=lambda **kwargs: FrozenInstallCoordinator(
                **kwargs, private_overlay_metadata_provider=provider))
        self.assertTrue(readiness.allowed, (readiness.code, readiness.message))
        verified = SimpleNamespace(succeeded=True, reconcile_result=SimpleNamespace(
            private_overlay=meta, action_results=(SimpleNamespace(owner_result=SimpleNamespace(
                private_result=SimpleNamespace(succeeded=True, resource_results=(SimpleNamespace(succeeded=True),)))),)))
        final = self.coordinator(session="44444444-4444-4444-8444-444444444444",
                                 private_overlay_metadata_provider=provider).resume_after_restart(bm020_result=verified)
        self.assertEqual(final.outcome, "complete", (final.code, final.message))
        self.assert_associated(target)
        self.assertTrue(self.backend.installed[DEMO].enabled)
        self.assertIsNone(self.store.inspect())

    def test_production_root_pinning_and_explicit_isolation_authority(self):
        from resources.lib import build_library as lib
        target = self.target()
        alternate = self.base / "alternate-library"
        shutil.copytree(self.fixture.root, alternate)
        raw = target.to_dict()
        tampered = {**raw, "root": str(alternate)}
        # Remove the fixture's explicitly injected authority to exercise production.
        token = lib._isolated_install_root.set(None)
        try:
            with patch.object(lib, "default_build_library", return_value=self.fixture.library):
                self.assertEqual(LibraryInstallTarget.from_dict(raw), target)
                with self.assertRaises(LibraryError): LibraryInstallTarget.from_dict(tampered)
                redirected = replace(target, source=LibrarySource(str(alternate), target.source.entry_id))
                with patch.object(LibrarySource, "load", side_effect=forbidden):
                    with self.assertRaises(LibraryError): redirected.load()
                with isolated_library_install_authority(lib.BuildLibrary(alternate)):
                    self.assertEqual(LibraryInstallTarget.from_dict(tampered).load()[1], target.source.load()[1])
                with self.assertRaises(LibraryError): LibraryInstallTarget.from_dict(tampered)
        finally:
            lib._isolated_install_root.reset(token)

    def test_tampered_root_cannot_redirect_durable_restart_or_resume(self):
        target = self.target(); first = self.awaiting(target)
        alternate = self.base / "alternate-library"
        shutil.copytree(self.fixture.root, alternate)
        raw = first.transaction.to_dict()
        raw["library_target"]["root"] = str(alternate)
        with self.assertRaises(Exception): FrozenInstallTransaction.from_dict(raw)
        restart_raw = self.restart_store.inspect().to_dict()
        restart_raw["request"]["library_target"]["root"] = str(alternate)
        with self.assertRaises(TransactionCorrupt): RestartTransaction.from_dict(restart_raw)
        self.store.transaction_path.write_text(json.dumps(raw))
        before = (list(self.config.mutations), list(self.policy.calls))
        result = self.coordinator(session=SESSION_B).resume_after_restart()
        self.assertIn(result.outcome, ("failed", "needs_attention"))
        self.assertEqual(before, (self.config.mutations, self.policy.calls))

    def test_library_execution_cannot_loosen_exact_required_policy(self):
        from resources.lib.frozen_resolution import FrozenInstallPolicy, FrozenInstallPolicyMode
        missing = self.with_missing_addon()
        self.fixture.raw["device_profiles"]["desk"]["frozen_install_policies"][0]["policy"] = "exact_required"
        self.fixture.write_sources(); target = self.target()
        override = (FrozenInstallPolicy(missing, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP),)
        with self.assertRaises(TypeError):
            self.coordinator().install_target(target, install_policies=override)
        result = self.coordinator().install_target(target, resolution_choices={missing: ResolutionChoice.SKIP})
        self.assertEqual(result.outcome, "failed")
        # Even the lower-level library entry cannot use a caller override.
        result = self.coordinator().install(None, manifest_path="", device_profile_id="desk",
            library_target=target, install_policies=override, resolution_choices={missing: ResolutionChoice.SKIP})
        self.assertEqual(result.outcome, "failed")
        self.assert_no_mutation()
        result = self.coordinator(runner=lambda request: SimpleNamespace(outcome="complete")).install(
            self.fixture.frozen, manifest_path="/offline-frozen.json", device_profile_id="desk",
            install_policies=override, resolution_choices={missing: ResolutionChoice.SKIP})
        self.assertEqual(result.outcome, "complete", (result.code, result.message))
        self.assertEqual(next(r for r in result.resolution_manifest.records if r.addon_id == missing).resolution,
                         InstallResolution.SKIPPED)

    def test_equivalent_active_requires_exact_library_source_and_profile(self):
        prior = self.seed_prior_association()
        entry = self.fixture.register()
        self.fixture.library.select(entry.entry_id, "desk")
        target = LibraryInstallTarget.from_plan_target(self.fixture.library.selected_plan_target())
        self.fixture.raw["build"]["version"] = "2.0.0"
        self.fixture.write_sources(); other_entry = self.fixture.register()
        other = replace(target, source=LibrarySource(str(self.fixture.root), other_entry.entry_id))
        first = self.awaiting(target)
        before = (list(self.config.mutations), list(self.policy.calls))
        self.assertEqual(self.coordinator().install_target(target).outcome, "active")
        self.assertEqual(self.fixture.library.current_applied_association(), prior)
        for incoming in (other, replace(target, device_profile_id="other")):
            with self.subTest(incoming=incoming):
                self.assertEqual(self.coordinator().install_target(incoming).code, "ACTIVE_TRANSACTION_CONFLICT")
        alternate = self.base / "alternate-library"; shutil.copytree(self.fixture.root, alternate)
        redirected = replace(target, source=LibrarySource(str(alternate), target.source.entry_id))
        with patch.object(LibrarySource, "load", side_effect=forbidden):
            self.assertEqual(self.coordinator().install_target(redirected).code, "ACTIVE_TRANSACTION_CONFLICT")
        result = self.coordinator().install(self.fixture.frozen, manifest_path="/offline.json", device_profile_id="desk")
        self.assertEqual(result.code, "ACTIVE_TRANSACTION_CONFLICT")
        self.assertEqual(self.store.inspect(), first.transaction)
        self.assertEqual(before, (self.config.mutations, self.policy.calls))

    def held_library(self):
        from resources.lib.frozen_install import FrozenInstalledAddon
        owner = "plugin.video.redlight"
        metadata = self.artifacts.import_zip(_zip(owner, "2.6.8"), expected_addon_id=owner, expected_version="2.6.8")
        self.fixture.frozen = replace(self.fixture.frozen, addons=self.fixture.frozen.addons + (
            AddonCaptureNode(owner, "2.6.8", "xbmc.python.pluginsource", True,
                            ProvenanceStatus.UNKNOWN, artifact=metadata),))
        self.fixture.raw["addons"].append({"addon_id": owner, "state": "enabled"})
        self.fixture.raw["private_overlay"] = {"type": "local_file", "overlay_id": "held", "required": True}
        self.fixture.raw["config"]["structured_private_resources"] = [redlight_declaration().safe_dict()]
        self.fixture.write_sources()
        self.store = FrozenInstallStore(self.base / "held-profile" / "addon_data" / "script.build.manager")
        self.policy = FakePolicy(AddonUpdatePolicy.AUTOMATIC)
        self.backend.installed[owner] = FrozenInstalledAddon(owner, "2.6.8", True)
        target = self.target()
        meta = PrivateOverlayMetadata("held", "sha256:" + "3" * 64, True, True)
        provider = lambda profile, fingerprint: (meta.overlay_id, meta.fingerprint, meta.required)
        requests = []
        def runner(request, *, transaction_access=None):
            requests.append(request)
            private = SimpleNamespace(succeeded=True, resource_results=(SimpleNamespace(succeeded=True),))
            reconcile = SimpleNamespace(success=True, private_overlay=meta, action_results=(
                SimpleNamespace(owner_result=SimpleNamespace(private_result=private)),))
            return SimpleNamespace(outcome="complete", reconcile_result=reconcile)
        coordinator = self.coordinator(runner=runner, private_overlay_metadata_provider=provider)
        first = coordinator.install_target(target)
        self.assertEqual(first.outcome, "awaiting_restart", (first.code, first.message))
        self.assertEqual(first.transaction.lifecycle_stage, FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART)
        return target, meta, provider, runner, requests, first.transaction

    def test_held_library_outage_restore_supported_retry_reloads_manifest_and_profile(self):
        target, meta, provider, runner, requests, initial = self.held_library()
        envelope = self.fixture.envelope(target.source.entry_id); saved = envelope.read_bytes(); envelope.unlink()
        coordinator = self.coordinator(session=SESSION_B, runner=runner, private_overlay_metadata_provider=provider)
        result = coordinator.resume_after_restart()
        self.assertEqual((result.outcome, result.code), ("needs_attention", "FROZEN_MANIFEST_INVALID"))
        held = self.store.inspect()
        self.assertEqual(held.activation_hold_ids, initial.activation_hold_ids)
        self.assertFalse(held.activation_hold_released)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.NEVER_CHECK)
        self.assertFalse(self.backend.installed["plugin.video.redlight"].enabled)
        self.assertEqual(requests, [])
        self.assertEqual(coordinator.abandon().code, "HELD_LIFECYCLE_CANNOT_BE_ABANDONED")
        # Retry while absent stays eligible and fails at the source validation boundary.
        retry_store = TransactionStore(str(self.base / "held-profile"))
        retry = coordinator.retry_held_quiescence(expected_transaction=held, restart_store=retry_store)
        self.assertEqual(retry.code, "FROZEN_HELD_RETRY_VALIDATION_FAILED")
        self.assertEqual(self.store.inspect(), held)
        envelope.write_bytes(saved)
        with patch.object(FrozenInstallCoordinator, "_configuration_profile", side_effect=forbidden):
            retry = coordinator.retry_held_quiescence(expected_transaction=held, restart_store=retry_store)
        self.assertEqual(retry.outcome, "complete", (retry.code, retry.message))
        self.assertEqual(requests[0].library_target, target)
        self.assertTrue(self.backend.installed["plugin.video.redlight"].enabled)
        self.assertEqual(self.policy.policy, AddonUpdatePolicy.AUTOMATIC)
        self.assertIsNone(self.store.inspect())

    def test_profile_source_outage_uses_retryable_validation_semantics(self):
        from resources.lib.frozen_install import FrozenInstallValidationError
        target, _, provider, runner, _, initial = self.held_library()
        self.fixture.envelope(target.source.entry_id).unlink()
        with self.assertRaises(FrozenInstallValidationError):
            self.coordinator()._transaction_profile(initial)

    def test_active_held_resume_rejects_different_target_or_profile(self):
        target, _, _, _, _, initial = self.held_library()
        # Register a second exact graph with different public build metadata.
        (self.fixture.packages / "shared").mkdir(parents=True)
        self.fixture.raw["build"]["version"] = "2.0.0"
        self.fixture.write_sources()
        other_entry = self.fixture.register()
        different_entry = replace(target, source=LibrarySource(target.source.root, other_entry.entry_id))
        for incoming in (replace(target, device_profile_id="other"), different_entry):
            result = self.coordinator(session=SESSION_B).install_target(incoming)
            self.assertEqual(result.code, "ACTIVE_TRANSACTION_CONFLICT")
        self.assertEqual(self.store.inspect(), initial)

    def test_library_empty_legacy_paths_and_bm020_source_schema_tie(self):
        target = self.target(); first = self.awaiting(target)
        for field in ("manifest_path", "configuration_manifest_path"):
            with self.subTest(field=field), self.assertRaises(Exception):
                FrozenInstallTransaction.from_dict({**first.transaction.to_dict(), field: "/legacy.json"})
        restart = self.restart_store.inspect().to_dict()
        with self.assertRaises(TransactionCorrupt): RestartTransaction.from_dict({**restart, "schema_version": 1})
        without = json.loads(json.dumps(restart)); without["request"].pop("library_target")
        with self.assertRaises(TransactionCorrupt): RestartTransaction.from_dict(without)
        with self.assertRaises(TransactionCorrupt):
            RestartTransaction.from_dict({**restart, "request": {**restart["request"], "manifest_path": "/legacy.json"}})

    def test_registry_readiness_rejects_other_library_selector_before_loading(self):
        target, meta, provider, runner, _, initial = self.held_library()
        request = ReconcileRequest("", "desk", library_target=replace(
            target, source=LibrarySource(target.source.root, "b" * 64)),
                                   source_software_fingerprint=initial.manifest_fingerprint,
                                   frozen_transaction_id=initial.transaction_id)
        preview = SimpleNamespace(request=request, success=True, private_overlay=meta)
        result = ensure_frozen_resume_registry_ready(SimpleNamespace(request=request), preview, SESSION_B,
            store=self.store, policy_backend=self.policy, manifest_loader=forbidden)
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "FROZEN_RESUME_IDENTITY_MISMATCH")

    def test_build_manager_rejects_library_frozen_fingerprint_mismatch(self):
        target = self.target()
        request = ReconcileRequest("", "desk", library_target=target, source_software_fingerprint="a" * 64)
        result = self.manager().preview(request)
        self.assertFalse(result.success)
        self.assertEqual(result.failure.code, "MANIFEST_LOAD_FAILED")
        self.assert_no_mutation()
