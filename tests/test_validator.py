"""
Tests for BM-014: resources.lib.validator — post-operation state validator.

Covers:
  - ValidationReport aggregate properties (is_valid, is_complete, passed,
    passes, failures, warnings, not_checked)
  - Repository domain validation (required=True only)
  - Addon domain validation (enabled / disabled / unknown state)
  - Dependency domain validation (all DependencyStatus values)
  - Skin domain validation
  - Configuration domain (NOT_CHECKED when config is non-None)
  - ValidationError on malformed input (duplicate addon_ids)
  - Domain ordering + lexical subject ordering
  - Read-only guarantee (inputs unmodified)
  - Aggregate semantics (is_valid, is_complete, passed)
"""

import unittest

from resources.lib.dependencies import (
    DependencyClosure,
    DependencyNode,
    DependencyStatus,
)
from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.manifest import (
    AddonEntry,
    BuildInfo,
    ConfigDeclarations,
    ManagedSettingScope,
    Repository,
    SkinEntry,
)
from resources.lib.config import (
    ConfigTargetKind,
    ConfigFile,
    ConfigSetting,
    ConfigSettingType,
    ConfigurationValidationState,
    EffectiveConfiguration,
)
from resources.lib.resolver import ResolvedBuild
from resources.lib.validator import (
    ValidationCheck,
    ValidationDomain,
    ValidationError,
    ValidationReport,
    ValidationStatus,
    validate_build_state,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _build_info() -> BuildInfo:
    return BuildInfo(id="test-build", version="1.0.0", name="Test Build")


def _resolved(
    *,
    repositories=(),
    addons=(),
    skin=None,
    config=None,
) -> ResolvedBuild:
    return ResolvedBuild(
        build=_build_info(),
        engine_min_version="1.0.0",
        platform_profile_id="macos",
        device_profile_id="test-device",
        repositories=repositories,
        addons=addons,
        skin=skin,
        config=config,
        optional_groups_applied=(),
        restart_policy=None,
        private_overlay=None,
    )


def _state(addons=(), active_skin="skin.estuary") -> KodiState:
    return KodiState(
        platform="macos",
        kodi_version="21.0",
        active_skin=active_skin,
        addons=tuple(addons),
    )


def _installed(addon_id, enabled=True, version="1.0.0") -> InstalledAddon:
    return InstalledAddon(addon_id=addon_id, enabled=enabled, version=version)


def _node(addon_id, status, required_by=(), version="1.0.0", enabled=True,
          min_version="", optional=False, cycle_path=None) -> DependencyNode:
    return DependencyNode(
        addon_id=addon_id,
        required_by=required_by,
        status=status,
        installed_version=version,
        installed_enabled=enabled,
        min_version_required=min_version,
        optional=optional,
        cycle_path=cycle_path,
    )


def _closure(*nodes) -> DependencyClosure:
    return DependencyClosure(
        root_addon_ids=("plugin.video.root",),
        nodes=tuple(nodes),
    )


# ---------------------------------------------------------------------------
# TestValidationReport
# ---------------------------------------------------------------------------

class TestValidationReport(unittest.TestCase):
    """Unit tests for ValidationReport aggregate properties."""

    def _make_check(self, status: ValidationStatus) -> ValidationCheck:
        return ValidationCheck(
            domain=ValidationDomain.ADDON,
            subject="plugin.video.x",
            status=status,
            expected="enabled",
            actual_state="disabled",
            reason="test check",
        )

    def test_empty_report_passes(self):
        report = ValidationReport(checks=())
        self.assertTrue(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)
        self.assertEqual(report.passes, ())
        self.assertEqual(report.failures, ())
        self.assertEqual(report.warnings, ())
        self.assertEqual(report.not_checked, ())

    def test_all_pass(self):
        c = self._make_check(ValidationStatus.PASS)
        report = ValidationReport(checks=(c,))
        self.assertTrue(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)
        self.assertEqual(len(report.passes), 1)
        self.assertEqual(len(report.failures), 0)

    def test_fail_makes_invalid(self):
        c = self._make_check(ValidationStatus.FAIL)
        report = ValidationReport(checks=(c,))
        self.assertFalse(report.is_valid)
        self.assertFalse(report.passed)
        self.assertTrue(report.is_complete)
        self.assertEqual(len(report.failures), 1)

    def test_not_checked_makes_incomplete(self):
        c = self._make_check(ValidationStatus.NOT_CHECKED)
        report = ValidationReport(checks=(c,))
        self.assertTrue(report.is_valid)
        self.assertFalse(report.is_complete)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.not_checked), 1)

    def test_warning_alone_does_not_prevent_passed(self):
        c = self._make_check(ValidationStatus.WARNING)
        report = ValidationReport(checks=(c,))
        self.assertTrue(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)
        self.assertEqual(len(report.warnings), 1)

    def test_fail_and_not_checked_both_false(self):
        fail = self._make_check(ValidationStatus.FAIL)
        nc = self._make_check(ValidationStatus.NOT_CHECKED)
        report = ValidationReport(checks=(fail, nc))
        self.assertFalse(report.is_valid)
        self.assertFalse(report.is_complete)
        self.assertFalse(report.passed)

    def test_mixed_statuses_filtered_correctly(self):
        checks = (
            self._make_check(ValidationStatus.PASS),
            self._make_check(ValidationStatus.FAIL),
            self._make_check(ValidationStatus.WARNING),
            self._make_check(ValidationStatus.NOT_CHECKED),
        )
        report = ValidationReport(checks=checks)
        self.assertEqual(len(report.passes), 1)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(len(report.warnings), 1)
        self.assertEqual(len(report.not_checked), 1)

    def test_report_is_frozen(self):
        report = ValidationReport(checks=())
        with self.assertRaises((AttributeError, TypeError)):
            report.checks = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestValidationError
# ---------------------------------------------------------------------------

class TestValidationError(unittest.TestCase):
    """ValidationError raised on malformed input."""

    def test_duplicate_addon_id_raises(self):
        desired = _resolved()
        actual = _state(addons=[
            _installed("plugin.video.dup"),
            _installed("plugin.video.dup", enabled=False),
        ])
        with self.assertRaises(ValidationError) as ctx:
            validate_build_state(desired, actual)
        self.assertIn("plugin.video.dup", str(ctx.exception))

    def test_unique_addon_ids_no_error(self):
        desired = _resolved()
        actual = _state(addons=[
            _installed("plugin.video.a"),
            _installed("plugin.video.b"),
        ])
        report = validate_build_state(desired, actual)
        self.assertIsInstance(report, ValidationReport)


# ---------------------------------------------------------------------------
# TestRepositoryValidation
# ---------------------------------------------------------------------------

