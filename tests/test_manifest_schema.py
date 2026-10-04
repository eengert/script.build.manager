"""
BM-002: Manifest schema v1 structural validation tests.

These tests use only the Python standard library (json, unittest).
Full JSON Schema validation (using the jsonschema package) is deferred
to BM-003 when the manifest parser is implemented. These tests perform
Python-level structural assertions that cover the key constraints in
resources/builds/schema-v1.json.

NOTE: No Kodi runtime imports. No real Kodi profiles are touched.
"""

import json
import os
import sys
import unittest

# Add repo root to path so resources/ is importable as a package if needed
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)

SCHEMA_PATH = os.path.join(REPO_ROOT, "resources", "builds", "schema-v1.json")
MINIMAL_PATH = os.path.join(REPO_ROOT, "resources", "builds", "examples", "minimal.json")
ERIC_MAIN_PATH = os.path.join(REPO_ROOT, "resources", "builds", "examples", "eric-main.example.json")
BM020A_FIXTURE_PATH = os.path.join(
    REPO_ROOT, "resources", "builds", "examples", "bm020a-executor.example.json"
)

VALID_ADDON_STATES = {"enabled", "disabled"}
VALID_OVERLAY_TYPES = {"local_file"}

KNOWN_TOP_LEVEL_KEYS = {
    "schema_version",
    "engine_min_version",
    "build",
    "repositories",
    "addons",
    "skin",
    "config",
    "platform_profiles",
    "device_profiles",
    "optional",
    "private_overlay",
    "restart_policy",
}


# ---------------------------------------------------------------------------
# Lightweight structural validator (test infrastructure only — NOT production)
# ---------------------------------------------------------------------------

class ManifestStructureError(Exception):
    """Raised when a manifest fails a structural check."""


def _assert(condition, message):
    if not condition:
        raise ManifestStructureError(message)


def validate_manifest_structure(doc, *, label="manifest"):
    """
    Performs structural checks equivalent to the key constraints in
    schema-v1.json. Raises ManifestStructureError on the first violation.

    This is test-only infrastructure. Full JSON Schema validation is
    deferred to BM-003.
    """
    _assert(isinstance(doc, dict), f"{label}: must be a JSON object")

    # Reject unknown top-level keys (additionalProperties: false)
    unknown = set(doc.keys()) - KNOWN_TOP_LEVEL_KEYS
    _assert(not unknown, f"{label}: unknown top-level keys: {unknown}")

    # schema_version — required, integer, must be 1
    _assert("schema_version" in doc, f"{label}: missing required 'schema_version'")
    _assert(
        isinstance(doc["schema_version"], int),
        f"{label}: 'schema_version' must be an integer"
    )
    _assert(
        doc["schema_version"] == 1,
        f"{label}: 'schema_version' must be 1, got {doc['schema_version']!r}"
    )

    # build — required object
    _assert("build" in doc, f"{label}: missing required 'build'")
    build = doc["build"]
    _assert(isinstance(build, dict), f"{label}: 'build' must be an object")
    _assert("id" in build, f"{label}: 'build.id' is required")
    _assert("version" in build, f"{label}: 'build.version' is required")
    _assert(isinstance(build["id"], str), f"{label}: 'build.id' must be a string")
    _assert(isinstance(build["version"], str), f"{label}: 'build.version' must be a string")
    _assert(build["id"], f"{label}: 'build.id' must not be empty")
    _assert(build["version"], f"{label}: 'build.version' must not be empty")

    # repositories — optional array
    if "repositories" in doc:
        repos = doc["repositories"]
        _assert(isinstance(repos, list), f"{label}: 'repositories' must be an array")
        for i, repo in enumerate(repos):
            _validate_repository(repo, label=f"{label}.repositories[{i}]")

    # addons — optional array
    if "addons" in doc:
        addons = doc["addons"]
        _assert(isinstance(addons, list), f"{label}: 'addons' must be an array")
        for i, entry in enumerate(addons):
            _validate_addon_entry(entry, label=f"{label}.addons[{i}]")

    # skin — optional object
    if "skin" in doc:
        _validate_skin_entry(doc["skin"], label=f"{label}.skin")

    # config — optional object
    if "config" in doc:
        _validate_config_declarations(doc["config"], label=f"{label}.config")

    # platform_profiles — optional object whose values are profile layers
    if "platform_profiles" in doc:
        pp = doc["platform_profiles"]
        _assert(isinstance(pp, dict), f"{label}: 'platform_profiles' must be an object")
        for key, layer in pp.items():
            _validate_profile_layer(layer, label=f"{label}.platform_profiles.{key}")

    # device_profiles — optional object
    if "device_profiles" in doc:
        dp = doc["device_profiles"]
        _assert(isinstance(dp, dict), f"{label}: 'device_profiles' must be an object")
        for key, profile in dp.items():
            _validate_device_profile(profile, label=f"{label}.device_profiles.{key}")

    # optional — optional array of groups
    if "optional" in doc:
        opt = doc["optional"]
        _assert(isinstance(opt, list), f"{label}: 'optional' must be an array")
        for i, group in enumerate(opt):
            _validate_optional_group(group, label=f"{label}.optional[{i}]")

    # private_overlay — optional object
    if "private_overlay" in doc:
        _validate_private_overlay_ref(doc["private_overlay"], label=f"{label}.private_overlay")

    # restart_policy — optional object
    if "restart_policy" in doc:
        rp = doc["restart_policy"]
        _assert(isinstance(rp, dict), f"{label}: 'restart_policy' must be an object")
        for key in rp:
            _assert(
                key in {"allow_skin_reload", "allow_kodi_restart"},
                f"{label}.restart_policy: unknown key {key!r}"
            )
        for key in ("allow_skin_reload", "allow_kodi_restart"):
            if key in rp:
                _assert(
                    isinstance(rp[key], bool),
                    f"{label}.restart_policy.{key} must be a boolean"
                )


