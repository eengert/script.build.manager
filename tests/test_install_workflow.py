"""Offline selection, review approval, preparation and execution binding tests."""
from dataclasses import replace
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from resources.lib.install_workflow import InstallWorkflow
from resources.lib.build_library import LibraryEntry, LibrarySource, LibraryInstallTarget, isolated_library_install_authority
from resources.lib.plan import PlanTarget
from resources.lib.plan_model import *
from resources.lib.status_model import OperationKind, OperationStatus, CheckGap
from resources.lib.frozen_install import FrozenInstallResult
from resources.lib.frozen_resolution import ResolutionChoice
from resources.lib.repository_preparation import PreparationCode
from resources.lib.ui.native_dialogs import NativeDialogs
from resources.lib.ui.controller import Route
from tests.test_create_workflow import NativeDialog
from tests.test_status_ui import Addon
from tests import test_build_library as library_fixture


def plan(state=PlanState.CHANGES_READY, rows=None, serial='one'):
    rows = rows if rows is not None else (
        SoftwareRow('plugin.demo', SoftwareAction.INSTALL_EXACT, 'Demo', '2.0.0'),)
    if state is PlanState.NO_CHANGES:
        rows = (SoftwareRow('plugin.demo', SoftwareAction.CURRENT, 'Demo'),)
    return BuildPlan(state, '2026-10-07T12:00:00Z', rows,
        SkinPlan(SkinPlanKind.NOT_APPLICABLE), SettingsPlan(SettingsPlanKind.NOT_APPLICABLE),
        PrivatePlan(PrivatePlanKind.NOT_USED), RestartPlan(RestartExpectation.EXPECTED),
        blockers=(PlanBlocker(BlockerCode.BUILD_DEFINITION_INVALID),) if state is PlanState.BLOCKED else (),
        gaps=(CheckGap.INSPECTION_FAILED,) if state is PlanState.INCOMPLETE else (),
        review=ReviewIdentity.from_material({c: serial for c in IdentityComponent})
            if state is PlanState.CHANGES_READY else None)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.entry = LibraryEntry('a'*64, 'demo', '1.0.0', 'Friendly Build', ('desk', 'other'))
        self.target = PlanTarget('/private/manifest', 'other', '/private/frozen',
                                 library_source=LibrarySource('/private/library', self.entry.entry_id))
        self.library = Mock()
        self.library.list_builds.return_value = (self.entry,)
        self.library.plan_target.return_value = self.target
        self.library.current_selection.side_effect = AssertionError('saved selection forbidden')
        self.library.select.side_effect = AssertionError('selection mutation forbidden')
        self.service = Mock()
        self.service.preview.return_value = plan()
        self.service.validate.return_value = ReviewCheck(ReviewFreshness.CURRENT)
        self.prepare = Mock()
        self.coordinator = Mock()
        self.coordinator.install_target.return_value = FrozenInstallResult('complete')
        self.factory = Mock(return_value=self.coordinator)
        self.operation = Mock(return_value=OperationStatus())
        self.workflow = InstallWorkflow(self.library, self.service, self.prepare, self.factory, self.operation)
        self.ui = Mock()
        self.ui.choose_install_build.return_value = self.entry
        self.ui.choose_install_profile.return_value = 'other'
        self.ui.confirm_install.return_value = True
        self.ui.prepare_install.side_effect = lambda f: f()
        self.ui.execute_install.side_effect = lambda f: f()

    def run_flow(self):
        with patch('resources.lib.install_workflow.LibraryInstallTarget.from_plan_target') as derive:
            self.workflow.run(self.ui)
            return derive

    def assert_no_execution(self):
        self.factory.assert_not_called()
        self.coordinator.install_target.assert_not_called()

    def test_exact_binding_validate_then_execute(self):
        events = []
        self.service.validate.side_effect = lambda t,r: (events.append(('validate', t, r)) or ReviewCheck(ReviewFreshness.CURRENT))
        self.coordinator.install_target.side_effect = lambda *a,**k: (events.append(('execute',)) or FrozenInstallResult('complete'))
        derive = self.run_flow()
        self.library.plan_target.assert_called_once_with(self.entry.entry_id, 'other')
        self.service.preview.assert_called_once_with(self.target)
        self.service.validate.assert_called_once_with(self.target, self.service.preview.return_value.review)
        derive.assert_called_once_with(self.target)
        self.coordinator.install_target.assert_called_once_with(derive.return_value,
            prepared_resolution=None, resolution_choices={}, interactive=False)
        self.assertEqual([e[0] for e in events], ['validate','execute'])
        self.prepare.prepare.assert_not_called()
        self.library.select.assert_not_called()
        self.library.current_selection.assert_not_called()
        self.ui.install_message.assert_called_once_with(32809)

    def test_empty_library(self):
        self.library.list_builds.return_value = ()
        self.run_flow()
        self.ui.install_message.assert_called_once_with(32802)
        self.service.preview.assert_not_called()
        self.assert_no_execution()

    def test_cancel_build_or_profile(self):
        for method in ('choose_install_build', 'choose_install_profile'):
            with self.subTest(method=method):
                self.setUp()
                getattr(self.ui, method).return_value = None
                self.run_flow()
                self.library.plan_target.assert_not_called()
                self.assert_no_execution()

    def test_non_reviewable_states(self):
        for state in (PlanState.NO_CHANGES, PlanState.BLOCKED, PlanState.INCOMPLETE):
            with self.subTest(state=state):
                self.setUp()
                self.service.preview.return_value = plan(state)
                self.run_flow()
                self.ui.show_install_review.assert_called_once()
                self.ui.confirm_install.assert_not_called()
                self.service.validate.assert_not_called()
                self.assert_no_execution()

    def test_decline_apply(self):
        self.ui.confirm_install.return_value = False
        self.run_flow()
        self.service.validate.assert_not_called()
        self.assert_no_execution()

    def decision(self, offered=(DecisionChoice.SKIP, DecisionChoice.CANCEL)):
        return plan(PlanState.DECISION_REQUIRED, (
            SoftwareRow('plugin.demo', SoftwareAction.DECISION, 'Demo', '1.0.0', offered),))

    def test_skip_remains_bound_and_only_offered_choices(self):
        self.service.preview.side_effect = [self.decision(), plan()]
        self.ui.choose_install_decision.return_value = DecisionChoice.SKIP
        derive = self.run_flow()
        prompt = self.ui.choose_install_decision.call_args.args[0]
        self.assertEqual(prompt.choices, (DecisionChoice.SKIP, DecisionChoice.CANCEL))
        chosen = self.service.preview.call_args_list[1].args[0]
        self.assertEqual(chosen.choices, (('plugin.demo', DecisionChoice.SKIP),))
        self.assertEqual(chosen.library_source, self.target.library_source)
        derive.assert_called_once_with(chosen)
        self.assertEqual(self.coordinator.install_target.call_args.kwargs['resolution_choices'],
                         {'plugin.demo': ResolutionChoice.SKIP})
        self.ui.install_message.assert_called_with(32816)

    def test_cancel_missing_package_and_unoffered_answer(self):
        for answer in (None, DecisionChoice.CANCEL, DecisionChoice.INSTALL_CURRENT):
            with self.subTest(answer=answer):
                self.setUp()
                self.service.preview.return_value = self.decision()
                self.ui.choose_install_decision.return_value = answer
                self.run_flow()
                self.assert_no_execution()
                self.prepare.prepare.assert_not_called()

    def test_stale_and_unverifiable_require_another_approval(self):
        for freshness in (ReviewFreshness.STALE, ReviewFreshness.UNVERIFIABLE):
            for approve_again in (False, True):
                with self.subTest(freshness=freshness, approve_again=approve_again):
                    self.setUp()
                    old, new = plan(serial='old'), plan(serial='new')
                    self.service.preview.side_effect = [old, new]
                    self.service.validate.side_effect = [ReviewCheck(freshness,
                        (IdentityComponent.SOFTWARE_STATE,) if freshness is ReviewFreshness.STALE else ()),
                        ReviewCheck(ReviewFreshness.CURRENT)]
                    self.ui.confirm_install.side_effect = [True, approve_again]
                    self.run_flow()
                    self.assertEqual(self.ui.confirm_install.call_count, 2)
                    self.assertIs(self.ui.confirm_install.call_args_list[1].args[2].state, PlanState.CHANGES_READY)
                    self.ui.install_message.assert_any_call(32808)
                    if approve_again:
                        self.service.validate.assert_called_with(self.target, new.review)
                        self.coordinator.install_target.assert_called_once()
                    else:
                        self.assert_no_execution()

    def test_pending_operation_prevents_selection_and_execution(self):
        for kind, text in ((OperationKind.RESTART_REQUIRED,32810),
                           (OperationKind.NEEDS_ATTENTION,32812), (OperationKind.UNAVAILABLE,32811)):
            with self.subTest(kind=kind):
                self.setUp()
                self.operation.return_value = SimpleNamespace(kind=kind)
                self.run_flow()
                self.library.list_builds.assert_not_called()
                self.ui.install_message.assert_called_once_with(text)
                self.assert_no_execution()

    def test_result_codes_ignore_raw_messages(self):
        for outcome, text in (('complete',32809),('awaiting_restart',32810),('active',32811),
                ('needs_attention',32817),('cancelled',32813),('failed',32814),
                ('user_resolution_required',32814),('unknown',32814)):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.coordinator.install_target.return_value = FrozenInstallResult(outcome,
                    message='/private/secret https://password@example.invalid ' + 'b'*64)
                self.run_flow()
                self.ui.install_message.assert_called_once_with(text)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.f = library_fixture.LibraryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_nonterminal_declined_and_stale_preserve_durable_applied_record(self):
        entry = self.f.register()
        library = self.f.library
        self.f.record_applied(entry, "desk")
        library.select(entry.entry_id, "other")
        before = (self.f.root / "applied.json").read_bytes()
        for case in ("cancelled", "failed", "active", "needs_attention",
                     "user_resolution_required", "awaiting_restart", "unknown", "declined", "stale"):
            with self.subTest(case=case):
                ui = Mock()
                ui.choose_install_build.return_value = entry
                ui.choose_install_profile.return_value = "other"
                ui.confirm_install.return_value = case not in ("declined", "stale")
                ui.execute_install.side_effect = lambda f: f()
                service = Mock()
                service.preview.return_value = plan()
                service.validate.return_value = ReviewCheck(ReviewFreshness.CURRENT)
                if case == "stale":
                    ui.confirm_install.side_effect = [True, False]
                    service.validate.return_value = ReviewCheck(ReviewFreshness.STALE, (IdentityComponent.BUILD,))
                coordinator = Mock()
                coordinator.install_target.return_value = FrozenInstallResult(case)
                workflow = InstallWorkflow(library, service, Mock(), lambda: coordinator,
                                           lambda: OperationStatus())
                with isolated_library_install_authority(library), patch.object(
                        library_fixture.lib.BuildLibrary, "_record_applied_completion", side_effect=AssertionError):
                    workflow.run(ui)
                self.assertEqual((self.f.root / "applied.json").read_bytes(), before)
                self.assertEqual(library.current_applied_association().device_profile_id, "desk")
                if case in ("declined", "stale"):
                    coordinator.install_target.assert_not_called()

    def test_readonly_arbitrary_target_preserves_saved_selection(self):
        entry = self.f.register()
        self.f.library.select(entry.entry_id, 'desk')
        before = (self.f.root / 'selection.json').read_bytes()
        with patch.object(self.f.library, 'current_selection', side_effect=AssertionError):
            target = self.f.library.plan_target(entry.entry_id, 'other')
        self.assertEqual(target.library_source, LibrarySource(str(self.f.root), entry.entry_id))
        self.assertEqual(target.device_profile_id, 'other')
        self.assertEqual((self.f.root / 'selection.json').read_bytes(), before)
        with self.assertRaises(Exception):
            self.f.library.plan_target(entry.entry_id, 'invented')


