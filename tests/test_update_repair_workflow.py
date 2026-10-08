"""Offline Update / Repair tests: applied-association start, reviewed Apply, G6 blockers,
different revisions, route wiring and presentation safety. Every owner is a fake."""
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch

from resources.lib.build_library import LibraryEntry, LibrarySource
from resources.lib.frozen_install import FrozenInstallResult
from resources.lib.frozen_resolution import FrozenInstallResolutionManifest, InstallResolution, ResolutionChoice
from resources.lib.plan import PlanTarget
from resources.lib.plan_model import (
    BlockerCode, BuildPlan, DecisionChoice, IdentityComponent, PlanBlocker, PlanState, PrivatePlan,
    PrivatePlanKind, RestartPlan, ReviewCheck, ReviewFreshness, ReviewIdentity, SettingsPlan,
    SettingsPlanKind, SkinPlan, SkinPlanKind, SoftwareAction, SoftwareRow,
)
from resources.lib.repository_preparation import PreparationCode, PreparedRepositoryResolution
from resources.lib.status_model import CheckGap, OperationKind
from resources.lib.ui import repair_view as repair
from resources.lib.ui.controller import Route
from resources.lib.ui.native_dialogs import NativeDialogs
from resources.lib.update_repair_workflow import UpdateRepairWorkflow

ROOT = Path(__file__).resolve().parents[1]
CHECKED = '2026-10-07T12:00:00Z'


def plan(state=PlanState.CHANGES_READY, rows=None, blockers=(), gaps=(), serial='one'):
    """A valid plan of the given state, built the way the frozen plan service builds one."""
    if rows is None:
        rows = {
            PlanState.NO_CHANGES: (SoftwareRow('plugin.demo', SoftwareAction.CURRENT, 'Demo', '2.0.0'),),
            PlanState.DECISION_REQUIRED: (SoftwareRow('plugin.demo', SoftwareAction.DECISION, 'Demo', '1.0.0',
                                                      (DecisionChoice.SKIP, DecisionChoice.CANCEL)),),
            PlanState.RESOLUTION_REQUIRED: (SoftwareRow('plugin.demo', SoftwareAction.INSTALL_REPOSITORY,
                                                        'Demo', '1.0.0'),),
        }.get(state, (SoftwareRow('plugin.demo', SoftwareAction.INSTALL_EXACT, 'Demo', '2.0.0'),))
    review = ReviewIdentity.from_material({c: serial for c in IdentityComponent}) \
        if state is PlanState.CHANGES_READY else None
    return BuildPlan(state, CHECKED, tuple(rows),
        SkinPlan(SkinPlanKind.NOT_APPLICABLE), SettingsPlan(SettingsPlanKind.NOT_APPLICABLE),
        PrivatePlan(PrivatePlanKind.NOT_USED), RestartPlan(), blockers=tuple(blockers),
        gaps=tuple(gaps), review=review)


def resolution(*records):
    """A stand-in applied install resolution; PlanTarget accepts it by type."""
    manifest = Mock(spec=FrozenInstallResolutionManifest)
    manifest.records = tuple(Mock(addon_id=aid, resolution=kind) for aid, kind in records)
    return manifest