def _validate_addon_entry(entry, *, label):
    _assert(isinstance(entry, dict), f"{label}: must be an object")
    _assert("addon_id" in entry, f"{label}: missing 'addon_id'")
    _assert("state" in entry, f"{label}: missing 'state'")
    _assert(isinstance(entry["addon_id"], str), f"{label}: 'addon_id' must be a string")
    _assert(entry["addon_id"], f"{label}: 'addon_id' must not be empty")
    _assert(
        entry["state"] in VALID_ADDON_STATES,
        f"{label}: 'state' must be one of {VALID_ADDON_STATES}, got {entry['state']!r}"
    )
    for key in entry:
        _assert(
            key in {"addon_id", "state", "note"},
            f"{label}: unknown key {key!r}"
        )


def _validate_repository(repo, *, label):
    _assert(isinstance(repo, dict), f"{label}: must be an object")
    _assert("addon_id" in repo, f"{label}: missing 'addon_id'")
    _assert(isinstance(repo["addon_id"], str), f"{label}: 'addon_id' must be a string")
    _assert(
        repo["addon_id"].startswith("repository."),
        f"{label}: 'addon_id' must start with 'repository.', got {repo['addon_id']!r}"
    )
    for key in repo:
        _assert(
            key in {"addon_id", "bootstrap_url", "required"},
            f"{label}: unknown key {key!r}"
        )
    if "required" in repo:
        _assert(isinstance(repo["required"], bool), f"{label}: 'required' must be a boolean")


def _validate_skin_entry(skin, *, label):
    _assert(isinstance(skin, dict), f"{label}: must be an object")
    _assert("addon_id" in skin, f"{label}: missing 'addon_id'")
    _assert(isinstance(skin["addon_id"], str), f"{label}: 'addon_id' must be a string")
    _assert(
        skin["addon_id"].startswith("skin."),
        f"{label}: 'addon_id' must start with 'skin.', got {skin['addon_id']!r}"
    )
    for key in skin:
        _assert(
            key in {"addon_id", "config_packages"},
            f"{label}: unknown key {key!r}"
        )
    if "config_packages" in skin:
        _assert(isinstance(skin["config_packages"], list), f"{label}: 'config_packages' must be an array")


