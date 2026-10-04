"""
Tests for BM-015: resources.lib.config — configuration package deployment.

Covers:
  - Package ID validation (path safety)
  - Package descriptor parsing and schema validation
  - Setting value type validation (string / bool / int / number)
  - Source and destination path safety
  - Package-internal duplicate rejection
  - Package overlay semantics and determinism
  - Manifest ownership and managed-target completeness
  - Preflight guarantee (zero mutations on any preflight failure)
  - Setting deployment (per type: no-op, drift, failures, verification)
  - Managed file deployment (create, no-op, update, failures, containment)
  - Batch ordering and idempotency
  - Secrets boundary (no private_overlay access, no raw values in results)

All tests run without Kodi. The Kodi runtime backend is exercised only for the
parts that do not require xbmc modules (lazy-import failure and containment).
"""

import json
import os
import shutil
import tempfile
import unittest
import weakref

from resources.lib.config import (
    ConfigApplyResult,
    ConfigAddonUnavailableError,
    ConfigBackendError,
    ConfigFile,
    ConfigOperationKind,
    ConfigOperationStatus,
    ConfigOwnershipError,
    ConfigPackageError,
    ConfigPackageLoader,
    ConfigSetting,
    ConfigSettingType,
    ConfigTargetKind,
    ConfigurationBackend,
    ConfigurationManager,
    ConfigurationValidationState,
    EffectiveConfiguration,
    KodiRuntimeConfigurationBackend,
    NUMBER_SIGNIFICANT_DIGITS,
    default_packages_root,
    validate_package_id,
    values_equal,
)
from resources.lib.manifest import (
    ConfigDeclarations,
    ManagedSettingScope,
    load_manifest_file,
)
from resources.lib.resolver import resolve_manifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def declarations(settings=(), files=(), packages=()):
    """Build a ConfigDeclarations from ((addon_id, key), ...) and paths."""
    by_addon = {}
    order = []
    for addon_id, key in settings:
        if addon_id not in by_addon:
            by_addon[addon_id] = []
            order.append(addon_id)
        by_addon[addon_id].append(key)
    return ConfigDeclarations(
        packages=tuple(packages),
        managed_settings=tuple(
            ManagedSettingScope(addon_id=a, keys=tuple(by_addon[a])) for a in order
        ),
        managed_files=tuple(files),
    )


class FakeConfigurationBackend(ConfigurationBackend):
    """In-memory backend. Records every call; no Kodi, no filesystem."""

    def __init__(self, settings=None, files=None, missing_addons=()):
        self.settings = dict(settings or {})
        self.files = dict(files or {})
        self.missing_addons = set(missing_addons)
        self.calls = []
        self.reads = []
        self.writes = []
        self.get_errors = {}
        self.set_errors = {}
        self.read_errors = {}
        self.write_errors = {}
        self.write_result = {}

    def get_setting(self, addon_id, key, setting_type):
        self.calls.append(("get_setting", addon_id, key))
        if addon_id in self.missing_addons:
            raise ConfigAddonUnavailableError(f"{addon_id} not installed")
        if (addon_id, key) in self.get_errors:
            raise ConfigBackendError(self.get_errors[(addon_id, key)])
        if (addon_id, key) not in self.settings:
            raise ConfigBackendError(f"unknown setting {addon_id}/{key}")
        return self.settings[(addon_id, key)]

    def set_setting(self, addon_id, key, setting_type, value):
        self.calls.append(("set_setting", addon_id, key))
        self.writes.append((addon_id, key))
        if (addon_id, key) in self.set_errors:
            raise ConfigBackendError(self.set_errors[(addon_id, key)])
        self.settings[(addon_id, key)] = self.write_result.get(
            (addon_id, key), value
        )

    def read_file(self, destination):
        self.calls.append(("read_file", destination))
        self.reads.append(destination)
        if destination in self.read_errors:
            raise ConfigBackendError(self.read_errors[destination])
        return self.files.get(destination)

    def write_file(self, destination, data):
        self.calls.append(("write_file", destination))
        self.writes.append(destination)
        if destination in self.write_errors:
            raise ConfigBackendError(self.write_errors[destination])
        self.files[destination] = self.write_result.get(destination, data)

    @property
    def mutations(self):
        """Every call that could have changed Kodi state."""
        return [c for c in self.calls if c[0] in (
            "set_setting", "set_skin_setting", "write_file"
        )]


class FakeSkinConfigurationBackend(FakeConfigurationBackend):
    """In-memory explicit skin namespace for BM-018D unit tests."""

    def __init__(self, settings=None, *, active_skin="skin.arctic.fuse.3"):
        super().__init__()
        self.skin_settings = dict(settings or {})
        self.active_skin = active_skin
        self.skin_get_errors = {}
        self.skin_set_errors = {}
        self.skin_write_result = {}

    def get_skin_setting(self, addon_id, key, setting_type):
        self.calls.append(("get_skin_setting", addon_id, key))
        if self.active_skin != addon_id:
            raise ConfigBackendError(
                f"requested skin {addon_id!r} is not active"
            )
        if (addon_id, key) in self.skin_get_errors:
            raise ConfigBackendError(self.skin_get_errors[(addon_id, key)])
        if (addon_id, key) not in self.skin_settings:
            raise ConfigBackendError(f"unknown skin setting {addon_id}/{key}")
        return self.skin_settings[(addon_id, key)]

    def set_skin_setting(self, addon_id, key, setting_type, value):
        self.calls.append(("set_skin_setting", addon_id, key))
        self.writes.append(("skin", addon_id, key))
        if self.active_skin != addon_id:
            raise ConfigBackendError(
                f"requested skin {addon_id!r} is not active"
            )
        if (addon_id, key) in self.skin_set_errors:
            raise ConfigBackendError(self.skin_set_errors[(addon_id, key)])
        self.skin_settings[(addon_id, key)] = self.skin_write_result.get(
            (addon_id, key), value
        )