def strings():
    """Localized identifiers from the shipped resource, with Kodi's escapes decoded."""
    text = (ROOT / 'resources/language/resource.language.en_gb/strings.po').read_text(encoding='utf-8')
    out = {}
    for match in re.finditer(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"', text):
        out[int(match.group(1))] = match.group(2).replace('\\n', '\n').replace('\\"', '"')
    return out


STRINGS = strings()


class Addon:
    def getLocalizedString(self, identifier):
        return STRINGS.get(int(identifier), str(identifier))

    def openSettings(self):
        raise AssertionError('settings must not open from Update / Repair')


class Dialog:
    """Scripted native dialogs that records every heading, label and body it shows."""

    def __init__(self, selects=(), answers=()):
        self.selects, self.answers = iter(selects), iter(answers)
        self.labels, self.views, self.oks, self.questions = [], [], [], []

    def select(self, heading, labels, preselect=0):
        self.labels.append((heading, list(labels)))
        return next(self.selects)

    def textviewer(self, heading, body):
        self.views.append((heading, body))

    def ok(self, heading, body):
        self.oks.append((heading, body))

    def yesno(self, heading, body, nolabel='', yeslabel=''):
        self.questions.append((heading, body))
        return next(self.answers)

    def everything(self):
        """Every visible string, for presentation checks."""
        visible = [h for h, _ in self.labels] + [text for _, labels in self.labels for text in labels]
        visible += [part for pair in self.views + self.oks + self.questions for part in pair]
        return '\n'.join(str(item) for item in visible)


class RepairWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.applied_entry = LibraryEntry('a' * 64, 'demo', '1.0.0', 'Friendly Build', ('desk', 'other'))
        self.applied = PlanTarget('/private/manifest', 'other', '/private/frozen',
                                  library_source=LibrarySource('/private/library', self.applied_entry.entry_id))
        self.library = Mock()
        self.library.associated_plan_target.return_value = self.applied
        self.library.get.return_value = self.applied_entry
        self.library.list_builds.return_value = (self.applied_entry,)
        self.library.current_selection.side_effect = AssertionError('saved selection forbidden')
        self.library.select.side_effect = AssertionError('selection mutation forbidden')
        self.service = Mock()
        self.service.preview.return_value = plan()
        self.service.validate.return_value = ReviewCheck(ReviewFreshness.CURRENT)
        self.preparation = Mock()
        self.coordinator = Mock()
        self.coordinator.install_target.return_value = FrozenInstallResult('complete')
        self.factory = Mock(return_value=self.coordinator)
        self.workflow = UpdateRepairWorkflow(self.library, self.service, self.preparation, self.factory)
        self.ui = Mock()
        self.ui.repair_choose_action.side_effect = ['check', None]
        self.ui.repair_approve.return_value = True
        self.ui.repair_prepare.side_effect = lambda run: run()
        self.ui.execute_install.side_effect = lambda run: run()
        self.ui.choose_install_decision.return_value = None

    def run_flow(self):
        with patch('resources.lib.update_repair_workflow.LibraryInstallTarget.from_plan_target') as derive:
            self.workflow.run(self.ui)
            return derive

    def assert_no_apply(self):
        self.ui.repair_approve.assert_not_called()
        self.service.validate.assert_not_called()
        self.factory.assert_not_called()
        self.assertEqual(self.coordinator.mock_calls, [])

    def test_construction_builds_no_mutating_owner(self):
        UpdateRepairWorkflow(self.library, self.service, self.preparation, self.factory)
        self.factory.assert_not_called()
        self.library.current_selection.assert_not_called()

    def test_no_verified_association_has_no_fallback_and_no_work(self):
        self.library.associated_plan_target.return_value = None
        self.run_flow()
        self.ui.repair_message.assert_called_once_with(repair.S_NO_VERIFIED_BUILD)
        self.ui.repair_choose_action.assert_not_called()
        self.library.list_builds.assert_not_called()
        self.library.plan_target.assert_not_called()
        self.service.preview.assert_not_called()
        self.assert_no_apply()

    def test_associated_no_op_shows_current_and_offers_no_apply(self):
        self.service.preview.return_value = plan(PlanState.NO_CHANGES)
        self.run_flow()
        self.service.preview.assert_called_once_with(self.applied)
        self.ui.repair_show_healthy.assert_called_once()
        self.assert_no_apply()

    def test_recorded_repository_package_blocks_apply_even_when_only_enablement_changes(self):
        self.applied = PlanTarget('/private/manifest', 'other', '/private/frozen',
                                  library_source=self.applied.library_source,
                                  install_resolution=resolution(('plugin.demo', InstallResolution.REPOSITORY_CURRENT)))
        self.library.associated_plan_target.return_value = self.applied
        self.service.preview.return_value = plan(PlanState.NO_CHANGES)
        self.run_flow()
        self.ui.repair_show_healthy.assert_called_once()
        self.assert_no_apply()
        self.service.preview.return_value = plan(PlanState.CHANGES_READY)
        self.ui.repair_choose_action.side_effect = ['check', None]
        self.run_flow()
        notes = self.ui.repair_show.call_args.args[1]
        self.assertEqual(notes, (repair.S_NOTE_RECORDED_PACKAGE,))
        self.assert_no_apply()

    def test_changes_ready_is_reviewed_confirmed_validated_then_executed_exactly(self):
        events = []
        self.ui.repair_approve.side_effect = lambda summary, model: events.append('approve') or True
        self.service.validate.side_effect = lambda t, r: (
            events.append('validate') or ReviewCheck(ReviewFreshness.CURRENT))
        self.coordinator.install_target.side_effect = lambda *a, **k: (
            events.append('execute') or FrozenInstallResult('complete'))
        derive = self.run_flow()
        self.assertEqual(events, ['approve', 'validate', 'execute'])
        self.service.validate.assert_called_once_with(self.applied, self.service.preview.return_value.review)
        derive.assert_called_once_with(self.applied)
        self.coordinator.install_target.assert_called_once_with(
            derive.return_value, prepared_resolution=None, resolution_choices={}, interactive=False)
        self.ui.repair_message.assert_called_with(32809)

    def test_declined_or_unconfirmed_changes_never_validate_or_execute(self):
        self.ui.repair_approve.return_value = False
        self.run_flow()
        self.service.validate.assert_not_called()
        self.factory.assert_not_called()

    def test_stale_or_unverifiable_review_never_applies_and_needs_a_new_review(self):
        for freshness in (ReviewFreshness.STALE, ReviewFreshness.UNVERIFIABLE):
            with self.subTest(freshness=freshness):
                self.setUp()
                old, new = plan(serial='old'), plan(serial='new')
                self.service.preview.side_effect = [old, new]
                self.service.validate.side_effect = [
                    ReviewCheck(freshness, (IdentityComponent.SOFTWARE_STATE,))
                    if freshness is ReviewFreshness.STALE else ReviewCheck(freshness),
                    ReviewCheck(ReviewFreshness.CURRENT)]
                self.ui.repair_choose_action.side_effect = ['check', None]
                self.ui.repair_approve.side_effect = [True, True]
                self.run_flow()
                self.assertEqual(self.service.preview.call_count, 2)
                self.assertEqual(self.ui.repair_approve.call_count, 2)
                self.ui.repair_message.assert_any_call(32808)
                self.service.validate.assert_called_with(self.applied, new.review)
                self.coordinator.install_target.assert_called_once()

    def test_decision_offers_only_permitted_choices_and_cancel_does_no_work(self):
        decision = plan(PlanState.DECISION_REQUIRED)
        self.service.preview.return_value = decision
        self.ui.choose_install_decision.return_value = DecisionChoice.CANCEL
        self.run_flow()
        prompt = self.ui.choose_install_decision.call_args.args[0]
        self.assertEqual(prompt.choices, (DecisionChoice.SKIP, DecisionChoice.CANCEL))
        self.service.preview.assert_called_once()
        self.preparation.prepare.assert_not_called()
        self.assert_no_apply()

    def test_answered_decision_is_bound_then_freshly_reviewed(self):
        self.service.preview.side_effect = [plan(PlanState.DECISION_REQUIRED), plan()]
        self.ui.choose_install_decision.return_value = DecisionChoice.SKIP
        derive = self.run_flow()
        chosen = self.service.preview.call_args_list[1].args[0]
        self.assertEqual(chosen.choices, (('plugin.demo', DecisionChoice.SKIP),))
        derive.assert_called_once_with(chosen)
        self.assertEqual(self.coordinator.install_target.call_args.kwargs['resolution_choices'],
                         {'plugin.demo': ResolutionChoice.SKIP})
        self.assertEqual(self.ui.repair_approve.call_count, 1)

    def test_answers_survive_a_stale_re_review_and_are_not_asked_again(self):
        self.service.preview.side_effect = [
            plan(PlanState.DECISION_REQUIRED), plan(serial='old'), plan(serial='new')]
        self.service.validate.side_effect = [
            ReviewCheck(ReviewFreshness.STALE, (IdentityComponent.SOFTWARE_STATE,)),
            ReviewCheck(ReviewFreshness.CURRENT)]
        self.ui.choose_install_decision.return_value = DecisionChoice.SKIP
        self.ui.repair_approve.side_effect = [True, True]
        self.run_flow()
        self.assertEqual(self.ui.choose_install_decision.call_count, 1)
        self.ui.repair_message.assert_any_call(32808)
        third = self.service.preview.call_args_list[2].args[0]
        self.assertEqual(third.choices, (('plugin.demo', DecisionChoice.SKIP),))
        self.assertEqual(self.coordinator.install_target.call_args.kwargs['resolution_choices'],
                         {'plugin.demo': ResolutionChoice.SKIP})

    def test_ignored_or_unoffered_answer_cannot_spin_or_bypass_review(self):
        self.service.preview.return_value = plan(PlanState.DECISION_REQUIRED)
        self.ui.choose_install_decision.return_value = DecisionChoice.SKIP
        self.run_flow()
        self.assertEqual(self.ui.choose_install_decision.call_count, 1)
        self.ui.repair_message.assert_called_with(32814)
        self.assert_no_apply()
        self.setUp()
        self.service.preview.return_value = plan(PlanState.DECISION_REQUIRED)
        self.ui.choose_install_decision.return_value = DecisionChoice.INSTALL_CURRENT
        self.run_flow()
        self.ui.repair_message.assert_called_with(32814)
        self.assert_no_apply()

    def test_repository_preparation_then_fresh_review_binds_prepared_and_choice(self):
        prepared = Mock(spec=PreparedRepositoryResolution)
        self.service.preview.side_effect = [
            offering_install_current(), plan(PlanState.RESOLUTION_REQUIRED), plan()]
        self.ui.choose_install_decision.return_value = DecisionChoice.INSTALL_CURRENT
        self.preparation.prepare.side_effect = lambda target: Mock(code=PreparationCode.READY, prepared=prepared)
        self.run_flow()
        self.preparation.prepare.assert_called_once()
        self.assertEqual(self.ui.repair_approve.call_count, 1)
        self.assertEqual(self.service.preview.call_count, 3)
        kwargs = self.coordinator.install_target.call_args.kwargs
        self.assertIs(kwargs['prepared_resolution'], prepared)
        self.assertEqual(kwargs['resolution_choices'], {'plugin.demo': ResolutionChoice.INSTALL_CURRENT})

    def test_failed_preparation_stops_without_apply(self):
        self.service.preview.side_effect = [offering_install_current(), plan(PlanState.RESOLUTION_REQUIRED)]
        self.ui.choose_install_decision.return_value = DecisionChoice.INSTALL_CURRENT
        self.preparation.prepare.return_value = Mock(code=PreparationCode.TARGET_INVALID, prepared=None)
        self.run_flow()
        self.ui.repair_message.assert_called_with(32804)
        self.assert_no_apply()

    def test_version_change_and_broken_install_are_visible_blockers_without_apply(self):
        cases = (
            (BlockerCode.DIFFERENT_VERSION_INSTALLED, SoftwareAction.DIFFERENT_VERSION, repair.S_NOTE_DIFFERENT_VERSION),
            (BlockerCode.INSTALLED_ADDON_BROKEN, SoftwareAction.BROKEN, repair.S_NOTE_BROKEN),
        )
        for code, action, note in cases:
            with self.subTest(code=code):
                self.setUp()
                self.service.preview.return_value = plan(
                    PlanState.BLOCKED, rows=(SoftwareRow('plugin.demo', action, 'Demo', '2.0.0'),),
                    blockers=(PlanBlocker(code, 'plugin.demo', 'Demo'),))
                self.run_flow()
                shown = self.ui.repair_show.call_args
                self.assertIn(note, shown.args[1])
                self.assert_no_apply()

    def test_pending_attention_and_incomplete_states_never_offer_apply(self):
        states = (
            plan(PlanState.BLOCKED, rows=(), blockers=(PlanBlocker(BlockerCode.OPERATION_PENDING),)),
            plan(PlanState.BLOCKED, rows=(), blockers=(PlanBlocker(BlockerCode.OPERATION_NEEDS_ATTENTION),)),
            plan(PlanState.INCOMPLETE, rows=(), gaps=(CheckGap.INSPECTION_FAILED,)),
        )
        for state in states:
            with self.subTest(state=state.state, blockers=[b.code for b in state.blockers]):
                self.setUp()
                self.service.preview.return_value = state
                self.run_flow()
                self.ui.repair_show.assert_called_once()
                self.assert_no_apply()

    def test_recorded_accepted_skip_is_carried_as_skip_and_reported_as_exception(self):
        self.applied = PlanTarget('/private/manifest', 'other', '/private/frozen',
                                  library_source=self.applied.library_source,
                                  install_resolution=resolution(('plugin.skipped', InstallResolution.SKIPPED)))
        self.library.associated_plan_target.return_value = self.applied
        self.run_flow()
        self.assertEqual(self.coordinator.install_target.call_args.kwargs['resolution_choices'],
                         {'plugin.skipped': ResolutionChoice.SKIP})
        self.ui.repair_message.assert_called_with(32816)

    def test_different_revision_uses_same_build_and_profile_only(self):
        other = LibraryEntry('b' * 64, 'demo', '2.0.0', 'Friendly Build', ('other',))
        wrong_profile = LibraryEntry('c' * 64, 'demo', '3.0.0', 'Friendly Build', ('desk',))
        unrelated = LibraryEntry('d' * 64, 'unrelated', '1.0.0', 'Unrelated', ('other',))
        self.library.list_builds.return_value = (self.applied_entry, other, wrong_profile, unrelated)
        desired = PlanTarget('/private/manifest', 'other', '/private/frozen',
                             library_source=LibrarySource('/private/library', other.entry_id))
        self.library.plan_target.return_value = desired
        self.ui.repair_choose_action.side_effect = ['revision', 'check', None]
        self.ui.choose_repair_revision.return_value = other
        derive = self.run_flow()
        offered = self.ui.choose_repair_revision.call_args.args[0]
        self.assertEqual([e.entry_id for e in offered], [self.applied_entry.entry_id, other.entry_id])
        self.library.plan_target.assert_called_once_with(other.entry_id, 'other')
        self.assertEqual(self.service.preview.call_args.args[0], desired)
        derive.assert_called_once_with(desired)
        self.library.current_selection.assert_not_called()
        self.library.select.assert_not_called()

    def test_choosing_a_revision_previews_and_writes_nothing(self):
        other = LibraryEntry('b' * 64, 'demo', '2.0.0', 'Friendly Build', ('other',))
        self.library.list_builds.return_value = (self.applied_entry, other)
        self.library.plan_target.return_value = self.applied
        self.ui.repair_choose_action.side_effect = ['revision', None]
        self.ui.choose_repair_revision.return_value = other
        self.run_flow()
        self.service.preview.assert_not_called()
        self.assert_no_apply()
        written = {call[0] for call in self.library.mock_calls if call[0]}
        self.assertTrue(written <= {'associated_plan_target', 'get', 'list_builds', 'plan_target'}, written)

    def test_without_another_compatible_revision_the_user_is_told_safely(self):
        self.ui.repair_choose_action.side_effect = ['revision', None]
        self.run_flow()
        self.ui.repair_message.assert_called_with(repair.S_NO_OTHER_REVISION)
        self.ui.choose_repair_revision.assert_not_called()

    def test_selecting_the_applied_revision_again_restores_the_verified_target(self):
        self.ui.repair_choose_action.side_effect = ['revision', 'check', None]
        self.ui.choose_repair_revision.return_value = self.applied_entry
        other = LibraryEntry('b' * 64, 'demo', '2.0.0', 'Friendly Build', ('other',))
        self.library.list_builds.return_value = (self.applied_entry, other)
        self.run_flow()
        self.library.plan_target.assert_not_called()
        self.assertEqual(self.service.preview.call_args.args[0], self.applied)


class RepairNativeTests(unittest.TestCase):
    def dialog(self, selects=(), answers=()):
        return Dialog(selects, answers)

    def test_repair_route_invokes_the_real_provider_once(self):
        workflow = Mock()
        provider = Mock(return_value=workflow)
        NativeDialogs(Addon(), self.dialog([2, -1]), lambda ms: None, repair_provider=provider).run()
        provider.assert_called_once_with()
        workflow.run.assert_called_once()

    def test_composition_failure_is_safe_and_redacted(self):
        dialog = self.dialog([2, -1])
        NativeDialogs(Addon(), dialog, lambda ms: None,
                      repair_provider=Mock(side_effect=RuntimeError('/private/path token=secret'))).run()
        self.assertEqual(dialog.oks, [(STRINGS[32102], STRINGS[repair.S_NOT_APPLIED])])
        self.assertNotIn('private', dialog.everything())

    def test_help_from_the_overview_opens_the_update_repair_help(self):
        dialog = self.dialog([3, 4])
        action = NativeDialogs(Addon(), dialog, lambda ms: None).repair_choose_action(_summary())
        self.assertIsNone(action)
        self.assertEqual(dialog.views[-1][0], STRINGS[32203])
        self.assertIn('not supported yet', dialog.views[-1][1])

    def test_overview_offers_check_revision_help_and_back_only(self):
        dialog = self.dialog([1])
        action = NativeDialogs(Addon(), dialog, lambda ms: None).repair_choose_action(_summary())
        self.assertEqual(action, 'check')
        self.assertEqual(dialog.labels[0][1], [STRINGS[repair.S_APPLIED_ROW] % ('Friendly Build', '1.0.0', 'desk'),
                                              STRINGS[32903], STRINGS[32904], STRINGS[32112], STRINGS[32113]])

    def test_apply_requires_choosing_apply_and_explicit_confirmation(self):
        ui = NativeDialogs(Addon(), self.dialog([0], [True]), lambda ms: None)
        self.assertTrue(ui.repair_approve(_summary(), _changes_model()))
        self.assertEqual(ui.dialog.questions[0][0], STRINGS[repair.S_CONFIRM_APPLY])
        for selects, answers in (([1], []), ([0], [False]), ([-1], [])):
            with self.subTest(selects=selects, answers=answers):
                ui = NativeDialogs(Addon(), self.dialog(selects, answers), lambda ms: None)
                self.assertFalse(ui.repair_approve(_summary(), _changes_model()))

    def test_blocked_and_no_op_presentation_never_offers_apply(self):
        dialog = self.dialog()
        ui = NativeDialogs(Addon(), dialog, lambda ms: None)
        ui.repair_show(_blocked_model(), (repair.S_NOTE_DIFFERENT_VERSION,))
        ui.repair_show_healthy(_changes_model())
        self.assertEqual(dialog.labels, [])
        self.assertIn(STRINGS[repair.S_NOTE_DIFFERENT_VERSION], dialog.views[0][1])
        self.assertEqual(dialog.views[1][0], STRINGS[repair.S_HEALTHY_TITLE])

    def test_presentation_never_shows_entry_ids_paths_or_private_values(self):
        applied = LibraryEntry('a' * 64, 'demo', '1.0.0', 'Friendly Build', ('desk',))
        library = Mock()
        library.associated_plan_target.return_value = PlanTarget(
            '/private/manifest', 'desk', '/private/frozen',
            library_source=LibrarySource('/private/library', applied.entry_id))
        library.get.return_value = applied
        library.list_builds.return_value = (applied,)
        service = Mock()
        service.preview.return_value = plan(PlanState.NO_CHANGES)
        factory = Mock()
        workflow = UpdateRepairWorkflow(library, service, Mock(), factory)
        dialog = self.dialog([1, 4])
        NativeDialogs(Addon(), dialog, lambda ms: None, repair_provider=lambda: workflow).repair()
        visible = dialog.everything()
        self.assertIn('Friendly Build', visible)
        for leaked in ('a' * 64, '/private', 'manifest', 'frozen', 'library'):
            self.assertNotIn(leaked, visible)
        factory.assert_not_called()


class RepairStringTests(unittest.TestCase):
    def test_stale_unavailable_copy_is_removed_and_limits_are_stated(self):
        self.assertNotIn('not available in this frontend build', STRINGS[32122])
        self.assertNotIn('remains unavailable', STRINGS[32302])
        self.assertIn('Update / Repair works from the build already applied', STRINGS[32302])
        self.assertIn('not supported yet', STRINGS[32303])
        self.assertNotIn('fixes a device', STRINGS[32303])
        self.assertIn('Does not reinstall everything', STRINGS[32303])

    def test_every_repair_identifier_is_defined_plain_and_bounded(self):
        for name, value in vars(repair).items():
            if not name.startswith('S_') or type(value) is not int:
                continue
            with self.subTest(name=name):
                self.assertIn(value, STRINGS)
                self.assertLess(len(STRINGS[value]), 400)
                self.assertNotIn('\\u', STRINGS[value])


def offering_install_current():
    """A missing-package decision that offers the repository-current package."""
    return plan(PlanState.DECISION_REQUIRED, rows=(SoftwareRow(
        'plugin.demo', SoftwareAction.DECISION, 'Demo', '1.0.0',
        (DecisionChoice.INSTALL_CURRENT, DecisionChoice.SKIP, DecisionChoice.CANCEL)),))


def _summary(changed=False):
    return repair.RepairSummary('Friendly Build', '1.0.0', 'desk', 'Friendly Build', '1.0.0', changed)


def _changes_model():
    from resources.lib.ui.plan_view import ReviewViewModel
    return ReviewViewModel.from_plan(plan(), fully_listed=True)


def _blocked_model():
    from resources.lib.ui.plan_view import ReviewViewModel
    blocked = plan(PlanState.BLOCKED, rows=(SoftwareRow('plugin.demo', SoftwareAction.DIFFERENT_VERSION, 'Demo', '2.0.0'),),
                   blockers=(PlanBlocker(BlockerCode.DIFFERENT_VERSION_INSTALLED, 'plugin.demo', 'Demo'),))
    return ReviewViewModel.from_plan(blocked, fully_listed=True)


if __name__ == '__main__':
    unittest.main()