def _validate_config_declarations(config, *, label):
    _assert(isinstance(config, dict), f"{label}: must be an object")
    for key in config:
        _assert(
            key in {
                "packages", "managed_settings", "managed_files", "private_settings",
                "structured_private_resources",
            },
            f"{label}: unknown key {key!r}"
        )
    if "packages" in config:
        _assert(isinstance(config["packages"], list), f"{label}: 'packages' must be an array")
    if "managed_files" in config:
        _assert(isinstance(config["managed_files"], list), f"{label}: 'managed_files' must be an array")
    if "managed_settings" in config:
        ms = config["managed_settings"]
        _assert(isinstance(ms, list), f"{label}: 'managed_settings' must be an array")
        for i, scope in enumerate(ms):
            _assert(isinstance(scope, dict), f"{label}.managed_settings[{i}]: must be an object")
            if "target" in scope:
                _assert(
                    scope["target"] in {"addon", "skin"},
                    f"{label}.managed_settings[{i}]: invalid target",
                )
            _assert("addon_id" in scope, f"{label}.managed_settings[{i}]: missing 'addon_id'")
            _assert("keys" in scope, f"{label}.managed_settings[{i}]: missing 'keys'")
            _assert(
                isinstance(scope["keys"], list) and scope["keys"],
                f"{label}.managed_settings[{i}]: 'keys' must be a non-empty array"
            )
    if "private_settings" in config:
        private = config["private_settings"]
        _assert(isinstance(private, list), f"{label}: 'private_settings' must be an array")
        seen = set()
        for i, declaration in enumerate(private):
            _assert(isinstance(declaration, dict), f"{label}.private_settings[{i}]: must be an object")
            allowed = {"target", "addon_id", "key", "type", "required", "sensitivity"}
            _assert(set(declaration) <= allowed, f"{label}.private_settings[{i}]: unknown key")
            identity = (
                declaration.get("target", "addon"),
                declaration.get("addon_id"),
                declaration.get("key"),
            )
            _assert(identity not in seen, f"{label}.private_settings[{i}]: duplicate target")
            seen.add(identity)
            _assert(isinstance(declaration.get("addon_id"), str), f"{label}.private_settings[{i}]: addon_id")
            _assert(isinstance(declaration.get("key"), str), f"{label}.private_settings[{i}]: key")
            _assert(declaration.get("type") in {"string", "bool", "int", "number"}, f"{label}.private_settings[{i}]: type")
            _assert(declaration.get("sensitivity") in {"secret", "credential", "token", "private_identifier"}, f"{label}.private_settings[{i}]: sensitivity")
            if "required" in declaration:
                _assert(isinstance(declaration["required"], bool), f"{label}.private_settings[{i}]: required")
    if "structured_private_resources" in config:
        resources = config["structured_private_resources"]
        _assert(isinstance(resources, list), f"{label}: 'structured_private_resources' must be an array")
        seen_resources = set()
        for i, declaration in enumerate(resources):
            resource_label = f"{label}.structured_private_resources[{i}]"
            _assert(isinstance(declaration, dict), f"{resource_label}: must be an object")
            allowed = {
                "resource_type", "owner_addon_id", "supported_versions", "schema_id",
                "resource_id", "fields", "adapter_id", "lifecycle", "required",
                "configure_before_activation",
            }
            _assert(set(declaration) <= allowed, f"{resource_label}: unknown key")
            required_keys = {
                "resource_type", "owner_addon_id", "supported_versions", "schema_id",
                "resource_id", "fields", "adapter_id",
            }
            _assert(required_keys <= set(declaration), f"{resource_label}: missing required keys")
            for key in ("resource_type", "owner_addon_id", "schema_id", "resource_id", "adapter_id"):
                _assert(isinstance(declaration[key], str) and declaration[key], f"{resource_label}.{key}: must be a non-empty string")
            identity = (declaration["resource_type"], declaration["resource_id"])
            _assert(identity not in seen_resources, f"{resource_label}: duplicate resource")
            seen_resources.add(identity)
            versions = declaration["supported_versions"]
            _assert(isinstance(versions, list) and versions, f"{resource_label}.supported_versions: must be a non-empty array")
            _assert(all(isinstance(version, str) and version for version in versions), f"{resource_label}.supported_versions: entries must be non-empty strings")
            _assert(declaration.get("lifecycle", "quiesced") in {"initialized_idle", "active", "quiesced", "restart_required"}, f"{resource_label}.lifecycle: invalid lifecycle")
            if "required" in declaration:
                _assert(isinstance(declaration["required"], bool), f"{resource_label}.required: must be a boolean")
            if "configure_before_activation" in declaration:
                _assert(
                    isinstance(declaration["configure_before_activation"], bool),
                    f"{resource_label}.configure_before_activation: must be a boolean",
                )
            fields = declaration["fields"]
            _assert(isinstance(fields, list) and fields, f"{resource_label}.fields: must be a non-empty array")
            seen_fields = set()
            for j, field in enumerate(fields):
                field_label = f"{resource_label}.fields[{j}]"
                _assert(isinstance(field, dict), f"{field_label}: must be an object")
                _assert(set(field) <= {"field_id", "type", "required", "sensitivity"}, f"{field_label}: unknown key")
                _assert({"field_id", "type"} <= set(field), f"{field_label}: missing required keys")
                _assert(isinstance(field["field_id"], str) and field["field_id"], f"{field_label}.field_id: must be a non-empty string")
                _assert(field["field_id"] not in seen_fields, f"{field_label}: duplicate field_id")
                seen_fields.add(field["field_id"])
                _assert(field["type"] in {"string", "bool", "int", "number"}, f"{field_label}.type: invalid type")
                if "required" in field:
                    _assert(isinstance(field["required"], bool), f"{field_label}.required: must be a boolean")
                if "sensitivity" in field:
                    _assert(field["sensitivity"] in {"secret", "credential", "token", "private_identifier"}, f"{field_label}.sensitivity: invalid sensitivity")