class TestRepositoryValidation(unittest.TestCase):
    """Repository domain: only required=True repos are validated."""

    def test_required_repo_installed_enabled_pass(self):
        repo_id = "repository.test"
        desired = _resolved(repositories=(Repository(addon_id=repo_id, required=True),))
        actual = _state(addons=[_installed(repo_id, enabled=True)])
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        self.assertEqual(len(repo_checks), 1)
        self.assertEqual(repo_checks[0].status, ValidationStatus.PASS)
        self.assertEqual(repo_checks[0].subject, repo_id)

    def test_required_repo_not_installed_fail(self):
        repo_id = "repository.missing"
        desired = _resolved(repositories=(Repository(addon_id=repo_id, required=True),))
        actual = _state(addons=[])
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        self.assertEqual(len(repo_checks), 1)
        self.assertEqual(repo_checks[0].status, ValidationStatus.FAIL)
        self.assertFalse(report.is_valid)

    def test_required_repo_installed_disabled_fail(self):
        repo_id = "repository.disabled"
        desired = _resolved(repositories=(Repository(addon_id=repo_id, required=True),))
        actual = _state(addons=[_installed(repo_id, enabled=False)])
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        self.assertEqual(repo_checks[0].status, ValidationStatus.FAIL)
        self.assertIn("disabled", repo_checks[0].actual_state)

    def test_optional_repo_absent_no_check(self):
        repo_id = "repository.optional"
        desired = _resolved(repositories=(Repository(addon_id=repo_id, required=False),))
        actual = _state(addons=[])
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        self.assertEqual(len(repo_checks), 0)

    def test_optional_repo_present_no_check(self):
        repo_id = "repository.optional"
        desired = _resolved(repositories=(Repository(addon_id=repo_id, required=False),))
        actual = _state(addons=[_installed(repo_id)])
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        self.assertEqual(len(repo_checks), 0)

    def test_no_repositories_no_checks(self):
        desired = _resolved(repositories=())
        actual = _state()
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        self.assertEqual(len(repo_checks), 0)

    def test_multiple_required_repos_lexical_order(self):
        desired = _resolved(repositories=(
            Repository(addon_id="repository.zzz", required=True),
            Repository(addon_id="repository.aaa", required=True),
        ))
        actual = _state(addons=[
            _installed("repository.aaa"),
            _installed("repository.zzz"),
        ])
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        self.assertEqual(len(repo_checks), 2)
        self.assertEqual(repo_checks[0].subject, "repository.aaa")
        self.assertEqual(repo_checks[1].subject, "repository.zzz")


# ---------------------------------------------------------------------------
# TestAddonValidation
# ---------------------------------------------------------------------------

class TestAddonValidation(unittest.TestCase):
    """Addon domain: desired enabled / disabled."""

    # --- desired "enabled" ---

    def test_enabled_desired_enabled_installed_enabled_pass(self):
        entry = AddonEntry(addon_id="plugin.video.foo", state="enabled")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[_installed("plugin.video.foo", enabled=True)])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.PASS)

    def test_enabled_desired_installed_disabled_fail(self):
        entry = AddonEntry(addon_id="plugin.video.foo", state="enabled")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[_installed("plugin.video.foo", enabled=False)])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)
        self.assertFalse(report.is_valid)

    def test_enabled_desired_not_installed_fail(self):
        entry = AddonEntry(addon_id="plugin.video.foo", state="enabled")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)
        self.assertIn("not installed", checks[0].actual_state)

    # --- desired "disabled" ---

    def test_disabled_desired_installed_disabled_pass(self):
        entry = AddonEntry(addon_id="plugin.video.bar", state="disabled")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[_installed("plugin.video.bar", enabled=False)])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.PASS)

    def test_disabled_desired_installed_enabled_fail(self):
        entry = AddonEntry(addon_id="plugin.video.bar", state="disabled")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[_installed("plugin.video.bar", enabled=True)])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)

    def test_disabled_desired_not_installed_fail(self):
        entry = AddonEntry(addon_id="plugin.video.bar", state="disabled")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)

    # --- unknown desired state ---

    def test_unknown_desired_state_fail(self):
        entry = AddonEntry(addon_id="plugin.video.bad", state="broken")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)
        self.assertIn("broken", checks[0].reason)

    # --- unmanaged add-ons ---

    def test_unmanaged_addon_ignored(self):
        desired = _resolved(addons=())
        actual = _state(addons=[
            _installed("plugin.video.unmanaged", enabled=True),
            _installed("plugin.video.also-unmanaged", enabled=False),
        ])
        report = validate_build_state(desired, actual)
        addon_checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(len(addon_checks), 0)

    # --- lexical ordering ---

    def test_addons_sorted_lexically(self):
        desired = _resolved(addons=(
            AddonEntry(addon_id="plugin.video.zzz", state="enabled"),
            AddonEntry(addon_id="plugin.video.aaa", state="enabled"),
            AddonEntry(addon_id="plugin.video.mmm", state="enabled"),
        ))
        actual = _state(addons=[
            _installed("plugin.video.aaa"),
            _installed("plugin.video.mmm"),
            _installed("plugin.video.zzz"),
        ])
        report = validate_build_state(desired, actual)
        addon_checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        subjects = [c.subject for c in addon_checks]
        self.assertEqual(subjects, sorted(subjects))


# ---------------------------------------------------------------------------
# TestDependencyValidation
# ---------------------------------------------------------------------------

