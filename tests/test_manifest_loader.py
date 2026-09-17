"""
BM-003: Manifest loader and validator tests.

Tests the production manifest.py module using Python stdlib only.
No Kodi runtime imports. No real Kodi profiles are touched.
"""

import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)

from resources.lib.manifest import (
    AddonEntry,
    BuildInfo,
    ConfigDeclarations,
    DeviceProfile,
    Manifest,
    ManifestError,
    ManifestParseError,
    ManifestValidationError,
    ManagedSettingScope,
    OptionalGroup,
    PrivateOverlayRef,
    ProfileLayer,
    Repository,
    RestartPolicy,
    SkinEntry,
    load_manifest_file,
    load_manifest_json,
    validate_manifest,
)

MINIMAL_PATH = os.path.join(REPO_ROOT, "resources", "builds", "examples", "minimal.json")
ERIC_MAIN_PATH = os.path.join(REPO_ROOT, "resources", "builds", "examples", "eric-main.example.json")


def _make(overrides=None, remove=None):
    """Build a minimal-valid manifest dict, optionally applying mutations."""
    doc = {"schema_version": 1, "build": {"id": "test-build", "version": "0.1.0"}}
    if overrides:
        doc.update(overrides)
    if remove:
        for key in remove:
            doc.pop(key, None)
    return doc


def _assert_invalid(test_case, doc, error_type=ManifestValidationError, *, contains=None):
    with test_case.assertRaises(error_type) as ctx:
        validate_manifest(doc)
    if contains:
        test_case.assertIn(
            contains, str(ctx.exception),
            f"Expected {contains!r} in error: {ctx.exception}",
        )


# ---------------------------------------------------------------------------
# Loading (file, string, error paths)
# ---------------------------------------------------------------------------