class PackageFixture(unittest.TestCase):
    """Base class providing a temporary package root."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="bm015-pkg-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.loader = ConfigPackageLoader(self.root)

    def write_package(self, package_id, descriptor, sources=None, *, raw=None):
        """Create <root>/<package_id>/package.json plus optional source files."""
        package_dir = os.path.join(self.root, package_id)
        os.makedirs(package_dir, exist_ok=True)
        text = raw if raw is not None else json.dumps(descriptor)
        with open(os.path.join(package_dir, "package.json"), "w",
                  encoding="utf-8") as handle:
            handle.write(text)
        for relative, content in (sources or {}).items():
            path = os.path.join(package_dir, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(content)
        return package_dir

    def simple_descriptor(self, package_id, settings=(), files=()):
        return {
            "schema_version": 1,
            "id": package_id,
            "settings": [
                {"addon_id": a, "key": k, "type": t, "value": v}
                for a, k, t, v in settings
            ],
            "files": [
                {"source": s, "destination": d} for s, d in files
            ],
        }


# ---------------------------------------------------------------------------
# Package ID validation
# ---------------------------------------------------------------------------

class TestPackageIdValidation(unittest.TestCase):

    def test_accepts_simple_id(self):
        self.assertEqual(validate_package_id("common"), "common")

    def test_accepts_dots_dashes_underscores_digits(self):
        for value in ("af3-common", "redlight.v1", "pkg_2", "0start"):
            self.assertEqual(validate_package_id(value), value)

    def test_rejects_empty(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("")

    def test_rejects_non_string(self):
        for value in (None, 1, 1.0, True, [], {}):
            with self.assertRaises(ConfigPackageError):
                validate_package_id(value)

    def test_rejects_absolute_path(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("/etc/passwd")

    def test_rejects_forward_slash(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("a/b")

    def test_rejects_backslash(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("a\\b")

    def test_rejects_dot_dot(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("..")

    def test_rejects_embedded_traversal(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("a..b")

    def test_rejects_traversal_sequence(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("../other")

    def test_rejects_whitespace_only(self):
        for value in (" ", "\t", "\n", "   "):
            with self.assertRaises(ConfigPackageError):
                validate_package_id(value)

    def test_rejects_internal_whitespace(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("a b")

    def test_rejects_uppercase(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("Common")

    def test_rejects_leading_dot(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id(".hidden")

    def test_rejects_null_byte(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("a\x00b")

    def test_rejects_overlong(self):
        with self.assertRaises(ConfigPackageError):
            validate_package_id("a" * 65)

    def test_accepts_max_length(self):
        value = "a" * 64
        self.assertEqual(validate_package_id(value), value)


# ---------------------------------------------------------------------------
# Descriptor parsing
# ---------------------------------------------------------------------------

class TestDescriptorParsing(PackageFixture):

    def test_valid_descriptor(self):
        self.write_package("common", self.simple_descriptor(
            "common",
            settings=[("plugin.video.example", "quality", "string", "1080p")],
        ))
        package = self.loader.load_package("common")
        self.assertEqual(package.package_id, "common")
        self.assertEqual(len(package.settings), 1)
        setting = package.settings[0]
        self.assertEqual(setting.addon_id, "plugin.video.example")
        self.assertEqual(setting.key, "quality")
        self.assertIs(setting.setting_type, ConfigSettingType.STRING)
        self.assertEqual(setting.value, "1080p")
        self.assertEqual(setting.package_id, "common")

    def test_omitted_target_defaults_to_addon(self):
        self.write_package("common", self.simple_descriptor(
            "common",
            settings=[("plugin.video.example", "quality", "string", "1080p")],
        ))
        self.assertIs(
            self.loader.load_package("common").settings[0].target_kind,
            ConfigTargetKind.ADDON,
        )

    def test_explicit_skin_target_is_typed(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "target": "skin", "addon_id": "skin.arctic.fuse.3",
                "key": "HomeSwitcher.EnableIcons", "type": "bool", "value": True,
            }],
        })
        parsed = self.loader.load_package("common").settings[0]
        self.assertIs(parsed.target_kind, ConfigTargetKind.SKIN)
        self.assertEqual(
            parsed.target,
            ("skin", "skin.arctic.fuse.3", "HomeSwitcher.EnableIcons"),
        )

    def test_skin_target_rejects_int_and_number_types(self):
        for setting_type, value in (("int", 1), ("number", 1.5)):
            with self.subTest(setting_type=setting_type):
                self.write_package("common", {
                    "schema_version": 1, "id": "common",
                    "settings": [{
                        "target": "skin", "addon_id": "skin.foo",
                        "key": "key", "type": setting_type, "value": value,
                    }],
                })
                with self.assertRaises(ConfigPackageError):
                    self.loader.load_package("common")

    def test_addon_and_skin_same_identity_are_distinct(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [
                {"addon_id": "same.id", "key": "key", "type": "string", "value": "a"},
                {"target": "skin", "addon_id": "same.id", "key": "key", "type": "string", "value": "b"},
            ],
        })
        self.assertEqual(len(self.loader.load_package("common").settings), 2)

    def test_settings_and_files_optional(self):
        self.write_package("empty", {"schema_version": 1, "id": "empty"})
        package = self.loader.load_package("empty")
        self.assertEqual(package.settings, ())
        self.assertEqual(package.files, ())

    def test_wrong_schema_version(self):
        self.write_package("common", {"schema_version": 2, "id": "common"})
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("unsupported version", str(ctx.exception))

    def test_schema_version_bool_rejected(self):
        self.write_package("common", {"schema_version": True, "id": "common"})
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_missing_schema_version(self):
        self.write_package("common", {"id": "common"})
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_mismatched_descriptor_id(self):
        self.write_package("common", {"schema_version": 1, "id": "other"})
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("directory is", str(ctx.exception))

    def test_missing_descriptor_id(self):
        self.write_package("common", {"schema_version": 1})
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_invalid_descriptor_id_grammar(self):
        self.write_package("common", {"schema_version": 1, "id": "../evil"})
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_malformed_json(self):
        self.write_package("common", None, raw="{not json")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_descriptor_not_an_object(self):
        self.write_package("common", None, raw="[]")
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_unknown_descriptor_field(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common", "hooks": ["rm -rf /"],
        })
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("hooks", str(ctx.exception))

    def test_unknown_setting_field(self):
        self.write_package("common", {
            "schema_version": 1,
            "id": "common",
            "settings": [{
                "addon_id": "plugin.video.example", "key": "k",
                "type": "string", "value": "v", "secret_ref": "token",
            }],
        })
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("secret_ref", str(ctx.exception))

    def test_unknown_file_field(self):
        self.write_package("common", {
            "schema_version": 1,
            "id": "common",
            "files": [{"source": "files/a", "destination": "b", "mode": "0777"}],
        }, sources={"files/a": b"x"})
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("mode", str(ctx.exception))

    def test_missing_setting_field(self):
        for omit in ("addon_id", "key", "type", "value"):
            entry = {
                "addon_id": "plugin.video.example", "key": "k",
                "type": "string", "value": "v",
            }
            del entry[omit]
            self.write_package("common", {
                "schema_version": 1, "id": "common", "settings": [entry],
            })
            with self.assertRaises(ConfigPackageError) as ctx:
                self.loader.load_package("common")
            self.assertIn(omit, str(ctx.exception))

    def test_missing_file_field(self):
        for omit in ("source", "destination"):
            entry = {"source": "files/a", "destination": "b"}
            del entry[omit]
            self.write_package("common", {
                "schema_version": 1, "id": "common", "files": [entry],
            }, sources={"files/a": b"x"})
            with self.assertRaises(ConfigPackageError) as ctx:
                self.loader.load_package("common")
            self.assertIn(omit, str(ctx.exception))

    def test_settings_must_be_array(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common", "settings": {},
        })
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_files_must_be_array(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common", "files": {},
        })
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_setting_entry_must_be_object(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common", "settings": ["x"],
        })
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_missing_package_directory(self):
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("absent")
        self.assertIn("not found", str(ctx.exception))

    def test_missing_descriptor_file(self):
        os.makedirs(os.path.join(self.root, "bare"))
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("bare")
        self.assertIn("package.json", str(ctx.exception))

    def test_invalid_addon_id(self):
        for bad in ("", "-leading", "has space", "UPPER OK but space"):
            self.write_package("common", {
                "schema_version": 1, "id": "common",
                "settings": [{
                    "addon_id": bad, "key": "k", "type": "string", "value": "v",
                }],
            })
            with self.assertRaises(ConfigPackageError):
                self.loader.load_package("common")

    def test_empty_setting_key(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "addon_id": "plugin.video.example", "key": "",
                "type": "string", "value": "v",
            }],
        })
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_invalid_setting_key_grammar(self):
        for bad in (" k", "k/v", "k v", ".k", "k\x00"):
            self.write_package("common", {
                "schema_version": 1, "id": "common",
                "settings": [{
                    "addon_id": "plugin.video.example", "key": bad,
                    "type": "string", "value": "v",
                }],
            })
            with self.assertRaises(ConfigPackageError):
                self.loader.load_package("common")

    def test_unsupported_setting_type(self):
        for bad in ("list", "json", "secret", "binary", "float"):
            self.write_package("common", {
                "schema_version": 1, "id": "common",
                "settings": [{
                    "addon_id": "plugin.video.example", "key": "k",
                    "type": bad, "value": "v",
                }],
            })
            with self.assertRaises(ConfigPackageError) as ctx:
                self.loader.load_package("common")
            self.assertIn("unsupported setting type", str(ctx.exception))

    def test_setting_type_must_be_string(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "addon_id": "plugin.video.example", "key": "k",
                "type": 1, "value": "v",
            }],
        })
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")


# ---------------------------------------------------------------------------
# Setting value typing
# ---------------------------------------------------------------------------

class TestSettingValueTypes(PackageFixture):

    def _load_value(self, setting_type, value):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "addon_id": "plugin.video.example", "key": "k",
                "type": setting_type, "value": value,
            }],
        })
        return self.loader.load_package("common").settings[0].value

    def _expect_reject(self, setting_type, value):
        with self.assertRaises(ConfigPackageError):
            self._load_value(setting_type, value)

    def test_string_accepts_string(self):
        self.assertEqual(self._load_value("string", "1080p"), "1080p")

    def test_string_accepts_empty_string(self):
        self.assertEqual(self._load_value("string", ""), "")

    def test_string_rejects_other_types(self):
        for value in (1, 1.5, True, None, [], {}):
            self._expect_reject("string", value)

    def test_bool_accepts_true_and_false(self):
        self.assertIs(self._load_value("bool", True), True)
        self.assertIs(self._load_value("bool", False), False)

    def test_bool_rejects_int(self):
        self._expect_reject("bool", 1)
        self._expect_reject("bool", 0)

    def test_bool_rejects_string(self):
        self._expect_reject("bool", "true")

    def test_bool_rejects_other_types(self):
        for value in (1.0, None, [], {}):
            self._expect_reject("bool", value)

    def test_int_accepts_integer(self):
        self.assertEqual(self._load_value("int", 20), 20)
        self.assertEqual(self._load_value("int", -3), -3)
        self.assertEqual(self._load_value("int", 0), 0)

    def test_int_rejects_bool(self):
        self._expect_reject("int", True)
        self._expect_reject("int", False)

    def test_int_rejects_float(self):
        self._expect_reject("int", 20.0)

    def test_int_rejects_string(self):
        self._expect_reject("int", "20")

    def test_number_accepts_float(self):
        self.assertEqual(self._load_value("number", 1.5), 1.5)

    def test_number_accepts_integer_json(self):
        self.assertEqual(self._load_value("number", 2), 2.0)

    def test_number_rejects_bool(self):
        self._expect_reject("number", True)

    def test_number_rejects_string(self):
        self._expect_reject("number", "1.5")

    def _raw_number_descriptor(self, literal):
        return (
            '{"schema_version": 1, "id": "common", "settings": ['
            '{"addon_id": "plugin.video.example", "key": "k", '
            '"type": "number", "value": ' + literal + '}]}'
        )

    def test_number_rejects_nan_literal(self):
        self.write_package("common", None, raw=self._raw_number_descriptor("NaN"))
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_number_rejects_infinity_literal(self):
        self.write_package(
            "common", None, raw=self._raw_number_descriptor("Infinity")
        )
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_number_rejects_negative_infinity_literal(self):
        self.write_package(
            "common", None, raw=self._raw_number_descriptor("-Infinity")
        )
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_number_rejects_excess_precision(self):
        with self.assertRaises(ConfigPackageError) as ctx:
            self._load_value("number", 3.1415926535)
        self.assertIn("significant digits", str(ctx.exception))

    def test_number_accepts_six_significant_digits(self):
        self.assertEqual(self._load_value("number", 3.14159), 3.14159)

    def test_number_significant_digits_constant(self):
        self.assertEqual(NUMBER_SIGNIFICANT_DIGITS, 6)


class TestNumberComparison(unittest.TestCase):

    def test_equal_numbers(self):
        self.assertTrue(values_equal(ConfigSettingType.NUMBER, 1.5, 1.5))

    def test_int_and_float_equal(self):
        self.assertTrue(values_equal(ConfigSettingType.NUMBER, 2, 2.0))

    def test_different_numbers(self):
        self.assertFalse(values_equal(ConfigSettingType.NUMBER, 1.5, 1.6))

    def test_agreement_within_kodi_serialization_precision(self):
        # Kodi keeps 6 significant digits; these are indistinguishable once stored.
        self.assertTrue(
            values_equal(ConfigSettingType.NUMBER, 1.5, 1.5000000000001)
        )

    def test_disagreement_beyond_serialization_precision_is_detected(self):
        self.assertFalse(values_equal(ConfigSettingType.NUMBER, 1.5, 1.50001))

    def test_negative_zero_equals_zero(self):
        self.assertTrue(values_equal(ConfigSettingType.NUMBER, -0.0, 0.0))

    def test_string_comparison_is_exact(self):
        self.assertTrue(values_equal(ConfigSettingType.STRING, "a", "a"))
        self.assertFalse(values_equal(ConfigSettingType.STRING, "a", "A"))

    def test_bool_comparison_is_identity(self):
        self.assertTrue(values_equal(ConfigSettingType.BOOL, True, True))
        self.assertFalse(values_equal(ConfigSettingType.BOOL, True, False))

    def test_int_comparison_is_exact(self):
        self.assertTrue(values_equal(ConfigSettingType.INT, 20, 20))
        self.assertFalse(values_equal(ConfigSettingType.INT, 20, 21))


# ---------------------------------------------------------------------------
# Source / destination path safety
# ---------------------------------------------------------------------------

class TestPathSafety(PackageFixture):

    def _file_package(self, source, destination, *, create=True):
        sources = {"files/ok.txt": b"content"} if create else {}
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [{"source": source, "destination": destination}],
        }, sources=sources)

    def test_valid_source_and_destination(self):
        self._file_package("files/ok.txt", "addon_data/x/ok.txt")
        package = self.loader.load_package("common")
        self.assertEqual(package.files[0].content, b"content")
        self.assertEqual(package.files[0].destination, "addon_data/x/ok.txt")

    def test_missing_source_file(self):
        self._file_package("files/absent.txt", "addon_data/x/ok.txt")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("does not exist", str(ctx.exception))

    def test_source_directory_rejected(self):
        self._file_package("files", "addon_data/x/ok.txt")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("not a regular file", str(ctx.exception))

    def test_source_traversal_rejected(self):
        self._file_package("../../etc/passwd", "addon_data/x/ok.txt")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("traversal", str(ctx.exception))

    def test_source_absolute_rejected(self):
        self._file_package("/etc/passwd", "addon_data/x/ok.txt")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("absolute", str(ctx.exception))

    def test_source_uri_scheme_rejected(self):
        self._file_package("special://home/x", "addon_data/x/ok.txt")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("URI-scheme", str(ctx.exception))

    def test_source_symlink_escape_rejected(self):
        outside = tempfile.mkdtemp(prefix="bm015-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "wb") as handle:
            handle.write(b"outside")
        package_dir = self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [{
                "source": "files/link.txt",
                "destination": "addon_data/x/ok.txt",
            }],
        })
        os.makedirs(os.path.join(package_dir, "files"), exist_ok=True)
        os.symlink(secret, os.path.join(package_dir, "files", "link.txt"))
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("escapes the package root", str(ctx.exception))

    def test_destination_traversal_rejected(self):
        self._file_package("files/ok.txt", "../outside.txt")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("traversal", str(ctx.exception))

    def test_destination_absolute_rejected(self):
        self._file_package("files/ok.txt", "/etc/passwd")
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("absolute", str(ctx.exception))

    def test_destination_special_scheme_rejected(self):
        for bad in ("special://home/addons/x", "smb://host/share/x",
                    "http://example.invalid/x"):
            self._file_package("files/ok.txt", bad)
            with self.assertRaises(ConfigPackageError) as ctx:
                self.loader.load_package("common")
            self.assertIn("URI-scheme", str(ctx.exception))

    def test_destination_unc_rejected(self):
        for bad in ("\\\\host\\share\\x", "//host/share/x"):
            self._file_package("files/ok.txt", bad)
            with self.assertRaises(ConfigPackageError) as ctx:
                self.loader.load_package("common")
            self.assertIn("UNC", str(ctx.exception))

    def test_destination_null_byte_rejected(self):
        self._file_package("files/ok.txt", "addon_data/x\x00/ok.txt")
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_destination_whitespace_only_rejected(self):
        self._file_package("files/ok.txt", "   ")
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_destination_backslash_normalized(self):
        self._file_package("files/ok.txt", "addon_data\\x\\ok.txt")
        package = self.loader.load_package("common")
        self.assertEqual(package.files[0].destination, "addon_data/x/ok.txt")

    def test_destination_dot_segments_normalized(self):
        self._file_package("files/ok.txt", "addon_data/./x/ok.txt")
        package = self.loader.load_package("common")
        self.assertEqual(package.files[0].destination, "addon_data/x/ok.txt")

    def test_destination_dot_only_rejected(self):
        self._file_package("files/ok.txt", ".")
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_descriptor_symlink_escape_rejected(self):
        outside = tempfile.mkdtemp(prefix="bm015-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        rogue = os.path.join(outside, "rogue.json")
        with open(rogue, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "id": "common"}, handle)
        package_dir = os.path.join(self.root, "common")
        os.makedirs(package_dir)
        os.symlink(rogue, os.path.join(package_dir, "package.json"))
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("escapes the package directory", str(ctx.exception))

    def test_package_id_cannot_escape_root_via_loader(self):
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("../..")


# ---------------------------------------------------------------------------
# Package-internal duplicates
# ---------------------------------------------------------------------------

class TestPackageInternalDuplicates(PackageFixture):

    def test_duplicate_setting_target_rejected(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "k", "string", "a"),
            ("plugin.video.example", "k", "string", "b"),
        ]))
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("duplicate setting target", str(ctx.exception))

    def test_same_key_different_addon_allowed(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.a", "k", "string", "a"),
            ("plugin.video.b", "k", "string", "b"),
        ]))
        self.assertEqual(len(self.loader.load_package("common").settings), 2)

    def test_duplicate_file_destination_rejected(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [
                {"source": "files/a.txt", "destination": "addon_data/x/f.txt"},
                {"source": "files/b.txt", "destination": "addon_data/x/f.txt"},
            ],
        }, sources={"files/a.txt": b"a", "files/b.txt": b"b"})
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.load_package("common")
        self.assertIn("duplicate file destination", str(ctx.exception))

    def test_duplicate_destination_after_normalization_rejected(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [
                {"source": "files/a.txt", "destination": "addon_data/x/f.txt"},
                {"source": "files/b.txt", "destination": "addon_data/./x/f.txt"},
            ],
        }, sources={"files/a.txt": b"a", "files/b.txt": b"b"})
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")

    def test_same_source_two_destinations_allowed(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [
                {"source": "files/a.txt", "destination": "addon_data/x/f.txt"},
                {"source": "files/a.txt", "destination": "addon_data/x/g.txt"},
            ],
        }, sources={"files/a.txt": b"a"})
        self.assertEqual(len(self.loader.load_package("common").files), 2)


# ---------------------------------------------------------------------------
# Overlay semantics
# ---------------------------------------------------------------------------

class TestOverlay(PackageFixture):

    def _build_layers(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "720p"),
            ("plugin.video.example", "shared", "string", "base"),
        ]))
        self.write_package("tvos", self.simple_descriptor("tvos", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
        ]))
        self.write_package("bonus-room", self.simple_descriptor(
            "bonus-room", settings=[
                ("plugin.video.example", "quality", "string", "2160p"),
            ],
        ))

    def test_single_package(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
        ]))
        effective = self.loader.resolve(declarations(
            packages=["common"],
            settings=[("plugin.video.example", "quality")],
        ))
        self.assertEqual(effective.packages, ("common",))
        self.assertEqual(len(effective.settings), 1)
        self.assertEqual(effective.settings[0].value, "1080p")

    def test_skin_selected_package_uses_existing_loader_and_ownership(self):
        self.write_package("skin-pkg", self.simple_descriptor(
            "skin-pkg", settings=[
                ("skin.foo", "accent", "string", "blue"),
            ],
        ))
        effective = self.loader.resolve(declarations(
            packages=["skin-pkg"], settings=[("skin.foo", "accent")],
        ))
        self.assertEqual(effective.packages, ("skin-pkg",))
        self.assertEqual(effective.settings[0].package_id, "skin-pkg")

    def test_skin_selected_package_cannot_expand_ownership(self):
        self.write_package("skin-pkg", self.simple_descriptor(
            "skin-pkg", settings=[
                ("skin.foo", "accent", "string", "blue"),
            ],
        ))
        with self.assertRaises(ConfigOwnershipError):
            self.loader.resolve(declarations(packages=["skin-pkg"]))

    def test_multiple_packages_union(self):
        self._build_layers()
        effective = self.loader.resolve(declarations(
            packages=["common", "tvos"],
            settings=[
                ("plugin.video.example", "quality"),
                ("plugin.video.example", "shared"),
            ],
        ))
        values = {(s.addon_id, s.key): s.value for s in effective.settings}
        self.assertEqual(values[("plugin.video.example", "shared")], "base")

    def test_later_package_wins_for_setting(self):
        self._build_layers()
        effective = self.loader.resolve(declarations(
            packages=["common", "tvos", "bonus-room"],
            settings=[
                ("plugin.video.example", "quality"),
                ("plugin.video.example", "shared"),
            ],
        ))
        winner = next(s for s in effective.settings if s.key == "quality")
        self.assertEqual(winner.value, "2160p")
        self.assertEqual(winner.package_id, "bonus-room")

    def test_reversed_order_changes_winner_deterministically(self):
        self._build_layers()
        decls = declarations(settings=[
            ("plugin.video.example", "quality"),
            ("plugin.video.example", "shared"),
        ])
        forward = self.loader.resolve(ConfigDeclarations(
            packages=("common", "tvos", "bonus-room"),
            managed_settings=decls.managed_settings,
        ))
        reverse = self.loader.resolve(ConfigDeclarations(
            packages=("bonus-room", "tvos", "common"),
            managed_settings=decls.managed_settings,
        ))
        self.assertEqual(
            next(s for s in forward.settings if s.key == "quality").value, "2160p"
        )
        self.assertEqual(
            next(s for s in reverse.settings if s.key == "quality").value, "720p"
        )

    def test_unrelated_targets_retained(self):
        self._build_layers()
        effective = self.loader.resolve(declarations(
            packages=["common", "bonus-room"],
            settings=[
                ("plugin.video.example", "quality"),
                ("plugin.video.example", "shared"),
            ],
        ))
        keys = {s.key for s in effective.settings}
        self.assertEqual(keys, {"quality", "shared"})

    def test_later_package_wins_for_file(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [{"source": "files/a.txt",
                       "destination": "addon_data/x/f.txt"}],
        }, sources={"files/a.txt": b"base"})
        self.write_package("tvos", {
            "schema_version": 1, "id": "tvos",
            "files": [{"source": "files/a.txt",
                       "destination": "addon_data/x/f.txt"}],
        }, sources={"files/a.txt": b"override"})
        effective = self.loader.resolve(declarations(
            packages=["common", "tvos"], files=["addon_data/x/f.txt"],
        ))
        self.assertEqual(len(effective.files), 1)
        self.assertEqual(effective.files[0].content, b"override")
        self.assertEqual(effective.files[0].package_id, "tvos")

    def test_duplicate_package_ids_collapsed_to_first_occurrence(self):
        self._build_layers()
        effective = self.loader.resolve(ConfigDeclarations(
            packages=("common", "tvos", "common"),
            managed_settings=(
                ManagedSettingScope(
                    addon_id="plugin.video.example", keys=("quality", "shared")
                ),
            ),
        ))
        self.assertEqual(effective.packages, ("common", "tvos"))
        winner = next(s for s in effective.settings if s.key == "quality")
        self.assertEqual(winner.value, "1080p")

    def test_resolve_is_repeatable(self):
        self._build_layers()
        decls = declarations(
            packages=["common", "tvos", "bonus-room"],
            settings=[
                ("plugin.video.example", "quality"),
                ("plugin.video.example", "shared"),
            ],
        )
        first = self.loader.resolve(decls)
        second = self.loader.resolve(decls)
        self.assertEqual(first, second)


class TestSkinTargetResolution(PackageFixture):

    @staticmethod
    def _scope(target_kind, addon_id, key):
        return ManagedSettingScope(
            target_kind=target_kind, addon_id=addon_id, keys=(key,)
        )

    def test_skin_target_requires_skin_ownership(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "target": "skin", "addon_id": "skin.foo", "key": "accent",
                "type": "string", "value": "blue",
            }],
        })
        with self.assertRaises(ConfigOwnershipError):
            self.loader.resolve(ConfigDeclarations(
                packages=("common",),
                managed_settings=(self._scope(
                    ConfigTargetKind.ADDON, "skin.foo", "accent"
                ),),
            ))

    def test_addon_and_skin_targets_with_same_addon_and_key_are_distinct(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [
                {"addon_id": "same.id", "key": "key", "type": "string", "value": "addon"},
                {"target": "skin", "addon_id": "same.id", "key": "key", "type": "string", "value": "skin"},
            ],
        })
        effective = self.loader.resolve(ConfigDeclarations(
            packages=("common",),
            managed_settings=(
                self._scope(ConfigTargetKind.ADDON, "same.id", "key"),
                self._scope(ConfigTargetKind.SKIN, "same.id", "key"),
            ),
        ))
        self.assertEqual(
            {setting.target for setting in effective.settings},
            {("addon", "same.id", "key"), ("skin", "same.id", "key")},
        )

    def test_skin_target_identity_changes_effective_identity(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "addon_id": "same.id", "key": "key", "type": "string", "value": "v",
            }],
        })
        addon = self.loader.resolve(ConfigDeclarations(
            packages=("common",),
            managed_settings=(self._scope(
                ConfigTargetKind.ADDON, "same.id", "key"
            ),),
        ))
        self.write_package("skinpkg", {
            "schema_version": 1, "id": "skinpkg",
            "settings": [{
                "target": "skin", "addon_id": "same.id", "key": "key",
                "type": "string", "value": "v",
            }],
        })
        skin = self.loader.resolve(ConfigDeclarations(
            packages=("skinpkg",),
            managed_settings=(self._scope(
                ConfigTargetKind.SKIN, "same.id", "key"
            ),),
        ))
        self.assertNotEqual(addon.identity, skin.identity)

    def test_af3_mutually_exclusive_modes_fail_preflight(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [
                {"target": "skin", "addon_id": "skin.arctic.fuse.3",
                 "key": "HomeSwitcher.EnableIcons", "type": "bool", "value": True},
                {"target": "skin", "addon_id": "skin.arctic.fuse.3",
                 "key": "HomeSwitcher.EnableIconText", "type": "bool", "value": True},
            ],
        })
        with self.assertRaises(ConfigPackageError) as ctx:
            self.loader.resolve(ConfigDeclarations(
                packages=("common",),
                managed_settings=(
                    self._scope(ConfigTargetKind.SKIN, "skin.arctic.fuse.3", "HomeSwitcher.EnableIcons"),
                    self._scope(ConfigTargetKind.SKIN, "skin.arctic.fuse.3", "HomeSwitcher.EnableIconText"),
                ),
            ))
        self.assertIn("mutually exclusive", str(ctx.exception))

    def test_missing_package_fails(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
        ]))
        with self.assertRaises(ConfigPackageError):
            self.loader.resolve(declarations(
                packages=["common", "absent"],
                settings=[("plugin.video.example", "quality")],
            ))

    def test_invalid_package_id_in_declarations_rejected(self):
        with self.assertRaises(ConfigPackageError):
            self.loader.resolve(declarations(packages=["../escape"]))

    def test_settings_sorted_deterministically(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.z", "b", "string", "1"),
            ("plugin.video.a", "z", "string", "2"),
            ("plugin.video.a", "a", "string", "3"),
        ]))
        effective = self.loader.resolve(declarations(
            packages=["common"],
            settings=[
                ("plugin.video.z", "b"),
                ("plugin.video.a", "z"),
                ("plugin.video.a", "a"),
            ],
        ))
        self.assertEqual(
            [(s.addon_id, s.key) for s in effective.settings],
            [("plugin.video.a", "a"), ("plugin.video.a", "z"),
             ("plugin.video.z", "b")],
        )

    def test_files_sorted_deterministically(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [
                {"source": "files/a", "destination": "addon_data/z.txt"},
                {"source": "files/a", "destination": "addon_data/a.txt"},
            ],
        }, sources={"files/a": b"x"})
        effective = self.loader.resolve(declarations(
            packages=["common"],
            files=["addon_data/z.txt", "addon_data/a.txt"],
        ))
        self.assertEqual(
            [f.destination for f in effective.files],
            ["addon_data/a.txt", "addon_data/z.txt"],
        )

# ---------------------------------------------------------------------------
# No config / empty config
# ---------------------------------------------------------------------------

class TestNoAndEmptyConfig(PackageFixture):

    def test_none_config_is_noop(self):
        effective = self.loader.resolve(None)
        self.assertEqual(effective, EffectiveConfiguration())
        self.assertTrue(effective.is_empty)

    def test_empty_config_is_noop(self):
        effective = self.loader.resolve(ConfigDeclarations())
        self.assertEqual(effective.packages, ())
        self.assertEqual(effective.settings, ())
        self.assertEqual(effective.files, ())
        self.assertTrue(effective.is_empty)

    def test_empty_package_with_no_declarations_is_valid(self):
        self.write_package("empty", {"schema_version": 1, "id": "empty"})
        effective = self.loader.resolve(declarations(packages=["empty"]))
        self.assertEqual(effective.packages, ("empty",))
        self.assertTrue(effective.is_empty)

    def test_apply_of_empty_configuration_makes_no_backend_calls(self):
        backend = FakeConfigurationBackend()
        result = ConfigurationManager(backend).apply(EffectiveConfiguration())
        self.assertEqual(result.results, ())
        self.assertTrue(result.all_applied)
        self.assertEqual(backend.calls, [])


# ---------------------------------------------------------------------------
# Ownership + completeness
# ---------------------------------------------------------------------------

class TestOwnership(PackageFixture):

    def test_declared_setting_allowed(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
        ]))
        effective = self.loader.resolve(declarations(
            packages=["common"], settings=[("plugin.video.example", "quality")],
        ))
        self.assertEqual(len(effective.settings), 1)

    def test_undeclared_setting_rejected(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
            ("plugin.video.foo", "some_unmanaged_key", "string", "x"),
        ]))
        with self.assertRaises(ConfigOwnershipError) as ctx:
            self.loader.resolve(declarations(
                packages=["common"],
                settings=[("plugin.video.example", "quality")],
            ))
        message = str(ctx.exception)
        self.assertIn("some_unmanaged_key", message)
        self.assertIn("not declared in config.managed_settings", message)

    def test_undeclared_key_on_declared_addon_rejected(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
            ("plugin.video.example", "other", "string", "x"),
        ]))
        with self.assertRaises(ConfigOwnershipError):
            self.loader.resolve(declarations(
                packages=["common"],
                settings=[("plugin.video.example", "quality")],
            ))

    def test_declared_file_allowed(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [{"source": "files/a", "destination": "addon_data/x/f.txt"}],
        }, sources={"files/a": b"x"})
        effective = self.loader.resolve(declarations(
            packages=["common"], files=["addon_data/x/f.txt"],
        ))
        self.assertEqual(len(effective.files), 1)

    def test_undeclared_file_rejected(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [{"source": "files/a", "destination": "addon_data/x/f.txt"}],
        }, sources={"files/a": b"x"})
        with self.assertRaises(ConfigOwnershipError) as ctx:
            self.loader.resolve(declarations(packages=["common"]))
        self.assertIn("not declared in config.managed_files", str(ctx.exception))

    def test_declared_setting_without_package_value_rejected(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
        ]))
        with self.assertRaises(ConfigOwnershipError) as ctx:
            self.loader.resolve(declarations(
                packages=["common"],
                settings=[
                    ("plugin.video.example", "quality"),
                    ("plugin.video.example", "missing"),
                ],
            ))
        message = str(ctx.exception)
        self.assertIn("unresolved managed configuration", message)
        self.assertIn("missing", message)

    def test_declared_file_without_package_content_rejected(self):
        self.write_package("common", {"schema_version": 1, "id": "common"})
        with self.assertRaises(ConfigOwnershipError) as ctx:
            self.loader.resolve(declarations(
                packages=["common"], files=["addon_data/x/f.txt"],
            ))
        self.assertIn("unresolved managed configuration", str(ctx.exception))

    def test_exact_complete_target_set_is_valid(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "addon_id": "plugin.video.example", "key": "quality",
                "type": "string", "value": "1080p",
            }],
            "files": [{"source": "files/a", "destination": "addon_data/x/f.txt"}],
        }, sources={"files/a": b"x"})
        effective = self.loader.resolve(declarations(
            packages=["common"],
            settings=[("plugin.video.example", "quality")],
            files=["addon_data/x/f.txt"],
        ))
        self.assertEqual(len(effective.settings), 1)
        self.assertEqual(len(effective.files), 1)

    def test_layered_packages_together_satisfy_completeness(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "a", "string", "1"),
        ]))
        self.write_package("tvos", self.simple_descriptor("tvos", settings=[
            ("plugin.video.example", "b", "string", "2"),
        ]))
        effective = self.loader.resolve(declarations(
            packages=["common", "tvos"],
            settings=[("plugin.video.example", "a"), ("plugin.video.example", "b")],
        ))
        self.assertEqual(len(effective.settings), 2)

    def test_manifest_declaring_unusable_managed_path_rejected(self):
        self.write_package("common", {"schema_version": 1, "id": "common"})
        with self.assertRaises(ConfigOwnershipError) as ctx:
            self.loader.resolve(ConfigDeclarations(
                packages=("common",),
                managed_files=("special://home/addons/evil",),
            ))
        self.assertIn("unusable managed file path", str(ctx.exception))

    def test_declared_file_matching_requires_normalized_equality(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "files": [{"source": "files/a", "destination": "addon_data/x/f.txt"}],
        }, sources={"files/a": b"x"})
        # Manifest paths are normalized by the manifest parser; config.py
        # normalizes again so equivalent spellings still match exactly.
        effective = self.loader.resolve(declarations(
            packages=["common"], files=["addon_data/./x/f.txt"],
        ))
        self.assertEqual(effective.files[0].destination, "addon_data/x/f.txt")


# ---------------------------------------------------------------------------
# Preflight guarantee
# ---------------------------------------------------------------------------

class TestPreflightGuarantee(PackageFixture):

    def _good_first_package(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
        ]))

    def _apply(self, decls, backend):
        effective = self.loader.resolve(decls)
        return ConfigurationManager(backend).apply(effective)

    def test_malformed_second_package_means_zero_mutation(self):
        self._good_first_package()
        self.write_package("tvos", None, raw="{broken")
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "quality"): "480p"}
        )
        with self.assertRaises(ConfigPackageError):
            self._apply(
                declarations(
                    packages=["common", "tvos"],
                    settings=[("plugin.video.example", "quality")],
                ),
                backend,
            )
        self.assertEqual(backend.calls, [])
        self.assertEqual(backend.mutations, [])

    def test_missing_source_in_later_package_means_zero_mutation(self):
        self._good_first_package()
        self.write_package("tvos", {
            "schema_version": 1, "id": "tvos",
            "files": [{"source": "files/absent",
                       "destination": "addon_data/x/f.txt"}],
        })
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "quality"): "480p"}
        )
        with self.assertRaises(ConfigPackageError):
            self._apply(
                declarations(
                    packages=["common", "tvos"],
                    settings=[("plugin.video.example", "quality")],
                    files=["addon_data/x/f.txt"],
                ),
                backend,
            )
        self.assertEqual(backend.mutations, [])

    def test_ownership_error_means_zero_mutation(self):
        self.write_package("common", self.simple_descriptor("common", settings=[
            ("plugin.video.example", "quality", "string", "1080p"),
            ("plugin.video.foo", "unmanaged", "string", "x"),
        ]))
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "quality"): "480p"}
        )
        with self.assertRaises(ConfigOwnershipError):
            self._apply(
                declarations(
                    packages=["common"],
                    settings=[("plugin.video.example", "quality")],
                ),
                backend,
            )
        self.assertEqual(backend.mutations, [])

    def test_completeness_error_means_zero_mutation(self):
        self._good_first_package()
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "quality"): "480p"}
        )
        with self.assertRaises(ConfigOwnershipError):
            self._apply(
                declarations(
                    packages=["common"],
                    settings=[
                        ("plugin.video.example", "quality"),
                        ("plugin.video.example", "unsupplied"),
                    ],
                ),
                backend,
            )
        self.assertEqual(backend.mutations, [])

    def test_bad_setting_type_in_later_package_means_zero_mutation(self):
        self._good_first_package()
        self.write_package("tvos", {
            "schema_version": 1, "id": "tvos",
            "settings": [{
                "addon_id": "plugin.video.example", "key": "count",
                "type": "int", "value": True,
            }],
        })
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "quality"): "480p"}
        )
        with self.assertRaises(ConfigPackageError):
            self._apply(
                declarations(
                    packages=["common", "tvos"],
                    settings=[
                        ("plugin.video.example", "quality"),
                        ("plugin.video.example", "count"),
                    ],
                ),
                backend,
            )
        self.assertEqual(backend.mutations, [])


# ---------------------------------------------------------------------------
# Setting deployment
# ---------------------------------------------------------------------------

def setting(addon_id="plugin.video.example", key="k",
            setting_type=ConfigSettingType.STRING, value="v",
            package_id="common", target_kind=ConfigTargetKind.ADDON):
    return ConfigSetting(
        addon_id=addon_id, key=key, setting_type=setting_type,
        value=value, package_id=package_id, target_kind=target_kind,
    )


class TestSettingDeployment(unittest.TestCase):

    def _apply_one(self, backend, cfg_setting):
        result = ConfigurationManager(backend).apply(
            EffectiveConfiguration(settings=(cfg_setting,))
        )
        self.assertEqual(len(result.results), 1)
        return result.results[0]

    # -- per type: no-op and drift -----------------------------------------

    def test_string_already_correct(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): "v"}
        )
        outcome = self._apply_one(backend, setting())
        self.assertIs(outcome.status, ConfigOperationStatus.ALREADY_CORRECT)
        self.assertEqual(backend.mutations, [])

    def test_string_drift_updated_and_verified(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): "old"}
        )
        outcome = self._apply_one(backend, setting())
        self.assertIs(outcome.status, ConfigOperationStatus.UPDATED)
        self.assertEqual(backend.settings[("plugin.video.example", "k")], "v")
        self.assertEqual(
            backend.calls,
            [("get_setting", "plugin.video.example", "k"),
             ("set_setting", "plugin.video.example", "k"),
             ("get_setting", "plugin.video.example", "k")],
        )

    def test_skin_bool_and_string_use_dedicated_namespace(self):
        backend = FakeSkinConfigurationBackend(settings={
            ("skin.arctic.fuse.3", "flag"): False,
            ("skin.arctic.fuse.3", "label"): "old",
        })
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            settings=(
                setting(
                    addon_id="skin.arctic.fuse.3", key="flag",
                    setting_type=ConfigSettingType.BOOL, value=True,
                    target_kind=ConfigTargetKind.SKIN,
                ),
                setting(
                    addon_id="skin.arctic.fuse.3", key="label", value="new",
                    target_kind=ConfigTargetKind.SKIN,
                ),
            ),
        ))
        self.assertTrue(result.all_applied)
        self.assertEqual(len(result.changed), 2)
        self.assertEqual(
            backend.calls,
            [("get_skin_setting", "skin.arctic.fuse.3", "flag"),
             ("set_skin_setting", "skin.arctic.fuse.3", "flag"),
             ("get_skin_setting", "skin.arctic.fuse.3", "flag"),
             ("get_skin_setting", "skin.arctic.fuse.3", "label"),
             ("set_skin_setting", "skin.arctic.fuse.3", "label"),
             ("get_skin_setting", "skin.arctic.fuse.3", "label")],
        )

    def test_skin_wrong_active_skin_fails_without_mutation(self):
        backend = FakeSkinConfigurationBackend(
            settings={("skin.arctic.fuse.3", "flag"): False},
            active_skin="skin.estuary",
        )
        outcome = self._apply_one(backend, setting(
            addon_id="skin.arctic.fuse.3", key="flag",
            setting_type=ConfigSettingType.BOOL, value=True,
            target_kind=ConfigTargetKind.SKIN,
        ))
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertEqual(backend.mutations, [])

    def test_skin_failed_read_fails_without_mutation(self):
        backend = FakeSkinConfigurationBackend()
        backend.skin_get_errors[("skin.arctic.fuse.3", "flag")] = "unavailable"
        outcome = self._apply_one(backend, setting(
            addon_id="skin.arctic.fuse.3", key="flag",
            setting_type=ConfigSettingType.BOOL, value=True,
            target_kind=ConfigTargetKind.SKIN,
        ))
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertEqual(backend.mutations, [])

    def test_skin_verification_mismatch_fails(self):
        backend = FakeSkinConfigurationBackend(
            settings={("skin.arctic.fuse.3", "flag"): False},
        )
        backend.skin_write_result[("skin.arctic.fuse.3", "flag")] = False
        outcome = self._apply_one(backend, setting(
            addon_id="skin.arctic.fuse.3", key="flag",
            setting_type=ConfigSettingType.BOOL, value=True,
            target_kind=ConfigTargetKind.SKIN,
        ))
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("verification mismatch", outcome.detail)

    def test_bool_already_correct(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): True}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.BOOL, value=True))
        self.assertIs(outcome.status, ConfigOperationStatus.ALREADY_CORRECT)

    def test_bool_drift(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): False}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.BOOL, value=True))
        self.assertIs(outcome.status, ConfigOperationStatus.UPDATED)
        self.assertIs(backend.settings[("plugin.video.example", "k")], True)

    def test_int_already_correct(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 20}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.INT, value=20))
        self.assertIs(outcome.status, ConfigOperationStatus.ALREADY_CORRECT)

    def test_int_drift(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 5}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.INT, value=20))
        self.assertIs(outcome.status, ConfigOperationStatus.UPDATED)
        self.assertEqual(backend.settings[("plugin.video.example", "k")], 20)

    def test_number_already_correct(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 1.5}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.NUMBER, value=1.5))
        self.assertIs(outcome.status, ConfigOperationStatus.ALREADY_CORRECT)
        self.assertEqual(backend.mutations, [])

    def test_number_already_correct_within_kodi_precision(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 1.5000000000001}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.NUMBER, value=1.5))
        self.assertIs(outcome.status, ConfigOperationStatus.ALREADY_CORRECT)

    def test_number_drift(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 0.5}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.NUMBER, value=1.5))
        self.assertIs(outcome.status, ConfigOperationStatus.UPDATED)
        self.assertEqual(backend.settings[("plugin.video.example", "k")], 1.5)

    def test_number_backend_returning_int_is_accepted(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 2}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.NUMBER, value=2.0))
        self.assertIs(outcome.status, ConfigOperationStatus.ALREADY_CORRECT)

    # -- failures ----------------------------------------------------------

    def test_read_failure_is_failed_not_default(self):
        backend = FakeConfigurationBackend()
        backend.get_errors[("plugin.video.example", "k")] = "JSON-RPC down"
        outcome = self._apply_one(backend, setting())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("could not read", outcome.detail)
        self.assertEqual(backend.mutations, [])

    def test_set_failure_is_failed(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): "old"}
        )
        backend.set_errors[("plugin.video.example", "k")] = "write refused"
        outcome = self._apply_one(backend, setting())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("could not set", outcome.detail)

    def test_verification_mismatch_is_failed(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): "old"}
        )
        backend.write_result[("plugin.video.example", "k")] = "something-else"
        outcome = self._apply_one(backend, setting())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("verification mismatch", outcome.detail)

    def test_verification_read_failure_is_failed(self):
        class OneShot(FakeConfigurationBackend):
            def get_setting(self, addon_id, key, setting_type):
                if ("set_setting", addon_id, key) in self.calls:
                    self.calls.append(("get_setting", addon_id, key))
                    raise ConfigBackendError("verify read failed")
                return super().get_setting(addon_id, key, setting_type)

        backend = OneShot(settings={("plugin.video.example", "k"): "old"})
        outcome = self._apply_one(backend, setting())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("could not verify", outcome.detail)

    def test_missing_target_addon_fails_clearly(self):
        backend = FakeConfigurationBackend(
            missing_addons=["plugin.video.example"]
        )
        outcome = self._apply_one(backend, setting())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("not installed or cannot be opened", outcome.detail)
        self.assertEqual(backend.mutations, [])

    def test_wrongly_typed_backend_response_fails_closed(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 1}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.STRING, value="v"))
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertEqual(backend.mutations, [])

    def test_bool_backend_returning_int_fails_closed(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): 1}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.BOOL, value=True))
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)

    def test_int_backend_returning_bool_fails_closed(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): True}
        )
        outcome = self._apply_one(backend, setting(
            setting_type=ConfigSettingType.INT, value=1))
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)

    # -- scope -------------------------------------------------------------

    def test_unmanaged_setting_never_touched(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.example", "k"): "old",
            ("plugin.video.example", "untouched"): "keep",
        })
        ConfigurationManager(backend).apply(
            EffectiveConfiguration(settings=(setting(),))
        )
        self.assertEqual(
            backend.settings[("plugin.video.example", "untouched")], "keep"
        )
        touched = {(c[1], c[2]) for c in backend.calls}
        self.assertEqual(touched, {("plugin.video.example", "k")})


# ---------------------------------------------------------------------------
# Managed file deployment
# ---------------------------------------------------------------------------

def config_file(destination="addon_data/x/f.txt", content=b"desired",
                source="files/a", package_id="common"):
    return ConfigFile(
        destination=destination, source=source,
        content=content, package_id=package_id,
    )


class TestFileDeployment(unittest.TestCase):

    def _apply_one(self, backend, cfg_file):
        result = ConfigurationManager(backend).apply(
            EffectiveConfiguration(files=(cfg_file,))
        )
        self.assertEqual(len(result.results), 1)
        return result.results[0]

    def test_missing_destination_created(self):
        backend = FakeConfigurationBackend()
        outcome = self._apply_one(backend, config_file())
        self.assertIs(outcome.status, ConfigOperationStatus.CREATED)
        self.assertEqual(backend.files["addon_data/x/f.txt"], b"desired")
        self.assertIsNone(outcome.previous_identity)

    def test_identical_destination_is_noop(self):
        backend = FakeConfigurationBackend(
            files={"addon_data/x/f.txt": b"desired"}
        )
        outcome = self._apply_one(backend, config_file())
        self.assertIs(outcome.status, ConfigOperationStatus.ALREADY_CORRECT)
        self.assertEqual(backend.mutations, [])

    def test_different_destination_updated(self):
        backend = FakeConfigurationBackend(
            files={"addon_data/x/f.txt": b"stale"}
        )
        outcome = self._apply_one(backend, config_file())
        self.assertIs(outcome.status, ConfigOperationStatus.UPDATED)
        self.assertEqual(backend.files["addon_data/x/f.txt"], b"desired")
        self.assertIsNotNone(outcome.previous_identity)
        self.assertNotEqual(outcome.previous_identity, outcome.expected_identity)

    def test_read_failure_is_failed(self):
        backend = FakeConfigurationBackend()
        backend.read_errors["addon_data/x/f.txt"] = "unreadable"
        outcome = self._apply_one(backend, config_file())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertEqual(backend.mutations, [])

    def test_write_failure_is_failed(self):
        backend = FakeConfigurationBackend()
        backend.write_errors["addon_data/x/f.txt"] = "read-only filesystem"
        outcome = self._apply_one(backend, config_file())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("could not write", outcome.detail)

    def test_post_write_mismatch_is_failed(self):
        backend = FakeConfigurationBackend()
        backend.write_result["addon_data/x/f.txt"] = b"corrupted"
        outcome = self._apply_one(backend, config_file())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("verification mismatch", outcome.detail)

    def test_post_write_absence_is_failed(self):
        class VanishingBackend(FakeConfigurationBackend):
            def write_file(self, destination, data):
                self.calls.append(("write_file", destination))
                self.writes.append(destination)

        backend = VanishingBackend()
        outcome = self._apply_one(backend, config_file())
        self.assertIs(outcome.status, ConfigOperationStatus.FAILED)
        self.assertIn("absent after writing", outcome.detail)

    def test_sibling_unmanaged_file_untouched(self):
        backend = FakeConfigurationBackend(files={
            "addon_data/x/f.txt": b"stale",
            "addon_data/x/sibling.txt": b"keep",
        })
        ConfigurationManager(backend).apply(
            EffectiveConfiguration(files=(config_file(),))
        )
        self.assertEqual(backend.files["addon_data/x/sibling.txt"], b"keep")
        self.assertEqual(
            {c[1] for c in backend.calls}, {"addon_data/x/f.txt"}
        )

    def test_empty_content_file_supported(self):
        backend = FakeConfigurationBackend()
        outcome = self._apply_one(backend, config_file(content=b""))
        self.assertIs(outcome.status, ConfigOperationStatus.CREATED)
        self.assertEqual(backend.files["addon_data/x/f.txt"], b"")

    def test_existing_empty_file_is_not_treated_as_absent(self):
        backend = FakeConfigurationBackend(files={"addon_data/x/f.txt": b""})
        outcome = self._apply_one(backend, config_file(content=b"desired"))
        self.assertIs(outcome.status, ConfigOperationStatus.UPDATED)


# ---------------------------------------------------------------------------
# Kodi runtime backend — filesystem containment (no Kodi required)
# ---------------------------------------------------------------------------

class TestKodiRuntimeBackendFilesystem(unittest.TestCase):
    """Exercise the real backend's file handling with a stubbed profile root."""

    def setUp(self):
        self.profile = tempfile.mkdtemp(prefix="bm015-profile-")
        self.addCleanup(shutil.rmtree, self.profile, ignore_errors=True)
        self.backend = KodiRuntimeConfigurationBackend()
        # Bypass xbmcvfs.translatePath; the containment logic under test is
        # everything that happens after translation.
        self.backend._translated_root = os.path.realpath(self.profile)

    def test_read_missing_file_returns_none(self):
        self.assertIsNone(self.backend.read_file("addon_data/x/f.txt"))

    def test_write_creates_parent_directories(self):
        self.backend.write_file("addon_data/x/y/f.txt", b"hello")
        path = os.path.join(self.profile, "addon_data", "x", "y", "f.txt")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"hello")

    def test_write_then_read_round_trip(self):
        self.backend.write_file("addon_data/x/f.txt", b"hello")
        self.assertEqual(self.backend.read_file("addon_data/x/f.txt"), b"hello")

    def test_write_replaces_existing_content(self):
        self.backend.write_file("addon_data/x/f.txt", b"first")
        self.backend.write_file("addon_data/x/f.txt", b"second")
        self.assertEqual(self.backend.read_file("addon_data/x/f.txt"), b"second")

    def test_write_leaves_no_staging_file_behind(self):
        self.backend.write_file("addon_data/x/f.txt", b"hello")
        entries = os.listdir(os.path.join(self.profile, "addon_data", "x"))
        self.assertEqual(entries, ["f.txt"])

    def test_write_does_not_touch_sibling_files(self):
        directory = os.path.join(self.profile, "addon_data", "x")
        os.makedirs(directory)
        with open(os.path.join(directory, "sibling.txt"), "wb") as handle:
            handle.write(b"keep")
        self.backend.write_file("addon_data/x/f.txt", b"hello")
        with open(os.path.join(directory, "sibling.txt"), "rb") as handle:
            self.assertEqual(handle.read(), b"keep")

    def test_traversal_destination_refused(self):
        with self.assertRaises(ConfigBackendError):
            self.backend.read_file("../escape.txt")
        with self.assertRaises(ConfigBackendError):
            self.backend.write_file("../escape.txt", b"x")

    def test_absolute_destination_refused(self):
        with self.assertRaises(ConfigBackendError):
            self.backend.write_file("/tmp/escape.txt", b"x")

    def test_special_scheme_destination_refused(self):
        with self.assertRaises(ConfigBackendError):
            self.backend.write_file("special://home/escape.txt", b"x")

    # -- symlink policy -----------------------------------------------------

    def _outside_dir(self):
        outside = tempfile.mkdtemp(prefix="bm015-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        return outside

    def test_destination_symlink_to_outside_profile_refused(self):
        outside = self._outside_dir()
        sentinel = os.path.join(outside, "sentinel.txt")
        with open(sentinel, "wb") as handle:
            handle.write(b"outside-sentinel")
        os.makedirs(os.path.join(self.profile, "addon_data"))
        os.symlink(sentinel, os.path.join(self.profile, "addon_data", "f.txt"))

        with self.assertRaises(ConfigBackendError) as ctx:
            self.backend.write_file("addon_data/f.txt", b"attacker")
        self.assertIn("symlink", str(ctx.exception))
        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"outside-sentinel")

    def test_destination_symlink_to_different_file_inside_profile_refused(self):
        directory = os.path.join(self.profile, "addon_data")
        os.makedirs(directory)
        other = os.path.join(directory, "unmanaged.txt")
        with open(other, "wb") as handle:
            handle.write(b"unmanaged-content")
        os.symlink(other, os.path.join(directory, "f.txt"))

        with self.assertRaises(ConfigBackendError) as ctx:
            self.backend.write_file("addon_data/f.txt", b"attacker")
        self.assertIn("symlink", str(ctx.exception))
        with open(other, "rb") as handle:
            self.assertEqual(handle.read(), b"unmanaged-content")

    def test_parent_directory_symlink_inside_profile_refused(self):
        os.makedirs(os.path.join(self.profile, "addon_data", "real"))
        os.symlink(
            os.path.join(self.profile, "addon_data", "real"),
            os.path.join(self.profile, "addon_data", "link"),
        )
        with self.assertRaises(ConfigBackendError) as ctx:
            self.backend.write_file("addon_data/link/f.txt", b"attacker")
        self.assertIn("symlink", str(ctx.exception))
        self.assertEqual(
            os.listdir(os.path.join(self.profile, "addon_data", "real")), []
        )

    def test_parent_directory_symlink_outside_profile_refused(self):
        outside = self._outside_dir()
        os.makedirs(os.path.join(self.profile, "addon_data"))
        os.symlink(outside, os.path.join(self.profile, "addon_data", "link"))
        with self.assertRaises(ConfigBackendError) as ctx:
            self.backend.write_file("addon_data/link/f.txt", b"attacker")
        self.assertIn("symlink", str(ctx.exception))
        self.assertEqual(os.listdir(outside), [])

    def test_symlinked_destination_is_refused_on_read_too(self):
        directory = os.path.join(self.profile, "addon_data")
        os.makedirs(directory)
        other = os.path.join(directory, "unmanaged.txt")
        with open(other, "wb") as handle:
            handle.write(b"unmanaged-content")
        os.symlink(other, os.path.join(directory, "f.txt"))
        with self.assertRaises(ConfigBackendError):
            self.backend.read_file("addon_data/f.txt")

    def test_broken_symlink_destination_refused(self):
        directory = os.path.join(self.profile, "addon_data")
        os.makedirs(directory)
        os.symlink(os.path.join(directory, "nowhere"),
                   os.path.join(directory, "f.txt"))
        with self.assertRaises(ConfigBackendError):
            self.backend.write_file("addon_data/f.txt", b"attacker")

    # -- staging file -------------------------------------------------------

    def test_legacy_predictable_staging_symlink_is_never_followed(self):
        """A pre-existing '.bm-config-tmp' symlink must not capture the write."""
        outside = self._outside_dir()
        sentinel = os.path.join(outside, "sentinel.txt")
        with open(sentinel, "wb") as handle:
            handle.write(b"outside-sentinel")
        directory = os.path.join(self.profile, "addon_data", "x")
        os.makedirs(directory)
        legacy = os.path.join(directory, "f.txt.bm-config-tmp")
        os.symlink(sentinel, legacy)

        self.backend.write_file("addon_data/x/f.txt", b"desired")

        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"outside-sentinel")
        self.assertEqual(self.backend.read_file("addon_data/x/f.txt"), b"desired")
        self.assertTrue(os.path.islink(legacy))

    def test_staging_file_name_is_not_predictable(self):
        self.backend.write_file("addon_data/x/f.txt", b"one")
        directory = os.path.join(self.profile, "addon_data", "x")
        self.assertNotIn("f.txt.bm-config-tmp", os.listdir(directory))

    def test_staging_artifact_cleaned_after_success(self):
        self.backend.write_file("addon_data/x/f.txt", b"one")
        self.backend.write_file("addon_data/x/f.txt", b"two")
        directory = os.path.join(self.profile, "addon_data", "x")
        self.assertEqual(sorted(os.listdir(directory)), ["f.txt"])

    def test_staging_artifact_cleaned_after_failure(self):
        directory = os.path.join(self.profile, "addon_data", "x")
        os.makedirs(directory)
        with open(os.path.join(directory, "f.txt"), "wb") as handle:
            handle.write(b"original")

        real_replace = os.replace

        def failing_replace(src, dst):
            raise OSError("simulated replace failure")

        os.replace = failing_replace
        try:
            with self.assertRaises(ConfigBackendError):
                self.backend.write_file("addon_data/x/f.txt", b"new")
        finally:
            os.replace = real_replace

        self.assertEqual(sorted(os.listdir(directory)), ["f.txt"])
        with open(os.path.join(directory, "f.txt"), "rb") as handle:
            self.assertEqual(handle.read(), b"original")

    def test_directory_destination_refused(self):
        os.makedirs(os.path.join(self.profile, "addon_data", "x", "f.txt"))
        with self.assertRaises(ConfigBackendError):
            self.backend.read_file("addon_data/x/f.txt")
        with self.assertRaises(ConfigBackendError):
            self.backend.write_file("addon_data/x/f.txt", b"x")

    def test_vfs_url_profile_root_fails_closed(self):
        class StubVfs:
            @staticmethod
            def translatePath(path):
                return "smb://host/share/profile/"

        backend = KodiRuntimeConfigurationBackend()
        backend._xbmcvfs = staticmethod(lambda: StubVfs)
        with self.assertRaises(ConfigBackendError) as ctx:
            backend.read_file("addon_data/x/f.txt")
        self.assertIn("local filesystem path", str(ctx.exception))

    def test_kodi_modules_absent_fails_closed(self):
        backend = KodiRuntimeConfigurationBackend()
        with self.assertRaises(ConfigBackendError):
            backend.get_setting("plugin.video.example", "k",
                                ConfigSettingType.STRING)
        with self.assertRaises(ConfigBackendError):
            backend.read_file("addon_data/x/f.txt")