def _validate_profile_layer(layer, *, label):
    _assert(isinstance(layer, dict), f"{label}: must be an object")
    allowed = {"label", "addons", "config", "skin", "include_optional", "frozen_install_policies"}
    for key in layer:
        _assert(key in allowed, f"{label}: unknown key {key!r}")
    if "addons" in layer:
        addons = layer["addons"]
        _assert(isinstance(addons, list), f"{label}: 'addons' must be an array")
        for i, entry in enumerate(addons):
            _validate_addon_entry(entry, label=f"{label}.addons[{i}]")
    if "config" in layer:
        _validate_config_declarations(layer["config"], label=f"{label}.config")
    if "skin" in layer:
        _validate_skin_entry(layer["skin"], label=f"{label}.skin")
    if "include_optional" in layer:
        _assert(
            isinstance(layer["include_optional"], list),
            f"{label}: 'include_optional' must be an array"
        )
    if "frozen_install_policies" in layer:
        _validate_frozen_install_policies(layer["frozen_install_policies"], label=label)


def _validate_device_profile(profile, *, label):
    _assert(isinstance(profile, dict), f"{label}: must be an object")
    allowed = {"label", "extends", "addons", "config", "skin", "include_optional", "frozen_install_policies"}
    for key in profile:
        _assert(key in allowed, f"{label}: unknown key {key!r}")
    _assert("extends" in profile, f"{label}: 'extends' is required for every device profile")
    _assert(isinstance(profile["extends"], str), f"{label}: 'extends' must be a string")
    _assert(profile["extends"], f"{label}: 'extends' must not be empty")
    # Validate shared sub-fields without re-checking the top-level key set
    if "addons" in profile:
        addons = profile["addons"]
        _assert(isinstance(addons, list), f"{label}: 'addons' must be an array")
        for i, entry in enumerate(addons):
            _validate_addon_entry(entry, label=f"{label}.addons[{i}]")
    if "config" in profile:
        _validate_config_declarations(profile["config"], label=f"{label}.config")
    if "skin" in profile:
        _validate_skin_entry(profile["skin"], label=f"{label}.skin")
    if "include_optional" in profile:
        _assert(
            isinstance(profile["include_optional"], list),
            f"{label}: 'include_optional' must be an array"
        )
    if "frozen_install_policies" in profile:
        _validate_frozen_install_policies(profile["frozen_install_policies"], label=label)


