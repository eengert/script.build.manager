"""Tests for the independent BM-021B global updater guard."""

import unittest

from resources.lib.update_guard import (
    AddonUpdateGuard,
    AddonUpdatePolicy,
    UpdateGuardError,
    UpdatePolicyBackend,
    KodiJsonRpcUpdatePolicyBackend,
)


class FakePolicyBackend(UpdatePolicyBackend):
    def __init__(self, policy=AddonUpdatePolicy.AUTOMATIC):
        self.policy = policy
        self.calls = []
        self.fail_set = False
        self.fail_read = False
        self.verify_override = None

    def get_policy(self):
        if self.fail_read:
            raise RuntimeError("read failed")
        return self.policy if self.verify_override is None else self.verify_override

    def set_policy(self, policy):
        self.calls.append(policy)
        if self.fail_set:
            raise RuntimeError("set failed")
        self.policy = policy


class TestAddonUpdateGuard(unittest.TestCase):
    def test_engage_reassert_and_explicit_restore(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.NOTIFY_ONLY)
        guard = AddonUpdateGuard(backend)
        snapshot = guard.engage()
        self.assertEqual(AddonUpdatePolicy.NOTIFY_ONLY, snapshot.original)
        self.assertEqual(AddonUpdatePolicy.NEVER_CHECK, backend.policy)
        guard.reassert()
        self.assertEqual(AddonUpdatePolicy.NOTIFY_ONLY, guard.restore())
        self.assertFalse(guard.engaged)

    def test_failure_to_set_fails_closed_without_snapshot(self):
        backend = FakePolicyBackend()
        backend.fail_set = True
        guard = AddonUpdateGuard(backend)
        with self.assertRaises(UpdateGuardError):
            guard.engage()
        self.assertFalse(guard.engaged)

    def test_failure_to_verify_leaves_guard_engaged(self):
        backend = FakePolicyBackend()
        guard = AddonUpdateGuard(backend)
        guard.engage()
        backend.verify_override = AddonUpdatePolicy.AUTOMATIC
        with self.assertRaises(UpdateGuardError):
            guard.reassert()
        self.assertTrue(guard.engaged)

    def test_restore_is_explicit_and_failure_does_not_silently_clear(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.NOTIFY_ONLY)
        guard = AddonUpdateGuard(backend)
        guard.engage()
        backend.fail_set = True
        with self.assertRaises(UpdateGuardError):
            guard.restore()
        self.assertTrue(guard.engaged)

    def test_json_rpc_adapter_uses_supported_setting(self):
        calls = []
        value = {"current": 0}

        def rpc(method, params):
            calls.append((method, params))
            if method == "Settings.GetSettingValue":
                return {"value": value["current"]}
            value["current"] = params["value"]
            return {"success": True}

        backend = KodiJsonRpcUpdatePolicyBackend(rpc)
        guard = AddonUpdateGuard(backend)
        guard.engage()
        guard.restore()
        self.assertEqual(
            ["Settings.GetSettingValue", "Settings.SetSettingValue",
             "Settings.GetSettingValue", "Settings.SetSettingValue",
             "Settings.GetSettingValue"],
            [method for method, _ in calls],
        )
        self.assertTrue(all(params["setting"] == "general.addonupdates" for _, params in calls))

    def test_malformed_policy_is_rejected(self):
        backend = FakePolicyBackend()
        backend.policy = "automatic"
        with self.assertRaises(UpdateGuardError):
            AddonUpdateGuard(backend).engage()
