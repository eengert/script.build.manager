"""
BM-006: Plan changes (desired-vs-actual planner) tests.

Tests plan_changes() using typed fixtures. No Kodi runtime. No real Kodi
profiles touched. All add-on state combinations, skin, config, repositories,
ordering, and error conditions are covered.
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
    Manifest,
    ManagedSettingScope,
    OptionalGroup,
    ProfileLayer,
    Repository,
    RestartPolicy,
    SkinEntry,
    load_manifest_file,
    validate_manifest,
)
from resources.lib.resolver import ResolvedBuild, resolve_manifest
from resources.lib.inspector import InstalledAddon, KodiState
from resources.lib.planner import (
    CONFIGURE,
    DISABLE_ADDON,
    ENABLE_ADDON,
    ENSURE_ABSENT,
    INSTALL_ADDON,
    INSTALL_REPOSITORY,
    SET_SKIN,
    Plan,
    PlanAction,
    PlanningError,
    plan_changes,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_build(build_id: str = "test-build", version: str = "1.0.0") -> BuildInfo:
    return BuildInfo(id=build_id, version=version)


def _make_resolved(
    addons=(),
    skin=None,
    config=None,
    repositories=(),
    build_id: str = "test-build",
    platform_profile_id: str = "macos",
    device_profile_id: str = "test-device",
) -> ResolvedBuild:
    return ResolvedBuild(
        build=_make_build(build_id),
        engine_min_version="",
        platform_profile_id=platform_profile_id,
        device_profile_id=device_profile_id,
        repositories=tuple(repositories),
        addons=tuple(addons),
        skin=skin,
        config=config,
        optional_groups_applied=(),
        restart_policy=None,
        private_overlay=None,
    )


def _make_state(
    addons=(),
    platform: str = "macos",
    kodi_version: str = "21.1",
    active_skin: str = "skin.estuary",
) -> KodiState:
    return KodiState(
        platform=platform,
        kodi_version=kodi_version,
        active_skin=active_skin,
        addons=tuple(
            InstalledAddon(addon_id=aid, enabled=enabled, version=ver)
            for aid, enabled, ver in addons
        ),
    )


def _addon(addon_id: str, enabled: bool, version: str = "1.0.0") -> tuple:
    """Helper for _make_state addons list."""
    return (addon_id, enabled, version)


def _desired(addon_id: str, state: str) -> AddonEntry:
    return AddonEntry(addon_id=addon_id, state=state)


def _action_kinds(plan: Plan) -> list:
    return [a.kind for a in plan.actions]


def _action_ids(plan: Plan) -> list:
    return [a.addon_id for a in plan.actions]


# ---------------------------------------------------------------------------
# TestAddonEnabled
# ---------------------------------------------------------------------------

class TestAddonEnabled(unittest.TestCase):

    def test_missing_installs(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "enabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertEqual(_action_kinds(plan), [INSTALL_ADDON])
        a = plan.actions[0]
        self.assertEqual(a.addon_id, "plugin.foo")
        self.assertEqual(a.desired_state, "enabled")
        self.assertEqual(a.current_state, "missing")

    def test_installed_disabled_enables(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "enabled")])
        actual = _make_state(addons=[_addon("plugin.foo", False)])
        plan = plan_changes(desired, actual)
        self.assertEqual(_action_kinds(plan), [ENABLE_ADDON])
        a = plan.actions[0]
        self.assertEqual(a.addon_id, "plugin.foo")
        self.assertEqual(a.desired_state, "enabled")
        self.assertEqual(a.current_state, "disabled")

    def test_installed_enabled_noop(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "enabled")])
        actual = _make_state(addons=[_addon("plugin.foo", True)])
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)


# ---------------------------------------------------------------------------
# TestAddonDisabled
# ---------------------------------------------------------------------------

class TestAddonDisabled(unittest.TestCase):

    def test_missing_installs_with_disabled_state(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "disabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertEqual(_action_kinds(plan), [INSTALL_ADDON])
        a = plan.actions[0]
        self.assertEqual(a.addon_id, "plugin.foo")
        self.assertEqual(a.desired_state, "disabled")
        self.assertEqual(a.current_state, "missing")

    def test_installed_enabled_disables(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "disabled")])
        actual = _make_state(addons=[_addon("plugin.foo", True)])
        plan = plan_changes(desired, actual)
        self.assertEqual(_action_kinds(plan), [DISABLE_ADDON])
        a = plan.actions[0]
        self.assertEqual(a.addon_id, "plugin.foo")
        self.assertEqual(a.desired_state, "disabled")
        self.assertEqual(a.current_state, "enabled")

    def test_installed_disabled_noop(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "disabled")])
        actual = _make_state(addons=[_addon("plugin.foo", False)])
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)

    def test_no_disable_emitted_for_missing_addon(self):
        """DISABLE_ADDON must not appear for an add-on that isn't installed."""
        desired = _make_resolved(addons=[_desired("plugin.foo", "disabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)
        self.assertNotIn(DISABLE_ADDON, kinds)
        self.assertIn(INSTALL_ADDON, kinds)


# ---------------------------------------------------------------------------
# TestAddonAbsent
# ---------------------------------------------------------------------------

class TestAddonAbsent(unittest.TestCase):

    def test_installed_enabled_ensures_absent(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "absent")])
        actual = _make_state(addons=[_addon("plugin.foo", True)])
        plan = plan_changes(desired, actual)
        self.assertEqual(_action_kinds(plan), [ENSURE_ABSENT])
        a = plan.actions[0]
        self.assertEqual(a.addon_id, "plugin.foo")
        self.assertEqual(a.desired_state, "absent")
        self.assertEqual(a.current_state, "enabled")

    def test_installed_disabled_ensures_absent(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "absent")])
        actual = _make_state(addons=[_addon("plugin.foo", False)])
        plan = plan_changes(desired, actual)
        self.assertEqual(_action_kinds(plan), [ENSURE_ABSENT])
        a = plan.actions[0]
        self.assertEqual(a.current_state, "disabled")

    def test_missing_noop(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "absent")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)

    def test_absent_does_not_emit_install(self):
        """An 'absent' desired state must never produce an install action."""
        desired = _make_resolved(addons=[_desired("plugin.foo", "absent")])
        actual = _make_state(addons=[_addon("plugin.foo", True)])
        plan = plan_changes(desired, actual)
        self.assertNotIn(INSTALL_ADDON, _action_kinds(plan))


