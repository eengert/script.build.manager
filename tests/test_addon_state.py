"""
Unit tests for resources/lib/addon_state.py (BM-013).

Tests cover:
  - AddonStateStatus enum values
  - Input validation (addon_id, desired_state)
  - ALREADY_CORRECT (idempotency: already at desired state)
  - ENABLED / DISABLED (successful mutations)
  - MISSING (not installed)
  - BLOCKED_REQUIRED_DEPENDENCY (dependency protection)
  - BLOCKED_SYSTEM (xbmc.* protection)
  - FAILED from backend errors (query, set, verify)
  - Verify-after-set mismatch (enable, disable)
  - Batch ordering (lexical) and isolation (one failure != stop)
  - Idempotency across two reconcile() calls
  - KodiRuntimeAddonStateBackend construction (outside Kodi)

All tests use fake in-memory backends — no Kodi instance required.
"""

import unittest
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from resources.lib.addon_state import (
    AddonStateBackend,
    AddonStateError,
    AddonStateInfo,
    AddonStateReconcileResult,
    AddonStateReconciler,
    AddonStateResult,
    AddonStateStatus,
    AddonStateValidationError,
    KodiRuntimeAddonStateBackend,
)


# ---------------------------------------------------------------------------
# Fake backend helpers
# ---------------------------------------------------------------------------

class FakeAddonStateBackend(AddonStateBackend):
    """Configurable in-memory fake. Tracks mutation calls."""

    def __init__(self, installed: Optional[Dict[str, AddonStateInfo]] = None) -> None:
        # addon_id → AddonStateInfo (current installed state)
        self._state: Dict[str, AddonStateInfo] = dict(installed or {})
        # Mutation log: list of (addon_id, enabled) tuples
        self.set_calls: List[Tuple[str, bool]] = []
        # Per-addon overrides: inject errors
        self._query_errors: Dict[str, Exception] = {}
        self._set_errors: Dict[str, Exception] = {}
        # After a set, what should verify return? None = compute from _state
        self._verify_override: Dict[str, Optional[AddonStateInfo]] = {}

    def inject_query_error(self, addon_id: str, exc: Exception) -> None:
        """Cause get_addon_details to raise exc for addon_id."""
        self._query_errors[addon_id] = exc

    def inject_set_error(self, addon_id: str, exc: Exception) -> None:
        """Cause set_addon_enabled to raise exc for addon_id."""
        self._set_errors[addon_id] = exc

    def inject_verify_override(
        self, addon_id: str, info: Optional[AddonStateInfo]
    ) -> None:
        """After set_addon_enabled, return this value from the next get_addon_details."""
        self._verify_override[addon_id] = info

    def get_addon_details(self, addon_id: str) -> Optional[AddonStateInfo]:
        if addon_id in self._query_errors:
            raise self._query_errors[addon_id]
        return self._state.get(addon_id)

    def set_addon_enabled(self, addon_id: str, enabled: bool) -> None:
        if addon_id in self._set_errors:
            raise self._set_errors[addon_id]
        self.set_calls.append((addon_id, enabled))
        if addon_id in self._verify_override:
            # Override: replace installed state with the injected override
            override = self._verify_override.pop(addon_id)
            if override is None:
                self._state.pop(addon_id, None)
            else:
                self._state[addon_id] = override
        elif addon_id in self._state:
            old = self._state[addon_id]
            self._state[addon_id] = AddonStateInfo(
                addon_id=old.addon_id,
                enabled=enabled,
                version=old.version,
            )


def _info(addon_id: str, enabled: bool, version: str = "1.0.0") -> AddonStateInfo:
    return AddonStateInfo(addon_id=addon_id, enabled=enabled, version=version)


def _reconcile(
    installed: Optional[Dict[str, AddonStateInfo]],
    desired: Dict[str, str],
    protected: Optional[frozenset] = None,
) -> AddonStateReconcileResult:
    backend = FakeAddonStateBackend(installed)
    reconciler = AddonStateReconciler(backend)
    kwargs = {}
    if protected is not None:
        kwargs["protected_dependency_ids"] = protected
    return reconciler.reconcile(desired, **kwargs)


# ---------------------------------------------------------------------------
# TestAddonStateStatus
# ---------------------------------------------------------------------------