def _validate_frozen_install_policies(policies, *, label):
    _assert(isinstance(policies, list), f"{label}: 'frozen_install_policies' must be an array")
    allowed_policies = {
        "exact_required",
        "exact_first_with_repository_fallback",
        "exact_first_with_repository_fallback_or_skip",
    }
    seen = set()
    for index, policy in enumerate(policies):
        entry_label = f"{label}.frozen_install_policies[{index}]"
        _assert(isinstance(policy, dict), f"{entry_label}: must be an object")
        _assert(set(policy) <= {"addon_id", "policy", "repository_id"}, f"{entry_label}: unknown key")
        addon_id = policy.get("addon_id")
        _assert(isinstance(addon_id, str) and addon_id, f"{entry_label}: addon_id is required")
        _assert(addon_id not in seen, f"{entry_label}: duplicate addon_id")
        seen.add(addon_id)
        _assert(policy.get("policy") in allowed_policies, f"{entry_label}: unsupported policy")
        repository_id = policy.get("repository_id", "")
        _assert(isinstance(repository_id, str), f"{entry_label}: repository_id must be a string")
        if repository_id:
            _assert(repository_id.startswith("repository."), f"{entry_label}: invalid repository_id")
            _assert(
                policy["policy"] != "exact_required",
                f"{entry_label}: exact-only policy cannot name a repository",
            )


def _validate_optional_group(group, *, label):
    _assert(isinstance(group, dict), f"{label}: must be an object")
    _assert("id" in group, f"{label}: missing required 'id'")
    _assert(isinstance(group["id"], str), f"{label}: 'id' must be a string")
    _assert(group["id"], f"{label}: 'id' must not be empty")
    allowed = {"id", "label", "description", "addons", "config"}
    for key in group:
        _assert(key in allowed, f"{label}: unknown key {key!r}")
    if "addons" in group:
        addons = group["addons"]
        _assert(isinstance(addons, list), f"{label}: 'addons' must be an array")
        for i, entry in enumerate(addons):
            _validate_addon_entry(entry, label=f"{label}.addons[{i}]")
    if "config" in group:
        _validate_config_declarations(group["config"], label=f"{label}.config")


def _validate_private_overlay_ref(ref, *, label):
    _assert(isinstance(ref, dict), f"{label}: must be an object")
    _assert("type" in ref, f"{label}: missing 'type'")
    _assert(
        ref["type"] in VALID_OVERLAY_TYPES,
        f"{label}: 'type' must be one of {VALID_OVERLAY_TYPES}, got {ref['type']!r}"
    )
    allowed = {"type", "path_hint", "description", "overlay_id", "required"}
    for key in ref:
        _assert(key in allowed, f"{label}: unknown key {key!r}")


# ---------------------------------------------------------------------------
# Tests: schema file itself
# ---------------------------------------------------------------------------

class TestSchemaFile(unittest.TestCase):

    def test_schema_file_is_valid_json(self):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        self.assertIsInstance(schema, dict)

    def test_schema_has_required_meta_fields(self):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        self.assertIn("$schema", schema)
        self.assertIn("title", schema)
        self.assertIn("type", schema)
        self.assertIn("required", schema)
        self.assertIn("properties", schema)
        self.assertIn("definitions", schema)

    def test_schema_declares_draft7(self):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        self.assertIn("draft-07", schema["$schema"])

    def test_schema_requires_schema_version_and_build(self):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        required = schema["required"]
        self.assertIn("schema_version", required)
        self.assertIn("build", required)

    def test_schema_forbids_additional_top_level_properties(self):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        self.assertFalse(
            schema.get("additionalProperties", True),
            "Top-level schema must have additionalProperties: false"
        )

    def test_schema_addon_state_enum_is_complete(self):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        state_enum = schema["definitions"]["addon_state"]["enum"]
        self.assertIn("enabled", state_enum)
        self.assertIn("disabled", state_enum)
        self.assertNotIn("absent", state_enum)
        self.assertEqual(len(state_enum), 2, "addon_state enum should have exactly 2 values")

    def test_schema_defines_all_key_definitions(self):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        defs = schema["definitions"]
        for name in (
            "addon_state", "addon_entry", "addon_override", "repository",
            "skin_entry", "config_declarations", "managed_setting_scope",
            "private_setting_declaration",
            "structured_private_resource",
            "profile_layer", "device_profile", "optional_group",
            "private_overlay_ref", "restart_policy",
        ):
            self.assertIn(name, defs, f"Missing definition: {name}")