# ---------------------------------------------------------------------------
# TestUnmanagedAddons
# ---------------------------------------------------------------------------

class TestUnmanagedAddons(unittest.TestCase):

    def test_unmanaged_addon_not_removed(self):
        """Add-ons in actual state but absent from desired are left alone."""
        desired = _make_resolved()
        actual = _make_state(addons=[_addon("plugin.unmanaged", True)])
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)

    def test_unmanaged_addon_alongside_desired_change(self):
        """Unmanaged addons do not affect planned changes for managed ones."""
        desired = _make_resolved(addons=[_desired("plugin.desired", "enabled")])
        actual = _make_state(addons=[_addon("plugin.unmanaged", True)])
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)
        self.assertEqual(kinds, [INSTALL_ADDON])
        self.assertEqual(plan.actions[0].addon_id, "plugin.desired")

    def test_unmanaged_no_ensure_absent_emitted(self):
        """ENSURE_ABSENT must never appear for an unmanaged add-on."""
        desired = _make_resolved()
        actual = _make_state(addons=[
            _addon("plugin.a", True),
            _addon("plugin.b", False),
        ])
        plan = plan_changes(desired, actual)
        self.assertNotIn(ENSURE_ABSENT, _action_kinds(plan))


# ---------------------------------------------------------------------------
# TestSkin
# ---------------------------------------------------------------------------