class TestAddonStateStatus(unittest.TestCase):
    def test_already_correct_value(self):
        self.assertEqual(AddonStateStatus.ALREADY_CORRECT, "already_correct")

    def test_enabled_value(self):
        self.assertEqual(AddonStateStatus.ENABLED, "enabled")

    def test_disabled_value(self):
        self.assertEqual(AddonStateStatus.DISABLED, "disabled")

    def test_missing_value(self):
        self.assertEqual(AddonStateStatus.MISSING, "missing")

    def test_blocked_required_dependency_value(self):
        self.assertEqual(
            AddonStateStatus.BLOCKED_REQUIRED_DEPENDENCY,
            "blocked_required_dependency",
        )

    def test_blocked_system_value(self):
        self.assertEqual(AddonStateStatus.BLOCKED_SYSTEM, "blocked_system")

    def test_failed_value(self):
        self.assertEqual(AddonStateStatus.FAILED, "failed")

    def test_str_enum(self):
        self.assertIsInstance(AddonStateStatus.ENABLED, str)


# ---------------------------------------------------------------------------
# TestAddonStateValidation
# ---------------------------------------------------------------------------

class TestAddonStateValidation(unittest.TestCase):
    """Input validation — no backend mutation should occur."""

    def _assert_failed_no_backend(
        self, desired: Dict[str, str], check_msg: str = ""
    ) -> AddonStateResult:
        backend = FakeAddonStateBackend({})
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile(desired)
        self.assertEqual(len(result.results), 1)
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.FAILED)
        self.assertEqual(backend.set_calls, [])
        if check_msg:
            self.assertIn(check_msg, r.message)
        return r

    def test_invalid_addon_id_empty(self):
        r = self._assert_failed_no_backend({"": "enabled"})
        self.assertIn("non-empty", r.message)

    def test_invalid_addon_id_starts_with_dot(self):
        self._assert_failed_no_backend({".starts_dot": "enabled"}, "not a valid")

    def test_invalid_addon_id_has_space(self):
        self._assert_failed_no_backend({"plugin video foo": "enabled"}, "not a valid")

    def test_invalid_addon_id_too_long(self):
        long_id = "a" * 101
        self._assert_failed_no_backend({long_id: "enabled"}, "not a valid")

    def test_invalid_desired_state_absent(self):
        r = self._assert_failed_no_backend(
            {"plugin.video.foo": "absent"}, "Invalid desired_state"
        )
        self.assertIsNone(r.was_enabled)
        self.assertIsNone(r.now_enabled)

    def test_invalid_desired_state_empty(self):
        self._assert_failed_no_backend({"plugin.video.foo": ""}, "Invalid desired_state")

    def test_invalid_desired_state_upper(self):
        self._assert_failed_no_backend(
            {"plugin.video.foo": "Enabled"}, "Invalid desired_state"
        )

    def test_valid_addon_id_minimal(self):
        """Single character addon_id is valid."""
        result = _reconcile(
            {"a": _info("a", enabled=True)}, {"a": "enabled"}
        )
        self.assertEqual(result.results[0].status, AddonStateStatus.ALREADY_CORRECT)

    def test_valid_addon_id_100_chars(self):
        """100-character addon_id is at the limit."""
        a100 = "a" + "b" * 99
        self.assertEqual(len(a100), 100)
        result = _reconcile(
            {a100: _info(a100, enabled=True)}, {a100: "enabled"}
        )
        self.assertEqual(result.results[0].status, AddonStateStatus.ALREADY_CORRECT)

    def test_validation_failed_not_all_correct(self):
        result = _reconcile({}, {"": "enabled"})
        self.assertFalse(result.all_correct)


# ---------------------------------------------------------------------------
# TestBasicEnable
# ---------------------------------------------------------------------------

class TestBasicEnable(unittest.TestCase):
    def test_disabled_to_enabled(self):
        result = _reconcile(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=False)},
            {"plugin.video.foo": "enabled"},
        )
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.ENABLED)
        self.assertFalse(r.was_enabled)
        self.assertTrue(r.now_enabled)
        self.assertTrue(result.all_correct)
        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0].addon_id, "plugin.video.foo")

    def test_already_enabled_no_mutation(self):
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=True)}
        )
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.foo": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.ALREADY_CORRECT)
        self.assertTrue(r.was_enabled)
        self.assertTrue(r.now_enabled)
        self.assertEqual(backend.set_calls, [])
        self.assertEqual(result.changed, ())


# ---------------------------------------------------------------------------
# TestBasicDisable
# ---------------------------------------------------------------------------