# ---------------------------------------------------------------------------
# Tests: minimal example
# ---------------------------------------------------------------------------

class TestMinimalExample(unittest.TestCase):

    def setUp(self):
        with open(MINIMAL_PATH) as f:
            self.doc = json.load(f)

    def test_minimal_is_valid_json(self):
        self.assertIsInstance(self.doc, dict)

    def test_minimal_passes_structural_validation(self):
        validate_manifest_structure(self.doc, label="minimal.json")

    def test_minimal_schema_version_is_1(self):
        self.assertEqual(self.doc["schema_version"], 1)

    def test_minimal_has_build_id_and_version(self):
        self.assertIn("id", self.doc["build"])
        self.assertIn("version", self.doc["build"])

    def test_minimal_has_no_unexpected_keys(self):
        unexpected = set(self.doc.keys()) - KNOWN_TOP_LEVEL_KEYS
        self.assertEqual(unexpected, set(), f"Unexpected keys: {unexpected}")


# ---------------------------------------------------------------------------
# Tests: eric-main example
# ---------------------------------------------------------------------------

class TestEricMainExample(unittest.TestCase):

    def setUp(self):
        with open(ERIC_MAIN_PATH) as f:
            self.doc = json.load(f)

    def test_eric_main_is_valid_json(self):
        self.assertIsInstance(self.doc, dict)

    def test_eric_main_passes_structural_validation(self):
        validate_manifest_structure(self.doc, label="eric-main.example.json")

    def test_eric_main_build_identity(self):
        self.assertEqual(self.doc["build"]["id"], "eric-main")
        self.assertEqual(self.doc["build"]["version"], "1.0.0")

    def test_eric_main_has_repositories(self):
        repos = self.doc.get("repositories", [])
        self.assertGreater(len(repos), 0, "Expected at least one repository")
        for repo in repos:
            self.assertTrue(repo["addon_id"].startswith("repository."))

    def test_eric_main_addons_have_valid_states(self):
        for entry in self.doc.get("addons", []):
            self.assertIn(entry["state"], VALID_ADDON_STATES)

    def test_eric_main_has_expected_addons(self):
        addon_ids = {a["addon_id"] for a in self.doc.get("addons", [])}
        for expected in (
            "skin.arctic.fuse.3",
            "plugin.video.redlight",
            "plugin.video.themoviedb.helper",
            "plugin.video.pov",
            "plugin.video.umbrella",
        ):
            self.assertIn(expected, addon_ids, f"Expected add-on missing: {expected}")

    def test_eric_main_skin_is_af3(self):
        skin = self.doc.get("skin", {})
        self.assertEqual(skin.get("addon_id"), "skin.arctic.fuse.3")

    def test_shipped_executable_examples_select_existing_packages(self):
        examples_dir = os.path.join(REPO_ROOT, "resources", "builds", "examples")
        packages_root = os.path.join(REPO_ROOT, "resources", "config", "packages")
        for filename in sorted(os.listdir(examples_dir)):
            if not filename.endswith(".example.json"):
                continue
            with self.subTest(example=filename):
                with open(os.path.join(examples_dir, filename), encoding="utf-8") as handle:
                    document = json.load(handle)
                package_ids = document.get("config", {}).get("packages", [])
                skin = document.get("skin", {})
                package_ids = list(package_ids) + list(skin.get("config_packages", []))
                for package_id in package_ids:
                    package_path = os.path.join(packages_root, package_id)
                    self.assertTrue(
                        os.path.isfile(os.path.join(package_path, "package.json")),
                        f"{filename} selects unavailable package {package_id!r}",
                    )


    def test_eric_main_has_platform_profiles(self):
        pp = self.doc.get("platform_profiles", {})
        self.assertIn("tvos", pp)
        self.assertIn("android", pp)

    def test_eric_main_device_profiles_extend_platform_profiles(self):
        pp_keys = set(self.doc.get("platform_profiles", {}).keys())
        for device_id, profile in self.doc.get("device_profiles", {}).items():
            if "extends" in profile:
                self.assertIn(
                    profile["extends"], pp_keys,
                    f"device_profiles.{device_id}.extends={profile['extends']!r} not in platform_profiles"
                )

    def test_eric_main_has_device_profiles_for_apple_tv_and_shield(self):
        dp = self.doc.get("device_profiles", {})
        # At least one tvos device and the shield
        tvos_devices = [k for k, v in dp.items() if v.get("extends") == "tvos"]
        android_devices = [k for k, v in dp.items() if v.get("extends") == "android"]
        self.assertGreater(len(tvos_devices), 0, "Expected at least one tvos device profile")
        self.assertGreater(len(android_devices), 0, "Expected at least one android device profile")

    def test_eric_main_has_optional_groups(self):
        opt = self.doc.get("optional", [])
        self.assertGreater(len(opt), 0, "Expected at least one optional group")
        for group in opt:
            self.assertIn("id", group)

    def test_eric_main_optional_groups_referenced_exist(self):
        opt_ids = {g["id"] for g in self.doc.get("optional", [])}
        for platform_id, layer in self.doc.get("platform_profiles", {}).items():
            for ref in layer.get("include_optional", []):
                self.assertIn(
                    ref, opt_ids,
                    f"platform_profiles.{platform_id}.include_optional references unknown group {ref!r}"
                )
        for device_id, profile in self.doc.get("device_profiles", {}).items():
            for ref in profile.get("include_optional", []):
                self.assertIn(
                    ref, opt_ids,
                    f"device_profiles.{device_id}.include_optional references unknown group {ref!r}"
                )

    def test_eric_main_has_private_overlay_reference(self):
        overlay = self.doc.get("private_overlay")
        self.assertIsNotNone(overlay, "Expected a private_overlay reference")
        self.assertEqual(overlay.get("type"), "local_file")

    def test_eric_main_no_secrets_in_addons(self):
        sensitive = {"password", "token", "secret", "credential", "api_key", "auth"}
        raw = json.dumps(self.doc).lower()
        for term in sensitive:
            # Expect it not to appear as a JSON key (value matches are false positives in descriptions)
            self.assertNotIn(f'"{term}":', raw, f"Found suspicious key {term!r} in manifest")

    def test_eric_main_no_real_credentials(self):
        # bootstrap_url uses .invalid TLD (per RFC 2606), confirming it is illustrative
        for repo in self.doc.get("repositories", []):
            url = repo.get("bootstrap_url", "")
            if url:
                self.assertIn(".invalid", url, "Example bootstrap_url should use .invalid TLD")


