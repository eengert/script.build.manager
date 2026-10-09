"""BM-UI-002C: truthful, read-only frozen-build plan, review identity and stale-plan checks (G3)."""

import ast
import contextlib
import io
import json
import os
import shutil
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from resources.lib import addons, artifacts, frozen_install
from resources.lib.artifacts import ArtifactStore
from resources.lib.frozen import (
    AddonCaptureNode, CaptureStatus, DependencyEdge, FrozenBuildManifest, ProvenanceStatus,
)
from resources.lib.frozen_install import FrozenInstalledAddon, FrozenInstallPhase
from resources.lib.frozen_resolution import (
    InstallResolution, InstallResolutionRecord, ResolutionState,
)
from resources.lib.manifest import (
    AddonEntry, BuildInfo, FrozenInstallPolicy, FrozenInstallPolicyMode,
)
from resources.lib.plan import (
    BuildPlanService, PlanOwners, PlanTarget, ReadOnlyArtifactStore,
)
from resources.lib.plan_model import (
    BlockerCode, BuildPlan, DecisionChoice, IdentityComponent, PlanBlocker, PlanState,
    PrivatePlan, PrivatePlanKind, RestartExpectation, RestartPlan, ReviewCheck,
    ReviewFreshness, ReviewIdentity, SettingsPlan, SettingsPlanKind, SkinPlan, SkinPlanKind,
    SoftwareAction, SoftwareRow,
)
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID
from resources.lib.status_model import CheckGap
from tests.test_status import (
    BUILD_ID, DB_SECRET, DEMO, MODULE, NOW, SECRET, SKIN, Harness, snapshot_tree,
)

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "repository.demo"
EXTRA = "plugin.video.extra"
LATE_DEPENDENCY = "script.module.z-late"
SKIN_TYPE = "xbmc.gui.skin"
REPO_TYPE = "xbmc.addon.repository"
PLUGIN_TYPE = "xbmc.python.pluginsource"


def make_zip(addon_id, version, *, repository=False):
    extension = (
        '<extension point="xbmc.addon.repository">'
        '<dir><info>http://127.0.0.1/addons.xml</info>'
        '<datadir zip="true">http://127.0.0.1/</datadir></dir></extension>'
        if repository else '<extension point="xbmc.python.pluginsource" library="default.py"/>')
    xml = ('<addon id="%s" name="%s" version="%s"><requires/>%s</addon>'
           % (addon_id, addon_id, version, extension))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("%s/addon.xml" % addon_id, xml)
        archive.writestr("%s/default.py" % addon_id, b"# fixture\n")
    return output.getvalue()


# Owners the plan must never reach, beyond everything Build Status already forbids.
PLAN_MUTATORS = (
    (frozen_install.KodiRuntimeFrozenArtifactBackend,
     ("install_exact", "set_addon_enabled", "resolve_repository_current")),
    (frozen_install.InMemoryFrozenArtifactBackend,
     ("install_exact", "set_addon_enabled", "resolve_repository_current")),
    (artifacts.ArtifactStore, ("__init__", "import_zip", "_publish_metadata")),
    (addons.KodiRuntimeAddonBackend, ("fetch_current_from_repository",)),
)


