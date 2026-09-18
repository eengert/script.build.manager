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
from resources.lib.manifest import ConfigDeclarations, ManagedSettingScope


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
        return [c for c in self.calls if c[0] in ("set_setting", "write_file")]


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
            package_id="common"):
    return ConfigSetting(
        addon_id=addon_id, key=key, setting_type=setting_type,
        value=value, package_id=package_id,
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

    def test_symlinked_directory_escape_refused(self):
        outside = tempfile.mkdtemp(prefix="bm015-outside-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        os.makedirs(os.path.join(self.profile, "addon_data"))
        os.symlink(outside, os.path.join(self.profile, "addon_data", "link"))
        with self.assertRaises(ConfigBackendError) as ctx:
            self.backend.write_file("addon_data/link/f.txt", b"x")
        self.assertIn("outside the Kodi profile root", str(ctx.exception))

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
        self.assertEqual(state.setting_targets, (("plugin.video.a", "k"),))
        self.assertEqual(state.file_targets, ("addon_data/f.txt",))
        self.assertEqual(state.verified_settings, (("plugin.video.a", "k"),))
        self.assertEqual(state.verified_files, ("addon_data/f.txt",))
        self.assertTrue(state.is_fully_verified)

    def test_failed_target_is_in_scope_but_not_verified(self):
        backend = FakeConfigurationBackend()
        backend.get_errors[("plugin.video.a", "k")] = "down"
        result = ConfigurationManager(backend).apply(EffectiveConfiguration(
            settings=(setting(addon_id="plugin.video.a", key="k", value="v"),),
        ))
        state = result.validation_state
        self.assertEqual(state.setting_targets, (("plugin.video.a", "k"),))
        self.assertEqual(state.verified_settings, ())
        self.assertEqual(state.failed_settings, (("plugin.video.a", "k"),))
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
            (("plugin.video.a", "z"), ("plugin.video.b", "k")),
        )

    def test_empty_snapshot_is_fully_verified_vacuously(self):
        state = ConfigurationValidationState()
        self.assertTrue(state.is_fully_verified)
        self.assertEqual(state.failed_settings, ())
        self.assertEqual(state.failed_files, ())


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


if __name__ == "__main__":
    unittest.main()