class NativeTests(unittest.TestCase):
    def ui(self, dialog, provider=None):
        return NativeDialogs(Addon(), dialog, lambda _: None, install_provider=provider)

    def test_install_route_and_update_unavailable(self):
        workflow = Mock()
        d = NativeDialog([1,-1])
        self.ui(d, lambda: workflow).run()
        workflow.run.assert_called_once()
        d = NativeDialog([2,0,-1,-1])
        self.ui(d, lambda: workflow).run()
        self.assertIn('not available', d.details[0][1])
        self.assertEqual(workflow.run.call_count, 1)

    def test_safe_composition_failure(self):
        d = NativeDialog([1,-1])
        self.ui(d, Mock(side_effect=RuntimeError('/private/path https://secret.invalid'))).run()
        self.assertEqual(d.results, [(Addon().getLocalizedString(32101), Addon().getLocalizedString(32814))])

    def test_friendly_build_and_only_declared_profiles(self):
        e = LibraryEntry('a'*64, 'internal', '1.2.0', 'Friendly', ('desk','other'))
        d = NativeDialog([0,1])
        ui = self.ui(d)
        self.assertIs(ui.choose_install_build((e,)), e)
        self.assertEqual(ui.choose_install_profile(e.device_profiles), 'other')
        labels = d.calls[0][1][0]
        self.assertIn('Friendly 1.2.0', labels)
        self.assertIn('desk, other', labels)
        self.assertNotIn(e.entry_id, labels)
        self.assertNotIn('internal', labels)
        self.assertEqual(d.calls[1][1], ['desk','other'])

    def test_safe_default_confirmation_and_help_return(self):
        e = LibraryEntry('a'*64, 'internal', '1.2.0', 'Friendly', ('desk',))
        from resources.lib.ui.plan_view import ReviewViewModel
        d = NativeDialog([2,0,1], confirms=[False])
        ui = self.ui(d)
        self.assertFalse(ui.confirm_install(e, 'desk', ReviewViewModel.from_plan(plan())))
        self.assertEqual(d.calls[0][2], 0)
        args, kwargs = d.questions[0]
        body = args[1]
        # Build Manager leaves Kodi's documented safe No-button default intact.
        self.assertNotIn('defaultbutton', kwargs)
        self.assertEqual(kwargs['nolabel'], Addon().getLocalizedString(32113))
        self.assertEqual(kwargs['yeslabel'], Addon().getLocalizedString(32807))
        self.assertEqual(body.splitlines(), [
            'Friendly 1.2.0',
            'Choose a device profile: desk',
            'Install Demo 2.0.0',
            'Temporary protection and a full Kodi restart may be required.',
        ])
        self.assertEqual(d.calls[1][2], 2)
        self.assertNotIn('a'*64, json.dumps(d.questions))

    def test_compact_confirmation_shows_the_single_friendly_change_in_four_lines(self):
        from resources.lib.ui.plan_view import ReviewViewModel
        entry = LibraryEntry('a'*64, 'internal-build-id', '1.0.0',
                             'BM-UI-003C-20261007', ('current-device-8794224972c6',))
        rows = (SoftwareRow('repository.eengert', SoftwareAction.ENABLE, 'Eengert Repository'),)
        model = ReviewViewModel.from_plan(plan(rows=rows))
        dialog = NativeDialog([1], confirms=[False])
        self.assertFalse(self.ui(dialog).confirm_install(
            entry, 'current-device-8794224972c6', model))

        args, kwargs = dialog.questions[0]
        body = args[1]
        self.assertEqual(body.splitlines(), [
            'BM-UI-003C-20261007 1.0.0',
            'Choose a device profile: current-device-8794224972c6',
            'Enable Eengert Repository',
            'Temporary protection and a full Kodi restart may be required.',
        ])
        self.assertLessEqual(len(body.splitlines()), 4)
        self.assertNotIn('\n\n', body)
        self.assertEqual(body.splitlines()[-1],
                         'Temporary protection and a full Kodi restart may be required.')
        for section in ('Add-ons', 'Settings', 'Skin', 'Private', 'Restart'):
            self.assertNotIn(section, body)
        for sensitive in ('repository.eengert', 'internal-build-id', 'a'*64,
                          '/private/', 'https://', 'SENTINEL_PRIVATE_VALUE'):
            self.assertNotIn(sensitive, body)
        self.assertNotIn('defaultbutton', kwargs)
        self.assertEqual(kwargs['nolabel'], 'Back')
        self.assertEqual(kwargs['yeslabel'], 'Apply Build')

    def test_multiple_changes_use_a_compact_count_and_accepted_skips_are_counted(self):
        from resources.lib.ui.plan_view import ReviewViewModel
        entry = LibraryEntry('a'*64, 'internal-build-id', '1.2.0', 'Friendly Build', ('desk',))
        rows = (
            SoftwareRow('plugin.demo', SoftwareAction.ENABLE, 'Demo Video'),
            SoftwareRow('plugin.module', SoftwareAction.INSTALL_EXACT, 'Demo Module', '2.0.0'),
        )
        model = ReviewViewModel.from_plan(plan(rows=rows))
        dialog = NativeDialog([1], confirms=[False])
        self.assertFalse(self.ui(dialog).confirm_install(entry, 'desk', model))
        body = dialog.questions[0][0][1]
        self.assertEqual(body.splitlines(), [
            'Friendly Build 1.2.0',
            'Choose a device profile: desk',
            'This build — changes: 2; accepted skips: 0',
            'Temporary protection and a full Kodi restart may be required.',
        ])
        for detail in ('Demo Video', 'Demo Module', 'Add-ons', 'Settings', 'Skin', 'Private', 'Restart'):
            self.assertNotIn(detail, body)

        exception_rows = (
            SoftwareRow('plugin.demo', SoftwareAction.ENABLE, 'Demo Video'),
            SoftwareRow('plugin.skip.one', SoftwareAction.ACCEPTED_SKIP, 'Skipped Alpha'),
            SoftwareRow('plugin.skip.two', SoftwareAction.ACCEPTED_SKIP, 'Skipped Beta'),
        )
        exception_model = ReviewViewModel.from_plan(plan(rows=exception_rows))
        exception_dialog = NativeDialog([1], confirms=[False])
        self.assertFalse(self.ui(exception_dialog).confirm_install(entry, 'desk', exception_model))
        exception_body = exception_dialog.questions[0][0][1]
        self.assertIn('This build — changes: 1; accepted skips: 2', exception_body)
        self.assertNotIn('Skipped Alpha', exception_body)
        self.assertNotIn('Skipped Beta', exception_body)
        self.assertEqual(exception_body.splitlines()[-1],
                         'Temporary protection and a full Kodi restart may be required.')

    def test_prepared_repository_label_actual_version(self):
        from resources.lib.ui.plan_view import ReviewViewModel
        d = NativeDialog([])
        ui = self.ui(d)
        model = ReviewViewModel.from_plan(plan(), repository_current=('plugin.demo',))
        body = ui.review_body(model)
        self.assertIn('current version of Demo 2.0.0', body)
        self.assertIn('may differ', body)