class PlanHarness(Harness):
    """The G2 harness plus a saved-package store and a complete saved software graph."""

    def __init__(self, test, *, with_private=True, with_resource=True):
        super().__init__(test, with_private=with_private, with_resource=with_resource,
                         with_frozen=True)
        self.store_root = self.profile / "addon_data" / "script.build.manager" / "frozen-artifacts"
        self.desired = replace(self.desired, frozen_install_policies=())
        self.broken = set()
        self.node_specs = {}
        self.zips = {}
        self.kodi.addons[REPOSITORY] = ("1.0.0", True)
        self.deps.installed[REPOSITORY] = ("1.0.0", True)
        self.set_graph()

    # -- saved software ------------------------------------------------------------------
    def set_graph(self, *, extra=(), without=(), policies=None, disabled=(), store=True, platform=()):
        """(Re)build the frozen graph and the saved packages it points at."""
        specs = {
            DEMO: ("1.0.0", PLUGIN_TYPE, (MODULE,)),
            MODULE: ("2.0.0", PLUGIN_TYPE, ()),
            SKIN: ("1.0.0", SKIN_TYPE, ()),
            REDLIGHT_ADDON_ID: ("2.6.8", PLUGIN_TYPE, ()),
            REPOSITORY: ("1.0.0", REPO_TYPE, ()),
        }
        for addon_id, version, kind, requires in extra:
            specs[addon_id] = (version, kind, requires)
        for addon_id in without:
            specs.pop(addon_id, None)
        writer = ArtifactStore(self.store_root) if store else None
        nodes = []
        for addon_id, (version, kind, requires) in sorted(specs.items()):
            artifact = None
            if writer is not None:
                data = make_zip(addon_id, version, repository=kind == REPO_TYPE)
                artifact = writer.import_zip(data, expected_addon_id=addon_id,
                                             expected_version=version)
                self.zips[addon_id] = artifact
            nodes.append(AddonCaptureNode(
                addon_id, version, kind, addon_id not in disabled,
                ProvenanceStatus.VERIFIED_REPOSITORY, artifact=artifact,
                dependency_edges=tuple(DependencyEdge(r) for r in requires)))
        nodes.append(AddonCaptureNode("xbmc.python", "3.0.1", "", True,
                                      ProvenanceStatus.VERIFIED_REPOSITORY, system=True))
        nodes.append(AddonCaptureNode("script.module.optional", "", "", False,
                                      ProvenanceStatus.UNKNOWN, optional=True,
                                      status=CaptureStatus.MISSING))
        for addon_id, version, kind, requires in platform:
            nodes.append(AddonCaptureNode(
                addon_id, version, kind, True, ProvenanceStatus.UNKNOWN,
                dependency_edges=tuple(DependencyEdge(r) for r in requires),
                platform_provided=True, status=CaptureStatus.PLATFORM_PROVIDED))
        self.frozen = FrozenBuildManifest(
            schema_version=2 if platform else 1, build_id=BUILD_ID, name="Plan fixture",
            created_at="2026-10-06T00:00:00Z", kodi_version="21.0", platform="macos",
            capture_status=CaptureStatus.COMPLETE, addons=tuple(nodes))
        if policies is not None:
            self.desired = replace(self.desired, frozen_install_policies=tuple(policies))

    def kodi_state(self):
        from resources.lib.inspector import KodiStateInspector
        return KodiStateInspector(self.kodi).inspect()

    def forget_package(self, addon_id):
        artifact = self.zips[addon_id]
        (self.store_root / "artifacts" / ("%s.zip" % artifact.sha256)).unlink()

    def policy(self, addon_id, mode, repository=REPOSITORY):
        return FrozenInstallPolicy(addon_id, mode, repository if mode is not
                                   FrozenInstallPolicyMode.EXACT_REQUIRED else "")

    # -- service -----------------------------------------------------------------------------
    def details(self, addon_id):
        if addon_id not in self.kodi.addons:
            return None
        version, enabled = self.kodi.addons[addon_id]
        return FrozenInstalledAddon(addon_id, version, enabled, addon_id in self.broken)

    def plan_owners(self, **overrides):
        values = dict(status=self.owners(), artifact_store=ReadOnlyArtifactStore(self.store_root),
                      addon_details=self.details)
        values.update(overrides)
        return PlanOwners(**values)

    def plan_service(self, **overrides):
        return BuildPlanService(self.plan_owners(**overrides))

    def plan_target(self, **kwargs):
        return PlanTarget("/build.json", "d", "/frozen.json", **kwargs)

    @contextlib.contextmanager
    def instrumented(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(super().instrumented())
            for cls, names in PLAN_MUTATORS:
                for name in names:
                    def tripwire(*a, _label="%s.%s" % (cls.__name__, name), **k):
                        self.touched.append(_label)
                        raise AssertionError("plan called " + _label)
                    stack.enter_context(patch.object(cls, name, tripwire))
            yield

    def assert_untouched(self):
        self.test.assertEqual(self.touched, [])
        self.test.assertEqual(self.config_backend.mutations, [])
        self.test.assertEqual(self.deps.mutations, [])
        self.test.assertEqual(self.deps.repository_reads, [])

    def plan(self, target=None, **kwargs):
        target = self.plan_target(**kwargs) if target is None else target
        with self.instrumented():
            plan = self.plan_service().preview(target)
        self.assert_untouched()
        return plan

    def validate(self, target, review):
        with self.instrumented():
            check = self.plan_service().validate(target, review)
        self.assert_untouched()
        return check


class PlanBase(unittest.TestCase):
    def current(self, **kwargs):
        harness = PlanHarness(self, **kwargs)
        harness.save_overlay()
        return harness

    def row(self, plan, addon_id):
        return {r.addon_id: r for r in plan.software}[addon_id]

    def actions(self, plan):
        return {r.addon_id: r.action for r in plan.software}

    def codes(self, plan):
        return {(b.code, b.addon_id) for b in plan.blockers}

    def assertSecretFree(self, *values):
        for value in values:
            for secret in (SECRET, DB_SECRET, "SENTINEL_BACKEND_ERROR_TEXT"):
                self.assertNotIn(secret, str(value))
                self.assertNotIn(secret, repr(value))

    def ready_plan(self, h, **kwargs):
        """A reviewed plan with real work to do: the add-on MODULE is missing."""
        del h.kodi.addons[MODULE]
        h.deps.installed.pop(MODULE, None)
        target = h.plan_target(**kwargs)
        plan = h.plan(target)
        self.assertEqual(plan.state, PlanState.CHANGES_READY, plan.to_safe_dict())
        self.assertIsNotNone(plan.review)
        return target, plan


# -- what would change -----------------------------------------------------------------------

class PlanContent(PlanBase):
    def test_10_no_drift_is_no_changes(self):
        plan = self.current().plan()
        self.assertEqual(plan.state, PlanState.NO_CHANGES, plan.to_safe_dict())
        self.assertEqual(set(self.actions(plan).values()), {SoftwareAction.CURRENT})
        self.assertEqual(plan.skin.kind, SkinPlanKind.CURRENT)
        self.assertEqual(plan.settings.kind, SettingsPlanKind.CURRENT)
        self.assertEqual(plan.private.kind, PrivatePlanKind.CURRENT)
        self.assertEqual(plan.restart.expectation, RestartExpectation.NOT_EXPECTED)
        self.assertEqual((plan.blockers, plan.gaps), ((), ()))
        self.assertIsNone(plan.review)
        self.assertFalse(plan.can_proceed)

    def test_11_missing_managed_addon_is_an_install_action(self):
        h = self.current()
        target, plan = self.ready_plan(h)
        row = self.row(plan, MODULE)
        self.assertEqual((row.action, row.version), (SoftwareAction.INSTALL_EXACT, "2.0.0"))
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        self.assertTrue(plan.can_proceed)
        others = {a for i, a in self.actions(plan).items() if i != MODULE}
        self.assertEqual(others, {SoftwareAction.CURRENT})

    def test_12_wrong_enabled_state_is_an_enable_or_disable_action(self):
        h = self.current()
        h.kodi.addons[MODULE] = ("2.0.0", False)
        h.set_graph(disabled=(DEMO,))
        h.save_overlay()
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        self.assertEqual(self.row(plan, MODULE).action, SoftwareAction.ENABLE)
        self.assertEqual(self.row(plan, DEMO).action, SoftwareAction.DISABLE)

    def test_13_wrong_installed_exact_version_is_blocked_under_current_capability(self):
        h = self.current()
        h.kodi.addons[MODULE] = ("2.0.1", True)
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.row(plan, MODULE).action, SoftwareAction.DIFFERENT_VERSION)
        self.assertEqual(self.codes(plan), {(BlockerCode.DIFFERENT_VERSION_INSTALLED, MODULE)})
        self.assertIsNone(plan.review)
        self.assertFalse(plan.can_proceed)

    def test_13b_broken_installed_addon_is_blocked(self):
        h = self.current()
        h.broken.add(MODULE)
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.row(plan, MODULE).action, SoftwareAction.BROKEN)
        self.assertEqual(self.codes(plan), {(BlockerCode.INSTALLED_ADDON_BROKEN, MODULE)})

    def test_13c_a_blocked_plan_never_carries_a_review(self):
        h = self.current()
        del h.kodi.addons[REDLIGHT_ADDON_ID]                 # work to do ...
        h.kodi.addons[MODULE] = ("2.0.1", True)               # ... and a blocker
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertIsNone(plan.review)
        self.assertFalse(plan.can_proceed)

    def test_14_managed_skin_drift_is_a_skin_action(self):
        h = self.current()
        h.kodi.skin = "skin.other"
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        self.assertEqual((plan.skin.kind, plan.skin.skin_id, plan.skin.current_skin_id),
                         (SkinPlanKind.SWITCH, SKIN, "skin.other"))

    def test_14b_an_unnamed_active_skin_is_not_a_proven_switch(self):
        h = self.current()
        h.kodi.skin = ""
        plan = h.plan()
        self.assertEqual(plan.skin.kind, SkinPlanKind.UNAVAILABLE)
        self.assertEqual(plan.state, PlanState.INCOMPLETE)
        self.assertEqual(plan.gaps, ())          # the skin line says it; this is not an unreadable add-on list

    def test_15_configuration_drift_is_a_count_only(self):
        h = self.current()
        h.config_backend.settings[(DEMO, "quality")] = "SENTINEL_LOW"
        h.config_backend.files["userdata/keymaps/demo.xml"] = b"<other/>"
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        self.assertEqual((plan.settings.kind, plan.settings.changing), (SettingsPlanKind.CHANGES, 2))
        self.assertNotIn("SENTINEL_LOW", repr(plan) + json.dumps(plan.to_safe_dict()))

    def test_16_private_drift_is_status_only(self):
        h = self.current()
        h.save_overlay(value=SECRET + "-changed")
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        self.assertEqual(plan.private.kind, PrivatePlanKind.CHANGES_NEEDED)
        self.assertSecretFree(plan, json.dumps(plan.to_safe_dict()), "\n".join(h.logs))
        self.assertNotIn(SECRET + "-changed", repr(plan) + "\n".join(h.logs))

    def test_17_private_unavailable_is_never_ready(self):
        h = self.current()
        h.config_backend.unreadable.add((DEMO, "api_token"))
        plan = h.plan()
        self.assertEqual(plan.private.kind, PrivatePlanKind.UNAVAILABLE)
        self.assertEqual(plan.state, PlanState.INCOMPLETE)
        self.assertIn(CheckGap.PRIVATE_UNAVAILABLE, plan.gaps)
        self.assertIsNone(plan.review)

    def test_17b_required_private_data_that_is_absent_blocks(self):
        h = self.current()
        h.overlay_store.path_for("status-overlay").unlink()
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertIn((BlockerCode.PRIVATE_DATA_MISSING, ""), self.codes(plan))

    def test_22_unmanaged_addons_never_generate_removal_actions(self):
        h = self.current()
        del h.kodi.addons[MODULE]
        plan = h.plan()
        ids = {r.addon_id for r in plan.software}
        self.assertFalse(ids & {"plugin.video.unmanaged", "script.module.other"})
        self.assertFalse({a.value for a in SoftwareAction} & {"remove", "uninstall", "delete"})
        for action in SoftwareAction:
            self.assertNotIn("remov", action.value)
            self.assertNotIn("uninstall", action.value)
        h.kodi.addons["plugin.video.unmanaged"] = ("9.9", True)
        h.kodi.addons["plugin.video.brand.new"] = ("1.0", False)
        again = h.plan()
        self.assertEqual(again.software, plan.software)

    def test_23_restart_implication_is_shown_truthfully(self):
        h = self.current()
        _target, plan = self.ready_plan(h)               # pre-activation resource: held add-ons restart
        self.assertEqual(plan.restart.expectation, RestartExpectation.EXPECTED)
        self.assertEqual(self.current().plan().restart.expectation, RestartExpectation.NOT_EXPECTED)
        h = self.current(with_resource=False)
        _target, plan = self.ready_plan(h)
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        self.assertEqual(plan.restart.expectation, RestartExpectation.NOT_EXPECTED)

    def test_a_fresh_device_gets_a_ready_plan_not_an_unavailable_one(self):
        h = self.current()
        for addon_id in (DEMO, MODULE, SKIN, REDLIGHT_ADDON_ID, REPOSITORY):
            del h.kodi.addons[addon_id]
            h.deps.installed.pop(addon_id, None)
        h.kodi.skin = "skin.estuary"
        h.config_backend.unreadable.update({(DEMO, "quality"), (DEMO, "api_token"),
                                            (SKIN, "Menu.Style")})
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.CHANGES_READY, plan.to_safe_dict())
        self.assertEqual({a for a in self.actions(plan).values()}, {SoftwareAction.INSTALL_EXACT})
        self.assertEqual(plan.settings.kind, SettingsPlanKind.CHANGES)
        self.assertEqual(plan.private.kind, PrivatePlanKind.CHANGES_NEEDED)
        self.assertEqual(plan.skin.kind, SkinPlanKind.SWITCH)
        self.assertEqual(plan.restart.expectation, RestartExpectation.EXPECTED)

    def test_rows_follow_the_installers_dependency_order(self):
        h = self.current()
        for addon_id in (DEMO, MODULE):
            del h.kodi.addons[addon_id]
        order = [r.addon_id for r in h.plan().software]
        self.assertLess(order.index(MODULE), order.index(DEMO))     # a dependency precedes its dependent
        self.assertEqual(order, [r.addon_id for r in h.plan().software])


# -- missing saved packages: decisions, choices, and what is blocked --------------------------