class TestDependencyValidation(unittest.TestCase):
    """Dependency domain: closure-based status mapping."""

    def test_no_closure_with_addons_emits_not_checked(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.x", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.x")])
        report = validate_build_state(desired, actual, dependency_closure=None)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 1)
        self.assertEqual(dep_checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertFalse(report.is_complete)

    def test_no_closure_no_addons_no_dep_checks(self):
        desired = _resolved(addons=())
        actual = _state()
        report = validate_build_state(desired, actual, dependency_closure=None)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 0)

    def test_satisfied_dep_pass(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(_node("script.module.dep", DependencyStatus.SATISFIED))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.PASS)

    def test_system_dep_pass(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(_node("xbmc.python", DependencyStatus.SYSTEM))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.PASS)

    def test_optional_dep_no_check(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(_node("script.module.opt", DependencyStatus.OPTIONAL, optional=True))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 0)

    def test_missing_dep_fail(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(DependencyNode(
            addon_id="script.module.absent",
            required_by=("plugin.video.root",),
            status=DependencyStatus.MISSING,
            installed_version=None,
            installed_enabled=None,
            min_version_required="",
            optional=False,
        ))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.FAIL)
        self.assertFalse(report.is_valid)

    def test_version_insufficient_dep_fail(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(DependencyNode(
            addon_id="script.module.old",
            required_by=("plugin.video.root",),
            status=DependencyStatus.VERSION_INSUFFICIENT,
            installed_version="1.0.0",
            installed_enabled=True,
            min_version_required="2.0.0",
            optional=False,
        ))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.FAIL)
        self.assertIn("1.0.0", dep_checks[0].reason)
        self.assertIn("2.0.0", dep_checks[0].reason)

    def test_metadata_error_dep_fail(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(DependencyNode(
            addon_id="script.module.broken",
            required_by=("plugin.video.root",),
            status=DependencyStatus.METADATA_ERROR,
            installed_version=None,
            installed_enabled=None,
            min_version_required="",
            optional=False,
        ))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.FAIL)

    def test_installed_disabled_dep_fail(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(_node(
            "script.module.disabled",
            DependencyStatus.INSTALLED_DISABLED,
            required_by=("plugin.video.root",),
            enabled=False,
        ))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.FAIL)
        self.assertIn("disabled", dep_checks[0].actual_state)

    def test_cycle_dep_warning(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(DependencyNode(
            addon_id="plugin.video.cycler",
            required_by=("plugin.video.root",),
            status=DependencyStatus.CYCLE,
            installed_version="1.0.0",
            installed_enabled=True,
            min_version_required="",
            optional=False,
            cycle_path=("plugin.video.cycler", "plugin.video.root", "plugin.video.cycler"),
        ))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.WARNING)
        self.assertIn("cycle", dep_checks[0].actual_state)

    def test_cycle_without_cycle_path_still_warning(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(DependencyNode(
            addon_id="plugin.video.cycler",
            required_by=(),
            status=DependencyStatus.CYCLE,
            installed_version="1.0.0",
            installed_enabled=True,
            min_version_required="",
            optional=False,
            cycle_path=None,
        ))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.WARNING)

    def test_dep_nodes_sorted_lexically(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(
            _node("script.module.zzz", DependencyStatus.SATISFIED),
            _node("script.module.aaa", DependencyStatus.SATISFIED),
            _node("script.module.mmm", DependencyStatus.SATISFIED),
        )
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        subjects = [c.subject for c in dep_checks]
        self.assertEqual(subjects, sorted(subjects))

    def test_closure_with_required_by_in_reason(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(DependencyNode(
            addon_id="script.module.missing-dep",
            required_by=("plugin.video.root",),
            status=DependencyStatus.MISSING,
            installed_version=None,
            installed_enabled=None,
            min_version_required="",
            optional=False,
        ))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertIn("plugin.video.root", dep_checks[0].reason)


# ---------------------------------------------------------------------------
# TestSkinValidation
# ---------------------------------------------------------------------------

class TestSkinValidation(unittest.TestCase):
    """Skin domain: desired skin installed and active."""

    def test_no_desired_skin_no_check(self):
        desired = _resolved(skin=None)
        actual = _state()
        report = validate_build_state(desired, actual)
        skin_checks = [c for c in report.checks if c.domain == ValidationDomain.SKIN]
        self.assertEqual(len(skin_checks), 0)

    def test_skin_installed_and_active_pass(self):
        skin_id = "skin.arctic.horizon"
        desired = _resolved(skin=SkinEntry(addon_id=skin_id))
        actual = _state(
            addons=[_installed(skin_id)],
            active_skin=skin_id,
        )
        report = validate_build_state(desired, actual)
        skin_checks = [c for c in report.checks if c.domain == ValidationDomain.SKIN]
        self.assertEqual(len(skin_checks), 1)
        self.assertEqual(skin_checks[0].status, ValidationStatus.PASS)

    def test_skin_installed_wrong_active_fail(self):
        desired_skin = "skin.arctic.horizon"
        active_skin = "skin.estuary"
        desired = _resolved(skin=SkinEntry(addon_id=desired_skin))
        actual = _state(
            addons=[_installed(desired_skin)],
            active_skin=active_skin,
        )
        report = validate_build_state(desired, actual)
        skin_checks = [c for c in report.checks if c.domain == ValidationDomain.SKIN]
        self.assertEqual(skin_checks[0].status, ValidationStatus.FAIL)
        self.assertIn(active_skin, skin_checks[0].actual_state)
        self.assertIn(desired_skin, skin_checks[0].expected)

    def test_skin_not_installed_fail(self):
        skin_id = "skin.arctic.horizon"
        desired = _resolved(skin=SkinEntry(addon_id=skin_id))
        actual = _state(addons=[], active_skin="skin.estuary")
        report = validate_build_state(desired, actual)
        skin_checks = [c for c in report.checks if c.domain == ValidationDomain.SKIN]
        self.assertEqual(skin_checks[0].status, ValidationStatus.FAIL)
        self.assertIn("not installed", skin_checks[0].actual_state)

    def test_skin_check_subject_is_skin_addon_id(self):
        skin_id = "skin.arctic.horizon"
        desired = _resolved(skin=SkinEntry(addon_id=skin_id))
        actual = _state(addons=[_installed(skin_id)], active_skin=skin_id)
        report = validate_build_state(desired, actual)
        skin_checks = [c for c in report.checks if c.domain == ValidationDomain.SKIN]
        self.assertEqual(skin_checks[0].subject, skin_id)


# ---------------------------------------------------------------------------
# TestConfigurationValidation
# ---------------------------------------------------------------------------

class TestConfigurationValidation(unittest.TestCase):
    """Configuration domain: NOT_CHECKED without a BM-015 snapshot."""

    def test_no_config_no_check(self):
        desired = _resolved(config=None)
        actual = _state()
        report = validate_build_state(desired, actual)
        config_checks = [c for c in report.checks if c.domain == ValidationDomain.CONFIGURATION]
        self.assertEqual(len(config_checks), 0)

    def test_config_present_emits_not_checked(self):
        cfg = ConfigDeclarations(
            packages=("my-pkg",),
            managed_settings=(ManagedSettingScope(addon_id="plugin.video.x", keys=("key1",)),),
            managed_files=("userdata/my.conf",),
        )
        desired = _resolved(config=cfg)
        actual = _state()
        report = validate_build_state(desired, actual)
        config_checks = [c for c in report.checks if c.domain == ValidationDomain.CONFIGURATION]
        self.assertEqual(len(config_checks), 1)
        self.assertEqual(config_checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_config_not_checked_makes_incomplete(self):
        cfg = ConfigDeclarations(packages=("my-pkg",))
        desired = _resolved(config=cfg)
        actual = _state()
        report = validate_build_state(desired, actual)
        self.assertFalse(report.is_complete)
        self.assertFalse(report.passed)

    def test_config_not_checked_does_not_make_invalid(self):
        cfg = ConfigDeclarations(packages=("my-pkg",))
        desired = _resolved(config=cfg)
        actual = _state()
        report = validate_build_state(desired, actual)
        self.assertTrue(report.is_valid)

    def test_configuration_state_ignored_when_config_is_none(self):
        state = ConfigurationValidationState(
            setting_targets=(("plugin.video.x", "key1"),),
            verified_settings=(("plugin.video.x", "key1"),),
        )
        report = validate_build_state(
            _resolved(config=None), _state(), configuration_state=state,
            effective_configuration=EffectiveConfiguration(),
        )
        config_checks = [
            c for c in report.checks if c.domain == ValidationDomain.CONFIGURATION
        ]
        self.assertEqual(config_checks, [])


# ---------------------------------------------------------------------------
# TestConfigurationStateIntegration (BM-015, Option A)
# ---------------------------------------------------------------------------

def _config(settings=(), files=(), packages=("my-pkg",)):
    by_addon = {}
    order = []
    for item in settings:
        if len(item) == 2:
            target_kind = ConfigTargetKind.ADDON
            addon_id, key = item
        else:
            target_kind, addon_id, key = item
            target_kind = ConfigTargetKind(target_kind)
        scope_id = (target_kind, addon_id)
        if scope_id not in by_addon:
            by_addon[scope_id] = []
            order.append(scope_id)
        by_addon[scope_id].append(key)
    return ConfigDeclarations(
        packages=tuple(packages),
        managed_settings=tuple(
            ManagedSettingScope(
                target_kind=target_kind,
                addon_id=addon_id,
                keys=tuple(by_addon[(target_kind, addon_id)]),
            )
            for target_kind, addon_id in order
        ),
        managed_files=tuple(files),
    )


def _effective(settings=(), files=(), packages=("my-pkg",)):
    """Build an EffectiveConfiguration from setting identity/value tuples."""
    normalized = []
    for item in settings:
        if len(item) == 3:
            target_kind = ConfigTargetKind.ADDON
            addon_id, key, value = item
        else:
            target_kind, addon_id, key, value = item
            target_kind = ConfigTargetKind(target_kind)
        normalized.append((target_kind, addon_id, key, value))
    return EffectiveConfiguration(
        packages=tuple(packages),
        settings=tuple(
            ConfigSetting(
                addon_id=addon_id, key=key,
                setting_type=ConfigSettingType.STRING, value=value,
                package_id=packages[0],
                target_kind=target_kind,
            )
            for target_kind, addon_id, key, value in normalized
        ),
        files=tuple(
            ConfigFile(destination=destination, source="files/a",
                       content=content, package_id=packages[0])
            for destination, content in files
        ),
    )


def _state_for(effective, verified_settings=None, verified_files=None):
    """Snapshot bound to `effective`, verifying everything unless told otherwise."""
    targets = tuple(sorted(
        (s.target_kind.value, s.addon_id, s.key)
        for s in effective.settings
    ))
    destinations = tuple(sorted(f.destination for f in effective.files))
    return ConfigurationValidationState(
        effective_identity=effective.identity,
        setting_targets=targets,
        file_targets=destinations,
        verified_settings=targets if verified_settings is None
        else tuple(verified_settings),
        verified_files=destinations if verified_files is None
        else tuple(verified_files),
    )


class TestConfigurationStateIntegration(unittest.TestCase):
    """CONFIGURATION domain driven by BM-015 artifacts (scope + identity)."""

    def _report(self, cfg, state, effective):
        return validate_build_state(
            _resolved(config=cfg), _state(),
            configuration_state=state,
            effective_configuration=effective,
        )

    def _config_checks(self, report):
        return [
            c for c in report.checks if c.domain == ValidationDomain.CONFIGURATION
        ]

    # -- happy path ---------------------------------------------------------

    def test_matching_scope_and_identity_passes(self):
        cfg = _config(
            settings=[("plugin.video.x", "key1")], files=["userdata/my.conf"]
        )
        effective = _effective(
            settings=[("plugin.video.x", "key1", "v")],
            files=[("userdata/my.conf", b"content")],
        )
        report = self._report(cfg, _state_for(effective), effective)
        checks = self._config_checks(report)
        self.assertEqual(len(checks), 2)
        self.assertTrue(all(c.status == ValidationStatus.PASS for c in checks))
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)

    def test_unverified_setting_fails(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        report = self._report(
            cfg, _state_for(effective, verified_settings=()), effective
        )
        checks = self._config_checks(report)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)
        self.assertFalse(report.is_valid)
        self.assertTrue(report.is_complete)

    def test_unverified_file_fails(self):
        cfg = _config(files=["userdata/my.conf"])
        effective = _effective(files=[("userdata/my.conf", b"content")])
        report = self._report(
            cfg, _state_for(effective, verified_files=()), effective
        )
        checks = self._config_checks(report)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)
        self.assertEqual(checks[0].subject, "userdata/my.conf")

    def test_mixed_pass_and_fail(self):
        cfg = _config(
            settings=[("plugin.video.x", "key1"), ("plugin.video.x", "key2")],
            files=["userdata/a.conf", "userdata/b.conf"],
        )
        effective = _effective(
            settings=[("plugin.video.x", "key1", "1"),
                      ("plugin.video.x", "key2", "2")],
            files=[("userdata/a.conf", b"a"), ("userdata/b.conf", b"b")],
        )
        state = _state_for(
            effective,
            verified_settings=(("plugin.video.x", "key1"),),
            verified_files=("userdata/b.conf",),
        )
        checks = self._config_checks(self._report(cfg, state, effective))
        statuses = {c.subject: c.status for c in checks}
        self.assertEqual(statuses["plugin.video.x/key1"], ValidationStatus.PASS)
        self.assertEqual(statuses["plugin.video.x/key2"], ValidationStatus.FAIL)
        self.assertEqual(statuses["userdata/a.conf"], ValidationStatus.FAIL)
        self.assertEqual(statuses["userdata/b.conf"], ValidationStatus.PASS)

    def test_scope_comparison_ignores_ordering(self):
        cfg = _config(settings=[
            ("plugin.video.x", "key2"), ("plugin.video.x", "key1"),
        ])
        effective = _effective(settings=[
            ("plugin.video.x", "key1", "1"), ("plugin.video.x", "key2", "2"),
        ])
        state = ConfigurationValidationState(
            effective_identity=effective.identity,
            setting_targets=(("plugin.video.x", "key2"),
                             ("plugin.video.x", "key1")),
            verified_settings=(("plugin.video.x", "key2"),
                               ("plugin.video.x", "key1")),
        )
        checks = self._config_checks(self._report(cfg, state, effective))
        self.assertEqual(len(checks), 2)
        self.assertTrue(all(c.status == ValidationStatus.PASS for c in checks))

    def test_settings_precede_files_and_each_group_is_sorted(self):
        cfg = _config(
            settings=[("plugin.video.z", "k"), ("plugin.video.a", "k")],
            files=["userdata/z.conf", "userdata/a.conf"],
        )
        effective = _effective(
            settings=[("plugin.video.z", "k", "1"), ("plugin.video.a", "k", "2")],
            files=[("userdata/z.conf", b"z"), ("userdata/a.conf", b"a")],
        )
        checks = self._config_checks(
            self._report(cfg, _state_for(effective), effective)
        )
        self.assertEqual(
            [c.subject for c in checks],
            ["plugin.video.a/k", "plugin.video.z/k",
             "userdata/a.conf", "userdata/z.conf"],
        )

    def test_declared_but_empty_scope_passes_domain(self):
        cfg = ConfigDeclarations(packages=("my-pkg",))
        effective = _effective()
        report = self._report(cfg, _state_for(effective), effective)
        checks = self._config_checks(report)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, ValidationStatus.PASS)
        self.assertEqual(checks[0].subject, "configuration_domain")
        self.assertTrue(report.passed)

    def test_skin_selected_package_is_in_expected_effective_identity(self):
        cfg = _config(
            settings=[("skin.foo", "accent")],
            packages=("ordinary", "skin-pkg"),
        )
        effective = _effective(
            settings=[("skin.foo", "accent", "blue")],
            packages=("ordinary", "skin-pkg"),
        )
        report = self._report(cfg, _state_for(effective), effective)
        checks = self._config_checks(report)
        self.assertEqual(checks[0].status, ValidationStatus.PASS)

    def test_skin_selected_package_mismatch_is_not_checked(self):
        cfg = _config(
            settings=[("skin.foo", "accent")],
            packages=("ordinary", "skin-pkg"),
        )
        stale = _effective(
            settings=[("skin.foo", "accent", "blue")],
            packages=("ordinary",),
        )
        expected = _effective(
            settings=[("skin.foo", "accent", "blue")],
            packages=("ordinary", "skin-pkg"),
        )
        checks = self._config_checks(self._report(cfg, _state_for(stale), expected))
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_skin_target_passes_with_explicit_scope_and_snapshot(self):
        cfg = _config(settings=[(
            "skin", "skin.foo", "accent"
        )])
        effective = _effective(settings=[(
            ConfigTargetKind.SKIN, "skin.foo", "accent", "blue"
        )])
        checks = self._config_checks(
            self._report(cfg, _state_for(effective), effective)
        )
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, ValidationStatus.PASS)
        self.assertEqual(checks[0].subject, "skin:skin.foo/accent")

    def test_skin_target_unverified_fails(self):
        cfg = _config(settings=[("skin", "skin.foo", "accent")])
        effective = _effective(settings=[(
            ConfigTargetKind.SKIN, "skin.foo", "accent", "blue"
        )])
        checks = self._config_checks(
            self._report(
                cfg, _state_for(effective, verified_settings=()), effective
            )
        )
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)

    def test_target_kind_mismatch_is_not_checked(self):
        cfg = _config(settings=[("addon", "same.id", "key")])
        effective = _effective(settings=[(
            ConfigTargetKind.SKIN, "same.id", "key", "v"
        )])
        checks = self._config_checks(
            self._report(cfg, _state_for(effective), effective)
        )
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    # -- missing artifacts --------------------------------------------------

    def test_missing_effective_configuration_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        report = validate_build_state(
            _resolved(config=cfg), _state(),
            configuration_state=_state_for(effective),
        )
        checks = self._config_checks(report)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertIn("effective_configuration", checks[0].reason)

    def test_missing_state_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        report = validate_build_state(
            _resolved(config=cfg), _state(), effective_configuration=effective,
        )
        checks = self._config_checks(report)
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertIn("configuration_state", checks[0].reason)

    # -- stale / mismatched identity ---------------------------------------

    def test_changed_desired_setting_value_is_not_checked(self):
        """Same scope, different desired value → stale snapshot, not a FAIL."""
        cfg = _config(settings=[("plugin.video.x", "key1")])
        old_effective = _effective(settings=[("plugin.video.x", "key1", "720p")])
        new_effective = _effective(settings=[("plugin.video.x", "key1", "4k")])
        stale = _state_for(old_effective)

        checks = self._config_checks(self._report(cfg, stale, new_effective))
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertIn("different effective configuration", checks[0].reason)

    def test_changed_file_content_is_not_checked(self):
        cfg = _config(files=["userdata/my.conf"])
        old_effective = _effective(files=[("userdata/my.conf", b"first")])
        new_effective = _effective(files=[("userdata/my.conf", b"second")])
        checks = self._config_checks(
            self._report(cfg, _state_for(old_effective), new_effective)
        )
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_changed_setting_type_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        as_string = _effective(settings=[("plugin.video.x", "key1", "1")])
        as_int = EffectiveConfiguration(
            packages=("my-pkg",),
            settings=(ConfigSetting(
                addon_id="plugin.video.x", key="key1",
                setting_type=ConfigSettingType.INT, value=1,
                package_id="my-pkg",
            ),),
        )
        checks = self._config_checks(
            self._report(cfg, _state_for(as_string), as_int)
        )
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_changed_winning_package_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")],
                      packages=("a", "b"))
        from_a = EffectiveConfiguration(
            packages=("a", "b"),
            settings=(ConfigSetting(
                addon_id="plugin.video.x", key="key1",
                setting_type=ConfigSettingType.STRING, value="v",
                package_id="a",
            ),),
        )
        from_b = EffectiveConfiguration(
            packages=("a", "b"),
            settings=(ConfigSetting(
                addon_id="plugin.video.x", key="key1",
                setting_type=ConfigSettingType.STRING, value="v",
                package_id="b",
            ),),
        )
        checks = self._config_checks(self._report(cfg, _state_for(from_a), from_b))
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_changed_package_order_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")], packages=("a", "b"))
        forward = _effective(
            settings=[("plugin.video.x", "key1", "v")], packages=("a", "b")
        )
        reverse = _effective(
            settings=[("plugin.video.x", "key1", "v")], packages=("b", "a")
        )
        # Reverse no longer corresponds to desired.config.packages either.
        checks = self._config_checks(self._report(cfg, _state_for(forward), reverse))
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_empty_identity_snapshot_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        state = ConfigurationValidationState(
            setting_targets=(("plugin.video.x", "key1"),),
            verified_settings=(("plugin.video.x", "key1"),),
        )
        checks = self._config_checks(self._report(cfg, state, effective))
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    # -- scope mismatches ---------------------------------------------------

    def test_partial_snapshot_is_not_checked(self):
        cfg = _config(settings=[
            ("plugin.video.x", "key1"), ("plugin.video.x", "key2"),
        ])
        effective = _effective(settings=[
            ("plugin.video.x", "key1", "1"), ("plugin.video.x", "key2", "2"),
        ])
        state = ConfigurationValidationState(
            effective_identity=effective.identity,
            setting_targets=(("plugin.video.x", "key1"),),
            verified_settings=(("plugin.video.x", "key1"),),
        )
        report = self._report(cfg, state, effective)
        checks = self._config_checks(report)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertFalse(report.is_complete)
        self.assertTrue(report.is_valid)

    def test_unrelated_snapshot_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        state = ConfigurationValidationState(
            effective_identity=effective.identity,
            setting_targets=(("plugin.video.other", "other"),),
            verified_settings=(("plugin.video.other", "other"),),
        )
        checks = self._config_checks(self._report(cfg, state, effective))
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_effective_scope_not_matching_manifest_is_not_checked(self):
        cfg = _config(settings=[
            ("plugin.video.x", "key1"), ("plugin.video.x", "key2"),
        ])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        checks = self._config_checks(
            self._report(cfg, _state_for(effective), effective)
        )
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertIn("manifest-declared managed scope", checks[0].reason)

    def test_effective_packages_not_matching_manifest_is_not_checked(self):
        cfg = _config(settings=[("plugin.video.x", "key1")], packages=("my-pkg",))
        effective = _effective(
            settings=[("plugin.video.x", "key1", "v")], packages=("other-pkg",)
        )
        checks = self._config_checks(
            self._report(cfg, _state_for(effective), effective)
        )
        self.assertEqual(checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertIn("config.packages", checks[0].reason)

    def test_duplicate_declared_packages_are_deduplicated_for_comparison(self):
        cfg = _config(settings=[("plugin.video.x", "key1")],
                      packages=("a", "b", "a"))
        effective = _effective(
            settings=[("plugin.video.x", "key1", "v")], packages=("a", "b")
        )
        checks = self._config_checks(
            self._report(cfg, _state_for(effective), effective)
        )
        self.assertTrue(all(c.status == ValidationStatus.PASS for c in checks))

    # -- read-only ----------------------------------------------------------

    def test_validator_remains_read_only_with_artifacts(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        state = _state_for(effective)
        desired = _resolved(config=cfg)
        actual = _state()
        before = (desired, actual, state, effective)
        validate_build_state(
            desired, actual,
            configuration_state=state, effective_configuration=effective,
        )
        self.assertEqual(before, (desired, actual, state, effective))

    def test_configuration_domain_is_last(self):
        cfg = _config(settings=[("plugin.video.x", "key1")])
        effective = _effective(settings=[("plugin.video.x", "key1", "v")])
        report = validate_build_state(
            _resolved(
                config=cfg,
                repositories=(Repository(addon_id="repository.test"),),
            ),
            _state(addons=(_installed("repository.test"),)),
            configuration_state=_state_for(effective),
            effective_configuration=effective,
        )
        domains = [c.domain for c in report.checks]
        self.assertEqual(domains[-1], ValidationDomain.CONFIGURATION)


# ---------------------------------------------------------------------------
# TestDomainOrdering
# ---------------------------------------------------------------------------

class TestDomainOrdering(unittest.TestCase):
    """Checks appear in REPOSITORY → ADDON → DEPENDENCY → SKIN → CONFIGURATION order."""

    _DOMAIN_ORDER = [
        ValidationDomain.REPOSITORY,
        ValidationDomain.ADDON,
        ValidationDomain.DEPENDENCY,
        ValidationDomain.SKIN,
        ValidationDomain.CONFIGURATION,
    ]

    def test_all_domains_sorted_by_domain_order(self):
        skin_id = "skin.arctic.horizon"
        repo_id = "repository.test"
        addon_id = "plugin.video.enabled"
        cfg = ConfigDeclarations(packages=("pkg",))
        desired = _resolved(
            repositories=(Repository(addon_id=repo_id, required=True),),
            addons=(AddonEntry(addon_id=addon_id, state="enabled"),),
            skin=SkinEntry(addon_id=skin_id),
            config=cfg,
        )
        actual = _state(
            addons=[_installed(repo_id), _installed(addon_id), _installed(skin_id)],
            active_skin=skin_id,
        )
        closure = DependencyClosure(
            root_addon_ids=(addon_id,),
            nodes=(_node("script.module.dep", DependencyStatus.SATISFIED),),
        )
        report = validate_build_state(desired, actual, closure)

        domain_sequence = [c.domain for c in report.checks]
        domain_indices = [self._DOMAIN_ORDER.index(d) for d in domain_sequence]
        # Each domain's index must be >= the previous (non-decreasing)
        for i in range(1, len(domain_indices)):
            self.assertGreaterEqual(
                domain_indices[i], domain_indices[i - 1],
                msg=f"Domain ordering violated at check {i}: "
                    f"{domain_sequence[i - 1]} before {domain_sequence[i]}",
            )

    def test_within_repository_domain_lexical(self):
        repos = (
            Repository(addon_id="repository.zzz", required=True),
            Repository(addon_id="repository.aaa", required=True),
        )
        desired = _resolved(repositories=repos)
        actual = _state(addons=[
            _installed("repository.aaa"),
            _installed("repository.zzz"),
        ])
        report = validate_build_state(desired, actual)
        repo_checks = [c for c in report.checks if c.domain == ValidationDomain.REPOSITORY]
        subjects = [c.subject for c in repo_checks]
        self.assertEqual(subjects, sorted(subjects))

    def test_within_addon_domain_lexical(self):
        desired = _resolved(addons=(
            AddonEntry(addon_id="z.addon", state="enabled"),
            AddonEntry(addon_id="a.addon", state="enabled"),
        ))
        actual = _state(addons=[_installed("a.addon"), _installed("z.addon")])
        report = validate_build_state(desired, actual)
        addon_checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        subjects = [c.subject for c in addon_checks]
        self.assertEqual(subjects, sorted(subjects))

    def test_within_dependency_domain_lexical(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(
            _node("z.module", DependencyStatus.SATISFIED),
            _node("a.module", DependencyStatus.SATISFIED),
            _node("m.module", DependencyStatus.SATISFIED),
        )
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        subjects = [c.subject for c in dep_checks]
        self.assertEqual(subjects, sorted(subjects))


# ---------------------------------------------------------------------------
# TestReadOnlyGuarantee
# ---------------------------------------------------------------------------

class TestReadOnlyGuarantee(unittest.TestCase):
    """validate_build_state must not modify its inputs."""

    def test_desired_addons_unchanged(self):
        entry = AddonEntry(addon_id="plugin.video.foo", state="enabled")
        desired = _resolved(addons=(entry,))
        original_addons = desired.addons

        actual = _state(addons=[_installed("plugin.video.foo")])
        validate_build_state(desired, actual)

        self.assertEqual(desired.addons, original_addons)

    def test_actual_addons_unchanged(self):
        actual = _state(addons=[_installed("plugin.video.foo")])
        original_addons = actual.addons

        desired = _resolved()
        validate_build_state(desired, actual)

        self.assertEqual(actual.addons, original_addons)

    def test_closure_nodes_unchanged(self):
        closure = _closure(_node("script.module.dep", DependencyStatus.SATISFIED))
        original_nodes = closure.nodes

        desired = _resolved()
        actual = _state()
        validate_build_state(desired, actual, closure)

        self.assertEqual(closure.nodes, original_nodes)


# ---------------------------------------------------------------------------
# TestAggregateSemantics
# ---------------------------------------------------------------------------

class TestAggregateSemantics(unittest.TestCase):
    """Aggregate properties: is_valid, is_complete, passed."""

    def test_all_pass_everything_true(self):
        desired = _resolved(
            repositories=(Repository(addon_id="repository.r", required=True),),
            addons=(AddonEntry(addon_id="plugin.video.x", state="enabled"),),
        )
        actual = _state(addons=[
            _installed("repository.r"),
            _installed("plugin.video.x"),
        ])
        # Closure rooted at the enabled add-on; no dep nodes → dep domain complete.
        closure = DependencyClosure(root_addon_ids=("plugin.video.x",), nodes=())
        report = validate_build_state(desired, actual, closure)
        self.assertTrue(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)

    def test_fail_prevents_passed(self):
        desired = _resolved(
            addons=(AddonEntry(addon_id="plugin.video.x", state="enabled"),),
        )
        actual = _state(addons=[_installed("plugin.video.x", enabled=False)])
        # Closure rooted at the enabled add-on; no dep nodes → dep domain complete.
        closure = DependencyClosure(root_addon_ids=("plugin.video.x",), nodes=())
        report = validate_build_state(desired, actual, closure)
        self.assertFalse(report.is_valid)
        self.assertFalse(report.passed)
        self.assertTrue(report.is_complete)

    def test_not_checked_prevents_passed(self):
        cfg = ConfigDeclarations(packages=("pkg",))
        desired = _resolved(config=cfg)
        actual = _state()
        report = validate_build_state(desired, actual)
        self.assertTrue(report.is_valid)
        self.assertFalse(report.is_complete)
        self.assertFalse(report.passed)

    def test_warning_alone_allows_passed(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        closure = _closure(DependencyNode(
            addon_id="plugin.video.cycle",
            required_by=(),
            status=DependencyStatus.CYCLE,
            installed_version="1.0.0",
            installed_enabled=True,
            min_version_required="",
            optional=False,
            cycle_path=("plugin.video.cycle",),
        ))
        report = validate_build_state(desired, actual, closure)
        self.assertTrue(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)
        self.assertEqual(len(report.warnings), 1)

    def test_no_checks_all_true(self):
        desired = _resolved()
        actual = _state()
        report = validate_build_state(desired, actual)
        self.assertTrue(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)

    def test_fail_and_warning_invalid_not_complete(self):
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.root", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.root")])
        # FAIL from missing dep + WARNING from cycle
        closure = _closure(
            DependencyNode(
                addon_id="script.module.missing",
                required_by=("plugin.video.root",),
                status=DependencyStatus.MISSING,
                installed_version=None,
                installed_enabled=None,
                min_version_required="",
                optional=False,
            ),
            DependencyNode(
                addon_id="plugin.video.cycle",
                required_by=(),
                status=DependencyStatus.CYCLE,
                installed_version="1.0.0",
                installed_enabled=True,
                min_version_required="",
                optional=False,
                cycle_path=("plugin.video.cycle",),
            ),
        )
        report = validate_build_state(desired, actual, closure)
        self.assertFalse(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(len(report.warnings), 1)


# ---------------------------------------------------------------------------
# TestDependencyClosureRootScope
# ---------------------------------------------------------------------------

class TestDependencyClosureRootScope(unittest.TestCase):
    """Closure root_addon_ids must exactly match enabled managed add-ons."""

    def test_enabled_addon_no_closure_emits_not_checked(self):
        """CASE 2: enabled desired add-on + closure=None → NOT_CHECKED."""
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.a", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.a")])
        report = validate_build_state(desired, actual, dependency_closure=None)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 1)
        self.assertEqual(dep_checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertFalse(report.is_complete)

    def test_enabled_addon_empty_closure_emits_not_checked(self):
        """CASE 4: enabled desired + closure with no roots → NOT_CHECKED (scope mismatch)."""
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.a", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.a")])
        empty_closure = DependencyClosure(root_addon_ids=(), nodes=())
        report = validate_build_state(desired, actual, empty_closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 1)
        self.assertEqual(dep_checks[0].status, ValidationStatus.NOT_CHECKED)
        self.assertFalse(report.is_complete)

    def test_enabled_addon_wrong_root_emits_not_checked(self):
        """CASE 4: enabled add-on A + closure rooted at unrelated B → NOT_CHECKED."""
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.a", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.a")])
        wrong_closure = DependencyClosure(root_addon_ids=("plugin.video.b",), nodes=())
        report = validate_build_state(desired, actual, wrong_closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 1)
        self.assertEqual(dep_checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_two_enabled_addons_partial_closure_emits_not_checked(self):
        """CASE 4: enabled roots A+B, closure only covers A → NOT_CHECKED."""
        desired = _resolved(addons=(
            AddonEntry(addon_id="plugin.video.a", state="enabled"),
            AddonEntry(addon_id="plugin.video.b", state="enabled"),
        ))
        actual = _state(addons=[_installed("plugin.video.a"), _installed("plugin.video.b")])
        partial_closure = DependencyClosure(root_addon_ids=("plugin.video.a",), nodes=())
        report = validate_build_state(desired, actual, partial_closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 1)
        self.assertEqual(dep_checks[0].status, ValidationStatus.NOT_CHECKED)

    def test_two_enabled_addons_reversed_roots_accepted(self):
        """CASE 3: enabled roots A+B, closure roots B+A (reversed order) → validates normally."""
        desired = _resolved(addons=(
            AddonEntry(addon_id="plugin.video.a", state="enabled"),
            AddonEntry(addon_id="plugin.video.b", state="enabled"),
        ))
        actual = _state(addons=[_installed("plugin.video.a"), _installed("plugin.video.b")])
        # Root order in closure is reversed relative to expected; should still match.
        closure = DependencyClosure(
            root_addon_ids=("plugin.video.b", "plugin.video.a"),
            nodes=(),
        )
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        # Roots match (set equality); no nodes → no dep checks at all (dep domain complete).
        self.assertEqual(len(dep_checks), 0)
        self.assertTrue(report.is_complete)

    def test_matching_roots_zero_nodes_dep_domain_complete(self):
        """CASE 3: closure roots match enabled add-on, zero dep nodes → dep domain complete."""
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.a", state="enabled"),))
        actual = _state(addons=[_installed("plugin.video.a")])
        closure = DependencyClosure(root_addon_ids=("plugin.video.a",), nodes=())
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 0)
        self.assertTrue(report.is_complete)

    def test_disabled_only_desired_no_dep_check(self):
        """CASE 1: only disabled desired add-on → dep validation not applicable; no NOT_CHECKED."""
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.d", state="disabled"),))
        actual = _state(addons=[_installed("plugin.video.d", enabled=False)])
        report = validate_build_state(desired, actual, dependency_closure=None)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 0)

    def test_mixed_enabled_disabled_only_enabled_required_in_roots(self):
        """CASE 3: enabled + disabled desired; closure rooted only at enabled ID → validates."""
        enabled_id = "plugin.video.enabled"
        disabled_id = "plugin.video.disabled"
        desired = _resolved(addons=(
            AddonEntry(addon_id=enabled_id, state="enabled"),
            AddonEntry(addon_id=disabled_id, state="disabled"),
        ))
        actual = _state(addons=[
            _installed(enabled_id, enabled=True),
            _installed(disabled_id, enabled=False),
        ])
        # Only the enabled add-on must be in roots; disabled is excluded from expected_roots.
        closure = DependencyClosure(root_addon_ids=(enabled_id,), nodes=())
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 0)
        self.assertTrue(report.is_complete)

    def test_unmanaged_actual_addons_do_not_affect_expected_roots(self):
        """Unmanaged installed add-ons are never included in expected_roots."""
        desired = _resolved(addons=(AddonEntry(addon_id="plugin.video.managed", state="enabled"),))
        actual = _state(addons=[
            _installed("plugin.video.managed"),
            _installed("plugin.video.unmanaged"),
            _installed("script.module.external"),
        ])
        # Closure rooted only at the managed add-on; unmanaged add-ons must not appear.
        closure = DependencyClosure(root_addon_ids=("plugin.video.managed",), nodes=())
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 0)
        self.assertTrue(report.is_complete)


