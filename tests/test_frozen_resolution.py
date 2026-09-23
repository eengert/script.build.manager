"""BM-023B explicit frozen-artifact recovery and resolution tests."""

import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import (
    AddonCaptureNode,
    CaptureStatus,
    DependencyEdge,
    FrozenBuildManifest,
    InMemoryInventoryBackend,
    ProvenanceStatus,
    capture_frozen_build,
)
from resources.lib.frozen_install import (
    FrozenInstallCoordinator,
    FrozenInstallPhase,
    FrozenInstallStore,
    FrozenInstallValidationError,
    InMemoryFrozenArtifactBackend,
    validate_frozen_install_plan,
    validate_frozen_manifest,
)
from resources.lib.frozen_resolution import (
    FrozenPlanActionKind,
    InstallResolution,
    InstallResolutionRecord,
    ResolutionChoice,
    ResolutionPrompt,
    ResolutionState,
    install_plan_fingerprint,
    resolution_fingerprint,
    resolved_software_fingerprint,
    summarize_frozen_recoverability,
)
from resources.lib.manifest import (
    FrozenInstallPolicy,
    FrozenInstallPolicyMode,
    ManifestValidationError,
    load_manifest_file,
    load_manifest_json,
)
from resources.lib.private_overlay import (
    PrivateOverlayValidationError,
    validate_private_overlay_resolution_compatibility,
)
from resources.lib.update_guard import AddonUpdatePolicy, UpdatePolicyBackend


SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"
YOUTUBE = "plugin.video.youtube"
REPOSITORY = "repository.fixture"
UMBRELLA = "plugin.video.umbrella"
PYSOCKS = "script.module.pysocks"


def _zip(addon_id, version, *, repository=False, requires=()):
    output = io.BytesIO()
    imports = "".join(
        f'<import addon="{addon}" version="{minimum}"/>'
        for addon, minimum in requires
    )
    extension = (
        '<extension point="xbmc.addon.repository">'
        '<dir><info>http://127.0.0.1/addons.xml</info>'
        '<datadir zip="true">http://127.0.0.1/</datadir></dir>'
        '</extension>'
        if repository else
        '<extension point="xbmc.python.pluginsource" library="default.py"/>'
    )
    xml = (
        f'<addon id="{addon_id}" name="{addon_id}" version="{version}">'
        f'<requires>{imports}</requires>{extension}</addon>'
    )
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{addon_id}/addon.xml", xml)
        archive.writestr(f"{addon_id}/default.py", b"# fixture\n")
    return output.getvalue()


class FakePolicy(UpdatePolicyBackend):
    def __init__(self):
        self.policy = AddonUpdatePolicy.NOTIFY_ONLY
        self.calls = []

    def get_policy(self):
        return self.policy

    def set_policy(self, policy):
        self.calls.append(AddonUpdatePolicy(policy))
        self.policy = AddonUpdatePolicy(policy)


class FrozenResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.install_store = FrozenInstallStore(self.root / "transactions")
        self.repo_zip = _zip(REPOSITORY, "1.0.0", repository=True)
        self.umbrella_zip = _zip(UMBRELLA, "5.0.0")
        self.repo_meta = self.artifacts.import_zip(
            self.repo_zip, expected_addon_id=REPOSITORY, expected_version="1.0.0", source="fixture"
        )
        self.umbrella_meta = self.artifacts.import_zip(
            self.umbrella_zip, expected_addon_id=UMBRELLA, expected_version="5.0.0", source="fixture"
        )
        self.policy = FakePolicy()
        self.backend = InMemoryFrozenArtifactBackend()

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, *, repository_id="", required_youtube=False, youtube_artifact=None):
        youtube_edge = DependencyEdge(
            YOUTUBE, "", optional=not required_youtube, required_by=(UMBRELLA,)
        )
        nodes = (
            AddonCaptureNode(
                REPOSITORY, "1.0.0", "xbmc.addon.repository", True,
                ProvenanceStatus.VERIFIED_REPOSITORY, artifact=self.repo_meta,
            ),
            AddonCaptureNode(
                YOUTUBE, "7.4.4+unofficial.2", "xbmc.python.pluginsource", True,
                ProvenanceStatus.REPOSITORY_EVIDENCE, artifact=youtube_artifact,
                status=CaptureStatus.COMPLETE,
            ),
            AddonCaptureNode(
                UMBRELLA, "5.0.0", "xbmc.python.pluginsource", True,
                ProvenanceStatus.VERIFIED_REPOSITORY, artifact=self.umbrella_meta,
                dependency_edges=(
                    youtube_edge,
                    DependencyEdge(PYSOCKS, "", optional=True, required_by=(UMBRELLA,)),
                ),
            ),
            AddonCaptureNode(
                PYSOCKS, "", "", False, ProvenanceStatus.UNKNOWN,
                optional=True, status=CaptureStatus.MISSING,
            ),
        )
        return FrozenBuildManifest(
            schema_version=1,
            build_id="bm023b-family-room-fixture",
            name="Family Room sanitized fixture",
            created_at="2026-09-22T00:00:00Z",
            kodi_version="21.1",
            platform="tvos",
            capture_status=CaptureStatus.COMPLETE,
            addons=nodes,
        )

    @staticmethod
    def _policy(repository_id="", mode=FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP):
        return FrozenInstallPolicy(YOUTUBE, mode, repository_id)

    def _coordinator(self, *, decider=None, configure=None, backend=None, loader=None):
        return FrozenInstallCoordinator(
            store=self.install_store,
            artifact_store=self.artifacts,
            policy_backend=self.policy,
            installer=backend or self.backend,
            session_id_provider=lambda: SESSION_A,
            resolution_decider=decider,
            configuration_runner=configure,
            manifest_loader=loader or (lambda _path: self._manifest(repository_id=REPOSITORY)),
        )

    def test_exact_artifact_available_is_classified_and_planned_exact_first(self):
        youtube_zip = _zip(YOUTUBE, "7.4.4+unofficial.2")
        youtube_meta = self.artifacts.import_zip(
            youtube_zip, expected_addon_id=YOUTUBE,
            expected_version="7.4.4+unofficial.2", source="fixture",
        )
        manifest = self._manifest(youtube_artifact=youtube_meta)
        summary = summarize_frozen_recoverability(
            manifest, self.artifacts, (self._policy(REPOSITORY),)
        )
        row = next(item for item in summary.addons if item.addon_id == YOUTUBE)
        plan = validate_frozen_install_plan(
            manifest, self.artifacts, (self._policy(REPOSITORY),)
        )
        self.assertEqual("exact_frozen", row.recoverability.value)
        self.assertEqual("7.4.4+unofficial.2", row.captured_version)
        self.assertIn(
            FrozenPlanActionKind.INSTALL_EXACT_ARTIFACT,
            [action.kind for action in plan.actions],
        )
        self.assertEqual("3 / 3", summary.exact_frozen_coverage)

    def test_exact_artifact_installs_captured_version_without_repository_query(self):
        youtube_zip = _zip(YOUTUBE, "7.4.4+unofficial.2")
        youtube_meta = self.artifacts.import_zip(
            youtube_zip, expected_addon_id=YOUTUBE,
            expected_version="7.4.4+unofficial.2", source="fixture",
        )
        result = self._coordinator(
            decider=lambda _prompt: self.fail("exact artifact must not prompt")
        ).install(
            self._manifest(youtube_artifact=youtube_meta),
            manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(REPOSITORY),),
        )
        self.assertEqual("complete", result.outcome)
        self.assertEqual("7.4.4+unofficial.2", self.backend.installed[YOUTUBE].version)
        self.assertEqual([], self.backend.repository_calls)

    def test_missing_exact_without_fallback_policy_is_blocking(self):
        summary = summarize_frozen_recoverability(self._manifest(), self.artifacts)
        row = next(item for item in summary.addons if item.addon_id == YOUTUBE)
        self.assertEqual("blocking_unrecoverable", row.recoverability.value)
        with self.assertRaises(FrozenInstallValidationError):
            validate_frozen_install_plan(self._manifest(), self.artifacts)

    def test_exact_missing_with_trusted_repo_requires_user_resolution(self):
        manifest = self._manifest(repository_id=REPOSITORY)
        policy = self._policy(REPOSITORY)
        summary = summarize_frozen_recoverability(manifest, self.artifacts, (policy,))
        row = next(item for item in summary.addons if item.addon_id == YOUTUBE)
        self.assertEqual("repository_recoverable", row.recoverability.value)
        self.assertTrue(row.repository_known)
        self.assertTrue(row.fallback_eligible)
        result = self._coordinator().install(
            manifest, manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(policy,),
        )
        self.assertEqual("user_resolution_required", result.outcome)
        self.assertEqual("USER_RESOLUTION_REQUIRED", result.code)
        self.assertIsNone(self.install_store.inspect())
        self.assertEqual([], self.backend.install_calls)

    def test_unknown_repository_keeps_fallback_unavailable_but_skip_explicit(self):
        manifest = self._manifest()
        policy = self._policy()
        summary = summarize_frozen_recoverability(manifest, self.artifacts, (policy,))
        row = next(item for item in summary.addons if item.addon_id == YOUTUBE)
        self.assertFalse(row.repository_known)
        self.assertTrue(row.repository_fallback_permitted)
        self.assertFalse(row.fallback_eligible)
        self.assertTrue(row.skip_eligible)
        self.assertEqual("manual_or_skip", row.recoverability.value)
        self.assertEqual(
            "ask to skip; manual installation may be needed later",
            row.likely_installation_behavior,
        )

    def test_skip_is_not_inferred_from_optional_edge_when_policy_is_exact_only(self):
        summary = summarize_frozen_recoverability(self._manifest(), self.artifacts)
        row = next(item for item in summary.addons if item.addon_id == YOUTUBE)
        self.assertFalse(row.skip_eligible)
        self.assertEqual((), row.dependency_skip_blockers)

    def test_skip_that_breaks_required_dependent_is_rejected(self):
        manifest = self._manifest(required_youtube=True)
        policy = self._policy()
        summary = summarize_frozen_recoverability(manifest, self.artifacts, (policy,))
        row = next(item for item in summary.addons if item.addon_id == YOUTUBE)
        self.assertEqual((UMBRELLA,), row.dependency_skip_blockers)
        self.assertFalse(row.skip_eligible)
        with self.assertRaises(FrozenInstallValidationError):
            validate_frozen_install_plan(
                manifest, self.artifacts, (policy,), skipped=(YOUTUBE,)
            )

    def test_unknown_repository_plan_has_skip_or_cancel_action_only(self):
        plan = validate_frozen_install_plan(
            self._manifest(), self.artifacts, (self._policy(),)
        )
        action = next(item for item in plan.actions if item.addon_id == YOUTUBE)
        self.assertEqual(FrozenPlanActionKind.PROMPT_SKIP_OR_CANCEL, action.kind)

    def test_capture_summary_reports_exact_coverage_and_nonexact_install_recoverability(self):
        result = self._captured_missing_youtube(repository_known=False)
        self.assertFalse(result.complete)
        self.assertEqual("1 / 2", result.exact_frozen_coverage)
        self.assertEqual("complete", result.recoverability.captured_desired_state)
        self.assertEqual("manual_or_skip_action_required", result.recoverability.install_recoverability)
        row = next(item for item in result.recoverability.addons if item.addon_id == YOUTUBE)
        self.assertFalse(row.exact_artifact_available)
        self.assertFalse(row.repository_known)
        self.assertTrue(row.skip_eligible)
        self.assertTrue(row.manual_action_possible)
        summary = result.to_dict()
        self.assertEqual("1 / 2", summary["exact_frozen_coverage"])
        self.assertEqual("complete", summary["captured_desired_state"])
        youtube = next(
            item for item in summary["recoverability"]["addons"]
            if item["addon_id"] == YOUTUBE
        )
        self.assertEqual("unavailable", youtube["exact_artifact"])
        self.assertIsNone(youtube["repository_id"])

    def test_capture_summary_reports_repository_recoverability_only_for_captured_repo(self):
        result = self._captured_missing_youtube(repository_known=True)
        row = next(item for item in result.recoverability.addons if item.addon_id == YOUTUBE)
        self.assertEqual("repository_recoverable", row.recoverability.value)
        self.assertEqual(REPOSITORY, row.repository_id)
        self.assertTrue(row.fallback_eligible)

    def test_absent_optional_dependency_is_excluded_from_exact_coverage(self):
        result = self._captured_missing_youtube(repository_known=False)
        self.assertNotIn(PYSOCKS, [item.addon_id for item in result.recoverability.addons])
        self.assertEqual("1 / 2", result.exact_frozen_coverage)

    def test_required_missing_dependency_blocks_without_counting_as_source_installed(self):
        missing_id = "script.module.required.missing"
        manifest = self._manifest()
        umbrella = next(node for node in manifest.addons if node.addon_id == UMBRELLA)
        missing = AddonCaptureNode(
            missing_id, "", "", False, ProvenanceStatus.UNKNOWN,
            status=CaptureStatus.MISSING,
        )
        manifest = replace(
            manifest,
            capture_status=CaptureStatus.MISSING,
            addons=tuple(
                replace(node, dependency_edges=node.dependency_edges + (
                    DependencyEdge(missing_id, "1.0.0", False, (UMBRELLA,)),
                )) if node.addon_id == umbrella.addon_id else node
                for node in manifest.addons
            ) + (missing,),
        )
        summary = summarize_frozen_recoverability(manifest, self.artifacts)
        row = next(item for item in summary.addons if item.addon_id == missing_id)
        self.assertFalse(row.installed_on_source)
        self.assertEqual("2 / 3", summary.exact_frozen_coverage)
        self.assertEqual("incomplete", summary.captured_desired_state)
        self.assertEqual("blocking_unrecoverable", summary.install_recoverability)
        with self.assertRaises(FrozenInstallValidationError):
            validate_frozen_install_plan(manifest, self.artifacts)

    def test_strict_validator_stays_exact_only_for_missing_artifact(self):
        with self.assertRaises(FrozenInstallValidationError):
            validate_frozen_manifest(self._manifest(), self.artifacts)
        plan = validate_frozen_install_plan(
            self._manifest(), self.artifacts, (self._policy(),)
        )
        self.assertEqual(3, len(plan.install_order))

    def test_unattended_resolution_returns_typed_state_without_mutation(self):
        result = self._coordinator().install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(),), interactive=False,
        )
        self.assertEqual("user_resolution_required", result.outcome)
        self.assertEqual("USER_RESOLUTION_REQUIRED", result.code)
        self.assertEqual([], self.backend.install_calls)
        self.assertIsNone(self.install_store.inspect())

    def test_cancel_build_creates_no_transaction_and_never_reports_success(self):
        result = self._coordinator(decider=lambda _prompt: ResolutionChoice.CANCEL).install(
            self._manifest(), manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(),),
        )
        self.assertEqual("cancelled", result.outcome)
        self.assertFalse(result.succeeded)
        self.assertEqual("BUILD_CANCELLED", result.code)
        self.assertIsNone(self.install_store.inspect())
        self.assertEqual([], self.backend.install_calls)

    def test_skip_completes_only_as_intentionally_skipped_and_stays_absent(self):
        manifest = self._manifest()
        result = self._coordinator(decider=lambda _prompt: ResolutionChoice.SKIP).install(
            manifest, manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(),),
        )
        self.assertEqual("complete", result.outcome)
        self.assertNotIn(YOUTUBE, self.backend.installed)
        record = next(item for item in result.resolution_manifest.records if item.addon_id == YOUTUBE)
        self.assertEqual(InstallResolution.SKIPPED, record.resolution)
        self.assertEqual(ResolutionState.SKIPPED, record.state)
        self.assertNotEqual("installed", record.state.value)
        self.assertEqual(manifest.fingerprint(), result.resolution_manifest.source_software_fingerprint)
        self.assertEqual("7.4.4+unofficial.2", next(
            node.version for node in manifest.addons if node.addon_id == YOUTUBE
        ))
        self.assertEqual(2, len([node for node in result.resolution_manifest.records if node.addon_id != YOUTUBE]))

    def test_family_room_fixture_skip_keeps_optional_pysocks_absent(self):
        manifest = self._manifest()
        configuration_requests = []

        def configure(request):
            configuration_requests.append(request)
            return SimpleNamespace(outcome="complete", success=True)

        result = self._coordinator(
            decider=lambda _prompt: ResolutionChoice.SKIP,
            configure=configure,
        ).install(
            manifest,
            manifest_path="/fixture.json",
            configuration_manifest_path="resources/builds/examples/eric-main.example.json",
            device_profile_id="family-room",
        )
        self.assertEqual("complete", result.outcome)
        self.assertNotIn(YOUTUBE, self.backend.installed)
        self.assertNotIn(PYSOCKS, self.backend.installed)
        self.assertNotIn(PYSOCKS, [record.addon_id for record in result.resolution_manifest.records])
        self.assertEqual(1, len(configuration_requests))
        resolved_youtube = next(
            record for record in configuration_requests[0].install_resolutions
            if record.addon_id == YOUTUBE
        )
        self.assertEqual(InstallResolution.SKIPPED, resolved_youtube.resolution)
        self.assertEqual(ResolutionState.SKIPPED, resolved_youtube.state)

    def test_repository_fallback_imports_and_records_resolved_package_without_rewriting_source(self):
        manifest = self._manifest(repository_id=REPOSITORY)
        original_fingerprint = manifest.fingerprint()
        repository_zip = _zip(YOUTUBE, "8.2.1")
        self.backend.repository_packages[(REPOSITORY, YOUTUBE)] = ("8.2.1", repository_zip)
        configuration_requests = []

        def configure(request):
            configuration_requests.append(request)
            return SimpleNamespace(outcome="complete", success=True)

        result = self._coordinator(
            decider=lambda _prompt: ResolutionChoice.INSTALL_CURRENT,
            configure=configure,
        ).install(
            manifest, manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(REPOSITORY),),
        )
        self.assertEqual("complete", result.outcome)
        record = next(item for item in result.resolution_manifest.records if item.addon_id == YOUTUBE)
        self.assertEqual(InstallResolution.REPOSITORY_CURRENT, record.resolution)
        self.assertEqual("7.4.4+unofficial.2", record.captured_version)
        self.assertEqual("8.2.1", record.resolved_version)
        self.assertEqual(REPOSITORY, record.repository_id)
        self.assertEqual(len(repository_zip), record.artifact_size)
        self.assertEqual(self.artifacts.import_zip(
            repository_zip, expected_addon_id=YOUTUBE, expected_version="8.2.1",
            source=f"repository:{REPOSITORY}",
        ).sha256, record.artifact_sha256)
        metadata = self.artifacts.get_metadata(record.artifact_sha256)
        self.assertEqual(YOUTUBE, metadata.addon_id)
        self.assertEqual("8.2.1", metadata.version)
        self.assertEqual(original_fingerprint, manifest.fingerprint())
        self.assertEqual(original_fingerprint, result.resolution_manifest.source_software_fingerprint)
        self.assertIsNone(self.install_store.inspect())
        self.assertEqual(64, len(result.resolution_manifest.resolution_fingerprint))
        resolved_request = next(
            item for item in configuration_requests[0].install_resolutions
            if item.addon_id == YOUTUBE
        )
        self.assertEqual(InstallResolution.REPOSITORY_CURRENT, resolved_request.resolution)
        self.assertEqual("8.2.1", resolved_request.resolved_version)

    def test_repository_current_resolution_uses_only_selected_repository(self):
        manifest = self._manifest(repository_id=REPOSITORY)
        other_repo = "repository.other"
        self.backend.repository_packages[(other_repo, YOUTUBE)] = ("99.0.0", _zip(YOUTUBE, "99.0.0"))
        result = self._coordinator(decider=lambda _prompt: ResolutionChoice.INSTALL_CURRENT).install(
            manifest, manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(REPOSITORY),),
        )
        self.assertNotEqual("complete", result.outcome)
        self.assertEqual([(YOUTUBE, REPOSITORY)], self.backend.repository_calls)
        self.assertNotIn(YOUTUBE, self.backend.installed)

    def test_resolution_and_resulting_state_fingerprints_are_separate_and_deterministic(self):
        manifest = self._manifest(repository_id=REPOSITORY)
        package = _zip(YOUTUBE, "8.2.1")
        imported = self.artifacts.import_zip(
            package, expected_addon_id=YOUTUBE, expected_version="8.2.1", source="fixture"
        )
        repo_record = InstallResolutionRecord(
            YOUTUBE, "7.4.4+unofficial.2", InstallResolution.REPOSITORY_CURRENT,
            ResolutionState.INSTALLED, repository_id=REPOSITORY,
            resolved_version="8.2.1", artifact_sha256=imported.sha256,
            artifact_size=imported.size,
        )
        skipped_record = InstallResolutionRecord(
            YOUTUBE, "7.4.4+unofficial.2", InstallResolution.SKIPPED,
            ResolutionState.SKIPPED,
        )
        exact_records = (
            next(
                InstallResolutionRecord(
                    node.addon_id, node.version, InstallResolution.EXACT,
                    ResolutionState.INSTALLED, desired_enabled=node.desired_enabled,
                    resolved_version=node.version, artifact_sha256=node.artifact.sha256,
                    artifact_size=node.artifact.size,
                )
                for node in manifest.addons if node.addon_id == REPOSITORY
            ),
            next(
                InstallResolutionRecord(
                    node.addon_id, node.version, InstallResolution.EXACT,
                    ResolutionState.INSTALLED, desired_enabled=node.desired_enabled,
                    resolved_version=node.version, artifact_sha256=node.artifact.sha256,
                    artifact_size=node.artifact.size,
                )
                for node in manifest.addons if node.addon_id == UMBRELLA
            ),
        )
        fallback_records = exact_records + (repo_record,)
        skip_records = exact_records + (skipped_record,)
        self.assertEqual(
            resolution_fingerprint(fallback_records),
            resolution_fingerprint(tuple(reversed(fallback_records))),
        )
        self.assertNotEqual(
            resolution_fingerprint(fallback_records), resolution_fingerprint(skip_records)
        )
        source_fingerprint = manifest.fingerprint()
        fallback_state = resolved_software_fingerprint(manifest, fallback_records)
        skipped_state = resolved_software_fingerprint(manifest, skip_records)
        self.assertNotEqual(source_fingerprint, fallback_state)
        self.assertNotEqual(fallback_state, skipped_state)
        self.assertNotEqual(
            fallback_state,
            resolved_software_fingerprint(
                manifest,
                tuple(replace(item, resolved_version="9.0.0") if item.addon_id == YOUTUBE else item
                      for item in fallback_records),
            ),
        )
        self.assertNotEqual(
            install_plan_fingerprint(manifest, (self._policy(REPOSITORY),)),
            install_plan_fingerprint(manifest, (self._policy(REPOSITORY, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY),)),
        )

    def test_resolution_choice_and_record_round_trip_are_safe(self):
        manifest = self._manifest(repository_id=REPOSITORY)
        self.backend.repository_packages[(REPOSITORY, YOUTUBE)] = ("8.2.1", _zip(YOUTUBE, "8.2.1"))
        result = self._coordinator(decider=lambda _prompt: ResolutionChoice.INSTALL_CURRENT).install(
            manifest, manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(REPOSITORY),),
        )
        loaded = self.install_store.load_resolution_manifest(
            result.resolution_manifest.resolution_fingerprint
        )
        self.assertEqual(result.resolution_manifest.to_dict(), loaded.to_dict())
        encoded = str(result.resolution_manifest.to_dict())
        self.assertNotIn("zip_bytes", encoded)
        self.assertNotIn("token", encoded.lower())

    def test_fallback_choice_survives_restart_without_duplicate_prompt(self):
        manifest = self._manifest(repository_id=REPOSITORY)
        self.backend.repository_packages[(REPOSITORY, YOUTUBE)] = ("8.2.1", _zip(YOUTUBE, "8.2.1"))
        prompts = []
        restart = SimpleNamespace(
            outcome="manual_restart_required",
            transaction=SimpleNamespace(transaction_id="33333333-3333-4333-8333-333333333333"),
        )
        initial = self._coordinator(
            decider=lambda prompt: prompts.append(prompt) or ResolutionChoice.INSTALL_CURRENT,
            configure=lambda _request: restart,
        ).install(
            manifest, manifest_path="/fixture.json", device_profile_id="family-room",
            install_policies=(self._policy(REPOSITORY),),
        )
        self.assertEqual("awaiting_restart", initial.outcome)
        self.assertEqual(1, len(prompts))
        stored = self.install_store.inspect()
        self.assertEqual(FrozenInstallPhase.AWAITING_RESTART, stored.phase)
        self.assertEqual("8.2.1", next(
            item.resolved_version for item in stored.resolution_records if item.addon_id == YOUTUBE
        ))
        resumed = FrozenInstallCoordinator(
            store=self.install_store,
            artifact_store=self.artifacts,
            policy_backend=self.policy,
            installer=self.backend,
            manifest_loader=lambda _path: manifest,
            session_id_provider=lambda: SESSION_B,
            resolution_decider=lambda _prompt: self.fail("restart must not prompt again"),
        ).resume_after_restart()
        self.assertEqual("complete", resumed.outcome)
        self.assertEqual(1, len(prompts))
        self.assertEqual("8.2.1", self.backend.installed[YOUTUBE].version)

    def test_private_overlay_compatibility_uses_declared_owners_and_all_resources(self):
        declarations = (SimpleNamespace(addon_id="plugin.video.redlight"),)
        resources = (
            SimpleNamespace(owner_addon_id="plugin.video.redlight", supported_versions=("2.6.8",)),
            SimpleNamespace(owner_addon_id="plugin.video.redlight", supported_versions=("2.6.8", "2.7.0")),
        )
        self.assertTrue(validate_private_overlay_resolution_compatibility(
            {YOUTUBE: "8.2.1"}, declarations, resources
        ))
        with self.assertRaises(PrivateOverlayValidationError):
            validate_private_overlay_resolution_compatibility(
                {"plugin.video.redlight": "2.7.0"}, declarations, resources
            )

    def test_family_room_youtube_policy_is_device_scoped(self):
        manifest = load_manifest_file("resources/builds/examples/eric-main.example.json")
        family = __import__("resources.lib.resolver", fromlist=["resolve_manifest"]).resolve_manifest(
            manifest, "family-room"
        )
        other = __import__("resources.lib.resolver", fromlist=["resolve_manifest"]).resolve_manifest(
            manifest, "bonus-room"
        )
        youtube_policy = next(item for item in family.frozen_install_policies if item.addon_id == YOUTUBE)
        self.assertEqual(
            FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP,
            youtube_policy.mode,
        )
        self.assertEqual("", youtube_policy.repository_id)
        self.assertNotIn(YOUTUBE, [item.addon_id for item in other.frozen_install_policies])

    def test_policy_parser_rejects_repository_on_exact_only_policy(self):
        document = json.loads(Path("resources/builds/examples/eric-main.example.json").read_text())
        policy = document["device_profiles"]["family-room"]["frozen_install_policies"][0]
        policy["policy"] = FrozenInstallPolicyMode.EXACT_REQUIRED.value
        policy["repository_id"] = REPOSITORY
        with self.assertRaises(ManifestValidationError):
            load_manifest_json(json.dumps(document))

    def test_declared_repository_must_be_captured_exact_and_enabled(self):
        unknown = self._policy("repository.uncaptured")
        unknown_row = next(
            item for item in summarize_frozen_recoverability(
                self._manifest(), self.artifacts, (unknown,)
            ).addons if item.addon_id == YOUTUBE
        )
        self.assertFalse(unknown_row.repository_known)
        self.assertFalse(unknown_row.fallback_eligible)

        manifest = self._manifest()
        manifest = replace(
            manifest,
            addons=tuple(
                replace(node, desired_enabled=False)
                if node.addon_id == REPOSITORY else node
                for node in manifest.addons
            ),
        )
        disabled_row = next(
            item for item in summarize_frozen_recoverability(
                manifest, self.artifacts, (self._policy(REPOSITORY),)
            ).addons if item.addon_id == YOUTUBE
        )
        self.assertFalse(disabled_row.repository_known)
        self.assertFalse(disabled_row.fallback_eligible)

    def test_missing_artifact_store_object_is_recoverable_but_not_exact(self):
        package = _zip(YOUTUBE, "7.4.4+unofficial.2")
        metadata = self.artifacts.import_zip(
            package, expected_addon_id=YOUTUBE,
            expected_version="7.4.4+unofficial.2", source="fixture",
        )
        manifest = self._manifest(youtube_artifact=metadata)
        self.artifacts.artifact_path(metadata.sha256).unlink()
        policy = self._policy(REPOSITORY)
        row = next(
            item for item in summarize_frozen_recoverability(
                manifest, self.artifacts, (policy,)
            ).addons if item.addon_id == YOUTUBE
        )
        self.assertFalse(row.exact_artifact_available)
        self.assertEqual("repository_recoverable", row.recoverability.value)
        self.assertTrue(row.fallback_eligible)
        with self.assertRaises(FrozenInstallValidationError):
            validate_frozen_manifest(manifest, self.artifacts)
        validate_frozen_install_plan(manifest, self.artifacts, (policy,))

    def test_installed_youtube_missing_exact_reports_manual_path_not_fake_exact_coverage(self):
        summary = summarize_frozen_recoverability(
            self._manifest(), self.artifacts, (self._policy(),)
        )
        row = next(item for item in summary.addons if item.addon_id == YOUTUBE)
        output = row.to_dict()
        self.assertFalse(row.exact_artifact_available)
        self.assertEqual("unavailable", output["exact_artifact"])
        self.assertFalse(output["repository_known"])
        self.assertFalse(output["fallback_eligible"])
        self.assertTrue(output["skip_eligible"])
        self.assertTrue(output["manual_action_possible"])

    def _captured_missing_youtube(self, *, repository_known):
        addons = [
            {"addonid": YOUTUBE, "version": "7.4.4+unofficial.2", "enabled": True,
             "type": "xbmc.python.pluginsource"},
            {"addonid": UMBRELLA, "version": "5.0.0", "enabled": True,
             "type": "xbmc.python.pluginsource"},
        ]
        xml = {
            YOUTUBE: b'<addon id="plugin.video.youtube" version="7.4.4+unofficial.2" name="YouTube" />',
            UMBRELLA: (
                f'<addon id="{UMBRELLA}" version="5.0.0" name="Umbrella">'
                f'<requires><import addon="{YOUTUBE}" optional="true"/>'
                f'<import addon="{PYSOCKS}" optional="true"/></requires></addon>'
            ).encode(),
        }
        cache = {
            (UMBRELLA, "5.0.0"): [("umbrella.zip", self.umbrella_zip)],
        }
        roots = [YOUTUBE, UMBRELLA]
        policies = (self._policy(REPOSITORY),) if repository_known else (self._policy(),)
        if repository_known:
            addons.append({"addonid": REPOSITORY, "version": "1.0.0", "enabled": True,
                           "type": "xbmc.addon.repository"})
            xml[REPOSITORY] = (
                f'<addon id="{REPOSITORY}" version="1.0.0" name="Fixture repository">'
                '<extension point="xbmc.addon.repository"><dir>'
                '<info>http://127.0.0.1/addons.xml</info>'
                '<datadir zip="true">http://127.0.0.1/</datadir>'
                '</dir></extension></addon>'
            ).encode()
            cache[(REPOSITORY, "1.0.0")] = [("repository.zip", self.repo_zip)]
            roots.append(REPOSITORY)
        return capture_frozen_build(
            backend=InMemoryInventoryBackend(addons, xml, package_cache=cache),
            store=self.artifacts,
            root_addon_ids=roots,
            build_id="capture-fixture",
            name="Sanitized capture fixture",
            created_at="2026-09-22T00:00:00Z",
            install_policies=policies,
        )


