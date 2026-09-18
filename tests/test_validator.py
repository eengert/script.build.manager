"""
Tests for BM-014: resources.lib.validator — post-operation state validator.

Covers:
  - ValidationReport aggregate properties (is_valid, is_complete, passed,
    passes, failures, warnings, not_checked)
  - Repository domain validation (required=True only)
  - Addon domain validation (enabled / disabled / absent / unknown state)
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
    """Addon domain: desired enabled / disabled / absent."""

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

    # --- desired "absent" ---

    def test_absent_desired_not_installed_pass(self):
        entry = AddonEntry(addon_id="plugin.video.old", state="absent")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.PASS)

    def test_absent_desired_installed_enabled_fail(self):
        entry = AddonEntry(addon_id="plugin.video.old", state="absent")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[_installed("plugin.video.old", enabled=True)])
        report = validate_build_state(desired, actual)
        checks = [c for c in report.checks if c.domain == ValidationDomain.ADDON]
        self.assertEqual(checks[0].status, ValidationStatus.FAIL)
        self.assertIn("installed", checks[0].actual_state)

    def test_absent_desired_installed_disabled_fail(self):
        entry = AddonEntry(addon_id="plugin.video.old", state="absent")
        desired = _resolved(addons=(entry,))
        actual = _state(addons=[_installed("plugin.video.old", enabled=False)])
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
        desired = _resolved()
        actual = _state()
        closure = _closure(_node("script.module.dep", DependencyStatus.SATISFIED))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.PASS)

    def test_system_dep_pass(self):
        desired = _resolved()
        actual = _state()
        closure = _closure(_node("xbmc.python", DependencyStatus.SYSTEM))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(dep_checks[0].status, ValidationStatus.PASS)

    def test_optional_dep_no_check(self):
        desired = _resolved()
        actual = _state()
        closure = _closure(_node("script.module.opt", DependencyStatus.OPTIONAL, optional=True))
        report = validate_build_state(desired, actual, closure)
        dep_checks = [c for c in report.checks if c.domain == ValidationDomain.DEPENDENCY]
        self.assertEqual(len(dep_checks), 0)

    def test_missing_dep_fail(self):
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
    """Configuration domain: NOT_CHECKED when config is non-None (BM-015 deferred)."""

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
        closure = _closure(_node("script.module.dep", DependencyStatus.SATISFIED))
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
        desired = _resolved()
        actual = _state()
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
        # Empty closure (non-None) suppresses NOT_CHECKED for the dep domain.
        empty_closure = DependencyClosure(root_addon_ids=(), nodes=())
        report = validate_build_state(desired, actual, empty_closure)
        self.assertTrue(report.is_valid)
        self.assertTrue(report.is_complete)
        self.assertTrue(report.passed)

    def test_fail_prevents_passed(self):
        desired = _resolved(
            addons=(AddonEntry(addon_id="plugin.video.x", state="enabled"),),
        )
        actual = _state(addons=[_installed("plugin.video.x", enabled=False)])
        # Empty closure (non-None) so the only NOT_CHECKED source is excluded.
        empty_closure = DependencyClosure(root_addon_ids=(), nodes=())
        report = validate_build_state(desired, actual, empty_closure)
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
        desired = _resolved()
        actual = _state()
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
        desired = _resolved()
        actual = _state()
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
        closure = _closure(_node(dep_id, DependencyStatus.SATISFIED))
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
        # Use a non-None empty closure so no NOT_CHECKED is emitted.
        empty_closure = DependencyClosure(root_addon_ids=(), nodes=())
        # Drifted state
        drifted_actual = _state(addons=[_installed(addon_id, enabled=False)])
        drifted_report = validate_build_state(desired, drifted_actual, empty_closure)
        self.assertFalse(drifted_report.is_valid)
        # Repaired state
        repaired_actual = _state(addons=[_installed(addon_id, enabled=True)])
        repaired_report = validate_build_state(desired, repaired_actual, empty_closure)
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