# ---------------------------------------------------------------------------
# TestFullScenario
# ---------------------------------------------------------------------------

class TestFullScenario(unittest.TestCase):
    """Integration-style: realistic desired + actual + closure combinations."""

    def test_clean_build_state_all_correct(self):
        """A fully provisioned build with one repo, two addons (enabled+disabled),
        skin, satisfied dep, and no config emits all PASS and passed=True."""
        repo_id = "repository.kodi-testing"
        enabled_id = "plugin.video.enabled"
        disabled_id = "plugin.video.disabled"
        skin_id = "skin.arctic.horizon"
        dep_id = "script.module.dep"

        desired = _resolved(
            repositories=(Repository(addon_id=repo_id, required=True),),
            addons=(
                AddonEntry(addon_id=enabled_id, state="enabled"),
                AddonEntry(addon_id=disabled_id, state="disabled"),
            ),
            skin=SkinEntry(addon_id=skin_id),
            config=None,
        )
        actual = _state(
            addons=[
                _installed(repo_id, enabled=True),
                _installed(enabled_id, enabled=True),
                _installed(disabled_id, enabled=False),
                _installed(skin_id, enabled=True),
                _installed(dep_id, enabled=True),
                _installed("plugin.video.unmanaged", enabled=True),
            ],
            active_skin=skin_id,
        )
        closure = DependencyClosure(
            root_addon_ids=(enabled_id,),
            nodes=(_node(dep_id, DependencyStatus.SATISFIED),),
        )
        report = validate_build_state(desired, actual, closure)
        self.assertTrue(report.passed)
        self.assertEqual(len(report.failures), 0)
        self.assertEqual(len(report.warnings), 0)
        self.assertEqual(len(report.not_checked), 0)

    def test_drift_enabled_addon_becomes_disabled(self):
        """A single enabled-desired addon found disabled → is_valid=False."""
        addon_id = "plugin.video.drifted"
        desired = _resolved(addons=(AddonEntry(addon_id=addon_id, state="enabled"),))
        actual = _state(addons=[_installed(addon_id, enabled=False)])
        report = validate_build_state(desired, actual)
        self.assertFalse(report.is_valid)
        fail_subjects = [c.subject for c in report.failures]
        self.assertIn(addon_id, fail_subjects)

    def test_drift_repaired_returns_to_pass(self):
        """After repairing drift, validate_build_state returns passed=True."""
        addon_id = "plugin.video.drifted"
        desired = _resolved(addons=(AddonEntry(addon_id=addon_id, state="enabled"),))
        # Closure rooted at the enabled add-on; no dep nodes → dep domain complete.
        closure = DependencyClosure(root_addon_ids=(addon_id,), nodes=())
        # Drifted state
        drifted_actual = _state(addons=[_installed(addon_id, enabled=False)])
        drifted_report = validate_build_state(desired, drifted_actual, closure)
        self.assertFalse(drifted_report.is_valid)
        # Repaired state
        repaired_actual = _state(addons=[_installed(addon_id, enabled=True)])
        repaired_report = validate_build_state(desired, repaired_actual, closure)
        self.assertTrue(repaired_report.passed)

    def test_validator_does_not_mutate_kodi_state(self):
        """validate_build_state does not alter actual.addons."""
        addon_id = "plugin.video.x"
        desired = _resolved(addons=(AddonEntry(addon_id=addon_id, state="enabled"),))
        addon = _installed(addon_id, enabled=True)
        actual = _state(addons=[addon])
        before = actual.addons

        validate_build_state(desired, actual)

        self.assertEqual(actual.addons, before)
        self.assertTrue(actual.addons[0].enabled)