# ---------------------------------------------------------------------------
# Kodi runtime backend — setting API + Addon lifetime (stubbed xbmcaddon)
# ---------------------------------------------------------------------------

class _StubSettings:
    """Stand-in for Kodi's xbmcaddon.Settings wrapper.

    Mirrors the property that made the original BM-015 bug silent: Kodi's
    CAddonSettings reaches its owning add-on through a WEAK reference, so this
    stub holds only a weakref to the Addon. If the Addon has been released, a
    setter still succeeds against in-memory state but Save() cannot reach its
    owner and nothing is persisted — no exception is raised.
    """

    def __init__(self, addon):
        self._store = addon.store
        self._owner = weakref.ref(addon)

    def _owner_alive(self):
        return self._owner() is not None

    def _get(self, kind, key):
        self._store["record"].append((kind, key, self._owner_alive()))
        if key not in self._store["values"]:
            raise RuntimeError(f"Invalid setting type for {key}")
        # In-memory reads work regardless of owner lifetime.
        return self._store["values"][key]

    def getString(self, key):
        return self._get("getString", key)

    def getBool(self, key):
        return self._get("getBool", key)

    def getInt(self, key):
        return self._get("getInt", key)

    def getNumber(self, key):
        return self._get("getNumber", key)

    def _set(self, kind, key, value):
        alive = self._owner_alive()
        self._store["record"].append((kind, key, alive, value))
        if self._store["fail_setters"]:
            return False
        self._store["memory"][key] = value
        if not alive:
            # Save() cannot reach a released owner: silent non-persistence.
            self._store["orphaned_writes"].append(key)
            return None
        self._store["values"][key] = value
        return None  # Kodi's Settings setters are void

    def setString(self, key, value):
        return self._set("setString", key, value)

    def setBool(self, key, value):
        return self._set("setBool", key, value)

    def setInt(self, key, value):
        return self._set("setInt", key, value)

    def setNumber(self, key, value):
        return self._set("setNumber", key, value)