class TestSkin(unittest.TestCase):

    def test_no_desired_skin_no_action(self):
        desired = _make_resolved(skin=None)
        actual = _make_state(active_skin="skin.estuary")
        plan = plan_changes(desired, actual)
        self.assertNotIn(SET_SKIN, _action_kinds(plan))

    def test_desired_skin_matches_active_no_action(self):
        desired = _make_resolved(skin=SkinEntry(addon_id="skin.estuary"))
        actual = _make_state(active_skin="skin.estuary",
                             addons=[_addon("skin.estuary", True)])
        plan = plan_changes(desired, actual)
        self.assertNotIn(SET_SKIN, _action_kinds(plan))

    def test_desired_skin_differs_emits_set_skin(self):
        desired = _make_resolved(skin=SkinEntry(addon_id="skin.arctic.fuse.3"),
                                 addons=[_desired("skin.arctic.fuse.3", "enabled")])
        actual = _make_state(active_skin="skin.estuary",
                             addons=[_addon("skin.arctic.fuse.3", True)])
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)
        self.assertIn(SET_SKIN, kinds)
        skin_action = next(a for a in plan.actions if a.kind == SET_SKIN)
        self.assertEqual(skin_action.addon_id, "skin.arctic.fuse.3")
        self.assertEqual(skin_action.desired_state, "active")
        self.assertEqual(skin_action.current_state, "skin.estuary")

    def test_desired_skin_not_installed_emits_install_and_set(self):
        """Skin not installed: must emit INSTALL_ADDON + SET_SKIN."""
        desired = _make_resolved(skin=SkinEntry(addon_id="skin.arctic.fuse.3"))
        actual = _make_state(active_skin="skin.estuary")
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)
        self.assertIn(INSTALL_ADDON, kinds)
        self.assertIn(SET_SKIN, kinds)
        install = next(a for a in plan.actions if a.kind == INSTALL_ADDON)
        self.assertEqual(install.addon_id, "skin.arctic.fuse.3")

    def test_desired_skin_in_addons_list_no_duplicate_install(self):
        """Skin in desired.addons already generates INSTALL; no duplicate."""
        desired = _make_resolved(
            addons=[_desired("skin.arctic.fuse.3", "enabled")],
            skin=SkinEntry(addon_id="skin.arctic.fuse.3"),
        )
        actual = _make_state(active_skin="skin.estuary")
        plan = plan_changes(desired, actual)
        install_count = sum(
            1 for a in plan.actions
            if a.kind == INSTALL_ADDON and a.addon_id == "skin.arctic.fuse.3"
        )
        self.assertEqual(install_count, 1, "Expected exactly one INSTALL_ADDON for skin")
        self.assertIn(SET_SKIN, _action_kinds(plan))

    def test_skin_active_but_disabled_in_desired_addons(self):
        """Skin active and in desired addons as disabled → DISABLE + SET if different."""
        # Skin is active but should be disabled in addons, and there's a different desired skin.
        # This is unusual, but we test the logic is consistent.
        desired = _make_resolved(
            addons=[_desired("skin.arctic.fuse.3", "disabled")],
            skin=SkinEntry(addon_id="skin.arctic.fuse.3"),
        )
        actual = _make_state(
            active_skin="skin.estuary",
            addons=[_addon("skin.arctic.fuse.3", True)],
        )
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)
        # Should disable the skin add-on per desired addons, and also set it as skin
        self.assertIn(DISABLE_ADDON, kinds)
        self.assertIn(SET_SKIN, kinds)

    def test_set_skin_current_state_is_actual_skin(self):
        desired = _make_resolved(skin=SkinEntry(addon_id="skin.foo"),
                                 addons=[_desired("skin.foo", "enabled")])
        actual = _make_state(active_skin="skin.estuary",
                             addons=[_addon("skin.foo", True)])
        plan = plan_changes(desired, actual)
        skin_action = next(a for a in plan.actions if a.kind == SET_SKIN)
        self.assertEqual(skin_action.current_state, "skin.estuary")

    def test_set_skin_current_state_none_when_no_active_skin(self):
        desired = _make_resolved(skin=SkinEntry(addon_id="skin.foo"),
                                 addons=[_desired("skin.foo", "enabled")])
        actual = _make_state(active_skin="",
                             addons=[_addon("skin.foo", True)])
        plan = plan_changes(desired, actual)
        skin_action = next(a for a in plan.actions if a.kind == SET_SKIN)
        self.assertEqual(skin_action.current_state, "none")


# ---------------------------------------------------------------------------
# TestConfig
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):

    def test_no_desired_config_no_configure_action(self):
        desired = _make_resolved(config=None)
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertNotIn(CONFIGURE, _action_kinds(plan))

    def test_desired_config_emits_configure(self):
        config = ConfigDeclarations(
            packages=("pkg-a",),
            managed_settings=(ManagedSettingScope(addon_id="plugin.foo", keys=("key1",)),),
            managed_files=("addon_data/plugin.foo/settings.xml",),
        )
        desired = _make_resolved(config=config)
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertIn(CONFIGURE, _action_kinds(plan))

    def test_configure_action_fields(self):
        config = ConfigDeclarations(packages=("pkg",))
        desired = _make_resolved(config=config)
        actual = _make_state()
        plan = plan_changes(desired, actual)
        cfg = next(a for a in plan.actions if a.kind == CONFIGURE)
        self.assertEqual(cfg.addon_id, "")
        self.assertEqual(cfg.desired_state, "configured")
        self.assertEqual(cfg.current_state, "unchecked")

    def test_exactly_one_configure_action(self):
        config = ConfigDeclarations(packages=("a", "b"))
        desired = _make_resolved(config=config)
        actual = _make_state()
        plan = plan_changes(desired, actual)
        configure_count = sum(1 for a in plan.actions if a.kind == CONFIGURE)
        self.assertEqual(configure_count, 1)

    def test_configure_does_not_claim_diff_details(self):
        """CONFIGURE must not fabricate which settings are wrong."""
        config = ConfigDeclarations(packages=("pkg",))
        desired = _make_resolved(config=config)
        actual = _make_state()
        plan = plan_changes(desired, actual)
        cfg = next(a for a in plan.actions if a.kind == CONFIGURE)
        # current_state must be unchecked, not any specific value
        self.assertEqual(cfg.current_state, "unchecked")


# ---------------------------------------------------------------------------
# TestRepositories
# ---------------------------------------------------------------------------

