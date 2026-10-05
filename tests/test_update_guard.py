"""Tests for the independent BM-021B global updater guard."""

import unittest

from resources.lib.update_guard import (
    AddonUpdateGuard,
    AddonUpdatePolicy,
    UpdateGuardError,
    UpdaterNotQuarantinedError,
    UpdaterStateUnavailableError,
    UpdatePolicyBackend,
    KodiJsonRpcUpdatePolicyBackend,
)


class FakePolicyBackend(UpdatePolicyBackend):
    def __init__(self, policy=AddonUpdatePolicy.AUTOMATIC):
        self.policy = policy
        self.calls = []
        self.reads = 0
        self.fail_set = False
        self.fail_read = False
        self.verify_override = None

    def get_policy(self):
        self.reads += 1
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


class TestInitialQuarantineWrite(unittest.TestCase):
    """The initial install is the one place that legitimately changes the setting."""

    def test_engage_with_original_from_automatic_writes_never_check_exactly_once(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.AUTOMATIC)
        guard = AddonUpdateGuard(backend)
        snapshot = guard.engage_with_original(AddonUpdatePolicy.AUTOMATIC)
        self.assertEqual([AddonUpdatePolicy.NEVER_CHECK], backend.calls)
        self.assertEqual(AddonUpdatePolicy.NEVER_CHECK, backend.policy)
        self.assertEqual(1, backend.reads)  # the read-back that verifies the write
        self.assertEqual(AddonUpdatePolicy.AUTOMATIC, snapshot.original)
        self.assertEqual(AddonUpdatePolicy.NEVER_CHECK, snapshot.guarded)

    def test_the_written_policy_is_verified_by_read_back(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.AUTOMATIC)
        backend.verify_override = AddonUpdatePolicy.AUTOMATIC  # Kodi did not keep the write
        guard = AddonUpdateGuard(backend)
        with self.assertRaises(UpdateGuardError):
            guard.engage_with_original(AddonUpdatePolicy.AUTOMATIC)
        self.assertEqual([AddonUpdatePolicy.NEVER_CHECK], backend.calls)
        self.assertFalse(guard.engaged)

    def test_engage_reads_the_original_then_writes_once_through_the_rpc_adapter(self):
        calls = []
        value = {"current": int(AddonUpdatePolicy.AUTOMATIC)}

        def rpc(method, params):
            calls.append((method, params.get("value")))
            if method == "Settings.GetSettingValue":
                return {"value": value["current"]}
            value["current"] = params["value"]
            return {"success": True}

        AddonUpdateGuard(KodiJsonRpcUpdatePolicyBackend(rpc)).engage()
        self.assertEqual(
            [("Settings.GetSettingValue", None), ("Settings.SetSettingValue", 2),
             ("Settings.GetSettingValue", None)],
            calls,
        )


