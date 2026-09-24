import unittest
import sys
from unittest.mock import MagicMock, patch

from resources.lib.addon_registry import (
    AddonRegistryReadinessCode,
    KodiRuntimeAddonRegistryBackend,
    StagedAddonExpectation,
    ensure_staged_addon_registered_for_configuration,
    ensure_staged_addons_registered_for_configuration,
)
from resources.lib.addon_state import AddonStateInfo


HELD = "plugin.video.held"
VERSION = "2.6.8"


class _Backend:
    def __init__(self, states=None, *, on_refresh=None):
        self.states = dict(states or {})
        self.on_refresh = on_refresh
        self.refresh_calls = 0
        self.queries = []
        self.service_started = False

    def get_addon_details(self, addon_id):
        self.queries.append(addon_id)
        return self.states.get(addon_id)

    def refresh_local_addons(self):
        self.refresh_calls += 1
        if self.on_refresh is not None:
            self.on_refresh(self)


class AddonRegistryReadinessTest(unittest.TestCase):
    def setUp(self):
        self.holds = {HELD}

    def _ready(self, backend, **kwargs):
        return ensure_staged_addon_registered_for_configuration(
            HELD,
            VERSION,
            backend=backend,
            activation_hold_provider=lambda: self.holds,
            **kwargs,
        )

    def test_held_addon_already_registered_needs_no_refresh(self):
        backend = _Backend({HELD: AddonStateInfo(HELD, False, VERSION)})
        result = self._ready(backend)
        self.assertTrue(result.ready)
        self.assertEqual(result.code, AddonRegistryReadinessCode.ALREADY_REGISTERED)
        self.assertFalse(result.refresh_attempted)
        self.assertEqual(backend.refresh_calls, 0)

    def test_missing_held_addon_requests_one_local_refresh(self):
        backend = _Backend(on_refresh=lambda target: target.states.update(
            {HELD: AddonStateInfo(HELD, False, VERSION)}
        ))
        result = self._ready(backend)
        self.assertTrue(result.ready)
        self.assertEqual(result.code, AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH)
        self.assertTrue(result.refresh_attempted)
        self.assertEqual(backend.refresh_calls, 1)

    def test_refresh_registers_exact_version_disabled_and_keeps_hold(self):
        backend = _Backend(on_refresh=lambda target: target.states.update(
            {HELD: AddonStateInfo(HELD, False, VERSION)}
        ))
        result = self._ready(backend)
        self.assertTrue(result.ready)
        self.assertEqual(result.items[0].registered_version, VERSION)
        self.assertIs(result.items[0].enabled, False)
        self.assertEqual(self.holds, {HELD})
        self.assertFalse(backend.service_started)

    def test_refresh_that_does_not_register_addon_fails_closed_after_timeout(self):
        clock = [0.0]
        backend = _Backend()

        def monotonic():
            return clock[0]

        def sleep(seconds):
            clock[0] += seconds

        result = self._ready(
            backend,
            timeout=1.0,
            poll_interval=0.5,
            monotonic=monotonic,
            sleeper=sleep,
        )
        self.assertFalse(result.ready)
        self.assertEqual(
            result.code,
            AddonRegistryReadinessCode.NOT_REGISTERED_AFTER_REFRESH,
        )
        self.assertTrue(result.refresh_attempted)
        self.assertEqual(backend.refresh_calls, 1)
        self.assertEqual(clock[0], 1.0)
        self.assertEqual(result.items[0].poll_count, result.poll_count)

    def test_wrong_version_fails_without_refresh(self):
        backend = _Backend({HELD: AddonStateInfo(HELD, False, "2.6.7")})
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.WRONG_VERSION)
        self.assertFalse(result.ready)
        self.assertEqual(backend.refresh_calls, 0)

    def test_wrong_version_discovered_by_refresh_fails_closed(self):
        backend = _Backend(on_refresh=lambda target: target.states.update(
            {HELD: AddonStateInfo(HELD, False, "2.6.7")}
        ))
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.WRONG_VERSION)
        self.assertTrue(result.refresh_attempted)

    def test_enabled_held_addon_fails_without_refresh(self):
        backend = _Backend({HELD: AddonStateInfo(HELD, True, VERSION)})
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.UNEXPECTEDLY_ENABLED)
        self.assertEqual(backend.refresh_calls, 0)

    def test_addon_enabled_during_refresh_fails_and_hold_remains(self):
        backend = _Backend(on_refresh=lambda target: target.states.update(
            {HELD: AddonStateInfo(HELD, True, VERSION)}
        ))
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.UNEXPECTEDLY_ENABLED)
        self.assertEqual(self.holds, {HELD})

    def test_missing_activation_hold_blocks_before_refresh(self):
        self.holds.clear()
        backend = _Backend()
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING)
        self.assertEqual(backend.refresh_calls, 0)
        self.assertEqual(backend.queries, [])

    def test_hold_loss_during_refresh_blocks_registry_success(self):
        def refresh(target):
            target.states[HELD] = AddonStateInfo(HELD, False, VERSION)
            self.holds.clear()

        backend = _Backend(on_refresh=refresh)
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.ACTIVATION_HOLD_MISSING)
        self.assertEqual(backend.refresh_calls, 1)

    def test_one_refresh_covers_multiple_missing_held_addons(self):
        second = "plugin.video.held2"
        self.holds.add(second)
        backend = _Backend(on_refresh=lambda target: target.states.update({
            HELD: AddonStateInfo(HELD, False, VERSION),
            second: AddonStateInfo(second, False, "1.4.0"),
        }))
        result = ensure_staged_addons_registered_for_configuration(
            (
                StagedAddonExpectation(second, "1.4.0"),
                StagedAddonExpectation(HELD, VERSION),
            ),
            backend=backend,
            activation_hold_provider=lambda: self.holds,
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.code, AddonRegistryReadinessCode.REGISTERED_AFTER_REFRESH)
        self.assertEqual(backend.refresh_calls, 1)
        self.assertEqual([item.addon_id for item in result.items], [HELD, second])

    def test_refresh_rechecks_previously_registered_held_addons(self):
        second = "plugin.video.held2"
        self.holds.add(second)

        def refresh(target):
            target.states[HELD] = AddonStateInfo(HELD, False, VERSION)
            target.states[second] = AddonStateInfo(second, True, "1.4.0")

        backend = _Backend({
            second: AddonStateInfo(second, False, "1.4.0"),
        }, on_refresh=refresh)
        result = ensure_staged_addons_registered_for_configuration(
            (
                StagedAddonExpectation(HELD, VERSION),
                StagedAddonExpectation(second, "1.4.0"),
            ),
            backend=backend,
            activation_hold_provider=lambda: self.holds,
        )
        self.assertEqual(
            result.code, AddonRegistryReadinessCode.UNEXPECTEDLY_ENABLED
        )
        self.assertEqual(backend.refresh_calls, 1)

    def test_no_held_addons_is_noop_for_ordinary_resume(self):
        backend = _Backend()
        result = ensure_staged_addons_registered_for_configuration(
            (), backend=backend, activation_hold_provider=lambda: self.holds,
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.code, AddonRegistryReadinessCode.NO_ADDONS_REQUIRED)
        self.assertEqual(backend.refresh_calls, 0)
        self.assertEqual(backend.queries, [])

    def test_registry_query_failure_does_not_refresh(self):
        class FailedQuery(_Backend):
            def get_addon_details(self, addon_id):
                raise RuntimeError("injected registry error")

        backend = FailedQuery()
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.REGISTRY_QUERY_FAILED)
        self.assertFalse(result.refresh_attempted)

    def test_refresh_failure_is_reported_without_retry(self):
        class FailedRefresh(_Backend):
            def refresh_local_addons(self):
                self.refresh_calls += 1
                raise RuntimeError("injected refresh error")

        backend = FailedRefresh()
        result = self._ready(backend)
        self.assertEqual(result.code, AddonRegistryReadinessCode.REFRESH_FAILED)
        self.assertTrue(result.refresh_attempted)
        self.assertEqual(backend.refresh_calls, 1)

    def test_invalid_expectation_fails_before_backend_access(self):
        backend = _Backend()
        result = ensure_staged_addon_registered_for_configuration(
            "bad/id", VERSION,
            backend=backend,
            activation_hold_provider=lambda: self.holds,
        )
        self.assertEqual(result.code, AddonRegistryReadinessCode.INVALID_EXPECTATION)
        self.assertEqual(backend.queries, [])
        self.assertEqual(backend.refresh_calls, 0)

    def test_production_backend_uses_only_update_local_addons_builtin(self):
        xbmc = MagicMock()
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            KodiRuntimeAddonRegistryBackend().refresh_local_addons()
        xbmc.executebuiltin.assert_called_once_with("UpdateLocalAddons")
        self.assertFalse(hasattr(KodiRuntimeAddonRegistryBackend(), "set_addon_enabled"))

    def test_refresh_logs_registry_state_before_and_after_without_private_values(self):
        xbmc = MagicMock()
        backend = _Backend(on_refresh=lambda target: target.states.update(
            {HELD: AddonStateInfo(HELD, False, VERSION)}
        ))
        with patch.dict(sys.modules, {"xbmc": xbmc}):
            result = self._ready(backend)
        self.assertTrue(result.ready)
        messages = [call.args[0] for call in xbmc.log.call_args_list]
        self.assertTrue(any(
            "stage=before_refresh" in message and "state=missing" in message
            for message in messages
        ))
        self.assertTrue(any(
            "stage=after_refresh" in message
            and f"version={VERSION}" in message
            and "enabled=false" in message
            and "readiness=registered_after_refresh" in message
            for message in messages
        ))
        self.assertTrue(any(
            "result=requested" in message for message in messages
        ))


if __name__ == "__main__":
    unittest.main()