class _StubAddon:
    """Stand-in for xbmcaddon.Addon sharing persisted state across handles.

    The deprecated typed setters exist so a test can prove they are never
    called; using one records a FORBIDDEN entry.
    """

    registry = {}

    def __init__(self, addon_id):
        if addon_id not in self.registry:
            raise RuntimeError(f"Unknown addon id: {addon_id}")
        self.store = self.registry[addon_id]

    def getSettings(self):
        return _StubSettings(self)

    def _deprecated(self, kind, key, value):
        self.store["record"].append(("FORBIDDEN-" + kind, key, True, value))
        self.store["values"][key] = value
        return True

    def setSettingString(self, key, value):
        return self._deprecated("setSettingString", key, value)

    def setSettingBool(self, key, value):
        return self._deprecated("setSettingBool", key, value)

    def setSettingInt(self, key, value):
        return self._deprecated("setSettingInt", key, value)

    def setSettingNumber(self, key, value):
        return self._deprecated("setSettingNumber", key, value)


class _StubKodiAddonModule(unittest.TestCase):
    """Base class installing a stub xbmcaddon module."""

    def setUp(self):
        import sys
        import types
        _StubAddon.registry = {
            "plugin.video.example": {
                "values": {
                    "text": "old", "flag": False, "count": 1, "ratio": 0.5,
                },
                "memory": {},
                "record": [],
                "orphaned_writes": [],
                "fail_setters": False,
            },
        }
        module = types.ModuleType("xbmcaddon")
        module.Addon = _StubAddon
        self._saved = sys.modules.get("xbmcaddon")
        sys.modules["xbmcaddon"] = module
        self.addCleanup(self._restore)
        self.backend = KodiRuntimeConfigurationBackend()

    def _restore(self):
        import sys
        if self._saved is None:
            sys.modules.pop("xbmcaddon", None)
        else:
            sys.modules["xbmcaddon"] = self._saved

    @property
    def store(self):
        return _StubAddon.registry["plugin.video.example"]

    @property
    def record(self):
        return self.store["record"]


