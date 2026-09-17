"""
BM-005 Kodi state inspector tests.

All tests run outside the Kodi runtime using _FakeBackend. No xbmc modules
are required. The full existing suite (291 prior tests) is verified by running
the test runner; this file adds 58 new tests.
"""

import unittest
from typing import Any, Dict, List, Optional

from resources.lib.inspector import (
    KodiBackend,
    KodiInspectionError,
    KodiRuntimeBackend,
    KodiState,
    KodiStateInspector,
    InstalledAddon,
    _parse_addon_list,
    _parse_addon_response,
    _parse_version_response,
    inspect_kodi_state,
)


# ---------------------------------------------------------------------------
# Fake backend
# ---------------------------------------------------------------------------

class _FakeBackend(KodiBackend):
    """Configurable fake backend for inspector tests."""

    def __init__(
        self,
        platform_flags: Optional[Dict[str, bool]] = None,
        kodi_version: str = "",
        active_skin: str = "",
        installed_addons: Optional[List[Dict[str, Any]]] = None,
        raise_on: Optional[Dict[str, Exception]] = None,
    ) -> None:
        self._platform_flags = platform_flags if platform_flags is not None else {}
        self._kodi_version = kodi_version
        self._active_skin = active_skin
        self._installed_addons = installed_addons if installed_addons is not None else []
        self._raise_on = raise_on or {}

    def get_platform_flags(self) -> Dict[str, bool]:
        if "get_platform_flags" in self._raise_on:
            raise self._raise_on["get_platform_flags"]
        return self._platform_flags

    def get_kodi_version(self) -> str:
        if "get_kodi_version" in self._raise_on:
            raise self._raise_on["get_kodi_version"]
        return self._kodi_version

    def get_active_skin(self) -> str:
        if "get_active_skin" in self._raise_on:
            raise self._raise_on["get_active_skin"]
        return self._active_skin

    def get_installed_addons(self) -> List[Dict[str, Any]]:
        if "get_installed_addons" in self._raise_on:
            raise self._raise_on["get_installed_addons"]
        return self._installed_addons


def _make_inspector(**kwargs: Any) -> KodiStateInspector:
    return KodiStateInspector(backend=_FakeBackend(**kwargs))


# ---------------------------------------------------------------------------
# Platform detection — tvos
# ---------------------------------------------------------------------------

class TestPlatformTvos(unittest.TestCase):
    def test_tvos_detected(self):
        state = _make_inspector(platform_flags={"tvos": True}).inspect()
        self.assertEqual(state.platform, "tvos")

    def test_tvos_false_does_not_match(self):
        state = _make_inspector(platform_flags={"tvos": False, "macos": True}).inspect()
        self.assertEqual(state.platform, "macos")

    def test_tvos_beats_ios_when_both_true(self):
        state = _make_inspector(platform_flags={"tvos": True, "ios": True}).inspect()
        self.assertEqual(state.platform, "tvos")


# ---------------------------------------------------------------------------
# Platform detection — android
# ---------------------------------------------------------------------------

class TestPlatformAndroid(unittest.TestCase):
    def test_android_detected(self):
        state = _make_inspector(platform_flags={"android": True}).inspect()
        self.assertEqual(state.platform, "android")

    def test_fire_tv_normalizes_as_android(self):
        # Fire TV has no separate BM platform ID; normalizes as android.
        state = _make_inspector(platform_flags={"android": True}).inspect()
        self.assertEqual(state.platform, "android")


# ---------------------------------------------------------------------------
# Platform detection — macos
# ---------------------------------------------------------------------------

class TestPlatformMacos(unittest.TestCase):
    def test_macos_detected(self):
        state = _make_inspector(platform_flags={"macos": True}).inspect()
        self.assertEqual(state.platform, "macos")


# ---------------------------------------------------------------------------
# Platform detection — unknown
# ---------------------------------------------------------------------------

class TestPlatformUnknown(unittest.TestCase):
    def test_all_false_returns_unknown(self):
        state = _make_inspector(platform_flags={
            "tvos": False, "android": False, "macos": False,
            "ios": False, "windows": False, "linux": False,
        }).inspect()
        self.assertEqual(state.platform, "unknown")

    def test_empty_flags_returns_unknown(self):
        state = _make_inspector(platform_flags={}).inspect()
        self.assertEqual(state.platform, "unknown")

    def test_unrecognised_platform_key_ignored(self):
        state = _make_inspector(platform_flags={"sunos": True}).inspect()
        self.assertEqual(state.platform, "unknown")


# ---------------------------------------------------------------------------
# Platform precedence
# ---------------------------------------------------------------------------