class TestLoading(unittest.TestCase):

    def test_load_manifest_file_minimal(self):
        m = load_manifest_file(MINIMAL_PATH)
        self.assertIsInstance(m, Manifest)
        self.assertEqual(m.schema_version, 1)

    def test_load_manifest_json_string(self):
        text = '{"schema_version": 1, "build": {"id": "x", "version": "0.1.0"}}'
        m = load_manifest_json(text)
        self.assertIsInstance(m, Manifest)
        self.assertEqual(m.build.id, "x")

    def test_load_manifest_file_missing_raises_parse_error(self):
        with self.assertRaises(ManifestParseError):
            load_manifest_file("/nonexistent/path/manifest.json")

    def test_load_manifest_json_malformed_raises_parse_error(self):
        with self.assertRaises(ManifestParseError):
            load_manifest_json("{ not valid json }")

    def test_load_manifest_json_array_root_raises_parse_error(self):
        with self.assertRaises(ManifestParseError):
            load_manifest_json("[1, 2, 3]")

    def test_load_manifest_json_null_root_raises_parse_error(self):
        with self.assertRaises(ManifestParseError):
            load_manifest_json("null")

    def test_validate_manifest_non_dict_raises_validation_error(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest([1, 2, 3])

    def test_load_manifest_file_with_tempfile(self):
        doc = {"schema_version": 1, "build": {"id": "tmp", "version": "1.0.0"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump(doc, fh)
            tmp_path = fh.name
        try:
            m = load_manifest_file(tmp_path)
            self.assertEqual(m.build.id, "tmp")
        finally:
            os.unlink(tmp_path)

    def test_manifest_error_is_base_of_parse_error(self):
        self.assertTrue(issubclass(ManifestParseError, ManifestError))

    def test_manifest_error_is_base_of_validation_error(self):
        self.assertTrue(issubclass(ManifestValidationError, ManifestError))


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

class TestSchemaVersion(unittest.TestCase):

    def test_missing_schema_version(self):
        _assert_invalid(self, _make(remove=["schema_version"]), contains="schema_version")

    def test_unsupported_schema_version_2(self):
        _assert_invalid(self, _make({"schema_version": 2}), contains="schema_version")

    def test_schema_version_as_string(self):
        _assert_invalid(self, _make({"schema_version": "1"}), contains="schema_version")

    def test_schema_version_as_boolean_true(self):
        # Python: isinstance(True, int) is True, so we must explicitly reject booleans
        _assert_invalid(self, _make({"schema_version": True}), contains="schema_version")

    def test_schema_version_zero(self):
        _assert_invalid(self, _make({"schema_version": 0}), contains="schema_version")


# ---------------------------------------------------------------------------
# Build field
# ---------------------------------------------------------------------------

class TestBuildField(unittest.TestCase):

    def test_missing_build(self):
        _assert_invalid(self, _make(remove=["build"]), contains="build")

    def test_missing_build_id(self):
        doc = _make({"build": {"version": "0.1.0"}})
        _assert_invalid(self, doc, contains="id")

    def test_missing_build_version(self):
        doc = _make({"build": {"id": "my-build"}})
        _assert_invalid(self, doc, contains="version")

    def test_invalid_build_id_uppercase(self):
        doc = _make({"build": {"id": "My-Build", "version": "0.1.0"}})
        _assert_invalid(self, doc, contains="build.id")

    def test_invalid_build_id_starts_with_dash(self):
        doc = _make({"build": {"id": "-bad", "version": "0.1.0"}})
        _assert_invalid(self, doc, contains="build.id")

    def test_invalid_build_version_not_semver(self):
        doc = _make({"build": {"id": "my-build", "version": "1.0"}})
        _assert_invalid(self, doc, contains="build.version")

    def test_invalid_build_version_with_prefix(self):
        doc = _make({"build": {"id": "my-build", "version": "v1.0.0"}})
        _assert_invalid(self, doc, contains="build.version")

    def test_unknown_field_in_build(self):
        doc = _make({"build": {"id": "x", "version": "0.1.0", "unexpected": "field"}})
        _assert_invalid(self, doc, contains="unexpected")

    def test_valid_build_with_optional_fields(self):
        doc = _make({"build": {
            "id": "my-build",
            "version": "1.2.3",
            "name": "My Build",
            "description": "A description.",
        }})
        m = validate_manifest(doc)
        self.assertEqual(m.build.name, "My Build")
        self.assertEqual(m.build.description, "A description.")

    def test_build_id_with_valid_characters(self):
        doc = _make({"build": {"id": "eric-main-2", "version": "0.1.0"}})
        m = validate_manifest(doc)
        self.assertEqual(m.build.id, "eric-main-2")


# ---------------------------------------------------------------------------
# Engine min version
# ---------------------------------------------------------------------------

class TestEngineMinVersion(unittest.TestCase):

    def test_valid_engine_min_version(self):
        doc = _make({"engine_min_version": "0.2.0"})
        m = validate_manifest(doc)
        self.assertEqual(m.engine_min_version, "0.2.0")

    def test_absent_engine_min_version(self):
        m = validate_manifest(_make())
        self.assertEqual(m.engine_min_version, "")

    def test_invalid_engine_min_version(self):
        doc = _make({"engine_min_version": "0.2"})
        _assert_invalid(self, doc, contains="engine_min_version")

    def test_engine_min_version_not_string(self):
        doc = _make({"engine_min_version": 1})
        _assert_invalid(self, doc, contains="engine_min_version")


# ---------------------------------------------------------------------------
# Unknown top-level fields
# ---------------------------------------------------------------------------

class TestUnknownTopLevelFields(unittest.TestCase):

    def test_unknown_top_level_key(self):
        _assert_invalid(self, _make({"totally_unknown_field": "value"}))

    def test_two_unknown_top_level_keys(self):
        _assert_invalid(self, _make({"foo": 1, "bar": 2}))


# ---------------------------------------------------------------------------
# Add-ons
# ---------------------------------------------------------------------------

class TestAddonEntries(unittest.TestCase):

    def _doc_with_addons(self, addons):
        return _make({"addons": addons})

    def test_valid_state_enabled(self):
        doc = self._doc_with_addons([{"addon_id": "plugin.video.foo", "state": "enabled"}])
        m = validate_manifest(doc)
        self.assertEqual(m.addons[0].state, "enabled")

    def test_valid_state_disabled(self):
        doc = self._doc_with_addons([{"addon_id": "plugin.video.foo", "state": "disabled"}])
        validate_manifest(doc)

    def test_valid_state_absent(self):
        doc = self._doc_with_addons([{"addon_id": "plugin.video.foo", "state": "absent"}])
        validate_manifest(doc)

    def test_invalid_state(self):
        doc = self._doc_with_addons([{"addon_id": "plugin.video.foo", "state": "maybe"}])
        _assert_invalid(self, doc, contains="state")

    def test_missing_state(self):
        doc = self._doc_with_addons([{"addon_id": "plugin.video.foo"}])
        _assert_invalid(self, doc, contains="state")

    def test_missing_addon_id(self):
        doc = self._doc_with_addons([{"state": "enabled"}])
        _assert_invalid(self, doc, contains="addon_id")

    def test_duplicate_addon_id(self):
        doc = self._doc_with_addons([
            {"addon_id": "plugin.video.foo", "state": "enabled"},
            {"addon_id": "plugin.video.foo", "state": "disabled"},
        ])
        _assert_invalid(self, doc, contains="duplicate")

    def test_malformed_addon_id_uppercase(self):
        doc = self._doc_with_addons([{"addon_id": "Plugin.Video.Foo", "state": "enabled"}])
        _assert_invalid(self, doc, contains="addon_id")

    def test_malformed_addon_id_starts_with_dot(self):
        doc = self._doc_with_addons([{"addon_id": ".bad", "state": "enabled"}])
        _assert_invalid(self, doc, contains="addon_id")

    def test_unknown_field_in_addon(self):
        doc = self._doc_with_addons([{
            "addon_id": "plugin.video.foo",
            "state": "enabled",
            "extra_field": "value",
        }])
        _assert_invalid(self, doc, contains="extra_field")

    def test_addon_with_note_is_valid(self):
        doc = self._doc_with_addons([{
            "addon_id": "plugin.video.foo",
            "state": "enabled",
            "note": "Required by something",
        }])
        m = validate_manifest(doc)
        self.assertEqual(m.addons[0].note, "Required by something")

    def test_addons_returned_as_tuple(self):
        doc = self._doc_with_addons([{"addon_id": "plugin.video.foo", "state": "enabled"}])
        m = validate_manifest(doc)
        self.assertIsInstance(m.addons, tuple)


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------

class TestRepositories(unittest.TestCase):

    def _doc_with_repos(self, repos):
        return _make({"repositories": repos})

    def test_valid_repository(self):
        doc = self._doc_with_repos([{
            "addon_id": "repository.eengert",
            "bootstrap_url": "https://example.invalid/repo.zip",
            "required": True,
        }])
        m = validate_manifest(doc)
        self.assertEqual(m.repositories[0].addon_id, "repository.eengert")

    def test_invalid_repository_id_missing_prefix(self):
        doc = self._doc_with_repos([{"addon_id": "plugin.video.foo"}])
        _assert_invalid(self, doc, contains="repository.")

    def test_duplicate_repository_ids(self):
        doc = self._doc_with_repos([
            {"addon_id": "repository.foo"},
            {"addon_id": "repository.foo"},
        ])
        _assert_invalid(self, doc, contains="duplicate")

    def test_bootstrap_url_ftp_rejected(self):
        doc = self._doc_with_repos([{
            "addon_id": "repository.foo",
            "bootstrap_url": "ftp://example.com/repo.zip",
        }])
        _assert_invalid(self, doc, contains="scheme")

    def test_bootstrap_url_with_credentials_rejected(self):
        doc = self._doc_with_repos([{
            "addon_id": "repository.foo",
            "bootstrap_url": "https://user:pass@example.com/repo.zip",
        }])
        _assert_invalid(self, doc, contains="credentials")

    def test_bootstrap_url_relative_rejected(self):
        doc = self._doc_with_repos([{
            "addon_id": "repository.foo",
            "bootstrap_url": "repo.zip",
        }])
        _assert_invalid(self, doc, contains="scheme")

    def test_bootstrap_url_http_allowed(self):
        # http is permitted for local/dev repositories
        doc = self._doc_with_repos([{
            "addon_id": "repository.local",
            "bootstrap_url": "http://192.168.1.1/repo.zip",
        }])
        m = validate_manifest(doc)
        self.assertEqual(m.repositories[0].bootstrap_url, "http://192.168.1.1/repo.zip")

    def test_unknown_field_in_repository(self):
        doc = self._doc_with_repos([{
            "addon_id": "repository.foo",
            "extra": "bad",
        }])
        _assert_invalid(self, doc, contains="extra")

    def test_required_field_must_be_boolean(self):
        doc = self._doc_with_repos([{
            "addon_id": "repository.foo",
            "required": "yes",
        }])
        _assert_invalid(self, doc, contains="boolean")

    def test_repositories_returned_as_tuple(self):
        doc = self._doc_with_repos([{"addon_id": "repository.foo"}])
        m = validate_manifest(doc)
        self.assertIsInstance(m.repositories, tuple)


# ---------------------------------------------------------------------------
# Skin
# ---------------------------------------------------------------------------

class TestSkin(unittest.TestCase):

    def test_valid_skin(self):
        doc = _make({"skin": {"addon_id": "skin.arctic.fuse.3"}})
        m = validate_manifest(doc)
        self.assertEqual(m.skin.addon_id, "skin.arctic.fuse.3")

    def test_skin_wrong_prefix(self):
        doc = _make({"skin": {"addon_id": "plugin.video.not_a_skin"}})
        _assert_invalid(self, doc, contains="skin.")

    def test_skin_unknown_field(self):
        doc = _make({"skin": {"addon_id": "skin.foo", "extra": "bad"}})
        _assert_invalid(self, doc, contains="extra")

    def test_skin_config_packages_are_tuple(self):
        doc = _make({"skin": {"addon_id": "skin.foo", "config_packages": ["pkg1"]}})
        m = validate_manifest(doc)
        self.assertIsInstance(m.skin.config_packages, tuple)
        self.assertIn("pkg1", m.skin.config_packages)

    def test_absent_skin_returns_none(self):
        m = validate_manifest(_make())
        self.assertIsNone(m.skin)


# ---------------------------------------------------------------------------
# Config declarations
# ---------------------------------------------------------------------------

class TestConfigDeclarations(unittest.TestCase):

    def _doc_with_config(self, config):
        return _make({"config": config})

    def test_valid_config(self):
        doc = self._doc_with_config({
            "packages": ["af3-common"],
            "managed_settings": [{"addon_id": "plugin.video.foo", "keys": ["key1"]}],
            "managed_files": ["addon_data/foo/settings.xml"],
        })
        m = validate_manifest(doc)
        self.assertEqual(m.config.packages, ("af3-common",))

    def test_duplicate_managed_settings_addon_id(self):
        doc = self._doc_with_config({
            "managed_settings": [
                {"addon_id": "plugin.video.foo", "keys": ["a"]},
                {"addon_id": "plugin.video.foo", "keys": ["b"]},
            ]
        })
        _assert_invalid(self, doc, contains="duplicate")

    def test_empty_managed_settings_keys(self):
        doc = self._doc_with_config({
            "managed_settings": [{"addon_id": "plugin.video.foo", "keys": []}]
        })
        _assert_invalid(self, doc, contains="keys")

    def test_malformed_packages_not_array(self):
        doc = self._doc_with_config({"packages": "not-an-array"})
        _assert_invalid(self, doc, contains="packages")

    def test_unknown_config_field(self):
        doc = self._doc_with_config({"packages": [], "bad_field": 1})
        _assert_invalid(self, doc, contains="bad_field")

    def test_absent_config_returns_none(self):
        m = validate_manifest(_make())
        self.assertIsNone(m.config)


# ---------------------------------------------------------------------------
# Managed file path safety
# ---------------------------------------------------------------------------

class TestManagedFilePaths(unittest.TestCase):

    def _doc_with_managed_files(self, paths):
        return _make({"config": {"managed_files": paths}})

    def test_safe_path_accepted(self):
        doc = self._doc_with_managed_files(["addon_data/skin.arctic.fuse.3/settings.xml"])
        m = validate_manifest(doc)
        self.assertIn("addon_data/skin.arctic.fuse.3/settings.xml", m.config.managed_files)

    def test_dotdot_traversal_rejected(self):
        doc = self._doc_with_managed_files(["../etc/passwd"])
        _assert_invalid(self, doc, contains="traversal")

    def test_embedded_dotdot_rejected(self):
        doc = self._doc_with_managed_files(["addon_data/../etc/passwd"])
        _assert_invalid(self, doc, contains="traversal")

    def test_absolute_posix_path_rejected(self):
        doc = self._doc_with_managed_files(["/etc/passwd"])
        _assert_invalid(self, doc, contains="absolute")

    def test_windows_drive_path_rejected(self):
        doc = self._doc_with_managed_files(["C:\\Windows\\System32\\file.xml"])
        _assert_invalid(self, doc, contains="Windows")

    def test_unc_path_rejected(self):
        doc = self._doc_with_managed_files(["\\\\server\\share\\file.xml"])
        _assert_invalid(self, doc, contains="UNC")

    def test_slash_slash_path_rejected(self):
        doc = self._doc_with_managed_files(["//server/share"])
        _assert_invalid(self, doc, contains="UNC")

    def test_null_byte_path_rejected(self):
        doc = self._doc_with_managed_files(["addon_data/\x00file"])
        _assert_invalid(self, doc, contains="null")

    def test_empty_path_rejected(self):
        doc = self._doc_with_managed_files([""])
        _assert_invalid(self, doc, contains="empty")

    def test_duplicate_managed_file_path_rejected(self):
        doc = self._doc_with_managed_files([
            "addon_data/foo/settings.xml",
            "addon_data/foo/settings.xml",
        ])
        _assert_invalid(self, doc, contains="duplicate")


# ---------------------------------------------------------------------------
# Platform and device profiles
# ---------------------------------------------------------------------------

class TestProfiles(unittest.TestCase):

    def test_device_profile_with_valid_extends(self):
        doc = _make({
            "platform_profiles": {"tvos": {}},
            "device_profiles": {"bonus-room": {"extends": "tvos"}},
        })
        m = validate_manifest(doc)
        self.assertEqual(m.device_profiles["bonus-room"].extends, "tvos")

    def test_device_profile_missing_extends(self):
        doc = _make({"device_profiles": {"bonus-room": {"label": "Bonus Room"}}})
        _assert_invalid(self, doc, contains="extends")

    def test_device_profile_extends_unknown_platform(self):
        doc = _make({
            "device_profiles": {"bonus-room": {"extends": "nonexistent-platform"}},
        })
        _assert_invalid(self, doc, contains="unknown platform profile")

    def test_device_profile_extends_references_correct_platform(self):
        doc = _make({
            "platform_profiles": {"android": {}, "tvos": {}},
            "device_profiles": {
                "shield": {"extends": "android"},
                "family-room": {"extends": "tvos"},
            },
        })
        m = validate_manifest(doc)
        self.assertEqual(m.device_profiles["shield"].extends, "android")
        self.assertEqual(m.device_profiles["family-room"].extends, "tvos")

    def test_duplicate_addon_override_in_platform_profile(self):
        doc = _make({
            "platform_profiles": {
                "tvos": {
                    "addons": [
                        {"addon_id": "plugin.video.foo", "state": "enabled"},
                        {"addon_id": "plugin.video.foo", "state": "disabled"},
                    ]
                }
            }
        })
        _assert_invalid(self, doc, contains="duplicate")

    def test_duplicate_addon_override_in_device_profile(self):
        doc = _make({
            "platform_profiles": {"tvos": {}},
            "device_profiles": {
                "bonus-room": {
                    "extends": "tvos",
                    "addons": [
                        {"addon_id": "plugin.video.foo", "state": "enabled"},
                        {"addon_id": "plugin.video.foo", "state": "disabled"},
                    ],
                }
            },
        })
        _assert_invalid(self, doc, contains="duplicate")

    def test_invalid_addon_state_in_platform_profile(self):
        doc = _make({
            "platform_profiles": {
                "tvos": {"addons": [{"addon_id": "plugin.video.foo", "state": "broken"}]}
            }
        })
        _assert_invalid(self, doc, contains="state")

    def test_unknown_field_in_platform_profile(self):
        doc = _make({"platform_profiles": {"tvos": {"unknown_key": "value"}}})
        _assert_invalid(self, doc, contains="unknown_key")

    def test_platform_profiles_returned_as_dict(self):
        doc = _make({"platform_profiles": {"tvos": {}}})
        m = validate_manifest(doc)
        self.assertIn("tvos", m.platform_profiles)
        self.assertIsInstance(m.platform_profiles["tvos"], ProfileLayer)

    def test_device_profiles_returned_as_dict(self):
        doc = _make({
            "platform_profiles": {"tvos": {}},
            "device_profiles": {"bonus-room": {"extends": "tvos"}},
        })
        m = validate_manifest(doc)
        self.assertIn("bonus-room", m.device_profiles)
        self.assertIsInstance(m.device_profiles["bonus-room"], DeviceProfile)


# ---------------------------------------------------------------------------
# Optional groups
# ---------------------------------------------------------------------------

class TestOptionalGroups(unittest.TestCase):

    def test_valid_optional_group(self):
        doc = _make({
            "optional": [{"id": "shield-extras", "label": "Shield extras"}]
        })
        m = validate_manifest(doc)
        self.assertEqual(m.optional[0].id, "shield-extras")

    def test_platform_profile_references_nonexistent_optional_group(self):
        doc = _make({
            "platform_profiles": {"android": {"include_optional": ["missing-group"]}},
        })
        _assert_invalid(self, doc, contains="unknown optional group")

    def test_device_profile_references_nonexistent_optional_group(self):
        doc = _make({
            "platform_profiles": {"android": {}},
            "device_profiles": {
                "shield": {"extends": "android", "include_optional": ["missing-group"]}
            },
        })
        _assert_invalid(self, doc, contains="unknown optional group")

    def test_platform_profile_references_existing_optional_group(self):
        doc = _make({
            "platform_profiles": {"android": {"include_optional": ["shield-extras"]}},
            "optional": [{"id": "shield-extras"}],
        })
        validate_manifest(doc)  # should not raise

    def test_duplicate_optional_group_ids(self):
        doc = _make({
            "optional": [
                {"id": "group-a"},
                {"id": "group-a"},
            ]
        })
        _assert_invalid(self, doc, contains="duplicate")

    def test_optional_group_missing_id(self):
        doc = _make({"optional": [{"label": "No ID"}]})
        _assert_invalid(self, doc, contains="id")

    def test_optional_group_invalid_id_pattern(self):
        doc = _make({"optional": [{"id": "Group With Spaces"}]})
        _assert_invalid(self, doc, contains="id")

    def test_optional_groups_returned_as_tuple(self):
        doc = _make({"optional": [{"id": "extras"}]})
        m = validate_manifest(doc)
        self.assertIsInstance(m.optional, tuple)


# ---------------------------------------------------------------------------
# Private overlay
# ---------------------------------------------------------------------------

class TestPrivateOverlay(unittest.TestCase):

    def test_valid_local_file_overlay(self):
        doc = _make({
            "private_overlay": {
                "type": "local_file",
                "path_hint": "~/.config/kodi-private/overlay.json",
                "description": "Private auth state.",
            }
        })
        m = validate_manifest(doc)
        self.assertEqual(m.private_overlay.type, "local_file")
        self.assertEqual(m.private_overlay.path_hint, "~/.config/kodi-private/overlay.json")

    def test_unsupported_overlay_type(self):
        doc = _make({"private_overlay": {"type": "s3_bucket"}})
        _assert_invalid(self, doc, contains="type")

    def test_overlay_missing_type(self):
        doc = _make({"private_overlay": {"path_hint": "~/foo.json"}})
        _assert_invalid(self, doc, contains="type")

    def test_overlay_non_dict(self):
        doc = _make({"private_overlay": "local_file"})
        _assert_invalid(self, doc)

    def test_overlay_unknown_field(self):
        doc = _make({"private_overlay": {"type": "local_file", "credentials": "bad"}})
        _assert_invalid(self, doc, contains="credentials")

    def test_absent_overlay_returns_none(self):
        m = validate_manifest(_make())
        self.assertIsNone(m.private_overlay)


# ---------------------------------------------------------------------------
# Restart policy
# ---------------------------------------------------------------------------

class TestRestartPolicy(unittest.TestCase):

    def test_valid_restart_policy(self):
        doc = _make({"restart_policy": {"allow_skin_reload": True, "allow_kodi_restart": False}})
        m = validate_manifest(doc)
        self.assertTrue(m.restart_policy.allow_skin_reload)
        self.assertFalse(m.restart_policy.allow_kodi_restart)

    def test_restart_policy_string_instead_of_bool(self):
        doc = _make({"restart_policy": {"allow_skin_reload": "yes"}})
        _assert_invalid(self, doc, contains="boolean")

    def test_restart_policy_integer_instead_of_bool(self):
        doc = _make({"restart_policy": {"allow_kodi_restart": 1}})
        _assert_invalid(self, doc, contains="boolean")

    def test_restart_policy_unknown_field(self):
        doc = _make({"restart_policy": {"allow_skin_reload": True, "extra": "bad"}})
        _assert_invalid(self, doc, contains="extra")

    def test_absent_restart_policy_returns_none(self):
        m = validate_manifest(_make())
        self.assertIsNone(m.restart_policy)

    def test_empty_restart_policy_uses_defaults(self):
        doc = _make({"restart_policy": {}})
        m = validate_manifest(doc)
        self.assertIsNotNone(m.restart_policy)
        self.assertTrue(m.restart_policy.allow_skin_reload)
        self.assertTrue(m.restart_policy.allow_kodi_restart)


# ---------------------------------------------------------------------------
# Unknown fields at representative nested levels
# ---------------------------------------------------------------------------

class TestUnknownFields(unittest.TestCase):

    def test_unknown_field_in_build(self):
        doc = _make({"build": {"id": "x", "version": "0.1.0", "bogus": "field"}})
        _assert_invalid(self, doc, contains="bogus")

    def test_unknown_field_in_addon_entry(self):
        doc = _make({"addons": [{"addon_id": "plugin.video.foo", "state": "enabled", "bogus": 1}]})
        _assert_invalid(self, doc, contains="bogus")

    def test_unknown_field_in_repository(self):
        doc = _make({"repositories": [{"addon_id": "repository.foo", "bogus": 1}]})
        _assert_invalid(self, doc, contains="bogus")

    def test_unknown_field_in_config(self):
        doc = _make({"config": {"packages": [], "bogus": 1}})
        _assert_invalid(self, doc, contains="bogus")

    def test_unknown_field_in_optional_group(self):
        doc = _make({"optional": [{"id": "extras", "bogus": 1}]})
        _assert_invalid(self, doc, contains="bogus")


# ---------------------------------------------------------------------------
# Example manifests
# ---------------------------------------------------------------------------

class TestExamples(unittest.TestCase):

    def test_minimal_loads_successfully(self):
        m = load_manifest_file(MINIMAL_PATH)
        self.assertIsInstance(m, Manifest)
        self.assertEqual(m.schema_version, 1)
        self.assertEqual(m.build.id, "minimal-example")
        self.assertEqual(m.build.version, "0.1.0")

    def test_minimal_has_empty_collections(self):
        m = load_manifest_file(MINIMAL_PATH)
        self.assertEqual(m.repositories, ())
        self.assertEqual(m.addons, ())
        self.assertIsNone(m.skin)
        self.assertIsNone(m.config)
        self.assertEqual(m.platform_profiles, {})
        self.assertEqual(m.device_profiles, {})
        self.assertEqual(m.optional, ())
        self.assertIsNone(m.private_overlay)
        self.assertIsNone(m.restart_policy)

    def test_eric_main_loads_successfully(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        self.assertIsInstance(m, Manifest)
        self.assertEqual(m.build.id, "eric-main")

    def test_eric_main_has_expected_profiles(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        self.assertIn("tvos", m.platform_profiles)
        self.assertIn("android", m.platform_profiles)
        self.assertIn("bonus-room", m.device_profiles)
        self.assertIn("shield", m.device_profiles)

    def test_eric_main_device_profiles_extend_valid_platforms(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        for device_id, profile in m.device_profiles.items():
            self.assertIn(
                profile.extends,
                m.platform_profiles,
                f"device_profiles.{device_id}.extends={profile.extends!r} not in platform_profiles",
            )

    def test_eric_main_has_repositories(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        self.assertGreater(len(m.repositories), 0)
        self.assertTrue(m.repositories[0].addon_id.startswith("repository."))

    def test_eric_main_has_skin(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        self.assertIsNotNone(m.skin)
        self.assertEqual(m.skin.addon_id, "skin.arctic.fuse.3")

    def test_eric_main_has_optional_groups(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        self.assertGreater(len(m.optional), 0)

    def test_eric_main_has_private_overlay_reference(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        self.assertIsNotNone(m.private_overlay)
        self.assertEqual(m.private_overlay.type, "local_file")

    def test_eric_main_has_restart_policy(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        self.assertIsNotNone(m.restart_policy)

    def test_eric_main_addons_are_addonentry_instances(self):
        m = load_manifest_file(ERIC_MAIN_PATH)
        for addon in m.addons:
            self.assertIsInstance(addon, AddonEntry)


# ---------------------------------------------------------------------------
# Typed representation
# ---------------------------------------------------------------------------

class TestTypedRepresentation(unittest.TestCase):

    def test_manifest_is_dataclass_instance(self):
        m = validate_manifest(_make())
        self.assertIsInstance(m, Manifest)

    def test_build_info_is_frozen(self):
        m = validate_manifest(_make())
        with self.assertRaises((AttributeError, TypeError)):
            m.build.id = "changed"  # type: ignore[misc]

    def test_addon_entry_is_frozen(self):
        doc = _make({"addons": [{"addon_id": "plugin.video.foo", "state": "enabled"}]})
        m = validate_manifest(doc)
        with self.assertRaises((AttributeError, TypeError)):
            m.addons[0].state = "disabled"  # type: ignore[misc]

    def test_collections_are_independent_of_input(self):
        """Parsed result should not share the input dict's list objects."""
        raw_addons = [{"addon_id": "plugin.video.foo", "state": "enabled"}]
        doc = _make({"addons": raw_addons})
        m = validate_manifest(doc)
        # Mutating the input after parsing must not affect the result
        raw_addons.append({"addon_id": "plugin.video.bar", "state": "disabled"})
        self.assertEqual(len(m.addons), 1)

    def test_profile_maps_are_dicts(self):
        doc = _make({"platform_profiles": {"tvos": {}}})
        m = validate_manifest(doc)
        self.assertIsInstance(m.platform_profiles, dict)


# ---------------------------------------------------------------------------
# Regression: BM-001 and BM-002 still work
# ---------------------------------------------------------------------------

class TestRegression(unittest.TestCase):

    def test_bm001_build_manager_still_importable(self):
        from resources.lib.build_manager import BuildManager
        self.assertIsNotNone(BuildManager)

    def test_bm001_resources_lib_still_a_package(self):
        import resources.lib
        self.assertIsNotNone(resources.lib)

    def test_bm002_schema_file_still_loads(self):
        import json
        import os
        schema_path = os.path.join(REPO_ROOT, "resources", "builds", "schema-v1.json")
        with open(schema_path) as f:
            schema = json.load(f)
        self.assertIn("$schema", schema)
        self.assertIn("definitions", schema)

    def test_bm002_minimal_example_still_valid_json(self):
        with open(MINIMAL_PATH) as f:
            doc = json.load(f)
        self.assertIsInstance(doc, dict)

    def test_manifest_module_has_no_kodi_imports(self):
        """manifest.py must not import any Kodi modules."""
        import resources.lib.manifest as manifest_mod
        import sys
        for mod_name in sys.modules:
            if mod_name.startswith("xbmc") or mod_name.startswith("xbmcaddon"):
                self.fail(
                    f"manifest.py triggered Kodi import: {mod_name}"
                )


if __name__ == "__main__":
    unittest.main()
