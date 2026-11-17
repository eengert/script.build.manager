"""Practical Auto-Keep through production methods; all Kodi calls are synthetic.

The last-check replacement control deliberately retains the documented race.
No test represents inspection plus SendClick as an atomic operation.
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import default as entry
from resources.lib.skin import KodiRuntimeSkinBackend, SkinActivator, SkinStatus
from resources.lib.ui.native_dialogs import NativeDialogs
from tests.test_skin import FakeClock

TARGET = 'skin.arctic.fuse.3'


class Kodi:
    def __init__(self, mode='normal'):
        self.clock = FakeClock()
        self.mode = mode
        self.configured = 'skin.estuary'
        self.dialog = 'unrelated' if mode == 'preexisting' else None
        self.commands, self.clicks, self.mutations = [], [], []
        self.modal_checks = 0
        self.progress = Mock()
        self.gui = SimpleNamespace(getCurrentWindowDialogId=self.topmost,
                                   DialogProgressBG=Mock(return_value=self.progress))
        # Deliberately non-English: matching must use the core localized strings.
        self.heading, self.body = 'Garder cette apparence ?', 'Conserver ce changement ?'

    def topmost(self):
        self.modal_checks += 1
        result = 10100 if self.dialog else -1
        if self.mode == 'wrong_topmost':
            result = 10160
        if self.mode == 'late_replacement' and self.modal_checks == 4:
            # After the final inspected result but before SendClick dispatch.
            self.dialog = 'unrelated'
        return result

    def getLocalizedString(self, identifier):
        if self.mode == 'empty_translation':
            return ''
        return {13123: self.heading, 13111: self.body}[identifier]

    def getInfoLabel(self, expression):
        expected = {'Control.GetLabel(1)': self.heading, 'Control.GetLabel(9)': self.body}
        value = expected[expression] if self.dialog == 'keep' else 'Unrelated prompt'
        if self.mode == 'wrong_heading' and expression == 'Control.GetLabel(1)':
            value = 'Another heading'
        if self.mode == 'wrong_body' and expression == 'Control.GetLabel(9)':
            value = 'Another body'
        if self.mode == 'unreadable':
            raise RuntimeError('private dialog text must not become success')
        return value

    def getSkinDir(self):
        return self.configured

    def sleep(self, milliseconds):
        self.clock.sleep(milliseconds / 1000)
        if milliseconds == 500 and self.mode == 'during_prepare':
            self.dialog = 'unrelated'

    def executeJSONRPC(self, request):
        req = json.loads(request)
        method = req['method']
        if method == 'Addons.GetAddonDetails':
            result = {'addon': {'addonid': TARGET, 'enabled': True}}
        elif method == 'Settings.SetSettingValue':
            self.mutations.append(req['params'])
            self.configured = TARGET
            self.dialog = None if self.mode in ('never', 'declined') else 'keep'
            if self.mode == 'declined':
                self.configured = 'skin.estuary'
            result = True
        elif method == 'Settings.GetSettingValue':
            result = {'value': self.configured}
        else:
            raise AssertionError(method)
        return json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': result})

    def getCondVisibility(self, condition):
        assert condition in ('Window.IsActive(yesnodialog)', 'Window.IsActive(10100)')
        visible = self.dialog is not None
        if self.mode == 'early_replacement' and self.dialog == 'keep':
            self.dialog = 'unrelated'
        return visible

    def executebuiltin(self, command, wait=False):
        self.commands.append((command, wait))
        if command == 'ActivateWindow(home)':
            return
        if command != 'SendClick(11)':
            raise AssertionError(command)
        if self.mode == 'click_typeerror':
            # Even a TypeError may follow dispatch: retrying is unsafe.
            self.clicks.append(self.dialog)
            raise TypeError('injected after dispatch')
        self.clicks.append(self.dialog)
        if self.mode != 'stuck':
            self.dialog = None
        if self.mode == 'reverted':
            self.configured = 'skin.estuary'


def activate(kodi, wrapped=False):
    backend = KodiRuntimeSkinBackend()
    with patch.object(backend, '_xbmc', return_value=kodi), patch.dict('sys.modules', {'xbmcgui': kodi.gui}):
        action = lambda: SkinActivator(backend, timeout=3, interval=.25,
                                      clock=kodi.clock, sleep=kodi.clock.sleep).activate(TARGET)
        if wrapped:
            ui = NativeDialogs(Mock(), Mock(), kodi.sleep,
                               busy=entry.background_busy(kodi.gui, 'Build Manager'))
            return ui.execute_install(action)
        return action()


class TestPracticalAutoKeep(unittest.TestCase):
    def test_normal_localized_keep_is_automatic_once(self):
        kodi = Kodi()
        result = activate(kodi)
        self.assertEqual(result.status, SkinStatus.ACTIVATED)
        self.assertEqual(kodi.clicks, ['keep'])
        self.assertEqual(kodi.commands.count(('SendClick(11)', True)), 1)
        self.assertIsNone(kodi.dialog)
        self.assertEqual(kodi.modal_checks, 4)  # observed + immediate pre-click, each bracketed
        self.assertLess(kodi.clock.now, 10)

    def test_conflicts_before_or_during_preparation_refuse_before_mutation(self):
        for mode in ('preexisting', 'during_prepare'):
            with self.subTest(mode=mode):
                kodi = Kodi(mode)
                self.assertEqual(activate(kodi).status, SkinStatus.FAILED)
                self.assertEqual(kodi.mutations, [])
                self.assertEqual(kodi.clicks, [])

    def test_wrong_content_topmost_or_unreadable_prompt_never_receives_yes(self):
        for mode in ('wrong_heading', 'wrong_body', 'wrong_topmost',
                     'unreadable', 'empty_translation', 'early_replacement'):
            with self.subTest(mode=mode):
                kodi = Kodi(mode)
                self.assertEqual(activate(kodi).status, SkinStatus.FAILED)
                self.assertEqual(kodi.clicks, [])
                self.assertFalse(any(command.startswith('SendClick') for command, _ in kodi.commands))

    def test_replacement_between_observation_and_confirmation_recheck_refuses(self):
        kodi = Kodi()
        original = kodi.topmost
        def replace_before_second_inspection():
            if kodi.modal_checks == 2:
                kodi.dialog = 'unrelated'
            return original()
        kodi.gui.getCurrentWindowDialogId = replace_before_second_inspection
        self.assertEqual(activate(kodi).status, SkinStatus.FAILED)
        self.assertEqual(kodi.clicks, [])

    def test_decline_no_prompt_timeout_stuck_and_reversion_fail_without_retry(self):
        for mode, clicks in (('declined', []), ('never', []),
                             ('stuck', ['keep']), ('reverted', ['keep'])):
            with self.subTest(mode=mode):
                kodi = Kodi(mode)
                self.assertEqual(activate(kodi).status, SkinStatus.FAILED)
                self.assertEqual(kodi.clicks, clicks)

    def test_click_exception_never_retries_even_typeerror(self):
        kodi = Kodi('click_typeerror')
        result = activate(kodi)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertNotIn('injected after dispatch', result.message)
        self.assertEqual(kodi.clicks, ['keep'])
        self.assertEqual(kodi.commands.count(('SendClick(11)', True)), 1)

    def test_final_inspection_error_is_value_free_and_never_clicks(self):
        kodi = Kodi()
        read = kodi.getInfoLabel
        def fail_final_inspection(expression):
            if kodi.modal_checks >= 3:
                raise RuntimeError('PRIVATE_DIALOG_CONTENT')
            return read(expression)
        kodi.getInfoLabel = fail_final_inspection
        result = activate(kodi)
        self.assertEqual(result.status, SkinStatus.FAILED)
        self.assertEqual(kodi.clicks, [])
        self.assertNotIn('PRIVATE_DIALOG_CONTENT', result.message)

    def test_malformed_topmost_identity_is_not_accepted(self):
        kodi = Kodi()
        kodi.gui.getCurrentWindowDialogId = lambda: 10100.0
        self.assertEqual(activate(kodi).status, SkinStatus.FAILED)
        self.assertEqual(kodi.clicks, [])

    def test_missing_supported_dialog_api_refuses_instead_of_generic_fallback(self):
        kodi = Kodi()
        kodi.gui.getCurrentWindowDialogId = None
        self.assertEqual(activate(kodi).status, SkinStatus.FAILED)
        self.assertEqual(kodi.clicks, [])

    def test_success_wording_limits_claim_to_reported_configuration(self):
        result = activate(Kodi())
        self.assertEqual(result.status, SkinStatus.ACTIVATED)
        self.assertIn('reported', result.message.lower())
        for unsupported in ('persisted', 'loaded', 'authenticated', 'on-disk'):
            self.assertNotIn(unsupported, result.message.lower())

    def test_already_reported_target_does_not_claim_loaded_or_durable_identity(self):
        kodi = Kodi()
        kodi.configured = TARGET
        result = activate(kodi)
        self.assertEqual(result.status, SkinStatus.ALREADY_ACTIVE)
        self.assertIn('reports', result.message)
        self.assertEqual(kodi.commands, [])
        self.assertEqual(kodi.mutations, [])

    def test_documented_residual_replacement_after_final_check_is_not_atomic(self):
        kodi = Kodi('late_replacement')
        # This is a retained limitation witness, never a claim of safe ownership.
        activate(kodi)
        self.assertEqual(kodi.clicks, ['unrelated'])
        self.assertEqual(kodi.commands.count(('SendClick(11)', True)), 1)

    def test_real_wrapper_uses_modeless_owned_progress_and_closes_after_skin(self):
        kodi = Kodi()
        self.assertEqual(activate(kodi, wrapped=True).status, SkinStatus.ACTIVATED)
        kodi.gui.DialogProgressBG.assert_called_once_with()
        kodi.progress.create.assert_called_once_with('Build Manager')
        kodi.progress.close.assert_called_once_with()
        self.assertEqual(kodi.commands[0], ('ActivateWindow(home)', False))
        self.assertFalse(any('busydialog' in command.lower() for command, _ in kodi.commands))


class HandleProgress:
    """Pinned handle semantics, without a native destructor or shared GUI.

    Kodi starts with null handle/open=False and close refuses a null handle.
    Injected failures after handle publication model partial initialization;
    arbitrary close failures are fault controls, not claims about native frequency.
    """
    def __init__(self, *, create_error=None, partial=False, close_error=None):
        self.create_error, self.partial = create_error, partial
        self.close_error = close_error
        self.handle = None
        self.open = False
        self.creates = self.closes = 0

    def create(self, heading):
        self.creates += 1
        if self.create_error is not None and not self.partial:
            raise self.create_error
        self.handle = SimpleNamespace(finished=False)
        self.open = True
        if self.create_error is not None:
            raise self.create_error

    def close(self):
        self.closes += 1
        if self.handle is None:
            raise RuntimeError('Dialog not created.')
        if self.close_error is not None:
            raise self.close_error
        self.handle.finished = True
        self.open = False


class TestBackgroundProgress(unittest.TestCase):
    def wrapper(self, busy):
        return NativeDialogs(Mock(), Mock(), Mock(), busy=busy)

    def test_callback_closes_only_its_handle_and_is_idempotent(self):
        gui = Mock()
        progress = gui.DialogProgressBG.return_value
        busy = entry.background_busy(gui, 'Build Manager')
        busy(False)
        busy(True)
        busy(True)
        busy(False)
        busy(False)
        gui.DialogProgressBG.assert_called_once_with()
        progress.create.assert_called_once_with('Build Manager')
        progress.close.assert_called_once_with()

    def test_entrypoint_wires_background_handle_without_modal_builtins(self):
        xbmc, addon, gui = Mock(), Mock(), Mock()
        addon.Addon.return_value.getLocalizedString.return_value = 'Build Manager'
        with patch.dict('sys.modules', {'xbmc': xbmc, 'xbmcaddon': addon, 'xbmcgui': gui}):
            with patch('resources.lib.ui.native_dialogs.NativeDialogs') as dialogs:
                def run():
                    busy = dialogs.call_args.kwargs['busy']
                    busy(True)
                    busy(False)
                dialogs.return_value.run.side_effect = run
                entry.main()
        gui.DialogProgressBG.assert_called_once_with()
        gui.DialogProgressBG.return_value.close.assert_called_once_with()
        xbmc.executebuiltin.assert_not_called()

    def test_next_operation_gets_its_own_new_handle(self):
        gui = Mock()
        first, second = HandleProgress(), HandleProgress()
        gui.DialogProgressBG.side_effect = [first, second]
        busy = entry.background_busy(gui, 'Build Manager')
        busy(True)
        busy(False)
        busy(True)
        self.assertEqual(first.closes, 1)
        self.assertTrue(first.handle.finished)
        self.assertEqual(second.closes, 0)
        self.assertTrue(second.open)
        busy(False)
        self.assertEqual(second.closes, 1)
        self.assertTrue(second.handle.finished)

    def test_execution_exception_closes_owned_progress(self):
        gui = Mock()
        ui = NativeDialogs(Mock(), Mock(), Mock(), busy=entry.background_busy(gui, 'Build Manager'))
        with self.assertRaisesRegex(RuntimeError, 'execution failed'):
            ui.execute_install(Mock(side_effect=RuntimeError('execution failed')))
        gui.DialogProgressBG.return_value.close.assert_called_once_with()

    def test_progress_creation_exception_cleans_up_before_execution(self):
        gui = Mock()
        primary = RuntimeError('create failed before handle allocation')
        first, second = HandleProgress(create_error=primary), HandleProgress()
        gui.DialogProgressBG.side_effect = [first, second]
        busy = entry.background_busy(gui, 'Build Manager')
        action = Mock()
        ui = self.wrapper(busy)
        with self.assertRaises(RuntimeError) as caught:
            ui.execute_install(action)
        self.assertIs(caught.exception, primary)  # null-handle cleanup must not mask it
        action.assert_not_called()
        self.assertEqual(first.closes, 1)
        self.assertIsNone(first.handle)
        self.assertFalse(first.open)
        busy(False)  # wrapper cleanup already ran; must now be a harmless no-op
        self.assertEqual(first.closes, 1)
        self.assertEqual(ui.execute_install(lambda: 'second completed'), 'second completed')
        self.assertEqual(second.creates, 1)
        self.assertTrue(second.handle.finished)
        self.assertFalse(second.open)

    def test_progress_close_failure_propagates_instead_of_claiming_completion(self):
        gui = Mock()
        primary = RuntimeError('close failed')
        first, second = HandleProgress(close_error=primary), HandleProgress()
        gui.DialogProgressBG.side_effect = [first, second]
        busy = entry.background_busy(gui, 'Build Manager')
        ui = self.wrapper(busy)
        action = Mock(return_value='completed work')
        with self.assertRaises(RuntimeError) as caught:
            ui.execute_install(action)
        self.assertIs(caught.exception, primary)
        action.assert_called_once_with()
        busy(False)
        self.assertEqual(first.closes, 1)
        # An unexpected native failure before MarkFinished could leave a handle
        # open. Clearing Python state is not proof that native cleanup succeeded.
        self.assertTrue(first.open)
        self.assertEqual(ui.execute_install(lambda: 'next completed'), 'next completed')
        self.assertTrue(second.handle.finished)

    def test_constructor_failure_does_not_poison_next_operation(self):
        gui = Mock()
        primary, good = RuntimeError('constructor failed'), HandleProgress()
        gui.DialogProgressBG.side_effect = [primary, good]
        ui = self.wrapper(entry.background_busy(gui, 'Build Manager'))
        action = Mock()
        with self.assertRaises(RuntimeError) as caught:
            ui.execute_install(action)
        self.assertIs(caught.exception, primary)
        action.assert_not_called()
        self.assertEqual(ui.execute_install(lambda: 'completed'), 'completed')
        self.assertTrue(good.handle.finished)

    def test_partial_create_failure_explicitly_closes_only_its_handle(self):
        gui = Mock()
        primary = RuntimeError('failed after handle publication')
        first, second, unrelated = (HandleProgress(create_error=primary, partial=True),
                                    HandleProgress(), HandleProgress())
        unrelated.create('another caller')
        gui.DialogProgressBG.side_effect = [first, second]
        busy = entry.background_busy(gui, 'Build Manager')
        ui = self.wrapper(busy)
        with self.assertRaises(RuntimeError) as caught:
            ui.execute_install(Mock(side_effect=AssertionError('must not execute')))
        self.assertIs(caught.exception, primary)
        self.assertTrue(first.handle.finished)
        self.assertFalse(first.open)
        self.assertEqual(first.closes, 1)
        self.assertEqual(unrelated.closes, 0)
        self.assertTrue(unrelated.open)
        self.assertEqual(ui.execute_install(lambda: 'completed'), 'completed')
        self.assertTrue(second.handle.finished)
        self.assertFalse(unrelated.handle.finished)

    def test_partial_create_and_cleanup_failure_preserve_primary_and_fresh_state(self):
        gui = Mock()
        primary = RuntimeError('primary create failure')
        first = HandleProgress(create_error=primary, partial=True,
                               close_error=RuntimeError('secondary cleanup failure'))
        good = HandleProgress()
        gui.DialogProgressBG.side_effect = [first, good]
        busy = entry.background_busy(gui, 'Build Manager')
        ui = self.wrapper(busy)
        with self.assertRaises(RuntimeError) as caught:
            ui.execute_install(Mock(side_effect=AssertionError('must not execute')))
        self.assertIs(caught.exception, primary)
        self.assertEqual(first.closes, 1)
        busy(False)
        self.assertEqual(first.closes, 1)
        self.assertTrue(first.open)  # unresolved cleanup is not modelled as success
        self.assertEqual(ui.execute_install(lambda: 'completed'), 'completed')
        self.assertTrue(good.handle.finished)

    def test_create_workflow_wrapper_cleans_failed_start_then_accepts_fresh_handle(self):
        from tests.test_create_workflow import WorkflowTests, NativeDialog, CreateAddon
        from resources.lib.ui.create_dialogs import CreateDialogs
        fixture = WorkflowTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        workflow = fixture.workflow
        workflow.execute = Mock(wraps=workflow.execute)
        primary = RuntimeError('create progress failed')
        first, good = HandleProgress(create_error=primary), HandleProgress()
        gui = Mock()
        gui.DialogProgressBG.side_effect = [first, good]
        busy = entry.background_busy(gui, 'Build Manager')
        def ui(tail='cancel'):
            # Create renders a sanitized failure and returns to its menu; Back
            # exits that existing UI path. Unlike execute_install it doesn't
            # propagate an execution exception to its caller.
            dialog = NativeDialog([0, 'apply', 'create', 'confirm', tail], inputs=['B1 synthetic build'])
            return NativeDialogs(CreateAddon(), dialog, lambda ms: None,
                                 create_provider=lambda: workflow, busy=busy,
                                 create_dialogs=CreateDialogs(CreateAddon(), show=dialog.show_page))
        first_ui = ui()
        first_ui.create()
        self.assertIn('32732', first_ui.dialog.results[0][1])
        self.assertNotIn(str(primary), str(first_ui.dialog.results))
        workflow.execute.assert_not_called()
        self.assertEqual(first.closes, 1)
        # The successful completion page is dismissed with its own OK action.
        ui(tail='ok').create()
        workflow.execute.assert_called_once()
        self.assertTrue(good.handle.finished)
        self.assertEqual(good.closes, 1)