class TestKodiRuntimeBackendSettings(_StubKodiAddonModule):
    """Pin the exact Kodi API the production backend uses for settings.

    The backend must use the current recommended Settings wrapper for BOTH
    reads and writes, and must keep the owning Addon alive across the call.
    The deprecated Addon.setSettingString/Bool/Int/Number must never be used.
    """

    def test_reads_use_the_settings_wrapper(self):
        value = self.backend.get_setting(
            "plugin.video.example", "text", ConfigSettingType.STRING
        )
        self.assertEqual(value, "old")
        self.assertEqual(self.record, [("getString", "text", True)])

    def test_each_type_reads_through_its_typed_wrapper_getter(self):
        for key, setting_type, getter in (
            ("text", ConfigSettingType.STRING, "getString"),
            ("flag", ConfigSettingType.BOOL, "getBool"),
            ("count", ConfigSettingType.INT, "getInt"),
            ("ratio", ConfigSettingType.NUMBER, "getNumber"),
        ):
            self.record.clear()
            self.backend.get_setting("plugin.video.example", key, setting_type)
            self.assertEqual(self.record, [(getter, key, True)])

    def test_writes_use_the_settings_wrapper_setters(self):
        for key, setting_type, value, setter in (
            ("text", ConfigSettingType.STRING, "new", "setString"),
            ("flag", ConfigSettingType.BOOL, True, "setBool"),
            ("count", ConfigSettingType.INT, 7, "setInt"),
            ("ratio", ConfigSettingType.NUMBER, 1.5, "setNumber"),
        ):
            self.record.clear()
            self.backend.set_setting(
                "plugin.video.example", key, setting_type, value
            )
            self.assertEqual(len(self.record), 1)
            self.assertEqual(self.record[0][0], setter)
            self.assertEqual(self.record[0][1], key)

    def test_addon_is_still_alive_when_the_setter_runs(self):
        """The owning Addon must not be released before the write completes."""
        for key, setting_type, value in (
            ("text", ConfigSettingType.STRING, "new"),
            ("flag", ConfigSettingType.BOOL, True),
            ("count", ConfigSettingType.INT, 7),
            ("ratio", ConfigSettingType.NUMBER, 1.5),
        ):
            self.record.clear()
            self.backend.set_setting(
                "plugin.video.example", key, setting_type, value
            )
            self.assertTrue(
                self.record[0][2],
                f"owning Addon was already released during the {key!r} write",
            )
        self.assertEqual(self.store["orphaned_writes"], [])

    def test_addon_is_still_alive_when_the_getter_runs(self):
        self.backend.get_setting(
            "plugin.video.example", "text", ConfigSettingType.STRING
        )
        self.assertTrue(self.record[0][2])

    def test_deprecated_addon_typed_setters_are_never_called(self):
        for key, setting_type, value in (
            ("text", ConfigSettingType.STRING, "new"),
            ("flag", ConfigSettingType.BOOL, True),
            ("count", ConfigSettingType.INT, 7),
            ("ratio", ConfigSettingType.NUMBER, 1.5),
        ):
            self.backend.set_setting(
                "plugin.video.example", key, setting_type, value
            )
        forbidden = [e for e in self.record if e[0].startswith("FORBIDDEN")]
        self.assertEqual(forbidden, [])

    def test_discarding_the_addon_would_silently_lose_the_write(self):
        """Documents the original defect the lifetime rule prevents.

        This is the shape the first BM-015 revision used: a helper that built
        the Settings wrapper and dropped the Addon. The setter does not raise,
        in-memory state changes, and nothing is persisted.
        """
        import gc

        def orphaned_settings():
            addon = _StubAddon("plugin.video.example")
            return addon.getSettings()          # addon released on return

        settings = orphaned_settings()
        gc.collect()
        settings.setString("text", "lost-value")

        self.assertEqual(self.store["memory"]["text"], "lost-value")
        self.assertEqual(self.store["values"]["text"], "old")
        self.assertEqual(self.store["orphaned_writes"], ["text"])
        self.assertFalse(self.record[-1][2])

    def test_verification_reads_through_a_fresh_addon_and_settings_pair(self):
        """Each accessor opens its own Addon; no handle is reused across ops."""
        manager = ConfigurationManager(self.backend)
        manager.apply(EffectiveConfiguration(settings=(
            setting(addon_id="plugin.video.example", key="text",
                    setting_type=ConfigSettingType.STRING, value="new"),
        )))
        kinds = [entry[0] for entry in self.record]
        self.assertEqual(kinds, ["getString", "setString", "getString"])
        self.assertTrue(all(entry[2] for entry in self.record))

    def test_number_is_passed_as_float(self):
        self.backend.set_setting(
            "plugin.video.example", "ratio", ConfigSettingType.NUMBER, 2
        )
        self.assertIsInstance(self.record[0][3], float)

    def test_write_then_read_round_trip(self):
        self.backend.set_setting(
            "plugin.video.example", "text", ConfigSettingType.STRING, "new"
        )
        self.assertEqual(
            self.backend.get_setting(
                "plugin.video.example", "text", ConfigSettingType.STRING
            ),
            "new",
        )

    def test_unknown_addon_raises_addon_unavailable(self):
        with self.assertRaises(ConfigAddonUnavailableError):
            self.backend.get_setting(
                "plugin.video.absent", "text", ConfigSettingType.STRING
            )

    def test_unknown_key_raises_backend_error(self):
        with self.assertRaises(ConfigBackendError) as ctx:
            self.backend.get_setting(
                "plugin.video.example", "absent", ConfigSettingType.STRING
            )
        self.assertNotIsInstance(ctx.exception, ConfigAddonUnavailableError)

    def test_setter_returning_false_is_a_failure(self):
        self.store["fail_setters"] = True
        with self.assertRaises(ConfigBackendError):
            self.backend.set_setting(
                "plugin.video.example", "text", ConfigSettingType.STRING, "new"
            )

    def test_manager_drives_the_real_backend_end_to_end(self):
        manager = ConfigurationManager(self.backend)
        effective = EffectiveConfiguration(settings=(
            setting(addon_id="plugin.video.example", key="text",
                    setting_type=ConfigSettingType.STRING, value="new"),
            setting(addon_id="plugin.video.example", key="count",
                    setting_type=ConfigSettingType.INT, value=7),
        ))
        first = manager.apply(effective)
        self.assertTrue(first.all_applied)
        self.assertEqual(len(first.changed), 2)
        second = manager.apply(effective)
        self.assertEqual(second.changed, ())
        self.assertEqual(len(second.unchanged), 2)
        self.assertEqual(self.store["orphaned_writes"], [])