class TestBM020AExecutorFixture(unittest.TestCase):

    def test_fixture_is_valid_and_explicitly_disposable(self):
        with open(BM020A_FIXTURE_PATH, encoding="utf-8") as handle:
            document = json.load(handle)
        validate_manifest_structure(document, label="bm020a-executor.example.json")
        self.assertEqual(document["build"]["id"], "bm020a-executor-validation")
        self.assertEqual(
            document["device_profiles"]["bm020a-disposable"]["extends"],
            "disposable",
        )
        self.assertEqual(document["skin"]["config_packages"], ["af3-common"])
        self.assertEqual(document["config"]["managed_files"], [])


# ---------------------------------------------------------------------------
# Tests: invalid manifests
# ---------------------------------------------------------------------------

class TestInvalidManifests(unittest.TestCase):

    def _make(self, overrides=None, remove=None):
        """Build a minimal-valid manifest and apply mutations."""
        doc = {"schema_version": 1, "build": {"id": "test-build", "version": "0.1.0"}}
        if overrides:
            doc.update(overrides)
        if remove:
            for key in remove:
                doc.pop(key, None)
        return doc

    def _assert_invalid(self, doc, *, contains=None):
        with self.assertRaises(ManifestStructureError) as ctx:
            validate_manifest_structure(doc)
        if contains:
            self.assertIn(contains, str(ctx.exception))

    def test_missing_schema_version(self):
        self._assert_invalid(self._make(remove=["schema_version"]), contains="schema_version")

    def test_wrong_schema_version(self):
        self._assert_invalid(self._make({"schema_version": 2}), contains="schema_version")

    def test_schema_version_as_string(self):
        self._assert_invalid(self._make({"schema_version": "1"}), contains="schema_version")

    def test_missing_build(self):
        self._assert_invalid(self._make(remove=["build"]), contains="build")

    def test_missing_build_id(self):
        doc = self._make({"build": {"version": "0.1.0"}})
        self._assert_invalid(doc, contains="build.id")

    def test_missing_build_version(self):
        doc = self._make({"build": {"id": "my-build"}})
        self._assert_invalid(doc, contains="build.version")

    def test_unknown_top_level_key(self):
        self._assert_invalid(self._make({"totally_unknown_field": "value"}))

    def test_invalid_addon_state(self):
        doc = self._make({"addons": [{"addon_id": "plugin.video.foo", "state": "maybe"}]})
        self._assert_invalid(doc, contains="state")

    def test_addon_missing_state(self):
        doc = self._make({"addons": [{"addon_id": "plugin.video.foo"}]})
        self._assert_invalid(doc, contains="state")

    def test_addon_missing_addon_id(self):
        doc = self._make({"addons": [{"state": "enabled"}]})
        self._assert_invalid(doc, contains="addon_id")

    def test_repository_wrong_prefix(self):
        doc = self._make({"repositories": [{"addon_id": "plugin.video.foo"}]})
        self._assert_invalid(doc, contains="repository.")

    def test_skin_wrong_prefix(self):
        doc = self._make({"skin": {"addon_id": "plugin.video.not_a_skin"}})
        self._assert_invalid(doc, contains="skin.")

    def test_private_overlay_invalid_type(self):
        doc = self._make({"private_overlay": {"type": "s3_bucket"}})
        self._assert_invalid(doc, contains="type")

    def test_platform_profile_invalid_addon_state(self):
        doc = self._make({
            "platform_profiles": {
                "tvos": {
                    "addons": [{"addon_id": "plugin.video.foo", "state": "broken"}]
                }
            }
        })
        self._assert_invalid(doc, contains="state")

    def test_device_profile_with_extends_is_valid(self):
        # extends is required; a device profile that provides it must be accepted.
        # Cross-reference validation (does the named platform exist?) is parser
        # logic deferred to BM-003/BM-004 — not enforced by the structural check.
        doc = self._make({
            "platform_profiles": {"tvos": {}},
            "device_profiles": {"bonus-room": {"extends": "tvos"}},
        })
        validate_manifest_structure(doc)  # should pass

    def test_device_profile_missing_extends_is_invalid(self):
        doc = self._make({
            "device_profiles": {"bonus-room": {"label": "Bonus Room"}},
        })
        self._assert_invalid(doc, contains="extends")

    def test_optional_group_missing_id(self):
        doc = self._make({"optional": [{"label": "No ID here"}]})
        self._assert_invalid(doc, contains="id")

    def test_restart_policy_invalid_type(self):
        doc = self._make({"restart_policy": {"allow_skin_reload": "yes"}})
        self._assert_invalid(doc, contains="boolean")

    def test_managed_settings_keys_must_be_non_empty(self):
        doc = self._make({
            "config": {
                "managed_settings": [
                    {"addon_id": "plugin.video.foo", "keys": []}
                ]
            }
        })
        self._assert_invalid(doc, contains="keys")


# ---------------------------------------------------------------------------
# Tests: existing BM-001 test suite still passes (import check)
# ---------------------------------------------------------------------------

class TestBM001StillImportable(unittest.TestCase):
    def test_build_manager_class_still_importable(self):
        from resources.lib.build_manager import BuildManager
        self.assertIsNotNone(BuildManager)

    def test_resources_lib_is_still_a_package(self):
        import resources.lib
        self.assertIsNotNone(resources.lib)


if __name__ == "__main__":
    unittest.main()