# ---------------------------------------------------------------------------
# TestValidationCheckFields
# ---------------------------------------------------------------------------

class TestValidationCheckFields(unittest.TestCase):
    """ValidationCheck: verify field presence, types, and frozen behaviour."""

    def test_check_is_frozen(self):
        check = ValidationCheck(
            domain=ValidationDomain.ADDON,
            subject="plugin.video.x",
            status=ValidationStatus.PASS,
            expected="enabled",
            actual_state="enabled",
            reason="test",
        )
        with self.assertRaises((AttributeError, TypeError)):
            check.status = ValidationStatus.FAIL  # type: ignore[misc]

    def test_check_fields_present(self):
        check = ValidationCheck(
            domain=ValidationDomain.REPOSITORY,
            subject="repository.test",
            status=ValidationStatus.FAIL,
            expected="installed and enabled",
            actual_state="not installed",
            reason="repository not installed",
        )
        self.assertEqual(check.domain, ValidationDomain.REPOSITORY)
        self.assertEqual(check.subject, "repository.test")
        self.assertEqual(check.status, ValidationStatus.FAIL)
        self.assertEqual(check.expected, "installed and enabled")
        self.assertEqual(check.actual_state, "not installed")
        self.assertIn("not installed", check.reason)

    def test_validation_status_str_enum(self):
        self.assertEqual(ValidationStatus.PASS, "pass")
        self.assertEqual(ValidationStatus.FAIL, "fail")
        self.assertEqual(ValidationStatus.WARNING, "warning")
        self.assertEqual(ValidationStatus.NOT_CHECKED, "not_checked")

    def test_validation_domain_str_enum(self):
        self.assertEqual(ValidationDomain.REPOSITORY, "repository")
        self.assertEqual(ValidationDomain.ADDON, "addon")
        self.assertEqual(ValidationDomain.DEPENDENCY, "dependency")
        self.assertEqual(ValidationDomain.SKIN, "skin")
        self.assertEqual(ValidationDomain.CONFIGURATION, "configuration")


if __name__ == "__main__":
    unittest.main()