class PreparationFlowTests(unittest.TestCase):
    def setUp(self):
        from tests import test_repository_preparation as fixture
        self.f = fixture.RepositoryPreparationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.initial = replace(self.f.target(), choices=())
        self.library = self.f.f.fixture.library
        self.h = self.f.harness()
        from resources.lib.resolver import resolve_manifest
        from resources.lib.plan import ReadOnlyArtifactStore
        self.service = self.h.plan_service(status=self.h.owners(resolver=resolve_manifest),
            artifact_store=ReadOnlyArtifactStore(self.f.store.root))

    def test_real_native_preparation_review_validate_and_saved_package_execution(self):
        from tests.test_library_install import forbidden
        from tests.test_status import DEMO
        events, targets, reviewed, checks = [], [], [], []
        service = Mock()
        def preview(target):
            result = self.service.preview(target)
            events.append(result.state)
            targets.append(target)
            return result
        service.preview.side_effect = preview
        def validate(target, review):
            checks.append((target,review))
            return self.service.validate(target,review)
        service.validate.side_effect = validate
        preparation = Mock()
        preparation.prepare.side_effect = self.f.prepare
        coordinator = self.f.f.coordinator()
        executor = Mock()
        executor.install_target.side_effect = coordinator.install_target
        workflow = InstallWorkflow(self.library, service, preparation,
            lambda: executor, lambda: OperationStatus())
        dialog = NativeDialog([0,0,0,0,1], confirms=[True])
        ui = NativeDialogs(Addon(), dialog, lambda _: None)
        original_confirm = ui.confirm_install
        def confirm(entry, profile, model):
            reviewed.append(model)
            return original_confirm(entry, profile, model)
        ui.confirm_install = confirm
        with self.f.f.isolated(), patch.object(self.f.f.backend, 'resolve_repository_current', side_effect=forbidden):
            workflow.run(ui)
        self.assertEqual(events, [PlanState.DECISION_REQUIRED, PlanState.RESOLUTION_REQUIRED,
                                  PlanState.CHANGES_READY])
        preparation.prepare.assert_called_once_with(targets[1])
        prepared = targets[2].prepared_resolution
        self.assertIsNotNone(prepared)
        self.assertEqual(targets[2].library_source, targets[0].library_source)
        self.assertEqual(targets[2].device_profile_id, targets[0].device_profile_id)
        self.assertEqual(targets[2].choices, targets[1].choices)
        self.assertIs(checks[0][0], targets[2])
        kwargs = executor.install_target.call_args.kwargs
        self.assertIs(kwargs['prepared_resolution'], prepared)
        self.assertEqual(kwargs['resolution_choices'], {DEMO: ResolutionChoice.INSTALL_CURRENT})
        self.assertEqual(set(kwargs), {'prepared_resolution','resolution_choices','interactive'})
        self.assertFalse(kwargs['interactive'])
        exact = executor.install_target.call_args.args[0]
        self.assertEqual(exact.source, targets[2].library_source)
        self.assertEqual(exact.device_profile_id, targets[2].device_profile_id)
        self.assertEqual(self.f.f.backend.installed[DEMO].version, '2.0.0')
        text = json.dumps([dialog.calls, dialog.details, dialog.questions, dialog.results])
        self.assertIn('current version of ' + DEMO + ' 2.0.0', text)
        self.assertIn('may differ', text)
        for sensitive in (str(self.library.root), exact.source.entry_id, prepared.source_identity,
                          'http://127.0.0.1', 'repository.demo'):
            self.assertNotIn(sensitive, text)
        self.assertEqual(len(self.f.downloads), 2)  # index/package once, none after Apply
        self.assertEqual(dialog.results[-1][1], Addon().getLocalizedString(32816))
        self.h.assert_untouched()

    def test_real_preparation_failure_never_reviews_or_executes(self):
        self.f.index = b'invalid xml /secret/path https://private.invalid'
        preparation = Mock()
        preparation.prepare.side_effect = self.f.prepare
        executor = Mock()
        workflow = InstallWorkflow(self.library, self.service, preparation,
            executor, lambda: OperationStatus())
        dialog = NativeDialog([0,0,0])
        ui = NativeDialogs(Addon(), dialog, lambda _: None)
        workflow.run(ui)
        executor.assert_not_called()
        self.assertFalse(dialog.questions)
        self.assertEqual(dialog.results[-1][1], Addon().getLocalizedString(32804))
        self.f.f.assert_no_mutation()