class TestBasicDisable(unittest.TestCase):
    def test_enabled_to_disabled(self):
        result = _reconcile(
            {"plugin.video.bar": _info("plugin.video.bar", enabled=True)},
            {"plugin.video.bar": "disabled"},
        )
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.DISABLED)
        self.assertTrue(r.was_enabled)
        self.assertFalse(r.now_enabled)
        self.assertTrue(result.all_correct)
        self.assertEqual(len(result.changed), 1)

    def test_already_disabled_no_mutation(self):
        backend = FakeAddonStateBackend(
            {"plugin.video.bar": _info("plugin.video.bar", enabled=False)}
        )
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.bar": "disabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.ALREADY_CORRECT)
        self.assertFalse(r.was_enabled)
        self.assertFalse(r.now_enabled)
        self.assertEqual(backend.set_calls, [])

    def test_all_correct_includes_disabled(self):
        result = _reconcile(
            {"plugin.video.bar": _info("plugin.video.bar", enabled=True)},
            {"plugin.video.bar": "disabled"},
        )
        self.assertTrue(result.all_correct)


# ---------------------------------------------------------------------------
# TestMissing
# ---------------------------------------------------------------------------

class TestMissing(unittest.TestCase):
    def test_not_installed_yields_missing(self):
        result = _reconcile({}, {"plugin.video.notinstalled": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.MISSING)
        self.assertIsNone(r.was_enabled)
        self.assertIsNone(r.now_enabled)

    def test_missing_not_all_correct(self):
        result = _reconcile({}, {"plugin.video.notinstalled": "enabled"})
        self.assertFalse(result.all_correct)

    def test_missing_no_mutation(self):
        backend = FakeAddonStateBackend({})
        reconciler = AddonStateReconciler(backend)
        reconciler.reconcile({"plugin.video.notinstalled": "enabled"})
        self.assertEqual(backend.set_calls, [])

    def test_missing_with_disable_desired(self):
        result = _reconcile({}, {"plugin.video.notinstalled": "disabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.MISSING)


# ---------------------------------------------------------------------------
# TestDependencyProtection
# ---------------------------------------------------------------------------

class TestDependencyProtection(unittest.TestCase):
    def test_protected_enabled_desired_disabled_blocked(self):
        """Protected add-on desired disabled → BLOCKED even if currently enabled."""
        result = _reconcile(
            {"script.module.dep": _info("script.module.dep", enabled=True)},
            {"script.module.dep": "disabled"},
            protected=frozenset({"script.module.dep"}),
        )
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.BLOCKED_REQUIRED_DEPENDENCY)
        self.assertFalse(result.all_correct)

    def test_protected_already_disabled_still_blocked(self):
        """Protected add-on desired disabled → BLOCKED even if already disabled.

        This is a configuration conflict: BM-012 needs it enabled; manifest
        wants it disabled. The block must not be silenced by ALREADY_CORRECT.
        """
        result = _reconcile(
            {"script.module.dep": _info("script.module.dep", enabled=False)},
            {"script.module.dep": "disabled"},
            protected=frozenset({"script.module.dep"}),
        )
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.BLOCKED_REQUIRED_DEPENDENCY)
        self.assertFalse(result.all_correct)

    def test_protected_desired_enabled_allowed(self):
        """Protected + desired enabled → proceed normally (enable or ALREADY_CORRECT)."""
        result = _reconcile(
            {"script.module.dep": _info("script.module.dep", enabled=False)},
            {"script.module.dep": "enabled"},
            protected=frozenset({"script.module.dep"}),
        )
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.ENABLED)

    def test_protected_desired_enabled_already_correct(self):
        result = _reconcile(
            {"script.module.dep": _info("script.module.dep", enabled=True)},
            {"script.module.dep": "enabled"},
            protected=frozenset({"script.module.dep"}),
        )
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.ALREADY_CORRECT)

    def test_protected_no_mutation(self):
        backend = FakeAddonStateBackend(
            {"script.module.dep": _info("script.module.dep", enabled=True)}
        )
        reconciler = AddonStateReconciler(backend)
        reconciler.reconcile(
            {"script.module.dep": "disabled"},
            protected_dependency_ids=frozenset({"script.module.dep"}),
        )
        self.assertEqual(backend.set_calls, [])

    def test_protected_addon_not_in_desired_unaffected(self):
        """Addon in protected but not in desired_states is never queried."""
        backend = FakeAddonStateBackend(
            {"script.module.other": _info("script.module.other", enabled=True)}
        )
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile(
            {"plugin.video.foo": "enabled"},
            protected_dependency_ids=frozenset({"script.module.other"}),
        )
        # plugin.video.foo not installed → MISSING; script.module.other not in results
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].addon_id, "plugin.video.foo")

    def test_blocked_includes_was_enabled_from_query(self):
        """was_enabled is populated from a diagnostic query for the BLOCKED case."""
        result = _reconcile(
            {"script.module.dep": _info("script.module.dep", enabled=True)},
            {"script.module.dep": "disabled"},
            protected=frozenset({"script.module.dep"}),
        )
        r = result.results[0]
        # The diagnostic query ran; was_enabled should be True
        self.assertTrue(r.was_enabled)