class Decisions(PlanBase):
    FALLBACK = FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY
    SKIPPABLE = FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP

    def missing_module(self, mode=None, **kwargs):
        """MODULE is neither installed nor saved; ``mode`` is the policy that governs it."""
        h = PlanHarness(self, **kwargs)
        h.set_graph(policies=[h.policy(MODULE, mode)] if mode else None)
        del h.kodi.addons[MODULE]
        h.deps.installed.pop(MODULE, None)
        h.forget_package(MODULE)
        h.save_overlay()
        return h

    def skippable_extra(self, **kwargs):
        """EXTRA is saved by the build, not installed, and its package is gone."""
        h = PlanHarness(self, **kwargs)
        h.set_graph(extra=[(EXTRA, "1.0.0", PLUGIN_TYPE, ())],
                    policies=[h.policy(EXTRA, self.SKIPPABLE)])
        h.forget_package(EXTRA)
        h.save_overlay()
        return h

    def test_18_missing_exact_package_with_no_recovery_is_blocked(self):
        h = self.missing_module(None)
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.row(plan, MODULE).action, SoftwareAction.PACKAGE_MISSING)
        self.assertEqual(self.codes(plan), {(BlockerCode.PACKAGE_MISSING, MODULE)})
        self.assertEqual(plan.decisions, ())

    def test_18b_an_installed_addon_whose_package_is_gone_cannot_be_recovered(self):
        h = self.current()
        h.set_graph(policies=[h.policy(MODULE, self.SKIPPABLE)])
        h.forget_package(MODULE)
        h.save_overlay()
        plan = h.plan()        # installed: Build Manager can neither skip it nor fetch a replacement
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.codes(plan), {(BlockerCode.PACKAGE_MISSING, MODULE)})

    def test_19_permitted_repository_fallback_needs_a_decision_until_chosen(self):
        h = self.missing_module(self.FALLBACK, with_resource=False)
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.DECISION_REQUIRED, plan.to_safe_dict())
        row = self.row(plan, MODULE)
        self.assertEqual(row.action, SoftwareAction.DECISION)
        self.assertEqual(row.choices, (DecisionChoice.INSTALL_CURRENT, DecisionChoice.CANCEL))
        self.assertIsNone(plan.review)
        chosen = h.plan(h.plan_target().with_choice(MODULE, DecisionChoice.INSTALL_CURRENT))
        self.assertEqual(chosen.state, PlanState.RESOLUTION_REQUIRED)
        self.assertEqual(self.row(chosen, MODULE).action, SoftwareAction.INSTALL_REPOSITORY)
        self.assertEqual(self.row(chosen, MODULE).version, "")      # only known after the download
        self.assertIsNone(chosen.review)

    def test_20_permitted_skip_needs_a_decision_until_chosen(self):
        h = self.skippable_extra(with_resource=False)
        del h.kodi.addons[MODULE]                                    # keeps real work in the plan
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.DECISION_REQUIRED)
        self.assertEqual(self.row(plan, EXTRA).choices, (
            DecisionChoice.INSTALL_CURRENT, DecisionChoice.SKIP, DecisionChoice.CANCEL))
        chosen = h.plan(h.plan_target().with_choice(EXTRA, DecisionChoice.SKIP))
        self.assertEqual(chosen.state, PlanState.CHANGES_READY)
        self.assertEqual(self.row(chosen, EXTRA).action, SoftwareAction.ACCEPTED_SKIP)
        self.assertEqual(self.row(chosen, MODULE).action, SoftwareAction.INSTALL_EXACT)

    def test_a_skip_alone_is_an_accepted_no_op(self):
        h = self.skippable_extra(with_resource=False)
        chosen = h.plan(h.plan_target().with_choice(EXTRA, DecisionChoice.SKIP))
        self.assertEqual(chosen.state, PlanState.NO_CHANGES)

    def test_21_chosen_resolution_is_part_of_plan_identity(self):
        h = self.skippable_extra(with_resource=False)
        del h.kodi.addons[MODULE]
        skip = h.plan(h.plan_target().with_choice(EXTRA, DecisionChoice.SKIP))
        # The same state with the other choice is a different plan with a different identity.
        fetch = h.plan(h.plan_target().with_choice(EXTRA, DecisionChoice.INSTALL_CURRENT))
        self.assertEqual(skip.state, PlanState.CHANGES_READY)
        self.assertEqual(fetch.state, PlanState.RESOLUTION_REQUIRED)
        self.assertIsNone(fetch.review)
        check = h.validate(h.plan_target().with_choice(EXTRA, DecisionChoice.INSTALL_CURRENT), skip.review)
        self.assertEqual(check.freshness, ReviewFreshness.STALE)
        self.assertIn(IdentityComponent.POLICY, check.changed)
        self.assertEqual(skip.review, h.plan(h.plan_target().with_choice(
            EXTRA, DecisionChoice.SKIP)).review)

    def test_cancelling_blocks_and_never_proceeds(self):
        h = self.missing_module(self.FALLBACK, with_resource=False)
        plan = h.plan(h.plan_target().with_choice(MODULE, DecisionChoice.CANCEL))
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.codes(plan), {(BlockerCode.USER_CANCELLED, MODULE)})
        self.assertIsNone(plan.review)

    def test_a_choice_the_policy_does_not_offer_is_not_honoured(self):
        h = self.missing_module(self.FALLBACK, with_resource=False)
        plan = h.plan(h.plan_target().with_choice(MODULE, DecisionChoice.SKIP))
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.codes(plan), {(BlockerCode.CHOICE_NOT_PERMITTED, MODULE)})

    def test_an_add_on_that_others_require_cannot_be_skipped(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(policies=[h.policy(MODULE, self.SKIPPABLE)])    # DEMO requires MODULE
        del h.kodi.addons[MODULE]
        h.forget_package(MODULE)
        h.save_overlay()
        plan = h.plan()
        self.assertEqual(self.row(plan, MODULE).choices, (
            DecisionChoice.INSTALL_CURRENT, DecisionChoice.CANCEL))

    def test_a_skin_or_resource_owner_cannot_be_skipped(self):
        for addon_id in (SKIN, REDLIGHT_ADDON_ID):
            with self.subTest(addon_id):
                h = PlanHarness(self)
                h.set_graph(policies=[h.policy(addon_id, self.SKIPPABLE)])
                del h.kodi.addons[addon_id]
                h.forget_package(addon_id)
                h.save_overlay()
                plan = h.plan(h.plan_target().with_choice(addon_id, DecisionChoice.SKIP))
                self.assertEqual(plan.state, PlanState.BLOCKED)
                self.assertIn((BlockerCode.CHOICE_CONFLICTS_WITH_BUILD, addon_id), self.codes(plan))

    def test_a_repository_fallback_is_refused_when_pre_activation_resources_need_exact_metadata(self):
        h = PlanHarness(self)                                       # Red Light holds its dependents
        h.set_graph(policies=[h.policy(MODULE, self.FALLBACK)])
        del h.kodi.addons[MODULE]
        h.forget_package(MODULE)
        h.save_overlay()
        plan = h.plan(h.plan_target().with_choice(MODULE, DecisionChoice.INSTALL_CURRENT))
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertIn((BlockerCode.CHOICE_CONFLICTS_WITH_BUILD, MODULE), self.codes(plan))

    def test_a_choice_for_an_installed_add_on_cannot_be_used_to_skip_it(self):
        h = self.skippable_extra(with_resource=False)
        h.kodi.addons[EXTRA] = ("1.0.0", True)
        plan = h.plan(h.plan_target().with_choice(EXTRA, DecisionChoice.SKIP))
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.codes(plan), {(BlockerCode.PACKAGE_MISSING, EXTRA)})


# -- prior accepted resolutions ---------------------------------------------------------------

class PriorResolutions(PlanBase):
    def skipped_extra(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(extra=[(EXTRA, "1.0.0", PLUGIN_TYPE, ())],
                    policies=[h.policy(EXTRA, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP)])
        h.forget_package(EXTRA)
        h.save_overlay()
        record = InstallResolutionRecord(EXTRA, "1.0.0", InstallResolution.SKIPPED,
                                         ResolutionState.SKIPPED)
        return h, h.resolution(record)

    def test_a_recorded_skip_is_accepted_without_a_new_decision(self):
        h, resolution = self.skipped_extra()
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.NO_CHANGES, plan.to_safe_dict())
        self.assertEqual(self.row(plan, EXTRA).action, SoftwareAction.ACCEPTED_SKIP)
        self.assertEqual(h.plan().state, PlanState.DECISION_REQUIRED)    # without it: asks again

    def test_a_recorded_skip_whose_add_on_is_now_present_is_blocked(self):
        h, resolution = self.skipped_extra()
        h.kodi.addons[EXTRA] = ("1.0.0", True)
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.codes(plan), {(BlockerCode.SKIPPED_ADDON_PRESENT, EXTRA)})

    def test_a_recorded_repository_version_is_what_current_means(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(policies=[h.policy(MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY)])
        resolved = ArtifactStore(h.store_root).import_zip(
            make_zip(MODULE, "2.0.1"), expected_addon_id=MODULE, expected_version="2.0.1")
        h.forget_package(MODULE)
        h.save_overlay()
        record = InstallResolutionRecord(
            MODULE, "2.0.0", InstallResolution.REPOSITORY_CURRENT, ResolutionState.INSTALLED,
            repository_id=REPOSITORY, resolved_version="2.0.1",
            artifact_sha256=resolved.sha256, artifact_size=resolved.size)
        resolution = h.resolution(record)
        h.kodi.addons[MODULE] = ("2.0.1", True)
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.NO_CHANGES, plan.to_safe_dict())
        self.assertEqual(self.row(plan, MODULE).version, "2.0.1")
        h.kodi.addons[MODULE] = ("2.0.0", True)
        self.assertEqual(self.row(h.plan(install_resolution=resolution), MODULE).action,
                         SoftwareAction.DIFFERENT_VERSION)
        del h.kodi.addons[MODULE]
        again = h.plan(install_resolution=resolution)
        self.assertEqual((self.row(again, MODULE).action, self.row(again, MODULE).version),
                         (SoftwareAction.INSTALL_EXACT, "2.0.1"))
        (h.store_root / "artifacts" / ("%s.zip" % resolved.sha256)).unlink()
        gone = h.plan(install_resolution=resolution)
        self.assertEqual(self.codes(gone), {(BlockerCode.PACKAGE_MISSING, MODULE)})

    def test_a_resolution_that_does_not_belong_here_leaves_the_plan_unchecked(self):
        h, resolution = self.skipped_extra()
        foreign = replace(resolution, build_id="another-build")
        plan = h.plan(install_resolution=foreign)
        self.assertEqual(plan.state, PlanState.INCOMPLETE)
        self.assertEqual(plan.gaps, (CheckGap.RESOLUTION_IDENTITY_MISMATCH,))
        self.assertEqual(plan.software, ())
        self.assertNotIn("another-build", repr(plan) + "\n".join(h.logs))


# -- inputs that cannot be trusted, and operations already under way ----------------------------

class InputsAndOperations(PlanBase):
    def test_a_frozen_graph_for_another_build_leaves_the_plan_unchecked(self):
        h = self.current()
        h.frozen = replace(h.frozen, build_id="another-build")
        plan = h.plan()
        self.assertEqual((plan.state, plan.gaps), (PlanState.INCOMPLETE, (CheckGap.BUILD_IDENTITY_MISMATCH,)))
        self.assertEqual(plan.software, ())
        self.assertNotIn("another-build", repr(plan) + "\n".join(h.logs))

    def test_unreadable_build_files_leave_the_plan_unchecked(self):
        h = self.current()
        h.resolver_failure = RuntimeError("SENTINEL_BACKEND_ERROR_TEXT " + SECRET)
        plan = h.plan()
        self.assertEqual((plan.state, plan.gaps), (PlanState.INCOMPLETE, (CheckGap.BUILD_UNREADABLE,)))
        self.assertSecretFree(plan, "\n".join(h.logs))

    def test_unavailable_kodi_state_leaves_the_plan_unchecked(self):
        h = self.current()
        h.kodi.get_installed_addons = lambda: (_ for _ in ()).throw(RuntimeError(SECRET))
        plan = h.plan()
        self.assertEqual((plan.state, plan.gaps), (PlanState.INCOMPLETE, (CheckGap.KODI_STATE_UNAVAILABLE,)))
        self.assertSecretFree(plan, "\n".join(h.logs))

    def test_a_pending_restart_or_unfinished_operation_blocks_a_new_plan(self):
        h = self.current()
        h.restart_transaction()
        plan = h.plan()
        self.assertEqual((plan.state, [b.code for b in plan.blockers]),
                         (PlanState.BLOCKED, [BlockerCode.OPERATION_PENDING]))
        h = self.current()
        h.frozen_transaction(FrozenInstallPhase.NEEDS_ATTENTION)
        plan = h.plan()
        self.assertEqual([b.code for b in plan.blockers], [BlockerCode.OPERATION_NEEDS_ATTENTION])
        self.assertIsNone(plan.review)

    def test_a_build_that_lists_nothing_proves_nothing(self):
        h = Harness(self, with_private=False, with_resource=False)
        h.desired = replace(h.desired, addons=(), skin=None, config=None, private_overlay=None,
                            frozen_install_policies=())
        h.frozen = replace(h.frozen, addons=tuple(n for n in h.frozen.addons if n.system))
        owners = PlanOwners(h.owners(), ReadOnlyArtifactStore(h.profile / "none"), lambda i: None)
        plan = BuildPlanService(owners).preview(PlanTarget("/b", "d", "/f"))
        self.assertEqual((plan.state, plan.gaps), (PlanState.INCOMPLETE, (CheckGap.NOTHING_TO_COMPARE,)))

    def test_a_managed_addon_the_build_did_not_save_is_blocked_not_guessed(self):
        h = self.current()
        h.desired = replace(h.desired, addons=h.desired.addons + (AddonEntry("plugin.video.cfg", "enabled"),))
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.codes(plan), {(BlockerCode.ADDON_NOT_IN_SAVED_SOFTWARE, "plugin.video.cfg")})
        self.assertEqual(self.row(plan, "plugin.video.cfg").action, SoftwareAction.NOT_SAVED)

    def test_a_declared_unfrozen_addon_in_the_wrong_state_is_enabled_or_disabled(self):
        h = self.current()
        h.desired = replace(h.desired, addons=h.desired.addons + (AddonEntry("plugin.video.cfg", "disabled"),))
        h.kodi.addons["plugin.video.cfg"] = ("1.0", True)
        plan = h.plan()
        self.assertEqual(self.row(plan, "plugin.video.cfg").action, SoftwareAction.DISABLE)
        from resources.lib.planner import DISABLE_ADDON, plan_changes
        expected = {(a.kind, a.addon_id) for a in plan_changes(h.desired, h.kodi_state()).actions}
        self.assertIn((DISABLE_ADDON, "plugin.video.cfg"), expected)      # the planner agrees


