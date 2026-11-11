"""Offline fault injection for shared Install/Repair preview conversion."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from resources.lib import failure_diagnostics as diag, plan_model
from resources.lib.ui import plan_view, repair_view
from resources.lib.ui.native_dialogs import NativeDialogs
from tests import test_update_repair_workflow as fixture

SECRET = '/private/profile credential=secret build-name private-value'
PREFIX = '[script.build.manager] diagnostic phase=install.plan_conversion.'


class PlanConversionDiagnostics(unittest.TestCase):
    def setUp(self):
        self.logs = []
        logger = patch.dict(sys.modules, xbmc=SimpleNamespace(LOGINFO=1,
            log=lambda message, level: self.logs.append(message)))
        logger.start()
        self.addCleanup(logger.stop)

    def flow(self):
        value = fixture.RepairWorkflowTests()
        value.setUp()
        return value

    def assert_attribution(self, suffix, name='TypeError'):
        errors = [line for line in self.logs if line.startswith(PREFIX) and ' exception=' in line]
        self.assertEqual(errors, [PREFIX + suffix + ' exception=' + name])
        for line in self.logs:
            self.assertRegex(line, r'^\[script.build.manager\] diagnostic phase=[a-z_.]+(?: exception=[A-Za-z_][A-Za-z0-9_]*)?$')
        for forbidden in (SECRET, 'plugin.demo', 'Friendly Build', 'Traceback'):
            self.assertNotIn(forbidden, '\n'.join(self.logs))

    def assert_no_apply(self, f):
        f.service.preview.assert_called_once()
        f.assert_no_apply()
        f.ui.execute_install.assert_not_called()
        f.preparation.prepare.assert_not_called()
        f.factory.assert_not_called()
        f.coordinator.install_target.assert_not_called()

    def test_repository_argument_failure_precedes_entry_and_all_apply_gates(self):
        f = self.flow()
        target = SimpleNamespace(**vars(f.applied))
        target.choices = (None,)  # Controlled malformed input; never a runtime target.
        f.library.associated_plan_target.return_value = target
        with self.assertRaises(TypeError): f.run_flow()
        self.assert_attribution('repository_current')
        self.assertFalse(any(x.startswith(PREFIX + 'entry') for x in self.logs))
        self.assert_no_apply(f)

    def test_entry_rejection_has_only_entry_failure(self):
        with self.assertRaises(ValueError):
            plan_view.ReviewViewModel.from_plan(object(), diagnostic=diag.emit)
        self.assert_attribution('entry', 'ValueError')

    def test_each_helper_failure_is_innermost_and_cannot_apply(self):
        cases = (('_sections', 'sections'), ('DecisionPrompt', 'decisions'),
                 ('_confirmation_summary', 'confirmation_summary'))
        for helper, suffix in cases:
            with self.subTest(helper=helper):
                self.logs.clear(); f = self.flow()
                if suffix == 'decisions':
                    f.service.preview.return_value = fixture.plan(fixture.PlanState.DECISION_REQUIRED)
                error = TypeError(SECRET)
                with patch.object(plan_view, helper, side_effect=error):
                    with self.assertRaises(TypeError) as caught: f.run_flow()
                self.assertIs(caught.exception, error)
                self.assert_attribution(suffix)
                self.assertIn('[script.build.manager] diagnostic phase=install.plan_conversion exception=TypeError', self.logs)
                self.assert_no_apply(f)

    def test_timestamp_and_model_failures_keep_generic_repair_fallback(self):
        for suffix in ('timestamp', 'model'):
            with self.subTest(suffix=suffix):
                self.logs.clear(); f = self.flow()
                ui = NativeDialogs(fixture.Addon(), None, lambda _: None,
                    repair_provider=lambda: SimpleNamespace(run=lambda _: f.workflow.run(f.ui)))
                ui.repair_message = Mock()
                if suffix == 'timestamp':
                    parser = Mock(side_effect=TypeError(SECRET))
                    injection = patch.object(plan_model, 'datetime', SimpleNamespace(strptime=parser))
                else:
                    injection = patch.object(plan_view.ReviewViewModel, '__init__', side_effect=TypeError(SECRET))
                with injection: ui.repair()
                self.assert_attribution(suffix)
                ui.repair_message.assert_called_once_with(repair_view.S_NOT_APPLIED)
                self.assert_no_apply(f)
                if suffix == 'timestamp': parser.assert_called_once()

    def test_successful_models_and_rendered_text_are_unchanged(self):
        for state in (fixture.PlanState.NO_CHANGES, fixture.PlanState.CHANGES_READY,
                      fixture.PlanState.DECISION_REQUIRED, fixture.PlanState.RESOLUTION_REQUIRED):
            with self.subTest(state=state):
                source = fixture.plan(state)
                with patch.object(plan_model.BuildPlan, 'checked_time_label', return_value='10:01') as clock:
                    expected = plan_view.ReviewViewModel.from_plan(source)
                    actual = plan_view.ReviewViewModel.from_plan(source, diagnostic=diag.emit)
                    self.assertEqual(actual, expected)
                    self.assertEqual(clock.call_count, 2)  # one per conversion, as before
                ui = NativeDialogs(fixture.Addon(), None, lambda _: None)
                self.assertEqual(ui.review_body(actual), ui.review_body(expected))
        self.assertFalse(any('exception=' in x for x in self.logs))

    def test_observer_and_logger_failures_preserve_results_exceptions_and_call_counts(self):
        source = fixture.plan()
        observer = Mock(side_effect=RuntimeError(SECRET))
        self.assertEqual(plan_view.ReviewViewModel.from_plan(source, diagnostic=observer),
                         plan_view.ReviewViewModel.from_plan(source))
        error = TypeError(SECRET)
        with patch.object(plan_view, '_sections', side_effect=error):
            with self.assertRaises(TypeError) as caught:
                plan_view.ReviewViewModel.from_plan(source, diagnostic=observer)
        self.assertIs(caught.exception, error)
        sys.modules['xbmc'].log = Mock(side_effect=RuntimeError(SECRET))
        f = self.flow(); f.run_flow()
        f.service.preview.assert_called_once()
        f.ui.repair_approve.assert_called_once()
        f.service.validate.assert_called_once()
        f.coordinator.install_target.assert_called_once()
        f.ui.repair_message.assert_called_once_with(32809)
