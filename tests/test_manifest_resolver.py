"""
BM-004: Profile resolver tests.

Tests resolve_manifest() using the typed Manifest produced by BM-003.
No Kodi runtime imports. No real Kodi profiles are touched.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)

from resources.lib.manifest import (
    AddonEntry,
    BuildInfo,
    ConfigDeclarations,
    DeviceProfile,
    Manifest,
    ManagedSettingScope,
    OptionalGroup,
    ProfileLayer,
    PrivateOverlayRef,
    Repository,
    RestartPolicy,
    SkinEntry,
    validate_manifest,
    load_manifest_file,
)
from resources.lib.resolver import (
    ManifestResolutionError,
    ResolvedBuild,
    resolve_manifest,
)

ERIC_MAIN_PATH = os.path.join(
    REPO_ROOT, "resources", "builds", "examples", "eric-main.example.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _addon(addon_id, state, note=""):
    return {"addon_id": addon_id, "state": state, **({"note": note} if note else {})}


def _skin(addon_id, config_packages=None):
    d = {"addon_id": addon_id}
    if config_packages is not None:
        d["config_packages"] = config_packages
    return d


def _config(packages=None, managed_settings=None, managed_files=None):
    d = {}
    if packages is not None:
        d["packages"] = packages
    if managed_settings is not None:
        d["managed_settings"] = managed_settings
    if managed_files is not None:
        d["managed_files"] = managed_files
    return d


def _ms(addon_id, keys, target=None):
    result = {"addon_id": addon_id, "keys": keys}
    if target is not None:
        result["target"] = target
    return result


def _make(doc):
    """Validate a manifest dict and return the typed Manifest."""
    return validate_manifest(doc)


def _base(extra=None):
    """Minimal manifest dict with a platform 'tvos' and device 'dev' (no profiles)."""
    doc = {
        "schema_version": 1,
        "build": {"id": "test", "version": "0.1.0"},
        "platform_profiles": {"tvos": {}},
        "device_profiles": {"dev": {"extends": "tvos"}},
    }
    if extra:
        doc.update(extra)
    return doc


# ---------------------------------------------------------------------------
# Base only: no platform or device overrides
# ---------------------------------------------------------------------------

class TestBaseOnly(unittest.TestCase):
    """Base-layer fields pass through when platform and device add nothing."""

    def setUp(self):
        doc = _base({
            "addons": [
                _addon("plugin.video.foo", "enabled"),
                _addon("plugin.video.bar", "disabled"),
            ],
            "skin": _skin("skin.test", ["pkg-a"]),
            "config": _config(
                packages=["pkg-a", "pkg-b"],
                managed_settings=[_ms("plugin.video.foo", ["key1", "key2"])],
                managed_files=["addon_data/skin.test/settings.xml"],
            ),
        })
        self.m = _make(doc)

    def test_base_addons_preserved(self):
        r = resolve_manifest(self.m, "dev")
        self.assertEqual(len(r.addons), 2)
        self.assertEqual(r.addons[0].addon_id, "plugin.video.foo")
        self.assertEqual(r.addons[0].state, "enabled")
        self.assertEqual(r.addons[1].addon_id, "plugin.video.bar")
        self.assertEqual(r.addons[1].state, "disabled")

    def test_base_skin_preserved(self):
        r = resolve_manifest(self.m, "dev")
        self.assertIsNotNone(r.skin)
        self.assertEqual(r.skin.addon_id, "skin.test")
        self.assertEqual(r.skin.config_packages, ("pkg-a",))

    def test_base_config_packages_preserved(self):
        r = resolve_manifest(self.m, "dev")
        self.assertIsNotNone(r.config)
        self.assertEqual(r.config.packages, ("pkg-a", "pkg-b"))

    def test_base_config_managed_settings_preserved(self):
        r = resolve_manifest(self.m, "dev")
        self.assertEqual(len(r.config.managed_settings), 1)
        self.assertEqual(r.config.managed_settings[0].addon_id, "plugin.video.foo")
        self.assertEqual(r.config.managed_settings[0].keys, ("key1", "key2"))

    def test_base_config_managed_files_preserved(self):
        r = resolve_manifest(self.m, "dev")
        self.assertEqual(r.config.managed_files, ("addon_data/skin.test/settings.xml",))

    def test_result_identity_fields(self):
        r = resolve_manifest(self.m, "dev")
        self.assertEqual(r.build.id, "test")
        self.assertEqual(r.platform_profile_id, "tvos")
        self.assertEqual(r.device_profile_id, "dev")
        self.assertEqual(r.optional_groups_applied, ())

    def test_no_base_config_returns_none_config(self):
        m = _make(_base())
        r = resolve_manifest(m, "dev")
        self.assertIsNone(r.config)

    def test_no_base_skin_returns_none_skin(self):
        m = _make(_base())
        r = resolve_manifest(m, "dev")
        self.assertIsNone(r.skin)


# ---------------------------------------------------------------------------
# Platform overrides
# ---------------------------------------------------------------------------

class TestPlatformOverrides(unittest.TestCase):

    def test_config_scopes_merge_by_target_kind(self):
        doc = _base({
            "config": {"managed_settings": [
                _ms("same.id", ["key"], target="addon"),
                _ms("same.id", ["key"], target="skin"),
            ]},
        })
        resolved = resolve_manifest(_make(doc), "dev")
        self.assertEqual(
            [(scope.target_kind.value, scope.addon_id, scope.keys)
             for scope in resolved.config.managed_settings],
            [("addon", "same.id", ("key",)),
             ("skin", "same.id", ("key",))],
        )

    def test_platform_overrides_existing_addon_state(self):
        doc = _base({
            "addons": [_addon("plugin.video.foo", "enabled")],
            "platform_profiles": {"tvos": {
                "addons": [_addon("plugin.video.foo", "disabled")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(len(r.addons), 1)
        self.assertEqual(r.addons[0].state, "disabled")

    def test_platform_adds_new_addon(self):
        doc = _base({
            "addons": [_addon("plugin.video.foo", "enabled")],
            "platform_profiles": {"tvos": {
                "addons": [_addon("plugin.video.bar", "enabled")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        ids = [a.addon_id for a in r.addons]
        self.assertIn("plugin.video.foo", ids)
        self.assertIn("plugin.video.bar", ids)

    def test_platform_omitted_addon_unchanged(self):
        doc = _base({
            "addons": [
                _addon("plugin.video.foo", "enabled"),
                _addon("plugin.video.bar", "enabled"),
            ],
            "platform_profiles": {"tvos": {
                "addons": [_addon("plugin.video.foo", "disabled")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        bar = next(a for a in r.addons if a.addon_id == "plugin.video.bar")
        self.assertEqual(bar.state, "enabled")

    def test_platform_skin_overrides_base(self):
        doc = _base({
            "skin": _skin("skin.base"),
            "platform_profiles": {"tvos": {
                "skin": _skin("skin.platform", ["plat-pkg"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.skin.addon_id, "skin.platform")
        self.assertEqual(r.skin.config_packages, ("plat-pkg",))

    def test_platform_config_packages_merged(self):
        doc = _base({
            "config": _config(packages=["base-pkg"]),
            "platform_profiles": {"tvos": {
                "config": _config(packages=["plat-pkg"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.config.packages, ("base-pkg", "plat-pkg"))

    def test_platform_config_managed_settings_keys_unioned(self):
        doc = _base({
            "config": _config(
                managed_settings=[_ms("plugin.video.foo", ["key1"])]
            ),
            "platform_profiles": {"tvos": {
                "config": _config(
                    managed_settings=[_ms("plugin.video.foo", ["key2"])]
                )
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        scope = r.config.managed_settings[0]
        self.assertEqual(scope.addon_id, "plugin.video.foo")
        self.assertIn("key1", scope.keys)
        self.assertIn("key2", scope.keys)

    def test_platform_config_managed_files_unioned(self):
        doc = _base({
            "config": _config(managed_files=["file-a.xml"]),
            "platform_profiles": {"tvos": {
                "config": _config(managed_files=["file-b.xml"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertIn("file-a.xml", r.config.managed_files)
        self.assertIn("file-b.xml", r.config.managed_files)

    def test_absent_base_skin_platform_skin_used(self):
        doc = _base({
            "platform_profiles": {"tvos": {
                "skin": _skin("skin.platform")
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.skin.addon_id, "skin.platform")


# ---------------------------------------------------------------------------
# Device overrides
# ---------------------------------------------------------------------------

class TestDeviceOverrides(unittest.TestCase):

    def test_device_override_wins_over_platform(self):
        doc = _base({
            "addons": [_addon("plugin.video.foo", "enabled")],
            "platform_profiles": {"tvos": {
                "addons": [_addon("plugin.video.foo", "disabled")]
            }},
            "device_profiles": {"dev": {
                "extends": "tvos",
                "addons": [_addon("plugin.video.foo", "absent")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.addons[0].state, "absent")

    def test_device_adds_new_addon_appended(self):
        doc = _base({
            "addons": [_addon("plugin.video.foo", "enabled")],
            "device_profiles": {"dev": {
                "extends": "tvos",
                "addons": [_addon("plugin.video.baz", "enabled")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        ids = [a.addon_id for a in r.addons]
        self.assertEqual(ids[-1], "plugin.video.baz")

    def test_device_skin_wins_over_platform(self):
        doc = _base({
            "skin": _skin("skin.base"),
            "platform_profiles": {"tvos": {
                "skin": _skin("skin.platform")
            }},
            "device_profiles": {"dev": {
                "extends": "tvos",
                "skin": _skin("skin.device", ["dev-pkg"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.skin.addon_id, "skin.device")
        self.assertEqual(r.skin.config_packages, ("dev-pkg",))

    def test_device_config_merges_with_platform(self):
        doc = _base({
            "config": _config(packages=["base-pkg"]),
            "platform_profiles": {"tvos": {
                "config": _config(packages=["plat-pkg"])
            }},
            "device_profiles": {"dev": {
                "extends": "tvos",
                "config": _config(packages=["dev-pkg"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertIn("base-pkg", r.config.packages)
        self.assertIn("plat-pkg", r.config.packages)
        self.assertIn("dev-pkg", r.config.packages)

    def test_device_without_skin_inherits_platform_skin(self):
        doc = _base({
            "platform_profiles": {"tvos": {
                "skin": _skin("skin.platform")
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.skin.addon_id, "skin.platform")


# ---------------------------------------------------------------------------
# Skin configuration package selection (BM-018B)
# ---------------------------------------------------------------------------

class TestSkinConfigPackages(unittest.TestCase):

    def test_ordinary_config_only_is_unchanged(self):
        r = resolve_manifest(_make(_base({
            "config": _config(packages=["ordinary"]),
        })), "dev")
        self.assertEqual(r.config.packages, ("ordinary",))

    def test_skin_packages_only_create_config(self):
        r = resolve_manifest(_make(_base({
            "skin": _skin("skin.foo", ["skin-a"]),
        })), "dev")
        self.assertEqual(r.config.packages, ("skin-a",))
        self.assertEqual(r.config.managed_settings, ())
        self.assertEqual(r.config.managed_files, ())

    def test_ordinary_then_skin_packages(self):
        r = resolve_manifest(_make(_base({
            "config": _config(packages=["ordinary"]),
            "skin": _skin("skin.foo", ["skin-a", "skin-b"]),
        })), "dev")
        self.assertEqual(r.config.packages, ("ordinary", "skin-a", "skin-b"))

    def test_duplicate_packages_are_first_seen_once(self):
        r = resolve_manifest(_make(_base({
            "config": _config(packages=["shared", "ordinary"]),
            "skin": _skin("skin.foo", ["shared", "skin-a"]),
        })), "dev")
        self.assertEqual(r.config.packages, ("shared", "ordinary", "skin-a"))

    def test_skin_package_order_is_preserved(self):
        r = resolve_manifest(_make(_base({
            "skin": _skin("skin.foo", ["z", "a", "m"]),
        })), "dev")
        self.assertEqual(r.config.packages, ("z", "a", "m"))

    def test_deeper_skin_replaces_parent_package_list(self):
        r = resolve_manifest(_make(_base({
            "skin": _skin("skin.base", ["base-skin"]),
            "platform_profiles": {"tvos": {
                "skin": _skin("skin.platform", ["platform-skin"]),
            }},
            "device_profiles": {"dev": {
                "extends": "tvos",
                "skin": _skin("skin.device", ["device-skin"]),
            }},
        })), "dev")
        self.assertEqual(r.config.packages, ("device-skin",))

    def test_inherited_skin_retains_package_list(self):
        r = resolve_manifest(_make(_base({
            "skin": _skin("skin.base", ["base-skin"]),
        })), "dev")
        self.assertEqual(r.config.packages, ("base-skin",))

    def test_optional_config_precedes_skin_packages(self):
        r = resolve_manifest(_make(_base({
            "skin": _skin("skin.foo", ["skin-pkg"]),
            "platform_profiles": {"tvos": {
                "include_optional": ["extras"],
            }},
            "optional": [{
                "id": "extras",
                "config": _config(packages=["optional-pkg"]),
            }],
        })), "dev")
        self.assertEqual(r.config.packages, ("optional-pkg", "skin-pkg"))

    def test_empty_skin_packages_do_not_create_config(self):
        r = resolve_manifest(_make(_base({
            "skin": _skin("skin.foo", []),
        })), "dev")
        self.assertIsNone(r.config)


# ---------------------------------------------------------------------------
# Optional groups
# ---------------------------------------------------------------------------

class TestOptionalGroups(unittest.TestCase):

    def _doc_with_optional(self, platform_include=None, device_include=None, groups=None):
        doc = {
            "schema_version": 1,
            "build": {"id": "test", "version": "0.1.0"},
            "addons": [_addon("plugin.video.base", "enabled")],
            "platform_profiles": {"tvos": {
                "include_optional": platform_include or []
            }},
            "device_profiles": {"dev": {
                "extends": "tvos",
                "include_optional": device_include or [],
            }},
        }
        if groups:
            doc["optional"] = groups
        return doc

    def test_platform_requested_group_applied(self):
        doc = self._doc_with_optional(
            platform_include=["extras"],
            groups=[{
                "id": "extras",
                "addons": [_addon("plugin.video.extra", "enabled")]
            }],
        )
        r = resolve_manifest(_make(doc), "dev")
        ids = [a.addon_id for a in r.addons]
        self.assertIn("plugin.video.extra", ids)
        self.assertEqual(r.optional_groups_applied, ("extras",))

    def test_device_requested_group_applied(self):
        doc = self._doc_with_optional(
            device_include=["extras"],
            groups=[{
                "id": "extras",
                "addons": [_addon("plugin.video.extra", "enabled")]
            }],
        )
        r = resolve_manifest(_make(doc), "dev")
        ids = [a.addon_id for a in r.addons]
        self.assertIn("plugin.video.extra", ids)
        self.assertEqual(r.optional_groups_applied, ("extras",))

    def test_same_group_in_platform_and_device_applied_once(self):
        doc = self._doc_with_optional(
            platform_include=["extras"],
            device_include=["extras"],
            groups=[{
                "id": "extras",
                "addons": [_addon("plugin.video.extra", "enabled")]
            }],
        )
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.optional_groups_applied, ("extras",))
        extra_count = sum(1 for a in r.addons if a.addon_id == "plugin.video.extra")
        self.assertEqual(extra_count, 1)

    def test_multiple_groups_applied_in_deterministic_order(self):
        doc = self._doc_with_optional(
            platform_include=["group-a", "group-b"],
            groups=[
                {"id": "group-a", "addons": [_addon("plugin.video.ga", "enabled")]},
                {"id": "group-b", "addons": [_addon("plugin.video.gb", "enabled")]},
            ],
        )
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.optional_groups_applied, ("group-a", "group-b"))
        ids = [a.addon_id for a in r.addons]
        self.assertLess(ids.index("plugin.video.ga"), ids.index("plugin.video.gb"))

    def test_platform_then_device_group_order(self):
        doc = self._doc_with_optional(
            platform_include=["group-a"],
            device_include=["group-b"],
            groups=[
                {"id": "group-a", "addons": [_addon("plugin.video.ga", "enabled")]},
                {"id": "group-b", "addons": [_addon("plugin.video.gb", "enabled")]},
            ],
        )
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.optional_groups_applied, ("group-a", "group-b"))

    def test_dedup_by_first_occurrence_platform_wins(self):
        """When platform and device both request group-a then group-b in different orders."""
        doc = self._doc_with_optional(
            platform_include=["group-a", "group-b"],
            device_include=["group-b", "group-a"],
            groups=[
                {"id": "group-a", "addons": [_addon("plugin.video.ga", "enabled")]},
                {"id": "group-b", "addons": [_addon("plugin.video.gb", "enabled")]},
            ],
        )
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.optional_groups_applied, ("group-a", "group-b"))

    def test_optional_addon_override_wins_after_device(self):
        doc = self._doc_with_optional(
            platform_include=["extras"],
            groups=[{
                "id": "extras",
                "addons": [_addon("plugin.video.base", "absent")]
            }],
        )
        r = resolve_manifest(_make(doc), "dev")
        base_addon = next(a for a in r.addons if a.addon_id == "plugin.video.base")
        self.assertEqual(base_addon.state, "absent")

    def test_optional_config_merges_correctly(self):
        doc = self._doc_with_optional(
            platform_include=["extras"],
            groups=[{
                "id": "extras",
                "config": _config(packages=["extras-pkg"])
            }],
        )
        doc["config"] = _config(packages=["base-pkg"])
        r = resolve_manifest(_make(doc), "dev")
        self.assertIn("base-pkg", r.config.packages)
        self.assertIn("extras-pkg", r.config.packages)


# ---------------------------------------------------------------------------
# Add-on states
# ---------------------------------------------------------------------------

class TestAddonStates(unittest.TestCase):

    def test_enabled_state_resolved(self):
        doc = _base({"addons": [_addon("plugin.video.foo", "enabled")]})
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.addons[0].state, "enabled")

    def test_disabled_state_resolved(self):
        doc = _base({"addons": [_addon("plugin.video.foo", "disabled")]})
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.addons[0].state, "disabled")

    def test_absent_state_resolved(self):
        doc = _base({"addons": [_addon("plugin.video.foo", "absent")]})
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.addons[0].state, "absent")

    def test_absent_remains_in_resolved_set(self):
        doc = _base({
            "addons": [_addon("plugin.video.foo", "enabled")],
            "device_profiles": {"dev": {
                "extends": "tvos",
                "addons": [_addon("plugin.video.foo", "absent")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(len(r.addons), 1)
        self.assertEqual(r.addons[0].state, "absent")

    def test_platform_disabled_then_device_enabled(self):
        doc = _base({
            "addons": [_addon("plugin.video.foo", "enabled")],
            "platform_profiles": {"tvos": {
                "addons": [_addon("plugin.video.foo", "disabled")]
            }},
            "device_profiles": {"dev": {
                "extends": "tvos",
                "addons": [_addon("plugin.video.foo", "enabled")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.addons[0].state, "enabled")


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------

class TestOrdering(unittest.TestCase):

    def test_addon_order_base_then_new(self):
        doc = _base({
            "addons": [
                _addon("plugin.video.a", "enabled"),
                _addon("plugin.video.b", "enabled"),
            ],
            "platform_profiles": {"tvos": {
                "addons": [_addon("plugin.video.c", "enabled")]
            }},
            "device_profiles": {"dev": {
                "extends": "tvos",
                "addons": [_addon("plugin.video.d", "enabled")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        ids = [a.addon_id for a in r.addons]
        self.assertEqual(ids, [
            "plugin.video.a", "plugin.video.b",
            "plugin.video.c", "plugin.video.d",
        ])

    def test_overridden_addon_retains_original_position(self):
        doc = _base({
            "addons": [
                _addon("plugin.video.a", "enabled"),
                _addon("plugin.video.b", "enabled"),
                _addon("plugin.video.c", "enabled"),
            ],
            "device_profiles": {"dev": {
                "extends": "tvos",
                "addons": [_addon("plugin.video.b", "disabled")]
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        ids = [a.addon_id for a in r.addons]
        self.assertEqual(ids, ["plugin.video.a", "plugin.video.b", "plugin.video.c"])
        self.assertEqual(r.addons[1].state, "disabled")

    def test_packages_first_seen_order(self):
        doc = _base({
            "config": _config(packages=["pkg-1", "pkg-2"]),
            "platform_profiles": {"tvos": {
                "config": _config(packages=["pkg-3", "pkg-1"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(list(r.config.packages).index("pkg-1"), 0)
        self.assertEqual(list(r.config.packages).index("pkg-2"), 1)
        self.assertEqual(list(r.config.packages).index("pkg-3"), 2)

    def test_duplicate_packages_ignored(self):
        doc = _base({
            "config": _config(packages=["pkg-a"]),
            "platform_profiles": {"tvos": {
                "config": _config(packages=["pkg-a", "pkg-b"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.config.packages.count("pkg-a"), 1)

    def test_managed_settings_addon_first_seen_order(self):
        doc = _base({
            "config": _config(managed_settings=[_ms("plugin.a", ["k1"])]),
            "platform_profiles": {"tvos": {
                "config": _config(managed_settings=[_ms("plugin.b", ["k2"])])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        addon_ids = [s.addon_id for s in r.config.managed_settings]
        self.assertEqual(addon_ids, ["plugin.a", "plugin.b"])

    def test_managed_settings_keys_first_seen_order(self):
        doc = _base({
            "config": _config(managed_settings=[_ms("plugin.a", ["k1", "k2"])]),
            "platform_profiles": {"tvos": {
                "config": _config(managed_settings=[_ms("plugin.a", ["k3", "k1"])])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.config.managed_settings[0].keys, ("k1", "k2", "k3"))

    def test_managed_files_first_seen_order_no_duplicates(self):
        doc = _base({
            "config": _config(managed_files=["file-a.xml", "file-b.xml"]),
            "platform_profiles": {"tvos": {
                "config": _config(managed_files=["file-c.xml", "file-a.xml"])
            }},
        })
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(list(r.config.managed_files).index("file-a.xml"), 0)
        self.assertEqual(list(r.config.managed_files).index("file-b.xml"), 1)
        self.assertEqual(list(r.config.managed_files).index("file-c.xml"), 2)
        self.assertEqual(r.config.managed_files.count("file-a.xml"), 1)

    def test_optional_group_application_order(self):
        """Groups are applied platform-first, then device, deduped by first occurrence."""
        doc = {
            "schema_version": 1,
            "build": {"id": "test", "version": "0.1.0"},
            "platform_profiles": {"tvos": {"include_optional": ["grp-a", "grp-b"]}},
            "device_profiles": {"dev": {"extends": "tvos", "include_optional": ["grp-c"]}},
            "optional": [
                {"id": "grp-a", "addons": [_addon("plugin.video.a", "enabled")]},
                {"id": "grp-b", "addons": [_addon("plugin.video.b", "enabled")]},
                {"id": "grp-c", "addons": [_addon("plugin.video.c", "enabled")]},
            ],
        }
        r = resolve_manifest(_make(doc), "dev")
        self.assertEqual(r.optional_groups_applied, ("grp-a", "grp-b", "grp-c"))
        ids = [a.addon_id for a in r.addons]
        self.assertLess(ids.index("plugin.video.a"), ids.index("plugin.video.b"))
        self.assertLess(ids.index("plugin.video.b"), ids.index("plugin.video.c"))


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors(unittest.TestCase):

    def test_unknown_device_profile_raises(self):
        m = _make(_base())
        with self.assertRaises(ManifestResolutionError) as ctx:
            resolve_manifest(m, "nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_error_message_names_the_device(self):
        m = _make(_base())
        with self.assertRaises(ManifestResolutionError) as ctx:
            resolve_manifest(m, "my-device")
        self.assertIn("my-device", str(ctx.exception))

    def test_missing_platform_in_constructed_manifest_raises(self):
        """Manually-constructed Manifest where device.extends has no matching platform."""
        m = Manifest(
            schema_version=1,
            build=BuildInfo(id="test", version="0.1.0"),
            platform_profiles={},
            device_profiles={
                "test-device": DeviceProfile(extends="missing-platform")
            },
        )
        with self.assertRaises(ManifestResolutionError) as ctx:
            resolve_manifest(m, "test-device")
        self.assertIn("missing-platform", str(ctx.exception))

    def test_missing_optional_group_in_constructed_manifest_raises(self):
        """Manually-constructed Manifest where platform.include_optional references a missing group."""
        m = Manifest(
            schema_version=1,
            build=BuildInfo(id="test", version="0.1.0"),
            platform_profiles={
                "tvos": ProfileLayer(include_optional=("no-such-group",))
            },
            device_profiles={
                "test-device": DeviceProfile(extends="tvos")
            },
        )
        with self.assertRaises(ManifestResolutionError) as ctx:
            resolve_manifest(m, "test-device")
        self.assertIn("no-such-group", str(ctx.exception))

    def test_resolution_error_is_manifest_error_subclass(self):
        from resources.lib.manifest import ManifestError
        self.assertTrue(issubclass(ManifestResolutionError, ManifestError))


# ---------------------------------------------------------------------------
# Example: eric-main.example.json
# ---------------------------------------------------------------------------

class TestEricMain(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manifest = load_manifest_file(ERIC_MAIN_PATH)

    # --- bonus-room (tvos, no optional groups) ---

    def test_bonus_room_resolves(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        self.assertIsInstance(r, ResolvedBuild)

    def test_bonus_room_platform(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        self.assertEqual(r.platform_profile_id, "tvos")

    def test_bonus_room_no_optional_groups(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        self.assertEqual(r.optional_groups_applied, ())

    def test_bonus_room_af3_enabled(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        af3 = next(a for a in r.addons if a.addon_id == "skin.arctic.fuse.3")
        self.assertEqual(af3.state, "enabled")

    def test_bonus_room_redlight_enabled(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        rl = next(a for a in r.addons if a.addon_id == "plugin.video.redlight")
        self.assertEqual(rl.state, "enabled")

    def test_bonus_room_tmdb_helper_disabled(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        tmdb = next(
            a for a in r.addons
            if a.addon_id == "plugin.video.themoviedb.helper"
        )
        self.assertEqual(tmdb.state, "disabled")

    def test_bonus_room_pov_enabled(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        pov = next(a for a in r.addons if a.addon_id == "plugin.video.pov")
        self.assertEqual(pov.state, "enabled")

    def test_bonus_room_umbrella_enabled(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        umb = next(a for a in r.addons if a.addon_id == "plugin.video.umbrella")
        self.assertEqual(umb.state, "enabled")

    def test_bonus_room_skin_is_af3(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        self.assertIsNotNone(r.skin)
        self.assertEqual(r.skin.addon_id, "skin.arctic.fuse.3")

    def test_bonus_room_repositories_carried(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        self.assertEqual(len(r.repositories), 1)
        self.assertEqual(r.repositories[0].addon_id, "repository.eengert")

    def test_bonus_room_restart_policy_carried(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        self.assertIsNotNone(r.restart_policy)
        self.assertTrue(r.restart_policy.allow_skin_reload)

    def test_bonus_room_private_overlay_reference_preserved(self):
        r = resolve_manifest(self.manifest, "bonus-room")
        self.assertIsNotNone(r.private_overlay)
        self.assertEqual(r.private_overlay.type, "local_file")

    # --- family-room (tvos, no device overrides) ---

    def test_family_room_base_addons_unchanged(self):
        r = resolve_manifest(self.manifest, "family-room")
        all_enabled = [
            "skin.arctic.fuse.3", "plugin.video.redlight",
            "plugin.video.themoviedb.helper", "plugin.video.pov",
            "plugin.video.umbrella",
        ]
        addon_map = {a.addon_id: a.state for a in r.addons}
        for addon_id in all_enabled:
            self.assertEqual(addon_map[addon_id], "enabled", addon_id)

    # --- shield (android platform, shield-extras optional group) ---

    def test_shield_resolves(self):
        r = resolve_manifest(self.manifest, "shield")
        self.assertIsInstance(r, ResolvedBuild)

    def test_shield_platform_is_android(self):
        r = resolve_manifest(self.manifest, "shield")
        self.assertEqual(r.platform_profile_id, "android")

    def test_shield_pov_disabled_by_android_platform(self):
        r = resolve_manifest(self.manifest, "shield")
        pov = next(a for a in r.addons if a.addon_id == "plugin.video.pov")
        self.assertEqual(pov.state, "disabled")

    def test_shield_umbrella_enabled(self):
        r = resolve_manifest(self.manifest, "shield")
        umb = next(a for a in r.addons if a.addon_id == "plugin.video.umbrella")
        self.assertEqual(umb.state, "enabled")

    def test_shield_extras_group_applied(self):
        r = resolve_manifest(self.manifest, "shield")
        self.assertIn("shield-extras", r.optional_groups_applied)

    def test_shield_android_helper_added_by_optional_group(self):
        r = resolve_manifest(self.manifest, "shield")
        ids = [a.addon_id for a in r.addons]
        self.assertIn("plugin.video.example.android-helper", ids)

    def test_shield_tmdb_helper_still_enabled(self):
        r = resolve_manifest(self.manifest, "shield")
        tmdb = next(
            a for a in r.addons
            if a.addon_id == "plugin.video.themoviedb.helper"
        )
        self.assertEqual(tmdb.state, "enabled")

    def test_shield_skin_inherited_from_base(self):
        r = resolve_manifest(self.manifest, "shield")
        self.assertIsNotNone(r.skin)
        self.assertEqual(r.skin.addon_id, "skin.arctic.fuse.3")

    def test_shield_config_packages_from_base(self):
        r = resolve_manifest(self.manifest, "shield")
        self.assertIsNotNone(r.config)
        self.assertIn("af3-common", r.config.packages)
        self.assertIn("redlight-common", r.config.packages)


# ---------------------------------------------------------------------------
# Typed representation of ResolvedBuild
# ---------------------------------------------------------------------------

class TestResolvedBuildType(unittest.TestCase):

    def test_result_is_resolved_build_instance(self):
        m = _make(_base())
        r = resolve_manifest(m, "dev")
        self.assertIsInstance(r, ResolvedBuild)

    def test_result_is_frozen(self):
        m = _make(_base())
        r = resolve_manifest(m, "dev")
        with self.assertRaises((AttributeError, TypeError)):
            r.device_profile_id = "changed"  # type: ignore[misc]

    def test_addons_is_tuple(self):
        m = _make(_base({"addons": [_addon("plugin.video.foo", "enabled")]}))
        r = resolve_manifest(m, "dev")
        self.assertIsInstance(r.addons, tuple)

    def test_optional_groups_applied_is_tuple(self):
        m = _make(_base())
        r = resolve_manifest(m, "dev")
        self.assertIsInstance(r.optional_groups_applied, tuple)

    def test_repositories_is_tuple(self):
        m = _make(_base())
        r = resolve_manifest(m, "dev")
        self.assertIsInstance(r.repositories, tuple)


# ---------------------------------------------------------------------------
# Regression: all BM-001/BM-002/BM-003 tests still pass
# ---------------------------------------------------------------------------

class TestBM004Regression(unittest.TestCase):

    def test_manifest_module_still_importable(self):
        import resources.lib.manifest as mod
        self.assertIsNotNone(mod)

    def test_resolver_module_importable(self):
        import resources.lib.resolver as mod
        self.assertIsNotNone(mod)

    def test_no_kodi_imports_in_resolver(self):
        import sys
        import resources.lib.resolver  # noqa: F401
        for mod_name in sys.modules:
            if mod_name.startswith("xbmc") or mod_name.startswith("xbmcaddon"):
                self.fail(f"resolver.py triggered Kodi import: {mod_name}")

    def test_bm003_validate_manifest_still_works(self):
        from resources.lib.manifest import validate_manifest
        m = validate_manifest({
            "schema_version": 1,
            "build": {"id": "test", "version": "0.1.0"},
        })
        self.assertEqual(m.build.id, "test")


if __name__ == "__main__":
    unittest.main()