# ---------------------------------------------------------------------------
# Batch behaviour, ordering, idempotency
# ---------------------------------------------------------------------------

class TestBatchAndIdempotency(unittest.TestCase):

    def _effective(self):
        return EffectiveConfiguration(
            packages=("common",),
            settings=(
                setting(addon_id="plugin.video.b", key="k", value="1"),
                setting(addon_id="plugin.video.a", key="z", value="2"),
                setting(addon_id="plugin.video.a", key="a", value="3"),
            ),
            files=(
                config_file(destination="addon_data/z.txt", content=b"z"),
                config_file(destination="addon_data/a.txt", content=b"a"),
            ),
        )

    def test_one_result_per_effective_target(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.b", "k"): "1",
            ("plugin.video.a", "z"): "2",
            ("plugin.video.a", "a"): "3",
        })
        result = ConfigurationManager(backend).apply(self._effective())
        self.assertEqual(len(result.results), 5)
        self.assertEqual(len(result.settings), 3)
        self.assertEqual(len(result.files), 2)

    def test_settings_precede_files_in_declared_order(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.b", "k"): "1",
            ("plugin.video.a", "z"): "2",
            ("plugin.video.a", "a"): "3",
        })
        result = ConfigurationManager(backend).apply(self._effective())
        kinds = [r.kind for r in result.results]
        self.assertEqual(kinds, [ConfigOperationKind.SETTING] * 3
                         + [ConfigOperationKind.FILE] * 2)

    def test_operation_order_follows_effective_order(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.b", "k"): "1",
            ("plugin.video.a", "z"): "2",
            ("plugin.video.a", "a"): "3",
        })
        result = ConfigurationManager(backend).apply(self._effective())
        self.assertEqual(
            [r.target for r in result.results],
            ["plugin.video.b/k", "plugin.video.a/z", "plugin.video.a/a",
             "addon_data/z.txt", "addon_data/a.txt"],
        )

    def test_no_undeclared_target_mutated(self):
        backend = FakeConfigurationBackend(
            settings={
                ("plugin.video.b", "k"): "stale",
                ("plugin.video.a", "z"): "2",
                ("plugin.video.a", "a"): "3",
                ("plugin.video.other", "x"): "keep",
            },
            files={"addon_data/other.txt": b"keep"},
        )
        ConfigurationManager(backend).apply(self._effective())
        self.assertEqual(backend.settings[("plugin.video.other", "x")], "keep")
        self.assertEqual(backend.files["addon_data/other.txt"], b"keep")

    def test_first_application_repairs_drift_second_is_noop(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.b", "k"): "drifted",
            ("plugin.video.a", "z"): "2",
            ("plugin.video.a", "a"): "3",
        })
        manager = ConfigurationManager(backend)
        effective = self._effective()

        first = manager.apply(effective)
        self.assertTrue(first.all_applied)
        self.assertEqual(len(first.changed), 3)  # one setting + two files

        backend.calls.clear()
        second = manager.apply(effective)
        self.assertTrue(second.all_applied)
        self.assertEqual(second.changed, ())
        self.assertEqual(len(second.unchanged), 5)
        self.assertEqual(backend.mutations, [])

    def test_one_failure_does_not_block_other_operations(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.a", "z"): "old",
            ("plugin.video.a", "a"): "old",
        })
        backend.get_errors[("plugin.video.b", "k")] = "unreadable"
        result = ConfigurationManager(backend).apply(self._effective())
        self.assertEqual(len(result.failed), 1)
        self.assertFalse(result.all_applied)
        self.assertEqual(len(result.changed), 4)

    def test_aggregate_properties(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.b", "k"): "1",
            ("plugin.video.a", "z"): "old",
            ("plugin.video.a", "a"): "3",
        })
        result = ConfigurationManager(backend).apply(self._effective())
        self.assertTrue(result.all_applied)
        self.assertEqual(len(result.unchanged), 2)
        self.assertEqual(len(result.changed), 3)
        self.assertEqual(result.failed, ())

    def test_empty_result_is_all_applied(self):
        self.assertTrue(ConfigApplyResult().all_applied)