# ---------------------------------------------------------------------------
# TestSystemAddon
# ---------------------------------------------------------------------------

class TestSystemAddon(unittest.TestCase):
    def test_xbmc_addon_blocked_enable(self):
        backend = FakeAddonStateBackend({})
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"xbmc.core": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.BLOCKED_SYSTEM)
        self.assertEqual(backend.set_calls, [])

    def test_xbmc_addon_blocked_disable(self):
        backend = FakeAddonStateBackend({"xbmc.gui": _info("xbmc.gui", enabled=True)})
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"xbmc.gui": "disabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.BLOCKED_SYSTEM)
        self.assertEqual(backend.set_calls, [])

    def test_xbmc_addon_not_all_correct(self):
        result = _reconcile({}, {"xbmc.python": "enabled"})
        self.assertFalse(result.all_correct)

    def test_xbmc_addon_message_contains_system(self):
        result = _reconcile({}, {"xbmc.gui": "disabled"})
        self.assertIn("system", result.results[0].message.lower())

    def test_xbmc_prefix_exact(self):
        """xbmc. prefix match is exact — 'xbmcx.foo' is not blocked."""
        result = _reconcile(
            {"xbmcx.foo": _info("xbmcx.foo", enabled=False)}, {"xbmcx.foo": "enabled"}
        )
        self.assertEqual(result.results[0].status, AddonStateStatus.ENABLED)


# ---------------------------------------------------------------------------
# TestFailures
# ---------------------------------------------------------------------------

class TestFailures(unittest.TestCase):
    def test_query_error_yields_failed(self):
        backend = FakeAddonStateBackend({})
        backend.inject_query_error(
            "plugin.video.foo", AddonStateError("Kodi unavailable")
        )
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.foo": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.FAILED)
        self.assertFalse(result.all_correct)
        self.assertEqual(backend.set_calls, [])

    def test_set_error_yields_failed(self):
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=False)}
        )
        backend.inject_set_error(
            "plugin.video.foo", AddonStateError("SetAddonEnabled rejected")
        )
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.foo": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.FAILED)
        self.assertFalse(r.now_enabled)

    def test_verify_error_yields_failed(self):
        """Infrastructure error on post-set verification → FAILED."""
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=False)}
        )
        call_count = [0]
        original_get = backend.get_addon_details

        def patched_get(addon_id: str):
            call_count[0] += 1
            if call_count[0] == 2:
                raise AddonStateError("Verify infra fail")
            return original_get(addon_id)

        backend.get_addon_details = patched_get
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.foo": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.FAILED)

    def test_verify_returns_none_yields_failed(self):
        """Verify query returns None (addon vanished after set) → FAILED."""
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=False)}
        )
        backend.inject_verify_override("plugin.video.foo", None)
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.foo": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.FAILED)

    def test_verify_mismatch_enable_yields_failed(self):
        """Verify after enable returns still-disabled → FAILED."""
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=False)}
        )
        # Override: after set, still disabled
        backend.inject_verify_override(
            "plugin.video.foo", _info("plugin.video.foo", enabled=False)
        )
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.foo": "enabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.FAILED)
        self.assertFalse(r.now_enabled)

    def test_verify_mismatch_disable_yields_failed(self):
        """Verify after disable returns still-enabled → FAILED."""
        backend = FakeAddonStateBackend(
            {"plugin.video.bar": _info("plugin.video.bar", enabled=True)}
        )
        # Override: after set, still enabled
        backend.inject_verify_override(
            "plugin.video.bar", _info("plugin.video.bar", enabled=True)
        )
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.bar": "disabled"})
        r = result.results[0]
        self.assertEqual(r.status, AddonStateStatus.FAILED)
        self.assertTrue(r.now_enabled)

    def test_failed_results_in_failed_tuple(self):
        backend = FakeAddonStateBackend({})
        backend.inject_query_error("plugin.video.foo", AddonStateError("err"))
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({"plugin.video.foo": "enabled"})
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0].addon_id, "plugin.video.foo")