class TestRepositories(unittest.TestCase):

    def test_required_missing_installs_repository(self):
        desired = _make_resolved(repositories=[
            Repository(addon_id="repository.eengert", required=True),
        ])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)
        self.assertIn(INSTALL_REPOSITORY, kinds)
        a = next(a for a in plan.actions if a.kind == INSTALL_REPOSITORY)
        self.assertEqual(a.addon_id, "repository.eengert")
        self.assertEqual(a.desired_state, "installed")
        self.assertEqual(a.current_state, "missing")

    def test_required_installed_no_action(self):
        desired = _make_resolved(repositories=[
            Repository(addon_id="repository.eengert", required=True),
        ])
        actual = _make_state(addons=[_addon("repository.eengert", True)])
        plan = plan_changes(desired, actual)
        self.assertNotIn(INSTALL_REPOSITORY, _action_kinds(plan))

    def test_optional_missing_no_action(self):
        """required=False repositories are not planned."""
        desired = _make_resolved(repositories=[
            Repository(addon_id="repository.optional", required=False),
        ])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertNotIn(INSTALL_REPOSITORY, _action_kinds(plan))

    def test_bootstrap_url_in_reason(self):
        desired = _make_resolved(repositories=[
            Repository(
                addon_id="repository.eengert",
                bootstrap_url="https://example.com/repo.zip",
                required=True,
            ),
        ])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        a = next(a for a in plan.actions if a.kind == INSTALL_REPOSITORY)
        self.assertIn("https://example.com/repo.zip", a.reason)

    def test_no_bootstrap_url_still_plans(self):
        desired = _make_resolved(repositories=[
            Repository(addon_id="repository.eengert", required=True),
        ])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertIn(INSTALL_REPOSITORY, _action_kinds(plan))

    def test_no_duplicate_install_repository(self):
        """Same required repo appearing once must produce exactly one action."""
        desired = _make_resolved(repositories=[
            Repository(addon_id="repository.eengert", required=True),
        ])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        repo_count = sum(
            1 for a in plan.actions
            if a.kind == INSTALL_REPOSITORY and a.addon_id == "repository.eengert"
        )
        self.assertEqual(repo_count, 1)


# ---------------------------------------------------------------------------
# TestOrdering
# ---------------------------------------------------------------------------

class TestOrdering(unittest.TestCase):

    def test_category_order_repo_install_enable_absent_skin_config(self):
        """Actions must appear in documented category order."""
        config = ConfigDeclarations(packages=("pkg",))
        desired = _make_resolved(
            repositories=[Repository(addon_id="repository.x", required=True)],
            addons=[
                _desired("plugin.absent",  "absent"),
                _desired("plugin.disable", "disabled"),
                _desired("plugin.enable",  "enabled"),
                _desired("plugin.new",     "enabled"),
                _desired("skin.foo",       "enabled"),
            ],
            skin=SkinEntry(addon_id="skin.foo"),
            config=config,
        )
        actual = _make_state(
            addons=[
                _addon("plugin.absent",  True),
                _addon("plugin.disable", True),
                _addon("plugin.enable",  False),
                _addon("skin.foo",       True),
            ],
            active_skin="skin.estuary",
        )
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)

        install_repo_idx = kinds.index(INSTALL_REPOSITORY)
        install_addon_idx = next(i for i, k in enumerate(kinds) if k == INSTALL_ADDON)
        enable_idx = kinds.index(ENABLE_ADDON)
        disable_idx = kinds.index(DISABLE_ADDON)
        absent_idx = kinds.index(ENSURE_ABSENT)
        skin_idx = kinds.index(SET_SKIN)
        config_idx = kinds.index(CONFIGURE)

        self.assertLess(install_repo_idx, install_addon_idx)
        self.assertLess(install_addon_idx, enable_idx)
        self.assertLess(install_addon_idx, disable_idx)
        self.assertLess(enable_idx, absent_idx)
        self.assertLess(disable_idx, absent_idx)
        self.assertLess(absent_idx, skin_idx)
        self.assertLess(skin_idx, config_idx)

    def test_lexical_order_within_install_category(self):
        desired = _make_resolved(addons=[
            _desired("plugin.z", "enabled"),
            _desired("plugin.a", "enabled"),
            _desired("plugin.m", "enabled"),
        ])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        install_ids = [a.addon_id for a in plan.actions if a.kind == INSTALL_ADDON]
        self.assertEqual(install_ids, sorted(install_ids))

    def test_lexical_order_within_enable_disable_category(self):
        desired = _make_resolved(addons=[
            _desired("plugin.z", "enabled"),
            _desired("plugin.a", "enabled"),
            _desired("plugin.m", "disabled"),
        ])
        actual = _make_state(addons=[
            _addon("plugin.z", False),
            _addon("plugin.a", False),
            _addon("plugin.m", True),
        ])
        plan = plan_changes(desired, actual)
        transition_ids = [
            a.addon_id for a in plan.actions
            if a.kind in (ENABLE_ADDON, DISABLE_ADDON)
        ]
        self.assertEqual(transition_ids, sorted(transition_ids))

    def test_lexical_order_within_ensure_absent_category(self):
        desired = _make_resolved(addons=[
            _desired("plugin.z", "absent"),
            _desired("plugin.a", "absent"),
            _desired("plugin.m", "absent"),
        ])
        actual = _make_state(addons=[
            _addon("plugin.z", True),
            _addon("plugin.a", False),
            _addon("plugin.m", True),
        ])
        plan = plan_changes(desired, actual)
        absent_ids = [a.addon_id for a in plan.actions if a.kind == ENSURE_ABSENT]
        self.assertEqual(absent_ids, sorted(absent_ids))

    def test_deterministic_across_different_manifest_list_order(self):
        """Two ResolvedBuilds with same logical state but different list order
        must produce identical Plans."""
        def make_desired_order_a() -> ResolvedBuild:
            return _make_resolved(addons=[
                _desired("plugin.c", "enabled"),
                _desired("plugin.a", "enabled"),
                _desired("plugin.b", "enabled"),
            ])

        def make_desired_order_b() -> ResolvedBuild:
            return _make_resolved(addons=[
                _desired("plugin.a", "enabled"),
                _desired("plugin.b", "enabled"),
                _desired("plugin.c", "enabled"),
            ])

        actual = _make_state()
        plan_a = plan_changes(make_desired_order_a(), actual)
        plan_b = plan_changes(make_desired_order_b(), actual)
        self.assertEqual(plan_a.actions, plan_b.actions)

    def test_deterministic_across_different_actual_order(self):
        """KodiState with same add-ons in different tuple order → identical Plan."""
        desired = _make_resolved(addons=[
            _desired("plugin.a", "disabled"),
            _desired("plugin.b", "enabled"),
            _desired("plugin.c", "enabled"),
        ])
        # actual1: addons in one order
        actual1 = _make_state(addons=[
            _addon("plugin.c", False),
            _addon("plugin.a", True),
            _addon("plugin.b", False),
        ])
        # actual2: same add-ons in different order
        actual2 = _make_state(addons=[
            _addon("plugin.a", True),
            _addon("plugin.b", False),
            _addon("plugin.c", False),
        ])
        plan1 = plan_changes(desired, actual1)
        plan2 = plan_changes(desired, actual2)
        self.assertEqual(plan1.actions, plan2.actions)