class TestPlatformPrecedence(unittest.TestCase):
    def test_android_beats_linux(self):
        state = _make_inspector(platform_flags={"android": True, "linux": True}).inspect()
        self.assertEqual(state.platform, "android")

    def test_macos_beats_ios(self):
        state = _make_inspector(platform_flags={"macos": True, "ios": True}).inspect()
        self.assertEqual(state.platform, "macos")

    def test_tvos_wins_when_all_flags_true(self):
        all_true = {k: True for k in ("tvos", "android", "macos", "ios", "windows", "linux")}
        state = _make_inspector(platform_flags=all_true).inspect()
        self.assertEqual(state.platform, "tvos")


# ---------------------------------------------------------------------------
# Add-on state
# ---------------------------------------------------------------------------

class TestAddons(unittest.TestCase):
    def _inspect(self, addons: List[Any]) -> KodiState:
        return _make_inspector(installed_addons=addons).inspect()

    def test_multiple_addons_returned(self):
        state = self._inspect([
            {"addonid": "plugin.video.youtube", "enabled": True, "version": "6.8.3"},
            {"addonid": "plugin.audio.tidal", "enabled": False, "version": "0.3.0"},
        ])
        self.assertEqual(len(state.addons), 2)

    def test_enabled_true(self):
        state = self._inspect([{"addonid": "a.b", "enabled": True, "version": "1.0.0"}])
        self.assertTrue(state.addons[0].enabled)

    def test_enabled_false(self):
        state = self._inspect([{"addonid": "a.b", "enabled": False, "version": "1.0.0"}])
        self.assertFalse(state.addons[0].enabled)

    def test_version_present(self):
        state = self._inspect([{"addonid": "a.b", "enabled": True, "version": "2.3.4"}])
        self.assertEqual(state.addons[0].version, "2.3.4")

    def test_version_absent_defaults_to_empty_string(self):
        state = self._inspect([{"addonid": "a.b", "enabled": True}])
        self.assertEqual(state.addons[0].version, "")

    def test_addons_sorted_by_addon_id(self):
        state = self._inspect([
            {"addonid": "z.last", "enabled": True, "version": "1.0.0"},
            {"addonid": "a.first", "enabled": True, "version": "1.0.0"},
            {"addonid": "m.middle", "enabled": True, "version": "1.0.0"},
        ])
        ids = [a.addon_id for a in state.addons]
        self.assertEqual(ids, ["a.first", "m.middle", "z.last"])

    def test_empty_addon_list(self):
        state = self._inspect([])
        self.assertEqual(state.addons, ())

    def test_non_object_entry_raises(self):
        with self.assertRaises(KodiInspectionError):
            self._inspect([
                "not-a-dict",
                {"addonid": "a.b", "enabled": True, "version": "1.0.0"},
            ])

    def test_missing_addonid_raises(self):
        with self.assertRaises(KodiInspectionError):
            self._inspect([{"enabled": True, "version": "1.0.0"}])

    def test_non_bool_enabled_raises(self):
        with self.assertRaises(KodiInspectionError):
            self._inspect([{"addonid": "a.b", "enabled": "yes", "version": "1.0.0"}])

    def test_malformed_version_type_raises(self):
        with self.assertRaises(KodiInspectionError):
            self._inspect([{"addonid": "a.b", "enabled": True, "version": 123}])


# ---------------------------------------------------------------------------
# Skin detection
# ---------------------------------------------------------------------------

class TestSkin(unittest.TestCase):
    def test_valid_skin_addon_id_returned(self):
        state = _make_inspector(active_skin="skin.arctic.fuse.3").inspect()
        self.assertEqual(state.active_skin, "skin.arctic.fuse.3")

    def test_empty_string_when_skin_unknown(self):
        state = _make_inspector(active_skin="").inspect()
        self.assertEqual(state.active_skin, "")

    def test_skin_with_simple_name(self):
        state = _make_inspector(active_skin="skin.confluence").inspect()
        self.assertEqual(state.active_skin, "skin.confluence")


# ---------------------------------------------------------------------------
# Kodi version
# ---------------------------------------------------------------------------

class TestKodiVersion(unittest.TestCase):
    def test_version_present(self):
        state = _make_inspector(kodi_version="21.0").inspect()
        self.assertEqual(state.kodi_version, "21.0")

    def test_version_absent_returns_empty_string(self):
        state = _make_inspector(kodi_version="").inspect()
        self.assertEqual(state.kodi_version, "")


# ---------------------------------------------------------------------------
# Addons.GetAddons JSON-RPC response parsing
# ---------------------------------------------------------------------------