# ---------------------------------------------------------------------------
# TestBatch
# ---------------------------------------------------------------------------

class TestBatch(unittest.TestCase):
    def test_lexical_order(self):
        installed = {
            "plugin.video.zzz": _info("plugin.video.zzz", enabled=False),
            "plugin.video.aaa": _info("plugin.video.aaa", enabled=False),
            "plugin.video.mmm": _info("plugin.video.mmm", enabled=False),
        }
        desired = {
            "plugin.video.zzz": "enabled",
            "plugin.video.aaa": "enabled",
            "plugin.video.mmm": "enabled",
        }
        result = _reconcile(installed, desired)
        ids = [r.addon_id for r in result.results]
        self.assertEqual(ids, sorted(ids))

    def test_one_failure_does_not_stop_others(self):
        backend = FakeAddonStateBackend(
            {
                "plugin.video.aaa": _info("plugin.video.aaa", enabled=False),
                "plugin.video.zzz": _info("plugin.video.zzz", enabled=False),
            }
        )
        backend.inject_query_error("plugin.video.aaa", AddonStateError("fail"))
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile(
            {"plugin.video.aaa": "enabled", "plugin.video.zzz": "enabled"}
        )
        statuses = {r.addon_id: r.status for r in result.results}
        self.assertEqual(statuses["plugin.video.aaa"], AddonStateStatus.FAILED)
        self.assertEqual(statuses["plugin.video.zzz"], AddonStateStatus.ENABLED)

    def test_unmanaged_addon_not_touched(self):
        """An add-on not in desired_states is never queried or mutated."""
        backend = FakeAddonStateBackend(
            {
                "plugin.video.managed": _info("plugin.video.managed", enabled=False),
                "plugin.video.unmanaged": _info(
                    "plugin.video.unmanaged", enabled=True
                ),
            }
        )
        get_calls = []
        original = backend.get_addon_details

        def track_get(addon_id):
            get_calls.append(addon_id)
            return original(addon_id)

        backend.get_addon_details = track_get
        reconciler = AddonStateReconciler(backend)
        reconciler.reconcile({"plugin.video.managed": "enabled"})
        self.assertNotIn("plugin.video.unmanaged", get_calls)
        self.assertNotIn(
            ("plugin.video.unmanaged", True), backend.set_calls
        )

    def test_all_correct_mixed(self):
        """all_correct requires every result be success-class."""
        installed = {
            "plugin.video.aaa": _info("plugin.video.aaa", enabled=False),
            "plugin.video.bbb": _info("plugin.video.bbb", enabled=True),
        }
        desired = {
            "plugin.video.aaa": "enabled",
            "plugin.video.bbb": "enabled",
        }
        result = _reconcile(installed, desired)
        self.assertTrue(result.all_correct)

    def test_all_correct_false_when_any_failed(self):
        backend = FakeAddonStateBackend(
            {"plugin.video.aaa": _info("plugin.video.aaa", enabled=True)}
        )
        backend.inject_query_error("plugin.video.bbb", AddonStateError("fail"))
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile(
            {"plugin.video.aaa": "enabled", "plugin.video.bbb": "enabled"}
        )
        self.assertFalse(result.all_correct)

    def test_empty_desired_returns_empty_result(self):
        backend = FakeAddonStateBackend({})
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile({})
        self.assertEqual(result.results, ())
        self.assertTrue(result.all_correct)
        self.assertEqual(result.changed, ())
        self.assertEqual(result.failed, ())


# ---------------------------------------------------------------------------
# TestIdempotency
# ---------------------------------------------------------------------------