class TestVerifyQuarantined(unittest.TestCase):
    """Post-restart verification reads only: it can never change the setting."""

    def assertNeverWrote(self, backend):
        self.assertEqual([], backend.calls)

    def test_never_check_is_verified_with_zero_setter_calls(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.NEVER_CHECK)
        guard = AddonUpdateGuard(backend)
        self.assertIsNone(guard.verify_quarantined())
        self.assertNeverWrote(backend)
        self.assertEqual(1, backend.reads)
        self.assertFalse(guard.engaged)  # durable ownership, not an in-memory snapshot

    def test_every_other_readable_policy_fails_with_the_existing_status_code(self):
        for policy in (AddonUpdatePolicy.AUTOMATIC, AddonUpdatePolicy.NOTIFY_ONLY, 0, 1):
            with self.subTest(policy=policy):
                backend = FakePolicyBackend(policy)
                with self.assertRaises(UpdaterNotQuarantinedError) as raised:
                    AddonUpdateGuard(backend).verify_quarantined()
                self.assertEqual("FROZEN_UPDATER_NOT_QUARANTINED", raised.exception.code)
                self.assertIsInstance(raised.exception, UpdateGuardError)
                self.assertNeverWrote(backend)
                self.assertEqual(AddonUpdatePolicy(policy), backend.policy)  # unchanged

    def test_unreadable_policy_fails_with_the_unavailable_status_code(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.NEVER_CHECK)
        backend.fail_read = True
        with self.assertRaises(UpdaterStateUnavailableError) as raised:
            AddonUpdateGuard(backend).verify_quarantined()
        self.assertEqual("FROZEN_UPDATER_STATE_UNAVAILABLE", raised.exception.code)
        self.assertIsInstance(raised.exception, UpdateGuardError)
        self.assertNeverWrote(backend)

    def test_malformed_policy_fails_with_the_unavailable_status_code(self):
        for value in ("automatic", None, 7, -1, True, False, {}, [2], object()):
            with self.subTest(value=value):
                backend = FakePolicyBackend()
                backend.policy = value
                with self.assertRaises(UpdaterStateUnavailableError) as raised:
                    AddonUpdateGuard(backend).verify_quarantined()
                self.assertEqual("FROZEN_UPDATER_STATE_UNAVAILABLE", raised.exception.code)
                self.assertNeverWrote(backend)

    def test_a_failing_setter_is_irrelevant_because_it_is_never_reached(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.AUTOMATIC)
        backend.fail_set = True
        with self.assertRaises(UpdaterNotQuarantinedError):
            AddonUpdateGuard(backend).verify_quarantined()
        self.assertNeverWrote(backend)

    def test_json_rpc_verification_issues_one_get_and_no_set(self):
        for response, expected in (
            ({"value": 2}, None),
            ({"value": 0}, UpdaterNotQuarantinedError),
            ({"value": 1}, UpdaterNotQuarantinedError),
            ({"value": 2.9}, UpdaterStateUnavailableError),
            ({"value": 2.01}, UpdaterStateUnavailableError),
            ({"value": 0.9}, UpdaterStateUnavailableError),
            ({"value": 1.9}, UpdaterStateUnavailableError),
            ({"value": 2.0}, UpdaterStateUnavailableError),
            ({"value": "2"}, UpdaterStateUnavailableError),
            ({"value": b"2"}, UpdaterStateUnavailableError),
            ({"value": False}, UpdaterStateUnavailableError),
            ({"value": float("nan")}, UpdaterStateUnavailableError),
            ({"value": float("inf")}, UpdaterStateUnavailableError),
            ({"value": float("-inf")}, UpdaterStateUnavailableError),
            ({"value": "x"}, UpdaterStateUnavailableError),
            ({"value": None}, UpdaterStateUnavailableError),
            ({"value": True}, UpdaterStateUnavailableError),
            ({"value": []}, UpdaterStateUnavailableError),
            ({"value": {}}, UpdaterStateUnavailableError),
            ({"value": object()}, UpdaterStateUnavailableError),
            ({}, UpdaterStateUnavailableError),
            ("garbage", UpdaterStateUnavailableError),
            (None, UpdaterStateUnavailableError),
        ):
            with self.subTest(response=response):
                calls = []

                def rpc(method, params, response=response):
                    calls.append(method)
                    return response

                guard = AddonUpdateGuard(KodiJsonRpcUpdatePolicyBackend(rpc))
                if expected is None:
                    guard.verify_quarantined()
                else:
                    with self.assertRaises(expected) as raised:
                        guard.verify_quarantined()
                    if expected is UpdaterNotQuarantinedError:
                        self.assertEqual(
                            "FROZEN_UPDATER_NOT_QUARANTINED", raised.exception.code
                        )
                    else:
                        self.assertEqual(
                            "FROZEN_UPDATER_STATE_UNAVAILABLE", raised.exception.code
                        )
                self.assertEqual(["Settings.GetSettingValue"], calls)
                self.assertNotIn("Settings.SetSettingValue", calls)

    def test_a_raising_rpc_transport_is_unavailable_not_a_write(self):
        calls = []

        def rpc(method, params):
            calls.append(method)
            raise RuntimeError("rpc down")

        with self.assertRaises(UpdaterStateUnavailableError):
            AddonUpdateGuard(KodiJsonRpcUpdatePolicyBackend(rpc)).verify_quarantined()
        self.assertEqual(["Settings.GetSettingValue"], calls)

    def test_verification_leaves_the_policy_untouched_for_a_later_explicit_restore(self):
        backend = FakePolicyBackend(AddonUpdatePolicy.NEVER_CHECK)
        guard = AddonUpdateGuard(backend)
        guard.verify_quarantined()
        self.assertEqual(AddonUpdatePolicy.AUTOMATIC, guard.restore_original(AddonUpdatePolicy.AUTOMATIC))
        self.assertEqual([AddonUpdatePolicy.AUTOMATIC], backend.calls)  # only the explicit restore wrote
