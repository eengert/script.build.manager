import unittest
import json
from dataclasses import replace
import tempfile
from pathlib import Path
from types import SimpleNamespace

from resources.lib.build_manager import ReconcileRequest
from resources.lib.frozen_install import (
    FrozenInstallCoordinator, FrozenInstallStore, FrozenInstallTransaction, FrozenInstalledAddon,
    FrozenInstallPhase,
    FrozenLifecycleStage,
    FrozenResumeRegistryReadiness,
    ensure_frozen_transaction_registry_ready,
    ensure_frozen_resume_registry_ready,
)
from resources.lib.frozen_resolution import (ResolutionState, default_exact_record,
    install_plan_fingerprint, resolution_fingerprint, resolved_software_fingerprint)
from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import (AddonCaptureNode, FrozenBuildManifest, CaptureStatus,
    DependencyEdge, ProvenanceStatus)
from resources.lib.redlight_resource import redlight_declaration
from tests.builtin_evidence import SyntheticBuiltinBackend, core_node
from tests.test_frozen_install import _zip
from resources.lib.update_guard import AddonUpdatePolicy


HELD = "plugin.video.held"
VERSION = "2.6.8"
MANIFEST_FP = "a" * 64
OVERLAY_FP = "sha256:" + "b" * 64
SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"


class _Manifest:
    def fingerprint(self):
        return MANIFEST_FP


class _Store:
    def __init__(self, transaction, events, root):
        self.transaction = transaction
        self.events = events
        self.root = root

    def inspect(self):
        self.events.append("reload_frozen_transaction")
        return self.transaction


class _Policy:
    def __init__(self, events, value=AddonUpdatePolicy.NEVER_CHECK):
        self.events = events
        self.value = value

    def get_policy(self):
        self.events.append("verify_updater_guard")
        return self.value


class _Registry:
    def __init__(self, events, *, register=True, enabled=False, version=VERSION):
        self.events = events
        self.register = register
        self.enabled = enabled
        self.version = version
        self.refresh_calls = 0

    def get_addon_details(self, addon_id):
        self.events.append("query_registry")
        if not self.register:
            return None
        return SimpleNamespace(
            addon_id=addon_id,
            version=self.version,
            enabled=self.enabled,
        )

    def refresh_local_addons(self):
        self.events.append("refresh_local_addons")
        self.refresh_calls += 1
        self.register = True


class _CoordinatorFactory:
    """Observe real admission; inject only synthetic target/platform evidence."""
    def __init__(self, events, backend):
        self.events = events
        self.backend = backend

    def __call__(self, **kwargs):
        events = self.events
        kwargs['installer'] = self.backend
        kwargs['private_overlay_metadata_provider'] = lambda profile, fp: ('overlay', OVERLAY_FP, True)

        class Coordinator(FrozenInstallCoordinator):
            def _restore_resolution(self, manifest, transaction, **options):
                result = super()._restore_resolution(manifest, transaction, **options)
                events.append('validate_manifest_plan_resolution')
                return result

            def _configuration_profile(self, path, profile_id):
                events.append('load_configuration_identity')
                return super()._configuration_profile(path, profile_id)

            def _activation_hold_ids(self, plan, profile):
                result = super()._activation_hold_ids(plan, profile)
                events.append('validate_activation_hold_graph')
                return result

            def _registry_readiness_ids(self, profile):
                events.append('identify_registry_readiness_owners')
                return super()._registry_readiness_ids(profile)

            def _private_overlay_metadata(self, profile, source_fingerprint):
                events.append('validate_private_overlay_identity')
                return super()._private_overlay_metadata(profile, source_fingerprint)

        return Coordinator(**kwargs)


class FrozenRegistryReadinessTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _inputs(self, events, *, policy_value=AddonUpdatePolicy.NEVER_CHECK,
                register=True, enabled=False, version=VERSION, overlay_id='overlay', source_fault=None):
        temporary = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        artifacts = ArtifactStore(root / 'artifacts')
        metadata = artifacts.import_zip(_zip(HELD, VERSION, requires=(('xbmc.gui', '5.17.0'),)),
            expected_addon_id=HELD, expected_version=VERSION)
        owner = AddonCaptureNode(HELD, VERSION, 'xbmc.python.pluginsource', True,
            ProvenanceStatus.UNKNOWN, artifact=metadata,
            dependency_edges=(DependencyEdge('xbmc.gui', '5.17.0'),))
        gui = AddonCaptureNode('xbmc.gui', '5.17.0', 'system', True,
            ProvenanceStatus.UNKNOWN, system=True, status=CaptureStatus.SYSTEM,
            dependency_edges=(DependencyEdge('xbmc.core', '0.1.0'),))
        manifest = FrozenBuildManifest(1, 'registry-fixture', 'Registry', '2026-10-20T00:00:00Z',
            '21.3', 'macos', CaptureStatus.COMPLETE, (owner, gui, core_node()))
        frozen_path = root / 'frozen.json'
        frozen_path.write_text(manifest.to_json())
        configuration_path = root / 'configuration.json'
        declaration = replace(redlight_declaration(), owner_addon_id=HELD, supported_versions=(VERSION,))
        configuration_path.write_text(json.dumps({
            'schema_version': 1, 'build': {'id': manifest.build_id, 'version': '1.0.0'},
            'platform_profiles': {'macos': {}}, 'device_profiles': {'disposable': {'extends': 'macos'}},
            'private_overlay': {'type': 'local_file', 'overlay_id': 'overlay', 'required': True},
            'config': {'structured_private_resources': [declaration.safe_dict()]}}))
        records = (replace(default_exact_record(owner), state=ResolutionState.INSTALLED),)
        transaction = FrozenInstallTransaction(
            transaction_id='33333333-3333-4333-8333-333333333333', build_id=manifest.build_id,
            manifest_path=str(frozen_path), device_profile_id='disposable',
            manifest_fingerprint=manifest.fingerprint(), phase=FrozenInstallPhase.AWAITING_RESTART,
            originating_kodi_session_id=SESSION_A, original_update_policy=AddonUpdatePolicy.AUTOMATIC,
            updater_guard_required=True, created_at='2026-10-20T00:00:00Z', updated_at='2026-10-20T00:00:00Z',
            configuration_manifest_path=str(configuration_path),
            lifecycle_stage=FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            activation_hold_ids=(HELD,), activation_hold_released=False,
            private_overlay_id='overlay', private_overlay_fingerprint=OVERLAY_FP, private_overlay_required=True,
            install_plan_fingerprint=install_plan_fingerprint(manifest, ()), resolution_records=records,
            resolution_fingerprint=resolution_fingerprint(records),
            resolved_software_fingerprint=resolved_software_fingerprint(manifest, records))

        class Store(FrozenInstallStore):
            def inspect(self):
                events.append('reload_frozen_transaction')
                return super().inspect()
        store = Store(root / 'state')
        store.create(transaction)
        installed = {HELD: FrozenInstalledAddon(HELD, version, enabled)} if register else {}
        backend = SyntheticBuiltinBackend(installed=installed)
        backend.builtin_state['xbmc.gui'] = FrozenInstalledAddon('xbmc.gui', '5.17.0', True)
        backend.builtin_abis['xbmc.gui'] = '5.17.0'
        reader = backend.read_verified_builtin_metadata
        def read_builtin(edge):
            events.append('verify_builtin:' + edge.addon_id)
            return reader(edge)
        backend.read_verified_builtin_metadata = read_builtin
        if source_fault == 'manifest-missing':
            frozen_path.unlink()
        elif source_fault == 'zip-missing':
            artifacts.artifact_path(metadata.sha256).unlink()
        elif source_fault == 'zip-corrupt':
            artifacts.artifact_path(metadata.sha256).write_bytes(b'corrupt')
        elif source_fault == 'builtin-missing':
            backend.builtin_state.pop('xbmc.gui')
        request = ReconcileRequest(str(configuration_path), 'disposable',
            source_software_fingerprint=manifest.fingerprint(), frozen_transaction_id=transaction.transaction_id)
        preview = SimpleNamespace(request=request, success=True, private_overlay=SimpleNamespace(
            overlay_id=overlay_id, fingerprint=OVERLAY_FP, required=True))
        registry = _Registry(events, register=register, enabled=enabled, version=version)
        before = store.transaction_path.read_bytes()
        result = ensure_frozen_resume_registry_ready(
            SimpleNamespace(request=request), preview, SESSION_B,
            store=store, artifact_store=artifacts, policy_backend=_Policy(events, policy_value),
            registry_backend=registry, coordinator_factory=_CoordinatorFactory(events, backend),
            timeout=1.0, poll_interval=0.25, monotonic=lambda: 0.0, sleeper=lambda seconds: None)
        self.assertEqual(before, store.transaction_path.read_bytes())
        self.assertEqual([], backend.install_calls)
        self.assertEqual([], backend.enable_calls)
        return result, registry

    def test_guard_and_identity_validation_precede_one_registry_refresh(self):
        events = []
        result, registry = self._inputs(events, register=False)
        self.assertTrue(result.allowed)
        self.assertEqual(registry.refresh_calls, 1)
        self.assertLess(events.index("verify_updater_guard"), events.index("refresh_local_addons"))
        self.assertLess(events.index("validate_manifest_plan_resolution"), events.index("refresh_local_addons"))
        self.assertLess(events.index("validate_activation_hold_graph"), events.index("refresh_local_addons"))
        self.assertLess(events.index("identify_registry_readiness_owners"), events.index("refresh_local_addons"))
        self.assertLess(events.index("reload_frozen_transaction"), events.index("refresh_local_addons"))
        self.assertLess(events.index('verify_builtin:xbmc.gui'), events.index('query_registry'))
        self.assertLess(events.index('verify_builtin:xbmc.core'), events.index('refresh_local_addons'))
        self.assertEqual(result.registry_result.items[0].expected_version, VERSION)

    def test_registered_exact_disabled_held_addon_skips_refresh(self):
        events = []
        result, registry = self._inputs(events)
        self.assertTrue(result.allowed)
        self.assertEqual(registry.refresh_calls, 0)

    def test_wrong_version_blocks_before_configuration(self):
        events = []
        result, registry = self._inputs(events, version="2.6.7")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "FROZEN_ADDON_REGISTRY_WRONG_VERSION")
        self.assertEqual(registry.refresh_calls, 0)

    def test_enabled_held_addon_blocks_without_changing_hold(self):
        events = []
        result, registry = self._inputs(events, enabled=True)
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "FROZEN_ADDON_REGISTRY_UNEXPECTEDLY_ENABLED")
        self.assertEqual(registry.refresh_calls, 0)

    def test_inactive_updater_guard_blocks_before_refresh(self):
        events = []
        result, registry = self._inputs(
            events, policy_value=AddonUpdatePolicy.AUTOMATIC, register=False,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "FROZEN_UPDATER_NOT_QUARANTINED")
        self.assertEqual(registry.refresh_calls, 0)

    def test_changed_overlay_identity_blocks_before_refresh(self):
        events = []
        result, registry = self._inputs(events, register=False, overlay_id='different')
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "FROZEN_PRIVATE_OVERLAY_IDENTITY_MISMATCH")
        self.assertEqual(registry.refresh_calls, 0)
        self.assertNotIn('query_registry', events)

    def test_missing_or_invalid_source_blocks_before_registry_mutation(self):
        for fault in ('manifest-missing', 'zip-missing', 'zip-corrupt', 'builtin-missing'):
            with self.subTest(fault=fault):
                events = []
                result, registry = self._inputs(events, register=False, source_fault=fault)
                self.assertFalse(result.allowed)
                self.assertEqual('FROZEN_RESUME_IDENTITY_INVALID', result.code)
                self.assertEqual(0, registry.refresh_calls)
                self.assertNotIn('query_registry', events)

    def test_full_activation_hold_is_rechecked_during_registry_refresh(self):
        events = []
        dependent = "plugin.video.held.dependent"
        transaction = SimpleNamespace(
            transaction_id="33333333-3333-4333-8333-333333333333",
            phase=FrozenInstallPhase.AWAITING_RESTART,
            lifecycle_stage=FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            activation_hold_ids=(HELD, dependent),
            activation_hold_released=False,
            updater_guard_required=True,
            originating_kodi_session_id=SESSION_A,
        )

        store = _Store(transaction, events, self.root)

        class Registry(_Registry):
            def refresh_local_addons(self):
                super().refresh_local_addons()
                replacement = SimpleNamespace(**vars(transaction))
                replacement.activation_hold_ids = (HELD,)
                store.transaction = replacement

        registry = Registry(events, register=False)
        result = ensure_frozen_transaction_registry_ready(
            transaction,
            (HELD, dependent),
            (HELD,),
            (SimpleNamespace(
                addon_id=HELD,
                state=ResolutionState.INSTALLED,
                resolved_version=VERSION,
            ),),
            current_session_id=SESSION_B,
            store=store,
            policy_backend=_Policy(events),
            registry_backend=registry,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(
            result.code,
            "FROZEN_ADDON_REGISTRY_ACTIVATION_HOLD_UNAVAILABLE",
        )
        self.assertEqual(registry.refresh_calls, 1)


if __name__ == "__main__":
    unittest.main()