# ---------------------------------------------------------------------------
# Validation state snapshot (BM-014 integration surface)
# ---------------------------------------------------------------------------

class TestValidationStateSnapshot(unittest.TestCase):

    def test_snapshot_covers_every_target(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.a", "k"): "v",
        })
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            settings=(setting(addon_id="plugin.video.a", key="k", value="v"),),
            files=(config_file(destination="addon_data/f.txt", content=b"x"),),
        ))
        state = result.validation_state
        self.assertEqual(state.setting_targets, (("addon", "plugin.video.a", "k"),))
        self.assertEqual(state.file_targets, ("addon_data/f.txt",))
        self.assertEqual(state.verified_settings, (("addon", "plugin.video.a", "k"),))
        self.assertEqual(state.verified_files, ("addon_data/f.txt",))
        self.assertTrue(state.is_fully_verified)

    def test_failed_target_is_in_scope_but_not_verified(self):
        backend = FakeConfigurationBackend()
        backend.get_errors[("plugin.video.a", "k")] = "down"
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            settings=(setting(addon_id="plugin.video.a", key="k", value="v"),),
        ))
        state = result.validation_state
        self.assertEqual(state.setting_targets, (("addon", "plugin.video.a", "k"),))
        self.assertEqual(state.verified_settings, ())
        self.assertEqual(state.failed_settings, (("addon", "plugin.video.a", "k"),))
        self.assertFalse(state.is_fully_verified)

    def test_failed_file_reported(self):
        backend = FakeConfigurationBackend()
        backend.write_errors["addon_data/f.txt"] = "read-only"
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            files=(config_file(destination="addon_data/f.txt"),),
        ))
        state = result.validation_state
        self.assertEqual(state.failed_files, ("addon_data/f.txt",))
        self.assertFalse(state.is_fully_verified)

    def test_snapshot_targets_sorted(self):
        backend = FakeConfigurationBackend(settings={
            ("plugin.video.b", "k"): "1",
            ("plugin.video.a", "z"): "2",
        })
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            settings=(
                setting(addon_id="plugin.video.b", key="k", value="1"),
                setting(addon_id="plugin.video.a", key="z", value="2"),
            ),
        ))
        self.assertEqual(
            result.validation_state.setting_targets,
            (("addon", "plugin.video.a", "z"),
             ("addon", "plugin.video.b", "k")),
        )

    def test_empty_snapshot_is_fully_verified_vacuously(self):
        state = ConfigurationValidationState()
        self.assertTrue(state.is_fully_verified)
        self.assertEqual(state.failed_settings, ())
        self.assertEqual(state.failed_files, ())