class EdgeCases(PlanBase):
    def test_an_incomplete_frozen_capture_is_not_a_plan_the_installer_would_accept(self):
        h = self.current()
        h.frozen = replace(h.frozen, capture_status=CaptureStatus.INCOMPLETE_PROVENANCE)
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(self.codes(plan), {(BlockerCode.SOFTWARE_PLAN_INVALID, "")})

    def test_an_unreadable_configuration_package_never_yields_a_ready_plan(self):
        h = self.current()

        class Broken:
            def resolve(self, config):
                raise RuntimeError("SENTINEL_BACKEND_ERROR_TEXT " + SECRET)
        plan = h.plan_service(status=h.owners(config_loader=Broken())).preview(h.plan_target())
        self.assertEqual(plan.settings.kind, SettingsPlanKind.UNAVAILABLE)
        self.assertEqual(plan.state, PlanState.INCOMPLETE)
        self.assertIn(CheckGap.CONFIGURATION_UNAVAILABLE, plan.gaps)
        self.assertSecretFree(plan, "\n".join(h.logs))

    def test_a_fallback_repository_that_was_not_saved_cannot_be_trusted(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(without=(REPOSITORY,), policies=[h.policy(
            MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY)])
        h.kodi.addons.pop(MODULE)
        h.forget_package(MODULE)
        h.save_overlay()
        plan = h.plan()
        self.assertEqual(self.codes(plan), {(BlockerCode.PACKAGE_MISSING, MODULE)})   # no trusted repository

    def test_the_plan_is_deterministic_for_unchanged_state(self):
        h = self.current()
        del h.kodi.addons[MODULE]
        first, second = h.plan(), h.plan()
        self.assertEqual(first.identity_material(), second.identity_material())
        self.assertEqual(first.review, second.review)

    def test_a_target_validates_its_inputs(self):
        for kwargs in (dict(configuration_manifest_path=""), dict(device_profile_id=""),
                       dict(software_manifest_path=""), dict(install_resolution=(1,)),
                       dict(choices=(("bad id", DecisionChoice.SKIP),)),
                       dict(choices=((DEMO, "skip"),)),
                       dict(choices=((DEMO, DecisionChoice.SKIP), (DEMO, DecisionChoice.CANCEL)))):
            values = dict(configuration_manifest_path="/b", device_profile_id="d",
                          software_manifest_path="/f")
            values.update(kwargs)
            with self.subTest(kwargs), self.assertRaises(ValueError):
                PlanTarget(**values)
        target = PlanTarget("/b", "d", "/f").with_choice(MODULE, DecisionChoice.SKIP)
        again = target.with_choice(MODULE, DecisionChoice.CANCEL).with_choice(DEMO, DecisionChoice.SKIP)
        self.assertEqual(again.choices, ((DEMO, DecisionChoice.SKIP), (MODULE, DecisionChoice.CANCEL)))
        self.assertEqual(target.choices, ((MODULE, DecisionChoice.SKIP),))


# -- is the reviewed plan still the plan? -------------------------------------------------------

class StaleReview(PlanBase):
    def reviewed(self, **kwargs):
        h = self.current(**kwargs)
        target, plan = self.ready_plan(h)
        return h, target, plan

    def assertStale(self, check, *components):
        self.assertEqual(check.freshness, ReviewFreshness.STALE, check)
        self.assertTrue(check.requires_new_review)
        for component in components:
            self.assertIn(component, check.changed)

    def test_24_unchanged_inputs_keep_the_review_valid(self):
        h, target, plan = self.reviewed()
        check = h.validate(target, plan.review)
        self.assertEqual((check.freshness, check.changed), (ReviewFreshness.CURRENT, ()))
        self.assertTrue(check.is_current)
        self.assertFalse(check.requires_new_review)
        self.assertEqual(h.validate(target, plan.review), check)                 # and again
        later = h.plan_service(status=h.owners(clock=lambda: "2026-10-07T09:00:00Z"))
        self.assertTrue(later.validate(target, plan.review).is_current)          # time is not identity
        self.assertEqual(later.preview(target).review, plan.review)

    def test_25_a_changed_build_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.desired = replace(h.desired, build=BuildInfo(BUILD_ID, "1.0.1"))
        self.assertStale(h.validate(target, plan.review), IdentityComponent.BUILD)

    def test_26_a_changed_frozen_manifest_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.set_graph(extra=[(EXTRA, "1.0.0", PLUGIN_TYPE, ())])
        h.kodi.addons[EXTRA] = ("1.0.0", True)
        self.assertStale(h.validate(target, plan.review), IdentityComponent.FROZEN)

    def test_27_a_changed_device_profile_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        self.assertStale(h.validate(replace(target, device_profile_id="d2"), plan.review),
                         IdentityComponent.DEVICE)

    def test_28_changed_managed_addon_state_makes_the_review_stale(self):
        for change in (lambda h: h.kodi.addons.__setitem__(DEMO, ("1.0.0", False)),
                       lambda h: h.kodi.addons.__setitem__(DEMO, ("1.0.1", True)),
                       lambda h: h.kodi.addons.__setitem__(MODULE, ("2.0.0", True)),
                       lambda h: h.broken.add(DEMO)):
            with self.subTest(change=change):
                h, target, plan = self.reviewed()
                change(h)
                self.assertStale(h.validate(target, plan.review), IdentityComponent.SOFTWARE_STATE)

    def test_29_a_changed_active_skin_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.kodi.skin = "skin.other"
        self.assertStale(h.validate(target, plan.review), IdentityComponent.SKIN_STATE)

    def test_30_changed_configuration_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.config_backend.settings[(DEMO, "quality")] = "SENTINEL_OTHER"
        check = h.validate(target, plan.review)
        self.assertStale(check, IdentityComponent.CONFIGURATION)
        self.assertNotIn("SENTINEL_OTHER", repr(check))

    def test_31_changed_private_status_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.save_overlay(value=SECRET + "-rotated")
        self.assertStale(h.validate(target, plan.review), IdentityComponent.PRIVATE)
        h2, target2, plan2 = self.reviewed()
        h2.config_backend.unreadable.add((DEMO, "api_token"))                     # becomes unverifiable
        self.assertTrue(h2.validate(target2, plan2.review).requires_new_review)

    def test_32_changed_resolution_choice_or_policy_makes_the_review_stale(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(extra=[(EXTRA, "1.0.0", PLUGIN_TYPE, ())],
                    policies=[h.policy(EXTRA, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP)])
        h.forget_package(EXTRA)
        del h.kodi.addons[MODULE]
        h.save_overlay()
        target = h.plan_target().with_choice(EXTRA, DecisionChoice.SKIP)
        plan = h.plan(target)
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        self.assertTrue(h.validate(target, plan.review).is_current)
        self.assertStale(h.validate(target.with_choice(EXTRA, DecisionChoice.INSTALL_CURRENT), plan.review),
                         IdentityComponent.POLICY)
        h.desired = replace(h.desired, frozen_install_policies=(
            h.policy(EXTRA, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY),))      # skip is no longer allowed
        self.assertStale(h.validate(target, plan.review), IdentityComponent.POLICY)

    def test_33_changed_package_availability_or_identity_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.forget_package(MODULE)                         # the package the install row depends on
        check = h.validate(target, plan.review)
        self.assertStale(check, IdentityComponent.ARTIFACTS, IdentityComponent.ACTIONS)
        h, target, plan = self.reviewed()
        path = h.store_root / "artifacts" / ("%s.zip" % h.zips[MODULE].sha256)
        path.write_bytes(path.read_bytes() + b"tampered")           # identity no longer matches
        self.assertStale(h.validate(target, plan.review), IdentityComponent.ARTIFACTS)

    def test_a_pending_operation_makes_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.restart_transaction()
        self.assertStale(h.validate(target, plan.review), IdentityComponent.OPERATION)

    def test_work_done_since_the_review_makes_it_stale_not_silently_empty(self):
        h, target, plan = self.reviewed()
        h.kodi.addons[MODULE] = ("2.0.0", True)                        # someone installed it already
        check = h.validate(target, plan.review)
        self.assertStale(check, IdentityComponent.ACTIONS)
        self.assertEqual(h.plan(target).state, PlanState.NO_CHANGES)       # a new preview says so

    def test_unmanaged_changes_do_not_make_the_review_stale(self):
        h, target, plan = self.reviewed()
        h.kodi.addons["plugin.video.unmanaged"] = ("7.7", True)
        h.kodi.addons["plugin.video.brand.new"] = ("1.0", True)
        self.assertTrue(h.validate(target, plan.review).is_current)

    def test_reverting_the_change_restores_the_review(self):
        h, target, plan = self.reviewed()
        h.kodi.skin = "skin.other"
        self.assertTrue(h.validate(target, plan.review).requires_new_review)
        h.kodi.skin = SKIN
        self.assertTrue(h.validate(target, plan.review).is_current)

    def test_a_review_cannot_be_proven_when_an_inspection_is_unavailable(self):
        h, target, plan = self.reviewed()
        h.kodi.get_installed_addons = lambda: (_ for _ in ()).throw(RuntimeError(SECRET))
        check = h.validate(target, plan.review)
        self.assertEqual(check.freshness, ReviewFreshness.UNVERIFIABLE)
        self.assertTrue(check.requires_new_review)
        self.assertSecretFree(check, "\n".join(h.logs))

    def test_anything_but_a_review_identity_is_unverifiable(self):
        h, target, plan = self.reviewed()
        for bogus in (None, "sha256:" + "0" * 64, plan, object()):
            self.assertEqual(h.validate(target, bogus).freshness, ReviewFreshness.UNVERIFIABLE)

    def test_validation_never_raises(self):
        h, target, plan = self.reviewed()
        h.resolver_failure = RuntimeError(SECRET)
        self.assertTrue(h.validate(target, plan.review).requires_new_review)


# -- zero mutation, no network, no private values -------------------------------------------------

class Safety(PlanBase):
    def scenarios(self):
        def hold(h):
            h.frozen_transaction(FrozenInstallPhase.AWAITING_RESTART, hold=(REDLIGHT_ADDON_ID,),
                                 released=False)
        return {
            "current": lambda h: None,
            "missing": lambda h: h.kodi.addons.pop(MODULE),
            "wrong version": lambda h: h.kodi.addons.__setitem__(MODULE, ("9.9", True)),
            "skin": lambda h: setattr(h.kodi, "skin", "skin.other"),
            "settings": lambda h: h.config_backend.settings.__setitem__((DEMO, "quality"), "x"),
            "private": lambda h: h.save_overlay(value="other"),
            "restart": lambda h: h.restart_transaction(),
            "hold": hold,
            "unreadable": lambda h: setattr(h, "resolver_failure", RuntimeError(SECRET)),
        }

    def test_34_planning_and_validation_call_no_mutating_owner_in_any_state(self):
        for name, arrange in self.scenarios().items():
            with self.subTest(name):
                h = self.current()
                target = h.plan_target()
                review = h.plan(target).review or self.ready_plan(self.current())[1].review
                arrange(h)
                plan = h.plan(target)                    # PlanHarness asserts every tripwire is untouched
                h.validate(target, review)
                self.assertTrue(h.config_backend.reads or name == "unreadable")
                self.assertIsInstance(plan, BuildPlan)

    def test_the_plan_instrumentation_is_live(self):
        h = self.current()
        with h.instrumented():
            for call in (lambda: frozen_install.KodiRuntimeFrozenArtifactBackend().install_exact("a.b", "1", b"x"),
                         lambda: frozen_install.InMemoryFrozenArtifactBackend().install_exact("a.b", "1", b"x"),
                         lambda: ArtifactStore(h.profile / "elsewhere"),
                         lambda: frozen_install.FrozenInstallStore(h.frozen_root),
                         lambda: addons.KodiRuntimeAddonBackend().fetch_current_from_repository("a.b", "r"),
                         lambda: __import__("urllib.request").request.urlopen("http://127.0.0.1:9/")):
                with self.assertRaises(AssertionError):
                    call()
        self.assertEqual(len(h.touched), 6)

    def test_state_and_files_are_identical_before_and_after(self):
        h = self.current()
        target, plan = self.ready_plan(h)
        h.restart_transaction()
        before = snapshot_tree(h.profile)
        kodi_before, config_before = dict(h.kodi.addons), (
            dict(h.config_backend.settings), dict(h.config_backend.files))
        for _ in range(2):
            h.plan(target)
            h.validate(target, plan.review)
        self.assertEqual(snapshot_tree(h.profile), before)
        self.assertEqual(h.kodi.addons, kodi_before)
        self.assertEqual((h.config_backend.settings, h.config_backend.files), config_before)

    def test_a_missing_package_store_is_not_created(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(store=False)
        shutil.rmtree(h.store_root)                  # the harness pre-creates it for the other tests
        h.save_overlay()
        before = snapshot_tree(h.profile)
        plan = h.plan()
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertEqual(snapshot_tree(h.profile), before)
        self.assertFalse(h.store_root.exists())
        self.assertFalse(h.frozen_root.exists() and (h.frozen_root / "install_resolutions").exists())

    def test_35_the_plan_never_downloads_or_consults_a_repository(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(policies=[h.policy(MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY)])
        del h.kodi.addons[MODULE]
        h.forget_package(MODULE)
        h.save_overlay()
        plan = h.plan(h.plan_target().with_choice(MODULE, DecisionChoice.INSTALL_CURRENT))
        self.assertEqual(plan.state, PlanState.RESOLUTION_REQUIRED)
        self.assertEqual(h.deps.repository_reads, [])                  # nothing consulted a repository
        self.assertEqual(h.touched, [])                                # urlopen / sockets / fetch tripwires
        store = ReadOnlyArtifactStore(h.store_root)
        with self.assertRaises(RuntimeError):
            store.import_zip(make_zip(DEMO, "1.0.0"), expected_addon_id=DEMO, expected_version="1.0.0")

    def test_36_sentinel_secrets_reach_no_public_view_log_or_serialization(self):
        for name, arrange in self.scenarios().items():
            with self.subTest(name):
                h = self.current()
                h.config_backend.settings[(DEMO, "api_token")] = SECRET
                arrange(h)
                target = h.plan_target()
                plan = h.plan(target)
                check = h.validate(target, plan.review) if plan.review else None
                everything = [plan, repr(plan), json.dumps(plan.to_safe_dict()), repr(plan.review),
                              str(plan.review), repr(check), "\n".join(h.logs), plan.identity_material()]
                self.assertSecretFree(*everything)
                if plan.review is not None:
                    self.assertNotIn(plan.review.digest, repr(everything))
                    for _component, digest in plan.review.parts:
                        self.assertNotIn(digest, repr(everything))

    def test_the_review_identity_binds_a_secret_blind_value_never_the_secret(self):
        h = self.current()
        target, plan = self.ready_plan(h)
        for _component, digest in plan.review.parts:
            self.assertEqual(len(digest), 64)
        text = repr(plan.review) + repr(plan.review.parts) + plan.review.digest
        self.assertSecretFree(text)
        h.save_overlay(value=SECRET + "-2")                     # a different private value, same shape
        self.assertNotEqual(h.plan(target).review, plan.review)


# -- the public contract itself ---------------------------------------------------------------------

def sections(**over):
    values = dict(skin=SkinPlan(SkinPlanKind.NOT_APPLICABLE),
                  settings=SettingsPlan(SettingsPlanKind.NOT_APPLICABLE),
                  private=PrivatePlan(PrivatePlanKind.NOT_USED), restart=RestartPlan())
    values.update(over)
    return values


def build(state, software=(), **over):
    return BuildPlan(state, NOW, tuple(software), **sections(**{
        k: v for k, v in over.items() if k in ("skin", "settings", "private", "restart")}),
        **{k: v for k, v in over.items() if k not in ("skin", "settings", "private", "restart")})


class Contract(unittest.TestCase):
    CURRENT = SoftwareRow(DEMO, SoftwareAction.CURRENT)
    INSTALL = SoftwareRow(MODULE, SoftwareAction.INSTALL_EXACT, version="2.0.0")
    DECISION = SoftwareRow(EXTRA, SoftwareAction.DECISION, choices=(
        DecisionChoice.SKIP, DecisionChoice.CANCEL))

    def test_a_plan_cannot_claim_more_than_it_checked(self):
        blocker = PlanBlocker(BlockerCode.PACKAGE_MISSING, MODULE)
        blocked = SoftwareRow(MODULE, SoftwareAction.PACKAGE_MISSING)
        for label, make in {
            "no-changes with work": lambda: build(PlanState.NO_CHANGES, [self.INSTALL]),
            "ready without work": lambda: build(PlanState.CHANGES_READY, [self.CURRENT]),
            "ready with a blocker": lambda: build(PlanState.CHANGES_READY, [self.INSTALL],
                                                 blockers=(blocker,)),
            "ready with a blocked row": lambda: build(PlanState.CHANGES_READY, [blocked]),
            "ready with an undecided add-on": lambda: build(PlanState.CHANGES_READY,
                                                           [self.INSTALL, self.DECISION]),
            "no-changes with a decision": lambda: build(PlanState.NO_CHANGES, [self.CURRENT, self.DECISION]),
            "decision required without one": lambda: build(PlanState.DECISION_REQUIRED, [self.CURRENT]),
            "ready with an unchecked skin": lambda: build(
                PlanState.CHANGES_READY, [self.INSTALL], skin=SkinPlan(SkinPlanKind.UNAVAILABLE)),
            "ready with a gap": lambda: build(PlanState.CHANGES_READY, [self.INSTALL],
                                              gaps=(CheckGap.PRIVATE_UNAVAILABLE,)),
            "incomplete without saying why": lambda: build(PlanState.INCOMPLETE, [self.CURRENT]),
            "blocked without blockers": lambda: build(PlanState.BLOCKED, [self.CURRENT]),
            "blockers on a ready plan": lambda: build(PlanState.NO_CHANGES, [self.CURRENT],
                                                      blockers=(blocker,)),
            "a blocked row without its blocker": lambda: build(PlanState.BLOCKED, [blocked],
                                                               blockers=(PlanBlocker(
                                                                   BlockerCode.OPERATION_PENDING),)),
            "a review on a plan that is not ready": lambda: build(
                PlanState.NO_CHANGES, [self.CURRENT], review=ReviewIdentity.from_material(
                    {c: 1 for c in IdentityComponent})),
            "a plan that compared nothing": lambda: build(PlanState.NO_CHANGES, []),
            "an unnamed add-on blocker": lambda: PlanBlocker(BlockerCode.PACKAGE_MISSING),
        }.items():
            with self.subTest(label), self.assertRaises(ValueError):
                make()

    def test_valid_plans_of_every_state_can_be_built(self):
        review = ReviewIdentity.from_material({c: 1 for c in IdentityComponent})
        plans = [
            build(PlanState.NO_CHANGES, [self.CURRENT]),
            build(PlanState.CHANGES_READY, [self.INSTALL], review=review),
            build(PlanState.DECISION_REQUIRED, [self.DECISION]),
            build(PlanState.RESOLUTION_REQUIRED, [SoftwareRow(MODULE, SoftwareAction.INSTALL_REPOSITORY)]),
            build(PlanState.BLOCKED, [SoftwareRow(MODULE, SoftwareAction.DIFFERENT_VERSION)],
                  blockers=(PlanBlocker(BlockerCode.DIFFERENT_VERSION_INSTALLED, MODULE),)),
            build(PlanState.INCOMPLETE, [], gaps=(CheckGap.KODI_STATE_UNAVAILABLE,),
                  skin=SkinPlan(SkinPlanKind.UNAVAILABLE)),
        ]
        self.assertEqual([p.state for p in plans], list(PlanState))
        self.assertTrue(plans[1].can_proceed)
        self.assertFalse(any(p.can_proceed for i, p in enumerate(plans) if i != 1))

    def test_rows_reject_text_a_kodi_dialog_could_interpret(self):
        for name in ("[B]bold[/B]", "$INFO[Window.Property(x)]", "line\nbreak", "nul\x00", "‮evil",
                     "x" * 65, 7):
            with self.subTest(repr(name)), self.assertRaises(ValueError):
                SoftwareRow(DEMO, SoftwareAction.CURRENT, name)
        for version in ("1.0 beta", "v" * 70, "../1", "$INFO[x]", "1.0\n", 7):
            with self.subTest(version), self.assertRaises(ValueError):
                SoftwareRow(DEMO, SoftwareAction.CURRENT, version=version)
        for kwargs in (dict(choices=(DecisionChoice.SKIP,)),                  # only decisions offer choices
                       dict(action=SoftwareAction.DECISION, choices=(DecisionChoice.SKIP,)),   # must allow cancel
                       dict(action=SoftwareAction.DECISION, choices=(DecisionChoice.CANCEL,)),
                       dict(addon_id="bad id"), dict(addon_id=""),
                       dict(action=SoftwareAction.INSTALL_EXACT)):             # an exact install names its version
            values = dict(addon_id=DEMO, action=SoftwareAction.CURRENT)
            values.update(kwargs)
            with self.subTest(kwargs), self.assertRaises(ValueError):
                SoftwareRow(**values)
        SoftwareRow(DEMO, SoftwareAction.CURRENT, "Red Light 2 (TMDb) 100%", "2.6.8+matrix.1")

    def test_counts_and_kinds_are_validated(self):
        for kind, count in ((SettingsPlanKind.CHANGES, 0), (SettingsPlanKind.CURRENT, 3),
                            (SettingsPlanKind.CHANGES, -1), (SettingsPlanKind.CHANGES, True),
                            (SettingsPlanKind.CHANGES, 10 ** 9), ("changes", 1)):
            with self.subTest((kind, count)), self.assertRaises(ValueError):
                SettingsPlan(kind, count)
        with self.assertRaises(ValueError):
            PrivatePlan("current")
        with self.assertRaises(ValueError):
            RestartPlan("expected")

    def test_the_review_identity_is_opaque_and_checked(self):
        material = {c: [c.value] for c in IdentityComponent}
        identity = ReviewIdentity.from_material(material)
        self.assertEqual(repr(identity), "ReviewIdentity(<opaque>)")
        self.assertNotIn(identity.digest, repr(identity) + str(identity))
        self.assertEqual(identity, ReviewIdentity.from_material(dict(material)))
        other = ReviewIdentity.from_material({**material, IdentityComponent.SKIN_STATE: "changed"})
        self.assertEqual(other.changed_since(identity), (IdentityComponent.SKIN_STATE,))
        self.assertNotEqual(other.digest, identity.digest)
        for bad in (identity.parts[:-1], (), (("build", "a" * 64),), None,
                    tuple((c, "z" * 64) for c in IdentityComponent)):
            with self.subTest(bad), self.assertRaises(ValueError):
                ReviewIdentity(bad)
        with self.assertRaises(ValueError):
            ReviewIdentity.from_material({IdentityComponent.BUILD: 1})
        for freshness, changed in ((ReviewFreshness.CURRENT, (IdentityComponent.BUILD,)),
                                   (ReviewFreshness.STALE, ()), ("stale", ())):
            with self.subTest((freshness, changed)), self.assertRaises(ValueError):
                ReviewCheck(freshness, changed)

    def test_plan_types_have_no_field_that_can_carry_free_text(self):
        from dataclasses import fields
        import resources.lib.plan_model as model
        allowed_text = {"addon_id", "display_name", "version", "skin_id", "current_skin_id", "checked_at"}
        for cls in (model.SoftwareRow, model.PlanBlocker, model.SkinPlan, model.SettingsPlan,
                    model.PrivatePlan, model.RestartPlan, model.BuildPlan, model.ReviewCheck,
                    model.ReviewIdentity):
            for field in fields(cls):
                annotation = str(field.type)
                if "str" in annotation.replace("Tuple[Tuple[IdentityComponent, str], ...]", ""):
                    self.assertIn(field.name, allowed_text, "%s.%s" % (cls.__name__, field.name))
        text = json.dumps(build(PlanState.NO_CHANGES, [self.CURRENT]).to_safe_dict())
        self.assertNotIn("review", json.loads(text) and [k for k in json.loads(text) if k == "digest"])


# -- structure and parity with the owners the plan reuses ---------------------------------------------

class ImportPolicy(unittest.TestCase):
    def tree(self, name):
        return ast.parse((ROOT / "resources/lib" / name).read_text())

    def test_the_public_contract_imports_only_the_standard_library_and_status_vocabulary(self):
        modules = {n.module for n in ast.walk(self.tree("plan_model.py")) if isinstance(n, ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(self.tree("plan_model.py")) if isinstance(n, ast.Import)
                    for a in n.names}
        self.assertTrue(all(m in {"__future__", "hashlib", "json", "re", "dataclasses", "datetime", "enum", "typing",
                                  "resources.lib.status_model"} for m in modules), modules)

    def test_the_plan_module_never_reaches_a_mutating_owner(self):
        tree = self.tree("plan.py")
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("addons", "repository", "addon_state", "skin", "restart_coordinator", "resume",
                       "update_guard", "installed_addon_source", "verified_addon_imports", "startup",
                       "transaction", "private_resource", "redlight_resource", "session"):
            self.assertNotIn("resources.lib." + banned, modules)
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        for banned in ("BuildManager", "ConfigurationManager", "PrivateOverlayManager", "AddonManager",
                       "RepositoryManager", "SkinActivator", "AddonStateReconciler",
                       "FrozenInstallCoordinator", "FrozenInstallStore", "ResumeCoordinator",
                       "RestartCoordinator", "AddonUpdateGuard", "DependencyAwareInstaller",
                       "get_current_kodi_session_id", "active_activation_hold_ids", "reconcile",
                       "PrivateOverlayStore", "TransactionStore"):
            self.assertNotIn(banned, names)
        from_manager = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                        and n.module == "resources.lib.build_manager" for a in n.names}
        self.assertEqual(from_manager, {"fingerprint_resolved_build"})          # a pure function only
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for verb in ("install", "install_exact", "uninstall", "apply", "apply_settings", "activate",
                     "reconcile", "enable", "disable", "set_setting", "set_skin_setting", "write_file",
                     "set_addon_enabled", "set_policy", "create", "clear", "clear_expected", "save",
                     "transition_expected", "rearm_held_quiescence", "acquire", "release",
                     "retry_held_quiescence", "resume", "abandon", "initialize", "capture",
                     "resolve_repository_current", "fetch_current_from_repository", "import_zip",
                     "locked", "mkdir", "makedirs", "unlink", "write", "write_text", "write_bytes",
                     "rename", "replace", "remove", "urlopen"):
            self.assertNotIn(verb, called)

    def test_the_presentation_modules_import_no_engine(self):
        for name in ("ui/plan_view.py",):
            path = ROOT / "resources/lib" / name
            if not path.exists():
                continue
            modules = {n.module for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ImportFrom)}
            self.assertTrue(all(m in {"__future__", "dataclasses", "resources.lib.plan_model",
                                      "resources.lib.status_model", "resources.lib.ui.models",
                                      "resources.lib.ui.status_view"} for m in modules), modules)


class ParityWithOwners(PlanBase):
    def test_hold_ids_match_the_installers_own(self):
        from types import SimpleNamespace
        from resources.lib.plan import _hold_ids
        h = self.current()
        h.set_graph(extra=[(EXTRA, "1.0.0", PLUGIN_TYPE, (REDLIGHT_ADDON_ID,))])
        nodes = tuple(n for n in h.frozen.addons if not n.system and not n.is_absent_optional_dependency)
        theirs = frozen_install.FrozenInstallCoordinator._activation_hold_ids(
            SimpleNamespace(install_order=nodes), h.desired)
        self.assertEqual(_hold_ids(nodes, h.desired), theirs)
        self.assertIn(EXTRA, theirs)                                   # dependents of a held add-on are held
        absent = tuple(n for n in nodes if n.addon_id != REDLIGHT_ADDON_ID)
        with self.assertRaises(Exception):
            frozen_install.FrozenInstallCoordinator._activation_hold_ids(
                SimpleNamespace(install_order=absent), h.desired)
        with self.assertRaises(ValueError):
            _hold_ids(absent, h.desired)
        plain = self.current(with_resource=False)
        self.assertEqual(_hold_ids(nodes, plain.desired), ())

    def test_skip_conflicts_match_the_installers_private_ownership_check(self):
        from types import SimpleNamespace
        coordinator = frozen_install.FrozenInstallCoordinator
        for addon_id, conflicts in ((DEMO, True), (REDLIGHT_ADDON_ID, True), (EXTRA, False)):
            with self.subTest(addon_id):
                h = PlanHarness(self)
                h.set_graph(extra=[(EXTRA, "1.0.0", PLUGIN_TYPE, ())],
                            policies=[h.policy(addon_id, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP)])
                h.kodi.addons.pop(addon_id, None)
                h.forget_package(addon_id)
                h.save_overlay()
                record = InstallResolutionRecord(addon_id, next(
                    n.version for n in h.frozen.addons if n.addon_id == addon_id),
                    InstallResolution.SKIPPED, ResolutionState.SKIPPED)
                try:
                    coordinator._check_private_ownership_compatibility(SimpleNamespace(), h.desired, (record,))
                    installer_conflicts = False
                except Exception:
                    installer_conflicts = True
                plan = h.plan(h.plan_target().with_choice(addon_id, DecisionChoice.SKIP))
                plan_conflicts = (BlockerCode.CHOICE_CONFLICTS_WITH_BUILD, addon_id) in self.codes(plan)
                self.assertEqual((installer_conflicts, plan_conflicts), (conflicts, conflicts))

    def test_a_skipped_skin_is_refused_by_the_reconciler_and_by_the_plan(self):
        from resources.lib.build_manager import BuildManager
        h = self.current()
        skip = InstallResolutionRecord(SKIN, "1.0.0", InstallResolution.SKIPPED, ResolutionState.SKIPPED)
        with self.assertRaises(ValueError):
            BuildManager._apply_install_resolutions(h.desired, (skip,))

    def test_the_stage_two_actions_come_from_the_builds_own_planner(self):
        from resources.lib.planner import plan_changes
        h = self.current()
        h.kodi.skin = "skin.other"
        actual = h.kodi_state()
        kinds = {(a.kind, a.addon_id) for a in plan_changes(h.desired, actual).actions}
        self.assertIn(("SET_SKIN", SKIN), kinds)
        self.assertEqual(h.plan().skin.kind, SkinPlanKind.SWITCH)


class G3CorrectionRegressions(PlanBase):
    def repository_fixture(self, requires=(), *, skip=False):
        h = PlanHarness(self, with_resource=False)
        policies = [h.policy(MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY)]
        if skip:
            policies.append(h.policy(EXTRA, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP))
        h.set_graph(extra=[(EXTRA, '1.0.0', PLUGIN_TYPE, ()),
                           (LATE_DEPENDENCY, '1.0.0', PLUGIN_TYPE, ())], policies=policies)
        data = make_zip(MODULE, '2.0.1')
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, 'w') as dest:
            for name in source.namelist():
                payload = source.read(name)
                if name.endswith('/addon.xml'):
                    payload = payload.replace(b'<requires/>', ('<requires>' + ''.join(
                        '<import addon="%s" version="%s"/>' % pair for pair in requires
                    ) + '</requires>').encode())
                dest.writestr(name, payload)
        saved = ArtifactStore(h.store_root).import_zip(
            output.getvalue(), expected_addon_id=MODULE, expected_version='2.0.1')
        h.forget_package(MODULE)
        records = [InstallResolutionRecord(
            MODULE, '2.0.0', InstallResolution.REPOSITORY_CURRENT, ResolutionState.INSTALLED,
            repository_id=REPOSITORY, resolved_version='2.0.1',
            artifact_sha256=saved.sha256, artifact_size=saved.size)]
        if skip:
            h.forget_package(EXTRA)
            records.append(InstallResolutionRecord(
                EXTRA, '1.0.0', InstallResolution.SKIPPED, ResolutionState.SKIPPED))
        h.save_overlay()
        del h.kodi.addons[MODULE]
        return h, h.resolution(*records), saved

    def test_stored_repository_resolution_is_bound_to_selected_policy(self):
        h, resolution, _ = self.repository_fixture()
        # Restore the exact captured package without changing the frozen graph.
        ArtifactStore(h.store_root).import_zip(make_zip(MODULE, '2.0.0'),
            expected_addon_id=MODULE, expected_version='2.0.0')
        original = h.desired
        target = h.plan_target(install_resolution=resolution)
        ready = h.plan(target)
        self.assertEqual(ready.state, PlanState.CHANGES_READY)
        self.assertIsNotNone(ready.review)
        h.desired = replace(original, frozen_install_policies=())
        before = snapshot_tree(h.profile)
        with h.instrumented():
            rejected = h.plan(target)
            validation = h.validate(target, ready.review)
            with self.assertRaises(frozen_install.FrozenInstallValidationError):
                self.installer_restore(h, resolution)
        self.assertNotIn(rejected.state, (PlanState.CHANGES_READY, PlanState.NO_CHANGES,
                                         PlanState.RESOLUTION_REQUIRED))
        self.assertIsNone(rejected.review)
        self.assertNotEqual(validation.freshness, ReviewFreshness.CURRENT)
        self.assertIn(CheckGap.RESOLUTION_IDENTITY_MISMATCH, rejected.gaps)
        self.assertEqual(before, snapshot_tree(h.profile))
        h.assert_untouched()
        self.assertSecretFree(rejected, h.logs)
        for digest in (resolution.install_plan_fingerprint, resolution.source_software_fingerprint):
            self.assertNotIn(digest, str(rejected.to_safe_dict()) + str(h.logs))
        h.desired = original
        self.assertEqual(h.plan(target).state, PlanState.CHANGES_READY)
        self.assertEqual(h.validate(target, ready.review).freshness, ReviewFreshness.CURRENT)

    def test_stored_skip_is_bound_to_selected_policy(self):
        h, resolution, _ = self.repository_fixture(skip=True)
        original = h.desired
        target = h.plan_target(install_resolution=resolution)
        ready = h.plan(target)
        self.assertIsNotNone(ready.review)
        h.desired = replace(original, frozen_install_policies=original.frozen_install_policies[:1])
        result = h.plan(target)
        self.assertIsNone(result.review)
        self.assertIn(CheckGap.RESOLUTION_IDENTITY_MISMATCH, result.gaps)
        self.assertNotEqual(h.validate(target, ready.review).freshness, ReviewFreshness.CURRENT)
        h.desired = original
        self.assertIsNotNone(h.plan(target).review)

    def test_matching_plan_identity_rejects_ineligible_records(self):
        from resources.lib.frozen_resolution import install_plan_fingerprint
        for kind in ('repository', 'skip', 'wrong_repository'):
            with self.subTest(kind=kind):
                h, resolution, _ = self.repository_fixture(skip=kind == 'skip')
                if kind == 'wrong_repository':
                    records = (replace(resolution.records[0], repository_id='repository.other'),)
                    resolution = h.resolution(*records)
                else:
                    h.desired = replace(h.desired, frozen_install_policies=())
                    resolution = replace(resolution, install_plan_fingerprint=
                        install_plan_fingerprint(h.frozen, h.desired.frozen_install_policies))
                result = h.plan(install_resolution=resolution)
                self.assertIsNone(result.review)
                self.assertIn(CheckGap.RESOLUTION_IDENTITY_MISMATCH, result.gaps)
                self.assertIn(CheckGap.RESOLUTION_IDENTITY_MISMATCH,
                              h.check(install_resolution=resolution).gaps)
                with self.assertRaises(frozen_install.FrozenInstallValidationError):
                    self.installer_restore(h, resolution)

    def test_matching_exact_resolution_remains_valid(self):
        from resources.lib.frozen_resolution import default_exact_record
        h = self.current(with_resource=False)
        resolution = h.resolution(*(replace(default_exact_record(node), state=ResolutionState.INSTALLED)
            for node in h.frozen.addons if not node.system and not node.is_absent_optional_dependency))
        self.assertEqual(h.plan(install_resolution=resolution).state, PlanState.NO_CHANGES)
        self.assertEqual(h.check(install_resolution=resolution).overall.value, "current")

    def test_unresolved_current_cannot_be_reviewed(self):
        h = self.current(with_resource=False)
        h.set_graph(policies=[h.policy(MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY)])
        h.forget_package(MODULE)
        h.save_overlay()
        del h.kodi.addons[MODULE]
        plan = h.plan(h.plan_target().with_choice(MODULE, DecisionChoice.INSTALL_CURRENT))
        self.assertEqual(plan.state.value, 'resolution_required')
        self.assertIsNone(plan.review)

    def test_saved_package_adds_required_edge_and_order(self):
        h, resolution, _ = self.repository_fixture(((LATE_DEPENDENCY, '1.0.0'),))
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        order = [row.addon_id for row in plan.software]
        self.assertLess(order.index(LATE_DEPENDENCY), order.index(MODULE))

    def test_saved_package_skip_conflict_is_blocked(self):
        h, resolution, _ = self.repository_fixture(((EXTRA, '1.0.0'),), skip=True)
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.BLOCKED)
        self.assertIn((BlockerCode.SOFTWARE_PLAN_INVALID, ''), self.codes(plan))
        self.assertIsNone(plan.review)

    def test_saved_package_uncaptured_or_newer_dependency_is_blocked(self):
        for dependency in (('plugin.video.unknown', '1.0.0'), (EXTRA, '9.0.0')):
            with self.subTest(dependency):
                h, resolution, _ = self.repository_fixture((dependency,))
                self.assertEqual(h.plan(install_resolution=resolution).state, PlanState.BLOCKED)

    def test_saved_package_unchanged_and_tampered(self):
        h, resolution, saved = self.repository_fixture()
        plan = h.plan(install_resolution=resolution)
        self.assertEqual(plan.state, PlanState.CHANGES_READY)
        (h.store_root / 'artifacts' / (saved.sha256 + '.zip')).write_bytes(b'bad zip')
        invalid = h.plan(install_resolution=resolution)
        self.assertEqual(invalid.state, PlanState.BLOCKED)
        self.assertIsNone(invalid.review)

    def unfrozen_fixture(self):
        h = self.current(with_resource=False)
        h.desired = replace(h.desired, addons=h.desired.addons + (AddonEntry(EXTRA, 'enabled'),))
        h.kodi.addons[EXTRA] = ('1.0.0', False)
        return h

    def test_unfrozen_managed_broken_blocks_and_stales(self):
        h = self.unfrozen_fixture()
        plan = h.plan()
        self.assertEqual(self.row(plan, EXTRA).action, SoftwareAction.ENABLE)
        self.assertIsNotNone(plan.review)
        h.broken.add(EXTRA)
        broken = h.plan()
        self.assertEqual(broken.state, PlanState.BLOCKED)
        self.assertEqual(self.row(broken, EXTRA).action, SoftwareAction.BROKEN)
        check = h.validate(h.plan_target(), plan.review)
        self.assertEqual(check.freshness, ReviewFreshness.STALE)
        self.assertIn(IdentityComponent.SOFTWARE_STATE, check.changed)
        with h.instrumented():
            _, material = h.plan_service()._evaluate(h.plan_target())
        self.assertEqual({r[0]: r[-1] for r in material[IdentityComponent.SOFTWARE_STATE]}[EXTRA], True)

    def test_unmanaged_broken_does_not_change_review(self):
        h = self.unfrozen_fixture()
        plan = h.plan()
        h.broken.add('plugin.video.unmanaged')
        self.assertEqual(h.validate(h.plan_target(), plan.review).freshness, ReviewFreshness.CURRENT)

    def two_private_settings(self):
        from resources.lib.manifest import PrivateSettingDeclaration
        from resources.lib.private_overlay import PrivateOverlayEntry
        from resources.lib.config import ConfigSettingType
        h = self.current(with_resource=False)
        h.desired = replace(h.desired, config=replace(h.desired.config,
            private_settings=h.desired.config.private_settings + (
                PrivateSettingDeclaration(DEMO, 'second_token', 'string', True, 'token'),)))
        overlay = h.overlay_store.load('status-overlay')
        h.overlay_store.save(replace(overlay, entries=overlay.entries + (
            PrivateOverlayEntry(DEMO, 'second_token', ConfigSettingType.STRING, SECRET),)))
        h.config_backend.settings[(DEMO, 'second_token')] = SECRET
        return h

    def test_private_settings_drift_cannot_hide_unreadability(self):
        h = self.two_private_settings()
        self.assertEqual(h.plan().private.kind, PrivatePlanKind.CURRENT)
        h.config_backend.settings[(DEMO, 'api_token')] = 'different'
        plan = h.plan()
        self.assertEqual(plan.private.kind, PrivatePlanKind.CHANGES_NEEDED)
        h.config_backend.unreadable.add((DEMO, 'second_token'))
        result = h.plan()
        self.assertEqual(result.private.kind, PrivatePlanKind.UNAVAILABLE)
        self.assertIsNone(result.review)
        self.assertNotEqual(h.validate(h.plan_target(), plan.review).freshness, ReviewFreshness.CURRENT)
        self.assertSecretFree(result, h.logs)

    def test_private_setting_drift_and_unreadable_real_resource(self):
        h = self.current()
        h.config_backend.settings[(DEMO, 'api_token')] = 'different'
        h.db.write_bytes(b'unreadable database')
        plan = h.plan()
        self.assertEqual(plan.private.kind, PrivatePlanKind.UNAVAILABLE)
        self.assertIsNone(plan.review)

    def test_review_constructor_rejects_noncanonical_parts(self):
        parts = tuple((component, 'a' * 64) for component in IdentityComponent)
        self.assertEqual(ReviewIdentity(parts).parts, parts)
        cases = (parts + (('unknown', 'a' * 64),), parts + (parts[0],),
                 (parts[0],) + parts[:-1], (('unknown', 'a' * 64),) + parts[1:], parts[:-1],
                 tuple(reversed(parts)), ((parts[0][0], 'bad'),) + parts[1:])
        for value in cases:
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                ReviewIdentity(value)

    def installer_restore(self, h, resolution):
        from types import SimpleNamespace
        from resources.lib.frozen_resolution import (
            default_exact_record, install_plan_fingerprint, resolution_fingerprint,
            resolved_software_fingerprint)
        records = {r.addon_id: r for r in resolution.records}
        for node in h.frozen.addons:
            if not node.system and not node.is_absent_optional_dependency and node.addon_id not in records:
                records[node.addon_id] = replace(default_exact_record(node), state=ResolutionState.INSTALLED)
        transaction = SimpleNamespace(
            policies=h.desired.frozen_install_policies,
            resolution_records=tuple(records.values()),
            install_plan_fingerprint=install_plan_fingerprint(h.frozen, h.desired.frozen_install_policies),
            manifest_fingerprint=h.frozen.fingerprint(),
            resolution_fingerprint=resolution_fingerprint(tuple(records.values())),
            resolved_software_fingerprint=resolved_software_fingerprint(h.frozen, tuple(records.values())))
        coordinator = frozen_install.FrozenInstallCoordinator(
            store=None, artifact_store=ReadOnlyArtifactStore(h.store_root), policy_backend=None, installer=None)
        return coordinator._restore_resolution(h.frozen, transaction)[0]

    def test_actual_installer_restoration_order_matches_g3(self):
        for requires in ((), ((LATE_DEPENDENCY, '1.0.0'),)):
            with self.subTest(requires):
                h, resolution, _ = self.repository_fixture(requires)
                before = snapshot_tree(h.profile)
                with h.instrumented():
                    installer = self.installer_restore(h, resolution)
                plan = h.plan(install_resolution=resolution)
                self.assertEqual([r.addon_id for r in plan.software],
                                 [n.addon_id for n in installer.install_order])
                self.assertEqual(before, snapshot_tree(h.profile))
                h.assert_untouched()

    def test_actual_installer_restoration_and_g3_reject_same_dependencies(self):
        for requires, skip in ((((EXTRA, '1.0.0'),), True),
                               ((('plugin.video.unknown', '1.0.0'),), False),
                               (((EXTRA, '9.0.0'),), False),
                               (((DEMO, '1.0.0'),), False)):
            with self.subTest(requires=requires, skip=skip):
                h, resolution, _ = self.repository_fixture(requires, skip=skip)
                with h.instrumented(), self.assertRaises(frozen_install.FrozenInstallValidationError):
                    self.installer_restore(h, resolution)
                self.assertEqual(h.plan(install_resolution=resolution).state, PlanState.BLOCKED)
                h.assert_untouched()

    def test_installed_saved_repository_package_is_still_parsed_and_integrity_checked(self):
        h, resolution, saved = self.repository_fixture(((EXTRA, '1.0.0'),), skip=True)
        h.kodi.addons[MODULE] = ('2.0.1', True)
        self.assertEqual(h.plan(install_resolution=resolution).state, PlanState.BLOCKED)
        h, resolution, saved = self.repository_fixture()
        h.kodi.addons[MODULE] = ('2.0.1', True)
        del h.kodi.addons[DEMO]
        plan = h.plan(install_resolution=resolution)
        self.assertIsNotNone(plan.review)
        (h.store_root / 'artifacts' / (saved.sha256 + '.zip')).write_bytes(b'bad zip')
        self.assertEqual(h.plan(install_resolution=resolution).state, PlanState.BLOCKED)
        self.assertNotEqual(h.validate(h.plan_target(install_resolution=resolution), plan.review).freshness,
                            ReviewFreshness.CURRENT)

    def test_unfrozen_disable_and_skin_health(self):
        h = self.unfrozen_fixture()
        h.desired = replace(h.desired, addons=h.desired.addons[:-1] + (AddonEntry(EXTRA, 'disabled'),))
        h.kodi.addons[EXTRA] = ('1.0.0', True)
        self.assertEqual(self.row(h.plan(), EXTRA).action, SoftwareAction.DISABLE)
        h.broken.add(EXTRA)
        self.assertEqual(self.row(h.plan(), EXTRA).action, SoftwareAction.BROKEN)
        h = self.current(with_resource=False)
        h.set_graph(without=(SKIN,))
        h.save_overlay()
        h.kodi.skin = 'skin.estuary'
        plan = h.plan()
        self.assertIsNotNone(plan.review)
        h.broken.add(SKIN)
        self.assertEqual(h.plan().state, PlanState.BLOCKED)
        self.assertIn(IdentityComponent.SOFTWARE_STATE,
                      h.validate(h.plan_target(), plan.review).changed)

    def test_unfrozen_health_unavailable_refuses_review(self):
        h = self.unfrozen_fixture()
        service = h.plan_service(addon_details=lambda aid: None if aid == EXTRA else h.details(aid))
        with h.instrumented():
            plan = service.preview(h.plan_target())
        self.assertEqual(plan.state, PlanState.INCOMPLETE)
        self.assertIsNone(plan.review)
        h.assert_untouched()

    def test_resolution_required_model_and_ui(self):
        from resources.lib.ui.plan_view import ReviewViewModel
        row = SoftwareRow(MODULE, SoftwareAction.INSTALL_REPOSITORY, MODULE)
        plan = build(PlanState.RESOLUTION_REQUIRED, [row])
        self.assertFalse(plan.can_proceed)
        self.assertEqual(ReviewViewModel.from_plan(plan).state, PlanState.RESOLUTION_REQUIRED)
        for state in (PlanState.CHANGES_READY, PlanState.NO_CHANGES):
            with self.assertRaises(ValueError):
                build(state, [row])


    def test_corrected_paths_preserve_profile_tree_and_private_output(self):
        for arrange in ('unresolved', 'stored', 'broken', 'private'):
            with self.subTest(arrange):
                if arrange == 'stored':
                    h, resolution, _ = self.repository_fixture(((LATE_DEPENDENCY, '1.0.0'),))
                    target = h.plan_target(install_resolution=resolution)
                elif arrange == 'unresolved':
                    h = self.current(with_resource=False)
                    h.set_graph(policies=[h.policy(MODULE, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY)])
                    h.forget_package(MODULE)
                    del h.kodi.addons[MODULE]
                    h.save_overlay()
                    target = h.plan_target().with_choice(MODULE, DecisionChoice.INSTALL_CURRENT)
                elif arrange == 'broken':
                    h = self.unfrozen_fixture()
                    h.broken.add(EXTRA)
                    target = h.plan_target()
                else:
                    h = self.two_private_settings()
                    h.config_backend.settings[(DEMO, 'api_token')] = 'different'
                    h.config_backend.unreadable.add((DEMO, 'second_token'))
                    target = h.plan_target()
                before = snapshot_tree(h.profile)
                plan = h.plan(target)
                self.assertEqual(before, snapshot_tree(h.profile))
                self.assertSecretFree(plan, plan.to_safe_dict(), h.logs)
                if plan.review is not None:
                    self.assertEqual(h.validate(target, plan.review).freshness, ReviewFreshness.CURRENT)
                    self.assertEqual(before, snapshot_tree(h.profile))


class PlatformProvidedPlan(PlanBase):
    """A bundled Kodi add-on is a verified requirement, never a managed row or a choice (D-028)."""

    PLATFORM = "script.module.platform"

    def test_platform_requirement_is_neither_a_missing_package_nor_a_skip_or_repository_row(self):
        h = PlanHarness(self)
        h.set_graph(platform=((self.PLATFORM, "5.1.0", "xbmc.python.module", ("xbmc.python",)),))
        h.save_overlay()
        plan = h.plan()
        self.assertNotIn(self.PLATFORM, self.actions(plan))
        self.assertEqual(plan.blockers, ())


if __name__ == "__main__":
    unittest.main()