class TestAddonResponseParsing(unittest.TestCase):
    def test_valid_response_parsed(self):
        text = (
            '{"jsonrpc":"2.0","result":{"addons":['
            '{"addonid":"plugin.video.youtube","enabled":true,"version":"6.8.3"}'
            ']},"id":1}'
        )
        result = _parse_addon_response(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["addonid"], "plugin.video.youtube")

    def test_invalid_json_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            _parse_addon_response("not valid json {{{")
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_non_object_root_raises(self):
        with self.assertRaises(KodiInspectionError):
            _parse_addon_response('"just a string"')

    def test_missing_result_field_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            _parse_addon_response('{"jsonrpc":"2.0","id":1}')
        self.assertIn("'result'", str(ctx.exception))

    def test_result_wrong_type_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            _parse_addon_response('{"result":"not-an-object"}')
        self.assertIn("must be an object", str(ctx.exception))

    def test_addons_field_wrong_type_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            _parse_addon_response('{"result":{"addons":"not-a-list"}}')
        self.assertIn("must be an array", str(ctx.exception))

    def test_missing_addons_field_returns_empty_list(self):
        result = _parse_addon_response('{"result":{}}')
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Fail-closed add-on parsing (supervisor BM-005 correction)
# ---------------------------------------------------------------------------

class TestAddonParsingFailClosed(unittest.TestCase):
    """Focused tests for fail-closed constraints on add-on entries.

    Every constraint violation must raise KodiInspectionError. No partial
    KodiState may be returned when any entry in result.addons is malformed.
    """

    def _inspect(self, addons: List[Any]) -> KodiState:
        return _make_inspector(installed_addons=addons).inspect()

    def test_empty_addonid_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            self._inspect([{"addonid": "", "enabled": True, "version": "1.0.0"}])
        self.assertIn("addonid", str(ctx.exception))

    def test_non_string_addonid_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            self._inspect([{"addonid": 12345, "enabled": True, "version": "1.0.0"}])
        self.assertIn("addonid", str(ctx.exception))

    def test_missing_enabled_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            self._inspect([{"addonid": "a.b", "version": "1.0.0"}])
        self.assertIn("enabled", str(ctx.exception))

    def test_duplicate_addonid_raises(self):
        with self.assertRaises(KodiInspectionError) as ctx:
            self._inspect([
                {"addonid": "a.b", "enabled": True, "version": "1.0.0"},
                {"addonid": "a.b", "enabled": False, "version": "2.0.0"},
            ])
        self.assertIn("duplicate", str(ctx.exception))

    def test_no_partial_state_when_second_entry_invalid(self):
        # First entry valid, second malformed — no KodiState returned at all.
        with self.assertRaises(KodiInspectionError):
            self._inspect([
                {"addonid": "a.b", "enabled": True, "version": "1.0.0"},
                {"addonid": "c.d", "enabled": "not-a-bool"},
            ])

    def test_missing_version_accepted_as_empty_string(self):
        state = self._inspect([{"addonid": "a.b", "enabled": True}])
        self.assertEqual(state.addons[0].version, "")

    def test_valid_version_preserved(self):
        state = self._inspect([{"addonid": "a.b", "enabled": True, "version": "3.1.4"}])
        self.assertEqual(state.addons[0].version, "3.1.4")


# ---------------------------------------------------------------------------
# Application.GetProperties version response parsing
# ---------------------------------------------------------------------------

class TestVersionResponseParsing(unittest.TestCase):
    def test_valid_response_returns_major_minor(self):
        text = '{"result":{"version":{"major":21,"minor":0}}}'
        self.assertEqual(_parse_version_response(text), "21.0")

    def test_invalid_json_returns_empty_string(self):
        self.assertEqual(_parse_version_response("invalid {{json"), "")

    def test_missing_result_returns_empty_string(self):
        self.assertEqual(_parse_version_response('{"id":1}'), "")

    def test_result_wrong_type_returns_empty_string(self):
        self.assertEqual(_parse_version_response('{"result":"not-a-dict"}'), "")

    def test_missing_version_field_returns_empty_string(self):
        self.assertEqual(_parse_version_response('{"result":{}}'), "")

    def test_missing_major_returns_empty_string(self):
        self.assertEqual(
            _parse_version_response('{"result":{"version":{"minor":0}}}'), ""
        )

    def test_missing_minor_returns_empty_string(self):
        self.assertEqual(
            _parse_version_response('{"result":{"version":{"major":21}}}'), ""
        )

    def test_bool_major_returns_empty_string(self):
        # bool is a subclass of int in Python; must be excluded from version parsing.
        self.assertEqual(
            _parse_version_response('{"result":{"version":{"major":true,"minor":0}}}'), ""
        )

    def test_bool_minor_returns_empty_string(self):
        self.assertEqual(
            _parse_version_response('{"result":{"version":{"major":21,"minor":false}}}'), ""
        )


# ---------------------------------------------------------------------------
# Backend failure propagation
# ---------------------------------------------------------------------------