class ResolutionDialogTest(unittest.TestCase):
    def _select(self, prompt, selected=0):
        observations = {}

        class Dialog:
            def select(self, heading, labels):
                observations["heading"] = heading
                observations["labels"] = list(labels)
                return selected

        with patch.dict("sys.modules", {"xbmcgui": SimpleNamespace(Dialog=Dialog)}):
            from resources.lib.frozen_install import _kodi_resolution_choice
            choice = _kodi_resolution_choice(prompt)
        return choice, observations

    def test_known_repository_offers_install_skip_and_cancel_with_version_warning(self):
        choice, seen = self._select(ResolutionPrompt(YOUTUBE, "7.4.4+unofficial.2", REPOSITORY, True))
        self.assertEqual(ResolutionChoice.INSTALL_CURRENT, choice)
        self.assertEqual(["Install Current Version", "Skip", "Cancel Build"], seen["labels"])
        self.assertIn("may differ from the captured source", seen["heading"])
        self.assertIn("7.4.4+unofficial.2", seen["heading"])

    def test_known_repository_without_skip_policy_does_not_offer_skip(self):
        _choice, seen = self._select(ResolutionPrompt(YOUTUBE, "1.0.0", REPOSITORY, False))
        self.assertEqual(["Install Current Version", "Cancel Build"], seen["labels"])

    def test_unknown_repository_offers_skip_and_cancel_but_not_install(self):
        choice, seen = self._select(ResolutionPrompt(YOUTUBE, "7.4.4+unofficial.2", "", True))
        self.assertEqual(ResolutionChoice.SKIP, choice)
        self.assertEqual(["Skip", "Cancel Build"], seen["labels"])
        self.assertNotIn("Install Current Version", seen["labels"])
        self.assertIn("manual", seen["heading"])

    def test_unknown_repository_without_skip_policy_fails_closed_without_dialog(self):
        choice, _seen = self._select(ResolutionPrompt(YOUTUBE, "1.0.0", "", False))
        self.assertIsNone(choice)


if __name__ == "__main__":
    unittest.main()
