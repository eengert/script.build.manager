import unittest
from types import SimpleNamespace

from resources.lib.build_manager import ReconcileRequest
from resources.lib.frozen_install import (
    FrozenInstallPhase,
    FrozenLifecycleStage,
    FrozenResumeRegistryReadiness,
    ensure_frozen_transaction_registry_ready,
    ensure_frozen_resume_registry_ready,
)
from resources.lib.frozen_resolution import ResolutionState
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
    def __init__(self, transaction, events):
        self.transaction = transaction
        self.events = events

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
    def __init__(self, events):
        self.events = events

    def __call__(self, **_kwargs):
        events = self.events

        class Coordinator:
            def _restore_resolution(self, manifest, transaction):
                events.append("validate_manifest_plan_resolution")
                return (
                    SimpleNamespace(),
                    (SimpleNamespace(
                        addon_id=HELD,
                        state=ResolutionState.INSTALLED,
                        resolved_version=VERSION,
                    ),),
                    None,
                )

            def _configuration_profile(self, path, profile_id):
                events.append("load_configuration_identity")
                self.asserted_profile = (path, profile_id)
                return SimpleNamespace()

            def _activation_hold_ids(self, _plan, _profile):
                events.append("validate_activation_hold_graph")
                return (HELD,)

            def _registry_readiness_ids(self, _profile):
                events.append("identify_registry_readiness_owners")
                return (HELD,)

            def _private_overlay_metadata(self, _profile, source_fingerprint):
                events.append("validate_private_overlay_identity")
                if source_fingerprint != MANIFEST_FP:
                    raise AssertionError("source fingerprint drift")
                return "overlay", OVERLAY_FP, True

        return Coordinator()


class FrozenRegistryReadinessTest(unittest.TestCase):
    def _inputs(self, events, *, policy_value=AddonUpdatePolicy.NEVER_CHECK,
                register=True, enabled=False, version=VERSION):
        request = ReconcileRequest(
            "/configuration.json",
            "disposable",
            source_software_fingerprint=MANIFEST_FP,
        )
        overlay = SimpleNamespace(
            overlay_id="overlay",
            fingerprint=OVERLAY_FP,
            required=True,
        )
        preview = SimpleNamespace(
            request=request,
            success=True,
            private_overlay=overlay,
        )
        bm020 = SimpleNamespace(request=request)
        transaction = SimpleNamespace(
            phase=FrozenInstallPhase.AWAITING_RESTART,
            lifecycle_stage=FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            activation_hold_ids=(HELD,),
            activation_hold_released=False,
            updater_guard_required=True,
            originating_kodi_session_id=SESSION_A,
            configuration_manifest_path="/configuration.json",
            device_profile_id="disposable",
            manifest_path="/frozen.json",
            manifest_fingerprint=MANIFEST_FP,
            private_overlay_id="overlay",
            private_overlay_fingerprint=OVERLAY_FP,
            private_overlay_required=True,
        )
        store = _Store(transaction, events)
        registry = _Registry(
            events, register=register, enabled=enabled, version=version,
        )
        policy = _Policy(events, policy_value)
        result = ensure_frozen_resume_registry_ready(
            bm020,
            preview,
            SESSION_B,
            store=store,
            artifact_store=object(),
            policy_backend=policy,
            registry_backend=registry,
            manifest_loader=lambda _path: _Manifest(),
            coordinator_factory=_CoordinatorFactory(events),
            timeout=1.0,
            poll_interval=0.25,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )
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
        request = ReconcileRequest(
            "/configuration.json", "disposable",
            source_software_fingerprint=MANIFEST_FP,
        )
        preview = SimpleNamespace(
            request=request,
            success=True,
            private_overlay=SimpleNamespace(
                overlay_id="different", fingerprint=OVERLAY_FP, required=True,
            ),
        )
        tx = SimpleNamespace(
            phase=FrozenInstallPhase.AWAITING_RESTART,
            lifecycle_stage=FrozenLifecycleStage.QUIESCENCE_AWAITING_RESTART,
            activation_hold_ids=(HELD,), activation_hold_released=False,
            updater_guard_required=True,
            originating_kodi_session_id=SESSION_A,
            configuration_manifest_path="/configuration.json",
            device_profile_id="disposable", manifest_path="/frozen.json",
            manifest_fingerprint=MANIFEST_FP,
            private_overlay_id="overlay", private_overlay_fingerprint=OVERLAY_FP,
            private_overlay_required=True,
        )
        registry = _Registry(events, register=False)
        result = ensure_frozen_resume_registry_ready(
            SimpleNamespace(request=request), preview, SESSION_B,
            store=_Store(tx, events), artifact_store=object(),
            policy_backend=_Policy(events), registry_backend=registry,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "FROZEN_PRIVATE_OVERLAY_IDENTITY_MISMATCH")
        self.assertEqual(registry.refresh_calls, 0)

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

        store = _Store(transaction, events)

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