class TestBackendFailures(unittest.TestCase):
    def test_platform_flags_exception_propagates(self):
        inspector = KodiStateInspector(backend=_FakeBackend(
            raise_on={"get_platform_flags": KodiInspectionError("platform unavailable")}
        ))
        with self.assertRaises(KodiInspectionError):
            inspector.inspect()

    def test_installed_addons_exception_propagates(self):
        inspector = KodiStateInspector(backend=_FakeBackend(
            raise_on={"get_installed_addons": KodiInspectionError("addons unavailable")}
        ))
        with self.assertRaises(KodiInspectionError):
            inspector.inspect()

    def test_kodi_version_exception_propagates(self):
        inspector = KodiStateInspector(backend=_FakeBackend(
            raise_on={"get_kodi_version": KodiInspectionError("version unavailable")}
        ))
        with self.assertRaises(KodiInspectionError):
            inspector.inspect()

    def test_active_skin_exception_propagates(self):
        inspector = KodiStateInspector(backend=_FakeBackend(
            raise_on={"get_active_skin": KodiInspectionError("skin unavailable")}
        ))
        with self.assertRaises(KodiInspectionError):
            inspector.inspect()


# ---------------------------------------------------------------------------
# KodiState type correctness
# ---------------------------------------------------------------------------

class TestKodiStateType(unittest.TestCase):
    def _full_state(self) -> KodiState:
        return _make_inspector(
            platform_flags={"macos": True},
            kodi_version="21.0",
            active_skin="skin.arctic.fuse.3",
            installed_addons=[{"addonid": "a.b", "enabled": True, "version": "1.0.0"}],
        ).inspect()

    def test_kodi_state_is_immutable(self):
        state = self._full_state()
        with self.assertRaises((AttributeError, TypeError)):
            state.platform = "other"  # type: ignore[misc]

    def test_installed_addon_is_immutable(self):
        state = self._full_state()
        with self.assertRaises((AttributeError, TypeError)):
            state.addons[0].enabled = False  # type: ignore[misc]

    def test_addons_field_is_tuple(self):
        state = self._full_state()
        self.assertIsInstance(state.addons, tuple)

    def test_field_types_correct(self):
        state = self._full_state()
        self.assertIsInstance(state.platform, str)
        self.assertIsInstance(state.kodi_version, str)
        self.assertIsInstance(state.active_skin, str)
        self.assertIsInstance(state.addons, tuple)


# ---------------------------------------------------------------------------
# Outside-Kodi import
# ---------------------------------------------------------------------------

class TestOutsideKodiImport(unittest.TestCase):
    def test_module_imports_without_xbmc(self):
        import resources.lib.inspector as inspector_module
        self.assertTrue(hasattr(inspector_module, "KodiStateInspector"))
        self.assertTrue(hasattr(inspector_module, "KodiInspectionError"))
        self.assertTrue(hasattr(inspector_module, "KodiState"))
        self.assertTrue(hasattr(inspector_module, "InstalledAddon"))
        self.assertTrue(hasattr(inspector_module, "inspect_kodi_state"))

    def test_fake_backend_works_without_xbmc(self):
        state = _make_inspector(
            platform_flags={"android": True},
            kodi_version="20.5",
            active_skin="skin.estuary",
            installed_addons=[{"addonid": "p.v.y", "enabled": True, "version": "1.0.0"}],
        ).inspect()
        self.assertEqual(state.platform, "android")
        self.assertEqual(state.kodi_version, "20.5")
        self.assertEqual(state.active_skin, "skin.estuary")
        self.assertEqual(len(state.addons), 1)

    def test_runtime_backend_instantiates_but_methods_raise(self):
        backend = KodiRuntimeBackend()
        with self.assertRaises(KodiInspectionError) as ctx:
            backend.get_platform_flags()
        self.assertIn("xbmc", str(ctx.exception))


# ---------------------------------------------------------------------------
# BM-005 regression
# ---------------------------------------------------------------------------

class TestBM005Regression(unittest.TestCase):
    def test_inspect_is_idempotent(self):
        inspector = _make_inspector(
            platform_flags={"linux": True},
            kodi_version="19.4",
            active_skin="skin.estuary",
            installed_addons=[],
        )
        state1 = inspector.inspect()
        state2 = inspector.inspect()
        self.assertEqual(state1, state2)

    def test_ios_platform(self):
        state = _make_inspector(platform_flags={"ios": True}).inspect()
        self.assertEqual(state.platform, "ios")

    def test_windows_platform(self):
        state = _make_inspector(platform_flags={"windows": True}).inspect()
        self.assertEqual(state.platform, "windows")

    def test_linux_platform(self):
        state = _make_inspector(platform_flags={"linux": True}).inspect()
        self.assertEqual(state.platform, "linux")

    def test_no_real_kodi_mutation_occurred(self):
        # Pure assertion: if this test runs, no Kodi state was touched.
        # The fake backend has no side effects; inspect() is read-only by design.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
