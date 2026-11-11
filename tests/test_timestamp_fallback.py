"""Optional timestamp failures never change health or plan authority."""
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from resources.lib import plan_model, status_model
from resources.lib.ui import plan_view, status_view
from resources.lib.ui.native_dialogs import NativeDialogs
from tests import test_status_ui as status_fixture
from tests import test_update_repair_workflow as repair_fixture
from tests import test_install_workflow as install_fixture

SECRET = '/private/profile token=secret private-setting build-name'


class TimestampFallback(unittest.TestCase):
    def setUp(self):
        self.logs = []
        logger = patch.dict(sys.modules, xbmc=SimpleNamespace(LOGINFO=1,
            log=lambda message, level: self.logs.append(message)))
        logger.start(); self.addCleanup(logger.stop)

    def parser_failure(self, module):
        return patch.object(module, 'datetime', SimpleNamespace(
            strptime=Mock(side_effect=TypeError(SECRET))))

    def test_current_changes_and_unchecked_status_keep_truth_and_single_provider_call(self):
        for source in (status_fixture.status(), status_fixture.changes_needed(), status_fixture.not_checked()):
            with self.subTest(overall=source.overall):
                provider = Mock(return_value=source)
                ui = NativeDialogs(status_fixture.Addon(), None, lambda _: None, status_provider=provider)
                with self.parser_failure(status_model):
                    model = ui.check_status()
                    body = ui.status_body(model)
                self.assertEqual(model.overall, source.overall)
                self.assertEqual(model.check_time, '')
                self.assertIn(status_fixture.STRINGS[status_view.OVERALL_LABEL[source.overall]], body)
                self.assertNotIn(status_fixture.STRINGS[status_view.S_CHECKED_AT].split('%')[0], body)
                provider.assert_called_once_with()
                self.assertNotIn(SECRET, body + '\n'.join(self.logs))

    def test_changes_ready_plan_keeps_rendered_changes_and_single_preview(self):
        f = repair_fixture.RepairWorkflowTests(); f.setUp()
        # Stop at the ordinary approval gate so no execution is possible.
        f.ui.repair_approve.return_value = False
        with self.parser_failure(plan_model): f.run_flow()
        f.service.preview.assert_called_once()
        f.ui.repair_approve.assert_called_once()
        model = f.ui.repair_approve.call_args.args[1]
        self.assertEqual(model.state, plan_model.PlanState.CHANGES_READY)
        self.assertEqual(model.check_time, '')
        self.assertEqual(model.confirmation_summary.change_count, 1)
        ui = NativeDialogs(repair_fixture.Addon(), None, lambda _: None)
        self.assertIn('Demo', ui.review_body(model))
        f.service.validate.assert_not_called()
        f.factory.assert_not_called()
        f.coordinator.install_target.assert_not_called()
        self.assertNotIn(SECRET, ui.review_body(model) + '\n'.join(self.logs))

    def test_successful_labels_keep_local_timezone_behavior(self):
        for source in (status_fixture.status(), repair_fixture.plan()):
            expected = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc).astimezone().strftime('%H:%M')
            # Use a fixed timestamp without changing the process timezone.
            from dataclasses import replace
            source = replace(source, checked_at='2026-10-07T12:00:00Z')
            self.assertEqual(source.checked_time_label(), expected)

    def test_typeerror_at_every_formatting_stage_is_local_to_optional_label(self):
        for module, source in ((status_model, status_fixture.status()), (plan_model, repair_fixture.plan())):
            for stage in ('strptime', 'replace', 'astimezone', 'strftime'):
                with self.subTest(module=module.__name__, stage=stage):
                    moment = Mock()
                    parser = Mock(return_value=moment)
                    operations = dict(strptime=parser, replace=moment.replace,
                        astimezone=moment.replace.return_value.astimezone,
                        strftime=moment.replace.return_value.astimezone.return_value.strftime)
                    operations[stage].side_effect = TypeError(SECRET)
                    with patch.object(module, 'datetime', SimpleNamespace(strptime=parser)):
                        self.assertEqual(source.checked_time_label(), '')

    def test_unrelated_status_typeerror_retains_unavailable_fallback(self):
        provider = Mock(return_value=status_fixture.status())
        ui = NativeDialogs(status_fixture.Addon(), None, lambda _: None, status_provider=provider)
        with patch.object(status_view, '_addons_row', side_effect=TypeError(SECRET)):
            self.assertEqual(ui.check_status(), status_view.StatusViewModel.unavailable())
        provider.assert_called_once_with()
        self.assertNotIn(SECRET, '\n'.join(self.logs))

    def test_unrelated_plan_typeerror_still_propagates(self):
        error = TypeError(SECRET)
        with patch.object(plan_view, '_sections', side_effect=error):
            with self.assertRaises(TypeError) as caught:
                plan_view.ReviewViewModel.from_plan(repair_fixture.plan())
        self.assertIs(caught.exception, error)

    def test_timestamp_failure_does_not_bypass_fresh_validation_or_duplicate_execution(self):
        for fixture in (install_fixture.WorkflowTests, repair_fixture.RepairWorkflowTests):
            f = fixture(); f.setUp()
            with self.parser_failure(plan_model): f.run_flow()
            f.service.preview.assert_called_once()
            f.service.validate.assert_called_once()
            f.coordinator.install_target.assert_called_once()
        self.assertNotIn(SECRET, '\n'.join(self.logs))