class CompositionTests(unittest.TestCase):
    def test_import_default_performs_no_runtime_work(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('offline_install_entrypoint',
            Path(__file__).resolve().parents[1] / 'default.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'xbmc': None, 'xbmcvfs': None, 'xbmcgui': None}):
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))

    def test_runtime_factory_defers_preparation_and_execution_owners(self):
        from resources.lib.install_workflow import runtime_install_workflow
        with patch('resources.lib.build_library.default_build_library') as library, \
             patch('resources.lib.plan.default_plan_owners') as owners, \
             patch('resources.lib.artifacts.ArtifactStore') as artifacts, \
             patch('resources.lib.frozen_install.FrozenInstallStore') as transactions, \
             patch('resources.lib.frozen_install._default_policy_backend') as policy, \
             patch('resources.lib.restart_coordinator.RestartCoordinator') as restart:
            workflow = runtime_install_workflow()
            self.assertIs(workflow.library, library.return_value)
            artifacts.assert_not_called()
            transactions.assert_not_called()
            policy.assert_not_called()
            restart.assert_not_called()
            owners.assert_called_once_with()


class FullReviewTests(unittest.TestCase):
    def test_install_review_shows_every_version_and_skip(self):
        from resources.lib.ui.plan_view import ReviewViewModel
        rows = tuple(SoftwareRow('plugin.demo%d' % i, SoftwareAction.INSTALL_EXACT,
                     'Video %d' % i, '2.0.%d' % i) for i in range(20)) + (
                     SoftwareRow('plugin.skipped', SoftwareAction.ACCEPTED_SKIP, 'Skipped Video'),)
        model = ReviewViewModel.from_plan(plan(rows=rows), fully_listed=True)
        ui = NativeDialogs(Addon(), NativeDialog([]), lambda _: None)
        body = ui.review_body(model)
        for i in range(20):
            self.assertIn('Video %d 2.0.%d' % (i,i), body)
        self.assertIn('Skipped Video', body)


class UnresolvedTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    run_flow = WorkflowTests.run_flow
    assert_no_execution = WorkflowTests.assert_no_execution

    def test_ready_without_review_never_offers_apply(self):
        self.service.preview.return_value = replace(plan(), review=None)
        self.run_flow()
        self.ui.confirm_install.assert_not_called()
        self.assert_no_execution()

    def test_resolution_without_approved_current_cannot_prepare_or_apply(self):
        self.service.preview.return_value = plan(PlanState.RESOLUTION_REQUIRED, (
            SoftwareRow('plugin.demo', SoftwareAction.INSTALL_REPOSITORY, 'Demo'),))
        self.run_flow()
        self.prepare.prepare.assert_not_called()
        self.ui.confirm_install.assert_not_called()
        self.assert_no_execution()

    def test_provider_ignoring_decision_cannot_loop_or_apply(self):
        self.service.preview.return_value = WorkflowTests.decision(self)
        self.ui.choose_install_decision.return_value = DecisionChoice.SKIP
        self.run_flow()
        self.assertEqual(self.service.preview.call_count, 2)
        self.ui.confirm_install.assert_not_called()
        self.assert_no_execution()