# ---------------------------------------------------------------------------
# TestNoop
# ---------------------------------------------------------------------------

class TestNoop(unittest.TestCase):

    def test_empty_desired_empty_actual_noop(self):
        desired = _make_resolved()
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)
        self.assertEqual(plan.action_count, 0)

    def test_all_desired_satisfied_noop(self):
        desired = _make_resolved(
            addons=[
                _desired("plugin.foo", "enabled"),
                _desired("plugin.bar", "disabled"),
            ],
            repositories=[Repository(addon_id="repository.x", required=True)],
        )
        actual = _make_state(addons=[
            _addon("plugin.foo", True),
            _addon("plugin.bar", False),
            _addon("repository.x", True),
        ])
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)

    def test_noop_with_skin_already_active(self):
        desired = _make_resolved(
            skin=SkinEntry(addon_id="skin.estuary"),
            addons=[_desired("skin.estuary", "enabled")],
        )
        actual = _make_state(
            active_skin="skin.estuary",
            addons=[_addon("skin.estuary", True)],
        )
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)

    def test_is_noop_property(self):
        desired = _make_resolved()
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertTrue(plan.is_noop)
        self.assertIsInstance(plan.is_noop, bool)

    def test_action_count_zero_when_noop(self):
        desired = _make_resolved()
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertEqual(plan.action_count, 0)

    def test_action_count_nonzero_when_changes_needed(self):
        desired = _make_resolved(addons=[_desired("plugin.new", "enabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertFalse(plan.is_noop)
        self.assertGreater(plan.action_count, 0)


# ---------------------------------------------------------------------------
# TestPlanType
# ---------------------------------------------------------------------------

class TestPlanType(unittest.TestCase):

    def test_plan_is_frozen(self):
        desired = _make_resolved()
        actual = _make_state()
        plan = plan_changes(desired, actual)
        with self.assertRaises(Exception):
            plan.actions = ()  # type: ignore[misc]

    def test_plan_action_is_frozen(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "enabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        a = plan.actions[0]
        with self.assertRaises(Exception):
            a.kind = "MUTATED"  # type: ignore[misc]

    def test_plan_actions_is_tuple(self):
        desired = _make_resolved()
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertIsInstance(plan.actions, tuple)

    def test_plan_action_fields_present(self):
        desired = _make_resolved(addons=[_desired("plugin.foo", "enabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        a = plan.actions[0]
        self.assertTrue(hasattr(a, "kind"))
        self.assertTrue(hasattr(a, "addon_id"))
        self.assertTrue(hasattr(a, "desired_state"))
        self.assertTrue(hasattr(a, "current_state"))
        self.assertTrue(hasattr(a, "reason"))


# ---------------------------------------------------------------------------
# TestDuplicateActualAddonIds
# ---------------------------------------------------------------------------

class TestDuplicateActualAddonIds(unittest.TestCase):

    def test_duplicate_actual_addon_id_raises_planning_error(self):
        """Manually constructed KodiState with duplicate addon_ids must fail clearly."""
        actual = KodiState(
            platform="macos",
            kodi_version="21.1",
            active_skin="skin.estuary",
            addons=(
                InstalledAddon(addon_id="plugin.foo", enabled=True, version="1.0"),
                InstalledAddon(addon_id="plugin.foo", enabled=False, version="2.0"),
            ),
        )
        desired = _make_resolved()
        with self.assertRaises(PlanningError) as ctx:
            plan_changes(desired, actual)
        self.assertIn("plugin.foo", str(ctx.exception))

    def test_no_duplicate_emitted_for_same_target(self):
        """No duplicate INSTALL_ADDON for same addon_id via two paths."""
        # Skin appears in both desired addons AND as desired skin:
        # only one INSTALL should appear.
        desired = _make_resolved(
            addons=[_desired("skin.arctic.fuse.3", "enabled")],
            skin=SkinEntry(addon_id="skin.arctic.fuse.3"),
        )
        actual = _make_state(active_skin="skin.estuary")
        plan = plan_changes(desired, actual)
        install_count = sum(
            1 for a in plan.actions
            if a.kind == INSTALL_ADDON and a.addon_id == "skin.arctic.fuse.3"
        )
        self.assertEqual(install_count, 1)


# ---------------------------------------------------------------------------
# TestIntegration
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """Integration tests using the example manifest and resolve_manifest()."""

    def setUp(self):
        examples_dir = os.path.join(REPO_ROOT, "resources", "builds", "examples")
        self.eric_manifest_path = os.path.join(examples_dir, "eric-main.example.json")

    def test_shield_fully_satisfied(self):
        """Shield with all desired addons already installed → no-op except config."""
        manifest = load_manifest_file(self.eric_manifest_path)
        desired = resolve_manifest(manifest, "shield")

        # Build an actual state that satisfies all desired addons for shield.
        # Shield resolves: base addons + android overlay + shield-extras
        # expected addons (from example manifest):
        # skin.arctic.fuse.3 enabled (base)
        # plugin.video.redlight enabled (base)
        # plugin.video.themoviedb.helper enabled (base)
        # plugin.video.pov disabled (android overrides base enabled→disabled)
        # plugin.video.umbrella enabled (base)
        # script.module.myaccounts enabled (base)
        # plugin.video.example.android-helper enabled (shield-extras optional)
        actual = _make_state(
            addons=[
                _addon("skin.arctic.fuse.3",                True,  "3.0.0"),
                _addon("plugin.video.redlight",              True,  "1.0.0"),
                _addon("plugin.video.themoviedb.helper",     True,  "1.0.0"),
                _addon("plugin.video.pov",                   False, "1.0.0"),
                _addon("plugin.video.umbrella",              True,  "1.0.0"),
                _addon("script.module.myaccounts",           True,  "1.0.0"),
                _addon("plugin.video.example.android-helper", True, "1.0.0"),
                _addon("repository.eengert",                 True,  "1.0.0"),
            ],
            active_skin="skin.arctic.fuse.3",
        )
        plan = plan_changes(desired, actual)
        # Config is non-None so CONFIGURE action expected; all else should be noop
        non_config = [a for a in plan.actions if a.kind != CONFIGURE]
        self.assertEqual(non_config, [], msg=f"Unexpected non-config actions: {non_config}")
        self.assertIn(CONFIGURE, _action_kinds(plan))

    def test_fresh_install_for_bonus_room(self):
        """Fresh Kodi (no addons, default estuary skin) → full install plan."""
        manifest = load_manifest_file(self.eric_manifest_path)
        desired = resolve_manifest(manifest, "bonus-room")
        # bonus-room extends tvos; themoviedb.helper is disabled; no optional groups
        actual = _make_state(active_skin="skin.estuary")
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)

        # Required repo must be installed
        self.assertIn(INSTALL_REPOSITORY, kinds)

        # Enabled addons must be installed
        # (skin.arctic.fuse.3, plugin.video.redlight, plugin.video.pov,
        #  plugin.video.umbrella, script.module.myaccounts)
        install_ids = {a.addon_id for a in plan.actions if a.kind == INSTALL_ADDON}
        self.assertIn("skin.arctic.fuse.3", install_ids)
        self.assertIn("plugin.video.redlight", install_ids)

        # themoviedb.helper is disabled by bonus-room; should have INSTALL (desired=disabled)
        helper_installs = [
            a for a in plan.actions
            if a.kind == INSTALL_ADDON
            and a.addon_id == "plugin.video.themoviedb.helper"
        ]
        self.assertEqual(len(helper_installs), 1)
        self.assertEqual(helper_installs[0].desired_state, "disabled")

        # Skin must change from estuary to arctic.fuse.3
        self.assertIn(SET_SKIN, kinds)

        # Config must be planned
        self.assertIn(CONFIGURE, kinds)

    def test_family_room_desired_pov_enabled(self):
        """family-room extends tvos — plugin.video.pov remains enabled (base state)."""
        manifest = load_manifest_file(self.eric_manifest_path)
        desired = resolve_manifest(manifest, "family-room")
        actual = _make_state(addons=[_addon("plugin.video.pov", True)])
        plan = plan_changes(desired, actual)
        # pov should be satisfied (enabled desired, enabled actual)
        pov_actions = [a for a in plan.actions if a.addon_id == "plugin.video.pov"]
        self.assertEqual(pov_actions, [])

    def test_shield_pov_disabled(self):
        """shield extends android — plugin.video.pov must be disabled on shield."""
        manifest = load_manifest_file(self.eric_manifest_path)
        desired = resolve_manifest(manifest, "shield")
        actual = _make_state(addons=[_addon("plugin.video.pov", True)])
        plan = plan_changes(desired, actual)
        pov_disable = [
            a for a in plan.actions
            if a.kind == DISABLE_ADDON and a.addon_id == "plugin.video.pov"
        ]
        self.assertEqual(len(pov_disable), 1)

    def test_plan_is_deterministic(self):
        """Same inputs → same plan on repeated calls."""
        manifest = load_manifest_file(self.eric_manifest_path)
        desired = resolve_manifest(manifest, "shield")
        actual = _make_state(active_skin="skin.estuary")
        plan1 = plan_changes(desired, actual)
        plan2 = plan_changes(desired, actual)
        self.assertEqual(plan1.actions, plan2.actions)


# ---------------------------------------------------------------------------
# TestReasonString
# ---------------------------------------------------------------------------

class TestReasonString(unittest.TestCase):

    def test_all_action_reasons_are_nonempty(self):
        """Every PlanAction must have a non-empty reason string."""
        config = ConfigDeclarations(packages=("pkg",))
        desired = _make_resolved(
            repositories=[Repository(addon_id="repository.x", required=True)],
            addons=[
                _desired("plugin.new",      "enabled"),
                _desired("plugin.disable",  "disabled"),
                _desired("plugin.enable",   "enabled"),
                _desired("plugin.absent",   "absent"),
                _desired("skin.foo",        "enabled"),
            ],
            skin=SkinEntry(addon_id="skin.foo"),
            config=config,
        )
        actual = _make_state(addons=[
            _addon("plugin.disable",  True),
            _addon("plugin.enable",   False),
            _addon("plugin.absent",   True),
            _addon("skin.foo",        True),
        ], active_skin="skin.estuary")
        plan = plan_changes(desired, actual)
        for action in plan.actions:
            self.assertTrue(action.reason, f"Empty reason for {action!r}")


# ---------------------------------------------------------------------------
# TestMultipleAddonTransitions
# ---------------------------------------------------------------------------

class TestMultipleAddonTransitions(unittest.TestCase):
    """Tests with multiple addons needing different transitions."""

    def test_mixed_transitions(self):
        desired = _make_resolved(addons=[
            _desired("plugin.a", "enabled"),   # needs install
            _desired("plugin.b", "enabled"),   # needs enable
            _desired("plugin.c", "disabled"),  # already satisfied
            _desired("plugin.d", "disabled"),  # needs disable
            _desired("plugin.e", "absent"),    # needs removal
            _desired("plugin.f", "absent"),    # already absent
        ])
        actual = _make_state(addons=[
            _addon("plugin.b", False),   # installed, disabled; need enable
            _addon("plugin.c", False),   # installed, disabled; already disabled
            _addon("plugin.d", True),    # installed, enabled; need disable
            _addon("plugin.e", True),    # installed; need removal
        ])
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)

        # plugin.a: missing + desired enabled → INSTALL
        self.assertIn(INSTALL_ADDON, kinds)
        # plugin.b: installed disabled + desired enabled → ENABLE
        self.assertIn(ENABLE_ADDON, kinds)
        # plugin.c: already disabled → nothing
        for a in plan.actions:
            if a.addon_id == "plugin.c":
                self.fail(f"Unexpected action for plugin.c: {a}")
        # plugin.d: installed enabled + desired disabled → DISABLE
        self.assertIn(DISABLE_ADDON, kinds)
        # plugin.e: installed + desired absent → ENSURE_ABSENT
        self.assertIn(ENSURE_ABSENT, kinds)

    def test_install_only_for_missing_not_present(self):
        """INSTALL not emitted for add-ons that are already present."""
        desired = _make_resolved(addons=[
            _desired("plugin.existing", "enabled"),
            _desired("plugin.new",      "enabled"),
        ])
        actual = _make_state(addons=[_addon("plugin.existing", True)])
        plan = plan_changes(desired, actual)
        install_ids = [a.addon_id for a in plan.actions if a.kind == INSTALL_ADDON]
        self.assertNotIn("plugin.existing", install_ids)
        self.assertIn("plugin.new", install_ids)

    def test_no_enable_for_addon_being_installed(self):
        """An add-on being installed must not also get an ENABLE action."""
        desired = _make_resolved(addons=[_desired("plugin.new", "enabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        install_ids = {a.addon_id for a in plan.actions if a.kind == INSTALL_ADDON}
        enable_ids  = {a.addon_id for a in plan.actions if a.kind == ENABLE_ADDON}
        overlap = install_ids & enable_ids
        self.assertEqual(overlap, set(), f"Add-on(s) have both INSTALL and ENABLE: {overlap}")


# ---------------------------------------------------------------------------
# TestPlanningError
# ---------------------------------------------------------------------------

class TestPlanningError(unittest.TestCase):

    def test_planning_error_is_exception(self):
        self.assertTrue(issubclass(PlanningError, Exception))

    def test_duplicate_addon_ids_in_kodi_state(self):
        state = KodiState(
            platform="macos", kodi_version="21.1", active_skin="",
            addons=(
                InstalledAddon(addon_id="dupe", enabled=True,  version=""),
                InstalledAddon(addon_id="dupe", enabled=False, version=""),
            ),
        )
        with self.assertRaises(PlanningError):
            plan_changes(_make_resolved(), state)

    def test_error_message_contains_addon_id(self):
        state = KodiState(
            platform="macos", kodi_version="21.1", active_skin="",
            addons=(
                InstalledAddon(addon_id="conflict.addon", enabled=True,  version=""),
                InstalledAddon(addon_id="conflict.addon", enabled=False, version=""),
            ),
        )
        with self.assertRaises(PlanningError) as ctx:
            plan_changes(_make_resolved(), state)
        self.assertIn("conflict.addon", str(ctx.exception))


# ---------------------------------------------------------------------------
# TestActionKindConstants
# ---------------------------------------------------------------------------

class TestActionKindConstants(unittest.TestCase):
    """Verify action kind constants are importable strings."""

    def test_all_kinds_are_strings(self):
        from resources.lib.planner import (
            CONFIGURE, DISABLE_ADDON, ENABLE_ADDON, ENSURE_ABSENT,
            INSTALL_ADDON, INSTALL_REPOSITORY, SET_SKIN,
        )
        for kind in (CONFIGURE, DISABLE_ADDON, ENABLE_ADDON, ENSURE_ABSENT,
                     INSTALL_ADDON, INSTALL_REPOSITORY, SET_SKIN):
            self.assertIsInstance(kind, str)
            self.assertTrue(kind)

    def test_all_kinds_are_distinct(self):
        from resources.lib.planner import (
            CONFIGURE, DISABLE_ADDON, ENABLE_ADDON, ENSURE_ABSENT,
            INSTALL_ADDON, INSTALL_REPOSITORY, SET_SKIN,
        )
        kinds = [CONFIGURE, DISABLE_ADDON, ENABLE_ADDON, ENSURE_ABSENT,
                 INSTALL_ADDON, INSTALL_REPOSITORY, SET_SKIN]
        self.assertEqual(len(kinds), len(set(kinds)))


# ---------------------------------------------------------------------------
# TestBM006Regression
# ---------------------------------------------------------------------------

class TestBM006Regression(unittest.TestCase):
    """Regression checks for known semantic rules."""

    def test_absent_not_emitted_for_unmanaged_addon(self):
        """add-on in actual but not in desired.addons must never become ENSURE_ABSENT."""
        desired = _make_resolved(addons=[_desired("plugin.managed", "enabled")])
        actual = _make_state(addons=[
            _addon("plugin.managed",   True),
            _addon("plugin.unmanaged", True),
        ])
        plan = plan_changes(desired, actual)
        absent_ids = [a.addon_id for a in plan.actions if a.kind == ENSURE_ABSENT]
        self.assertNotIn("plugin.unmanaged", absent_ids)

    def test_install_for_enabled_not_disable_for_missing(self):
        """desired=enabled + missing → INSTALL only, never DISABLE."""
        desired = _make_resolved(addons=[_desired("plugin.foo", "enabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertNotIn(DISABLE_ADDON, _action_kinds(plan))

    def test_install_for_disabled_not_enable_for_missing(self):
        """desired=disabled + missing → INSTALL only, never ENABLE."""
        desired = _make_resolved(addons=[_desired("plugin.foo", "disabled")])
        actual = _make_state()
        plan = plan_changes(desired, actual)
        self.assertNotIn(ENABLE_ADDON, _action_kinds(plan))

    def test_skin_install_prerequisite_before_set_skin(self):
        """If skin needs installation, INSTALL_ADDON must come before SET_SKIN."""
        desired = _make_resolved(skin=SkinEntry(addon_id="skin.new"))
        actual = _make_state(active_skin="skin.estuary")
        plan = plan_changes(desired, actual)
        kinds = _action_kinds(plan)
        install_idx = kinds.index(INSTALL_ADDON)
        skin_idx = kinds.index(SET_SKIN)
        self.assertLess(install_idx, skin_idx)

    def test_plan_changes_does_not_mutate_inputs(self):
        """plan_changes() must not alter the desired or actual inputs."""
        desired = _make_resolved(addons=[_desired("plugin.foo", "enabled")])
        actual = _make_state()
        original_addons = desired.addons
        original_actual_addons = actual.addons
        plan_changes(desired, actual)
        self.assertEqual(desired.addons, original_addons)
        self.assertEqual(actual.addons, original_actual_addons)


if __name__ == "__main__":
    unittest.main()
