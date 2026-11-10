"""Sanitized boundaries only: no native calls or actual status/install owners."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from resources.lib import failure_diagnostics as diag
from resources.lib import install_workflow
from resources.lib import status as status_service
from resources.lib.status_model import BuildPresentation, OverallStatus
from resources.lib.ui.native_dialogs import NativeDialogs
from resources.lib.ui.status_view import StatusViewModel
from tests import test_install_workflow as fixture
from tests import test_status_ui as status_fixture

SECRET = '/private/credential TOKEN=never-log-this build-name private-setting'


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        # Exercise the actual emitter, substituting only its Kodi log sink.
        import sys
        self.kodi = patch.dict(sys.modules, xbmc=SimpleNamespace(
            LOGINFO=1, log=lambda message, level: self.logs.append(message)))
        self.kodi.start()
        self.addCleanup(self.kodi.stop)

    def assert_failure(self, phase, cls='ValueError'):
        self.assertIn('[script.build.manager] diagnostic phase=' + phase + ' exception=' + cls, self.logs)
        self.assertNotIn(SECRET, '\n'.join(self.logs))
        for message in self.logs:
            self.assertRegex(message, r'^\[script.build.manager\] diagnostic phase=[a-z_.]+(?: exception=[A-Za-z_][A-Za-z0-9_]*)?$')

    def test_logger_failure_cannot_replace_return_or_original_exception(self):
        sink = Mock(side_effect=RuntimeError(SECRET))
        self.assertEqual(diag.call('status.provider', lambda: 42, log=sink), 42)
        error = ValueError(SECRET)
        def fail(): raise error
        with self.assertRaises(ValueError) as raised:
            diag.call('status.provider', fail, log=sink)
        self.assertIs(raised.exception, error)
        diag.emit(SECRET, error, log=self.logs.append)
        self.assertEqual(self.logs, [])

    def test_status_provider_and_conversion_failures_keep_fallback_and_single_call(self):
        for phase in ('status.provider', 'status.view_model'):
            with self.subTest(phase=phase):
                self.logs.clear()
                provider = Mock(return_value=status_fixture.changes_needed())
                ui = NativeDialogs(status_fixture.Addon(), None, lambda _: None, status_provider=provider)
                if phase == 'status.provider':
                    provider.side_effect = ValueError(SECRET)
                    model = ui.check_status()
                else:
                    with patch.object(StatusViewModel, 'from_status', side_effect=ValueError(SECRET)):
                        model = ui.check_status()
                self.assertEqual(model, StatusViewModel.unavailable())
                provider.assert_called_once_with()
                self.assert_failure(phase)

    def test_status_success_is_not_rechecked(self):
        source = status_fixture.changes_needed()
        provider = Mock(return_value=source)
        ui = NativeDialogs(status_fixture.Addon(), None, lambda _: None, status_provider=provider)
        self.assertEqual(ui.check_status().overall, OverallStatus.CHANGES_NEEDED)
        provider.assert_called_once_with()
        self.assertFalse(any('exception=' in line for line in self.logs))

    def test_post_engine_context_failure_preserves_existing_context_fallback(self):
        with patch('resources.lib.build_library.default_build_library', side_effect=ValueError(SECRET)):
            value = status_service.default_build_presentation(object(), log=self.logs.append)
        self.assertEqual(value, BuildPresentation(applied_unreadable=True))
        self.assert_failure('status.presentation')

    def test_post_engine_attach_failure_is_distinguished_without_second_inspection(self):
        check = Mock(return_value=status_fixture.changes_needed())
        with patch.object(status_service, 'default_status_target', return_value=None), \
             patch.object(status_service, 'default_status_owners'), \
             patch.object(status_service, 'BuildStatusService', return_value=SimpleNamespace(check=check)), \
             patch.object(status_service, 'default_build_presentation', side_effect=ValueError(SECRET)):
            with self.assertRaises(ValueError):
                status_service.check_build_status(log=self.logs.append)
        check.assert_called_once_with(None)
        self.assert_failure('status.presentation')

    def flow(self):
        value = fixture.WorkflowTests()
        value.setUp()
        return value

    def test_install_failures_before_execution_never_invoke_coordinator(self):
        boundaries = {
            'install.operation_gate': lambda f: f.operation,
            'install.library': lambda f: f.library.list_builds,
            'install.build_selection': lambda f: f.ui.choose_install_build,
            'install.profile_selection': lambda f: f.ui.choose_install_profile,
            'install.target': lambda f: f.library.plan_target,
            'install.preview': lambda f: f.service.preview,
            'install.confirmation': lambda f: f.ui.confirm_install,
            'install.validation': lambda f: f.service.validate,
            'install.execution_wrapper': lambda f: f.ui.execute_install,
            'install.coordinator_factory': lambda f: f.factory,
        }
        for phase, choose in boundaries.items():
            with self.subTest(phase=phase):
                self.logs.clear(); f = self.flow()
                choose(f).side_effect = ValueError(SECRET)
                with self.assertRaises(ValueError): f.run_flow()
                self.assert_failure(phase)
                f.coordinator.install_target.assert_not_called()
                self.assertFalse(any('phase=install.coordinator_invoke' in x for x in self.logs))

    def test_plan_conversion_failure_is_not_execution(self):
        f = self.flow()
        with patch.object(install_workflow.ReviewViewModel, 'from_plan', side_effect=ValueError(SECRET)):
            with self.assertRaises(ValueError): f.run_flow()
        self.assert_failure('install.plan_conversion')
        f.assert_no_execution()

    def test_decision_and_preparation_failure_boundaries(self):
        for phase in ('install.decision', 'install.preparation'):
            with self.subTest(phase=phase):
                self.logs.clear(); f = self.flow()
                if phase == 'install.decision':
                    f.service.preview.return_value = SimpleNamespace(state=fixture.PlanState.DECISION_REQUIRED)
                    model = SimpleNamespace(decisions=(SimpleNamespace(
                        addon_id='plugin.demo', choices=(fixture.DecisionChoice.CANCEL,)),))
                    f.ui.choose_install_decision.side_effect = ValueError(SECRET)
                else:
                    f.target = fixture.replace(f.target, choices=(('plugin.demo', fixture.DecisionChoice.INSTALL_CURRENT),))
                    f.library.plan_target.return_value = f.target
                    f.service.preview.return_value = SimpleNamespace(state=fixture.PlanState.RESOLUTION_REQUIRED)
                    model = SimpleNamespace()
                    f.ui.prepare_install.side_effect = ValueError(SECRET)
                with patch.object(install_workflow.ReviewViewModel, 'from_plan', return_value=model):
                    with self.assertRaises(ValueError): f.run_flow()
                self.assert_failure(phase)
                f.assert_no_execution()

    def test_expected_preview_resolution_is_not_an_exception(self):
        f = self.flow()
        f.service.preview.return_value = SimpleNamespace(state=fixture.PlanState.RESOLUTION_REQUIRED)
        with patch.object(install_workflow.ReviewViewModel, 'from_plan', return_value=SimpleNamespace()):
            f.run_flow()
        f.ui.install_message.assert_called_once_with(32804)
        f.assert_no_execution()
        self.assertIn('[script.build.manager] diagnostic phase=install.resolution_required', self.logs)
        self.assertFalse(any('exception=' in line for line in self.logs))

    def test_logging_failure_does_not_change_successful_workflow(self):
        f = self.flow()
        import sys
        sys.modules['xbmc'].log = Mock(side_effect=RuntimeError(SECRET))
        f.run_flow()
        f.ui.confirm_install.assert_called_once()
        f.service.validate.assert_called_once()
        f.coordinator.install_target.assert_called_once()
        f.ui.install_message.assert_called_once_with(32809)

    def test_execution_target_and_result_presentation_failures(self):
        f = self.flow()
        with patch.object(install_workflow.LibraryInstallTarget, 'from_plan_target', side_effect=ValueError(SECRET)):
            with self.assertRaises(ValueError): f.workflow.run(f.ui)
        self.assert_failure('install.execution_target')
        f.assert_no_execution()
        self.logs.clear(); f = self.flow()
        f.ui.install_message.side_effect = ValueError(SECRET)
        with self.assertRaises(ValueError): f.run_flow()
        self.assert_failure('install.result_presentation')
        f.coordinator.install_target.assert_called_once()

    def test_coordinator_failure_has_invocation_but_no_result(self):
        f = self.flow(); f.coordinator.install_target.side_effect = ValueError(SECRET)
        with self.assertRaises(ValueError): f.run_flow()
        f.coordinator.install_target.assert_called_once()
        f.ui.confirm_install.assert_called_once()
        f.service.validate.assert_called_once()
        self.assert_failure('install.coordinator_invoke')
        self.assertNotIn('[script.build.manager] diagnostic phase=install.coordinator_result', self.logs)

    def test_success_and_expected_resolution_result_are_not_exceptions(self):
        for result in ('complete', 'user_resolution_required'):
            with self.subTest(result=result):
                self.logs.clear(); f = self.flow()
                f.coordinator.install_target.return_value = SimpleNamespace(outcome=result)
                f.run_flow()
                f.coordinator.install_target.assert_called_once()
                f.ui.install_message.assert_called_once_with(32809 if result == 'complete' else 32814)
                self.assertIn('[script.build.manager] diagnostic phase=install.coordinator_result', self.logs)
                self.assertEqual(any('phase=install.resolution_required' in x for x in self.logs), result != 'complete')
                self.assertFalse(any('exception=' in x for x in self.logs))

    def test_native_escaping_exception_keeps_original_message(self):
        provider = Mock(side_effect=ValueError(SECRET))
        ui = NativeDialogs(status_fixture.Addon(), None, lambda _: None, install_provider=provider)
        ui.install_message = Mock()
        ui.install()
        ui.install_message.assert_called_once_with(32814)
        provider.assert_called_once_with()
        self.assert_failure('install.workflow')