# ---------------------------------------------------------------------------
# EffectiveConfiguration identity
# ---------------------------------------------------------------------------

class TestEffectiveConfigurationIdentity(PackageFixture):
    """The identity must cover desired CONTENT, not merely target scope."""

    def _effective(self, packages, settings_by_package, files_by_package=None):
        for package_id in packages:
            entries = settings_by_package.get(package_id, [])
            files = (files_by_package or {}).get(package_id)
            descriptor = {
                "schema_version": 1,
                "id": package_id,
                "settings": [
                    {"addon_id": a, "key": k, "type": t, "value": v}
                    for a, k, t, v in entries
                ],
            }
            sources = {}
            if files is not None:
                descriptor["files"] = [{
                    "source": "files/a.txt",
                    "destination": "addon_data/x/f.txt",
                }]
                sources["files/a.txt"] = files
            self.write_package(package_id, descriptor, sources=sources)

        keys = sorted({
            (a, k)
            for entries in settings_by_package.values()
            for a, k, _t, _v in entries
        })
        managed_files = (
            ["addon_data/x/f.txt"] if files_by_package else []
        )
        return self.loader.resolve(declarations(
            packages=packages, settings=keys, files=managed_files,
        ))

    def test_identity_is_a_sha256_string(self):
        effective = self._effective(
            ["common"],
            {"common": [("plugin.video.example", "quality", "string", "1080p")]},
        )
        self.assertTrue(effective.identity.startswith("sha256:"))
        self.assertEqual(len(effective.identity), len("sha256:") + 64)

    def test_identity_is_stable_across_resolutions(self):
        args = (
            ["common"],
            {"common": [("plugin.video.example", "quality", "string", "1080p")]},
        )
        first = self._effective(*args)
        second = self.loader.resolve(declarations(
            packages=["common"], settings=[("plugin.video.example", "quality")],
        ))
        self.assertEqual(first.identity, second.identity)

    def test_changed_desired_setting_value_changes_identity(self):
        before = self._effective(
            ["common"],
            {"common": [("plugin.video.example", "quality", "string", "720p")]},
        )
        after = self._effective(
            ["common"],
            {"common": [("plugin.video.example", "quality", "string", "4k")]},
        )
        self.assertEqual(
            {(s.addon_id, s.key) for s in before.settings},
            {(s.addon_id, s.key) for s in after.settings},
        )
        self.assertNotEqual(before.identity, after.identity)

    def test_changed_setting_type_changes_identity(self):
        before = self._effective(
            ["common"],
            {"common": [("plugin.video.example", "limit", "int", 1)]},
        )
        after = self._effective(
            ["common"],
            {"common": [("plugin.video.example", "limit", "number", 1)]},
        )
        self.assertNotEqual(before.identity, after.identity)

    def test_changed_file_content_changes_identity(self):
        before = self._effective(
            ["common"], {"common": []}, files_by_package={"common": b"first"}
        )
        after = self._effective(
            ["common"], {"common": []}, files_by_package={"common": b"second"}
        )
        self.assertEqual(
            [f.destination for f in before.files],
            [f.destination for f in after.files],
        )
        self.assertNotEqual(before.identity, after.identity)

    def test_changed_package_order_affecting_winner_changes_identity(self):
        settings = {
            "common": [("plugin.video.example", "quality", "string", "720p")],
            "device": [("plugin.video.example", "quality", "string", "4k")],
        }
        forward = self._effective(["common", "device"], settings)
        reverse = self._effective(["device", "common"], settings)
        self.assertNotEqual(forward.identity, reverse.identity)

    def test_changed_winning_package_changes_identity_even_for_same_value(self):
        """Same effective value, different responsible package → new identity."""
        settings = {
            "common": [("plugin.video.example", "quality", "string", "4k")],
            "device": [("plugin.video.example", "quality", "string", "4k")],
        }
        forward = self._effective(["common", "device"], settings)
        reverse = self._effective(["device", "common"], settings)
        self.assertEqual(
            forward.settings[0].value, reverse.settings[0].value
        )
        self.assertNotEqual(forward.settings[0].package_id,
                            reverse.settings[0].package_id)
        self.assertNotEqual(forward.identity, reverse.identity)

    def test_added_target_changes_identity(self):
        before = self._effective(
            ["common"],
            {"common": [("plugin.video.example", "quality", "string", "4k")]},
        )
        after = self._effective(
            ["common"],
            {"common": [
                ("plugin.video.example", "quality", "string", "4k"),
                ("plugin.video.example", "limit", "int", 5),
            ]},
        )
        self.assertNotEqual(before.identity, after.identity)

    def test_identity_contains_no_raw_values(self):
        effective = self._effective(
            ["common"],
            {"common": [
                ("plugin.video.example", "quality", "string", "secret-marker"),
            ]},
        )
        self.assertNotIn("secret-marker", effective.identity)

    def test_empty_configuration_has_a_stable_identity(self):
        self.assertEqual(
            EffectiveConfiguration().identity, EffectiveConfiguration().identity
        )

    def test_apply_result_carries_the_effective_identity(self):
        effective = self._effective(
            ["common"],
            {"common": [("plugin.video.example", "quality", "string", "4k")]},
        )
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "quality"): "4k"}
        )
        result = ConfigurationManager(backend).apply(effective)
        self.assertEqual(result.effective_identity, effective.identity)
        self.assertEqual(
            result.validation_state.effective_identity, effective.identity
        )


# ---------------------------------------------------------------------------
# Secrets boundary
# ---------------------------------------------------------------------------

class TestSecretsBoundary(PackageFixture):

    @staticmethod
    def _config_source():
        import resources.lib.config as config_module
        with open(config_module.__file__, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_module_does_not_read_private_overlay(self):
        source = self._config_source()
        # The only permitted mentions are in documentation prose.
        self.assertNotIn("private_overlay=", source)
        self.assertNotIn(".private_overlay", source)

    def test_module_imports_no_kodi_modules_at_module_level(self):
        # Kodi modules must be imported lazily (indented, inside a method) so
        # the module is importable and unit-testable outside Kodi.
        for line in self._config_source().splitlines():
            if line.startswith("import xbmc") or line.startswith("from xbmc"):
                self.fail(f"module-level Kodi import found: {line}")

    def test_results_do_not_contain_raw_setting_values(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): "old-value-marker"}
        )
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            settings=(setting(value="new-value-marker"),)
        ))
        blob = repr(result)
        self.assertNotIn("new-value-marker", blob)
        self.assertNotIn("old-value-marker", blob)

    def test_results_do_not_contain_raw_file_content(self):
        backend = FakeConfigurationBackend(
            files={"addon_data/x/f.txt": b"old-content-marker"}
        )
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            files=(config_file(content=b"new-content-marker"),)
        ))
        blob = repr(result)
        self.assertNotIn("new-content-marker", blob)
        self.assertNotIn("old-content-marker", blob)

    def test_result_identifies_target_and_package_for_diagnostics(self):
        backend = FakeConfigurationBackend(
            settings={("plugin.video.example", "k"): "old"}
        )
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            settings=(setting(package_id="af3-common"),)
        ))
        outcome = result.results[0]
        self.assertEqual(outcome.addon_id, "plugin.video.example")
        self.assertEqual(outcome.key, "k")
        self.assertEqual(outcome.package_id, "af3-common")

    def test_secret_reference_setting_type_rejected(self):
        self.write_package("common", {
            "schema_version": 1, "id": "common",
            "settings": [{
                "addon_id": "plugin.video.example", "key": "token",
                "type": "secret", "value": "ref:vault",
            }],
        })
        with self.assertRaises(ConfigPackageError):
            self.loader.load_package("common")


# ---------------------------------------------------------------------------
# Embedded package root
# ---------------------------------------------------------------------------

class TestDefaultPackagesRoot(unittest.TestCase):

    def test_points_at_resources_config_packages(self):
        root = default_packages_root()
        self.assertTrue(root.endswith(os.path.join("resources", "config", "packages")))

    def test_directory_exists_in_the_addon(self):
        self.assertTrue(os.path.isdir(default_packages_root()))

    def test_loader_accepts_it(self):
        loader = ConfigPackageLoader(default_packages_root())
        self.assertEqual(loader.resolve(None), EffectiveConfiguration())

    def test_loader_rejects_empty_root(self):
        with self.assertRaises(ConfigPackageError):
            ConfigPackageLoader("")


class TestAF3CommonProductionPackage(unittest.TestCase):
    """The reviewed BM-018E package is exact, typed, and skin-scoped."""

    SKIN = "skin.arctic.fuse.3"
    BOOLS = {
        "HomeSwitcher.Vertical": False,
        "HomeSwitcher.EnableIcons": False,
        "HomeSwitcher.EnableIconText": True,
        "HomeSwitcher.DisableHeader": True,
        "HomeSwitcher.DisableDate": True,
        "HomeSwitcher.DisableSearch": False,
        "HomeSwitcher.DisableFirstWidgetFocus": False,
        "HomeSwitcher.LoopBack": False,
        "Spotlight.EnableSlide": False,
        "Spotlight.UseMenuButton": False,
        "View.UseDetailedListLabels": True,
        "Widgets.EnableShowMore": True,
        "Widgets.DisableNoResultsItem": False,
    }
    STRINGS = {
        "Navigation.OnBack": "Previous",
        "Seekbar.TimeDisplay": "Combined",
        "Skin.FlixArt.Size": "ExtraLarge",
    }
    UNMANAGED = {
        "OSD.AutoOnPause", "OSD.AutoOnPause.Delay", "Plotline.Movie",
        "Plotline.TVShow", "Mouse.PointerSize", "SeasonalTheme.PropsDensity",
    }

    def _declarations(self):
        return ConfigDeclarations(
            packages=("af3-common",),
            managed_settings=(ManagedSettingScope(
                target_kind=ConfigTargetKind.SKIN,
                addon_id=self.SKIN,
                keys=tuple(list(self.BOOLS) + list(self.STRINGS)),
            ),),
            managed_files=(),
        )

    def test_exact_policy_values_and_types_resolve(self):
        effective = ConfigPackageLoader(default_packages_root()).resolve(
            self._declarations()
        )
        self.assertEqual(effective.packages, ("af3-common",))
        self.assertEqual(effective.files, ())
        actual = {
            setting.key: (setting.setting_type.value, setting.value)
            for setting in effective.settings
        }
        expected = {
            **{key: ("bool", value) for key, value in self.BOOLS.items()},
            **{key: ("string", value) for key, value in self.STRINGS.items()},
        }
        self.assertEqual(actual, expected)
        self.assertTrue(all(setting.target_kind is ConfigTargetKind.SKIN
                            for setting in effective.settings))

    def test_six_reviewed_candidates_are_not_managed(self):
        effective = ConfigPackageLoader(default_packages_root()).resolve(
            self._declarations()
        )
        self.assertTrue(self.UNMANAGED.isdisjoint(
            {setting.key for setting in effective.settings}
        ))

    def test_package_descriptor_has_no_file_overlay(self):
        package = ConfigPackageLoader(default_packages_root()).load_package(
            "af3-common"
        )
        self.assertEqual(len(package.settings), 16)
        self.assertEqual(package.files, ())

    def test_example_manifest_declares_exact_skin_ownership(self):
        manifest = load_manifest_file(os.path.join(
            os.path.dirname(__file__), "..", "resources", "builds", "examples",
            "eric-main.example.json",
        ))
        resolved = resolve_manifest(manifest, "family-room")
        skin_scope = next(
            scope for scope in resolved.config.managed_settings
            if scope.target_kind is ConfigTargetKind.SKIN
        )
        self.assertEqual(skin_scope.addon_id, self.SKIN)
        self.assertEqual(set(skin_scope.keys), set(self.BOOLS) | set(self.STRINGS))
        self.assertEqual(resolved.config.managed_files, ())
        self.assertIn("af3-common", resolved.config.packages)


if __name__ == "__main__":
    unittest.main()
