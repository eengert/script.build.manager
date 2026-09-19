"""Unit tests for BM-018A skin activation."""

import unittest
from typing import Dict, List

from resources.lib.skin import (
    SkinActivator,
    SkinBackend,
    SkinResult,
    SkinState,
    SkinStatus,
    SkinValidationError,
)


class FakeSkinBackend(SkinBackend):
    def __init__(self, active="skin.estuary", skins=None):
        self.active = active
        self.skins: Dict[str, SkinState] = dict(skins or {})
        self.calls: List[str] = []

    def get_active_skin(self):
        self.calls.append("get_active")
        return self.active

    def get_skin_state(self, addon_id):
        self.calls.append(f"get_state:{addon_id}")
        return self.skins.get(addon_id, SkinState(False, False))

    def activate_skin(self, addon_id):
        self.calls.append(f"activate:{addon_id}")
        self.active = addon_id

    def confirm_skin_change(self):
        self.calls.append("confirm")


class TestSkinActivator(unittest.TestCase):
    def test_invalid_id_rejected_before_backend(self):
        backend = FakeSkinBackend()
        with self.assertRaises(SkinValidationError):
            SkinActivator(backend).activate("skin.foo;evil")
        self.assertEqual(backend.calls, [])

    def test_already_active_is_noop(self):
        backend = FakeSkinBackend(active="skin.arctic.fuse.3")
        result = SkinActivator(backend).activate("skin.arctic.fuse.3")
        self.assertEqual(result.status, SkinStatus.ALREADY_ACTIVE)
        self.assertEqual(backend.calls, ["get_active"])

    def test_missing_or_disabled_is_failure_without_activation(self):
        for state in (SkinState(False, False), SkinState(True, False)):
            backend = FakeSkinBackend(skins={"skin.foo": state})
            result = SkinActivator(backend).activate("skin.foo")
            self.assertEqual(result.status, SkinStatus.FAILED)
            self.assertNotIn("activate:skin.foo", backend.calls)

    def test_activation_confirms_and_verifies(self):
        backend = FakeSkinBackend(skins={"skin.foo": SkinState(True, True)})
        result = SkinActivator(backend, sleep=lambda _: None).activate("skin.foo")
        self.assertEqual(result, SkinResult(
            "skin.foo", SkinStatus.ACTIVATED, "skin.foo",
            "Skin activated and verified",
        ))
        self.assertEqual(backend.calls, [
            "get_active", "get_state:skin.foo", "activate:skin.foo",
            "confirm", "get_active",
        ])

    def test_revert_is_failure(self):
        class RevertingBackend(FakeSkinBackend):
            def activate_skin(self, addon_id):
                self.calls.append(f"activate:{addon_id}")
                self.active = "skin.estuary"

        backend = RevertingBackend(skins={"skin.foo": SkinState(True, True)})
        result = SkinActivator(backend, timeout=0).activate("skin.foo")
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertIn("did not remain active", result.message)

    def test_runtime_backend_is_importable_without_kodi(self):
        from resources.lib.skin import KodiRuntimeSkinBackend
        self.assertIsNotNone(KodiRuntimeSkinBackend())


if __name__ == "__main__":
    unittest.main()