class TestIdempotency(unittest.TestCase):
    def test_enable_then_re_reconcile_already_correct(self):
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=False)}
        )
        reconciler = AddonStateReconciler(backend)
        desired = {"plugin.video.foo": "enabled"}

        r1 = reconciler.reconcile(desired)
        self.assertEqual(r1.results[0].status, AddonStateStatus.ENABLED)
        self.assertEqual(len(backend.set_calls), 1)

        r2 = reconciler.reconcile(desired)
        self.assertEqual(r2.results[0].status, AddonStateStatus.ALREADY_CORRECT)
        self.assertEqual(len(backend.set_calls), 1)  # no second call

    def test_disable_then_re_reconcile_already_correct(self):
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=True)}
        )
        reconciler = AddonStateReconciler(backend)
        desired = {"plugin.video.foo": "disabled"}

        r1 = reconciler.reconcile(desired)
        self.assertEqual(r1.results[0].status, AddonStateStatus.DISABLED)

        r2 = reconciler.reconcile(desired)
        self.assertEqual(r2.results[0].status, AddonStateStatus.ALREADY_CORRECT)
        self.assertEqual(len(backend.set_calls), 1)


# ---------------------------------------------------------------------------
# TestAddonStateResult
# ---------------------------------------------------------------------------

class TestAddonStateResult(unittest.TestCase):
    def test_result_is_frozen(self):
        r = AddonStateResult(
            addon_id="plugin.video.foo",
            desired_state="enabled",
            status=AddonStateStatus.ENABLED,
            was_enabled=False,
            now_enabled=True,
            message="ok",
        )
        with self.assertRaises((AttributeError, TypeError)):
            r.status = AddonStateStatus.FAILED  # type: ignore[misc]

    def test_info_is_frozen(self):
        info = AddonStateInfo(addon_id="plugin.video.foo", enabled=True, version="1.0.0")
        with self.assertRaises((AttributeError, TypeError)):
            info.enabled = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestAddonStateReconcileResult
# ---------------------------------------------------------------------------

class TestAddonStateReconcileResult(unittest.TestCase):
    def test_changed_contains_only_mutations(self):
        installed = {
            "plugin.video.aaa": _info("plugin.video.aaa", enabled=False),
            "plugin.video.bbb": _info("plugin.video.bbb", enabled=True),
        }
        desired = {
            "plugin.video.aaa": "enabled",
            "plugin.video.bbb": "enabled",
        }
        result = _reconcile(installed, desired)
        # aaa changed, bbb was already correct
        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0].addon_id, "plugin.video.aaa")

    def test_failed_contains_only_failures(self):
        backend = FakeAddonStateBackend(
            {"plugin.video.foo": _info("plugin.video.foo", enabled=True)}
        )
        backend.inject_query_error("plugin.video.bar", AddonStateError("err"))
        reconciler = AddonStateReconciler(backend)
        result = reconciler.reconcile(
            {"plugin.video.foo": "enabled", "plugin.video.bar": "enabled"}
        )
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0].addon_id, "plugin.video.bar")
        self.assertEqual(len(result.changed), 0)


# ---------------------------------------------------------------------------
# TestKodiRuntimeAddonStateBackend
# ---------------------------------------------------------------------------

class TestKodiRuntimeAddonStateBackend(unittest.TestCase):
    """Unit tests for the production backend. No live Kodi required."""

    def test_instantiation_succeeds(self):
        """Backend is instantiable outside Kodi."""
        backend = KodiRuntimeAddonStateBackend()
        self.assertIsNotNone(backend)

    def test_get_addon_details_raises_without_kodi(self):
        backend = KodiRuntimeAddonStateBackend()
        with self.assertRaises(AddonStateError):
            backend.get_addon_details("plugin.video.foo")

    def test_set_addon_enabled_raises_without_kodi(self):
        backend = KodiRuntimeAddonStateBackend()
        with self.assertRaises(AddonStateError):
            backend.set_addon_enabled("plugin.video.foo", True)

    def test_get_addon_details_not_installed(self):
        """JSON-RPC error -32602 → None (not installed)."""
        backend = KodiRuntimeAddonStateBackend()
        mock_xbmc = MagicMock()
        import json
        mock_xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32602, "message": "Invalid params"},
        })
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            result = backend.get_addon_details("plugin.video.notinstalled")
        self.assertIsNone(result)

    def test_get_addon_details_other_rpc_error_raises(self):
        """JSON-RPC errors other than -32602 → AddonStateError."""
        backend = KodiRuntimeAddonStateBackend()
        mock_xbmc = MagicMock()
        import json
        mock_xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        })
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            with self.assertRaises(AddonStateError):
                backend.get_addon_details("plugin.video.foo")

    def test_get_addon_details_success(self):
        """Successful GetAddonDetails response → AddonStateInfo."""
        backend = KodiRuntimeAddonStateBackend()
        mock_xbmc = MagicMock()
        import json
        mock_xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "addon": {
                    "addonid": "plugin.video.foo",
                    "enabled": True,
                    "version": "2.0.1",
                }
            },
        })
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            info = backend.get_addon_details("plugin.video.foo")
        self.assertIsNotNone(info)
        self.assertEqual(info.addon_id, "plugin.video.foo")
        self.assertTrue(info.enabled)
        self.assertEqual(info.version, "2.0.1")

    def test_set_addon_enabled_success(self):
        """Successful SetAddonEnabled → no error raised."""
        backend = KodiRuntimeAddonStateBackend()
        mock_xbmc = MagicMock()
        import json
        mock_xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": "OK",
        })
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            backend.set_addon_enabled("plugin.video.foo", True)  # no exception

    def test_set_addon_enabled_rpc_error_raises(self):
        """SetAddonEnabled JSON-RPC error → AddonStateError."""
        backend = KodiRuntimeAddonStateBackend()
        mock_xbmc = MagicMock()
        import json
        mock_xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "Internal error"},
        })
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            with self.assertRaises(AddonStateError):
                backend.set_addon_enabled("plugin.video.foo", True)

    # ------------------------------------------------------------------
    # Fail-closed enabled-field validation (BM-013 correction)
    # ------------------------------------------------------------------

    def _make_mock_xbmc_with_addon(self, enabled_value) -> tuple:
        """Return (backend, mock_xbmc) configured with a GetAddonDetails response
        whose 'enabled' field is set to enabled_value."""
        import json
        backend = KodiRuntimeAddonStateBackend()
        mock_xbmc = MagicMock()
        mock_xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "addon": {
                    "addonid": "plugin.video.foo",
                    "enabled": enabled_value,
                    "version": "1.0.0",
                }
            },
        })
        return backend, mock_xbmc

    def test_enabled_true_accepted(self):
        """enabled=True (bool) → AddonStateInfo returned."""
        backend, mock_xbmc = self._make_mock_xbmc_with_addon(True)
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            info = backend.get_addon_details("plugin.video.foo")
        self.assertIsNotNone(info)
        self.assertTrue(info.enabled)

    def test_enabled_false_accepted(self):
        """enabled=False (bool) → AddonStateInfo returned."""
        backend, mock_xbmc = self._make_mock_xbmc_with_addon(False)
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            info = backend.get_addon_details("plugin.video.foo")
        self.assertIsNotNone(info)
        self.assertFalse(info.enabled)

    def test_enabled_missing_raises(self):
        """enabled field absent → AddonStateError (fail closed)."""
        import json
        backend = KodiRuntimeAddonStateBackend()
        mock_xbmc = MagicMock()
        mock_xbmc.executeJSONRPC.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "addon": {
                    "addonid": "plugin.video.foo",
                    "version": "1.0.0",
                    # "enabled" deliberately omitted
                }
            },
        })
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            with self.assertRaises(AddonStateError):
                backend.get_addon_details("plugin.video.foo")

    def test_enabled_none_raises(self):
        """enabled=None → AddonStateError (fail closed)."""
        backend, mock_xbmc = self._make_mock_xbmc_with_addon(None)
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            with self.assertRaises(AddonStateError):
                backend.get_addon_details("plugin.video.foo")

    def test_enabled_int_zero_raises(self):
        """enabled=0 (int) → AddonStateError; bool subclasses int, but 0 is not bool."""
        backend, mock_xbmc = self._make_mock_xbmc_with_addon(0)
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            with self.assertRaises(AddonStateError):
                backend.get_addon_details("plugin.video.foo")

    def test_enabled_int_one_raises(self):
        """enabled=1 (int) → AddonStateError; must be an actual bool."""
        backend, mock_xbmc = self._make_mock_xbmc_with_addon(1)
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            with self.assertRaises(AddonStateError):
                backend.get_addon_details("plugin.video.foo")

    def test_enabled_string_false_raises(self):
        """enabled='false' (str) → AddonStateError (fail closed)."""
        backend, mock_xbmc = self._make_mock_xbmc_with_addon("false")
        with patch.object(backend, "_xbmc", return_value=mock_xbmc):
            with self.assertRaises(AddonStateError):
                backend.get_addon_details("plugin.video.foo")


if __name__ == "__main__":
    unittest.main()
