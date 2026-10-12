"""Pure localized advisory presentation; no native dialog execution."""
import ast
from dataclasses import fields
from pathlib import Path
import re
import unittest

from resources.lib.capture_recovery_assessor import RecoveryReason
from resources.lib.ui.create_recovery_view import (CreateRecoveryView, present_create_recovery,
    RecoveryPresentationInput as Input, RecoveryPresentationReason as R)


class RecoveryViewTests(unittest.TestCase):
    def test_each_reason_is_localized_and_non_actionable(self):
        source = (Path(__file__).parents[1] / 'resources/language/resource.language.en_gb/strings.po').read_text()
        ids = re.findall(r'msgctxt "#(\d+)"', source)
        self.assertEqual(len(ids), len(set(ids)))
        localized = {int(i): ast.literal_eval(text) for i, text in re.findall(
            r'msgctxt "#(\d+)"\nmsgid ("[^\n]*")', source)}
        for reason in R:
            view = present_create_recovery(Input(reason))
            self.assertEqual([f.name for f in fields(view)], ['title_id', 'body_id'])
            for identifier in (view.title_id, view.body_id):
                self.assertTrue(localized[identifier])
                self.assertNotIn('%', localized[identifier])
            self.assertNotIn('Disable Red Light manually', localized[view.body_id])
            self.assertFalse(any(callable(v) for v in vars(view).values()))
        self.assertEqual(set(range(33000, 33008)) - localized.keys(), set())

    def test_manual_disable_requires_specific_trusted_condition(self):
        self.assertEqual({r.value for r in R}, {r.value for r in RecoveryReason})
        self.assertEqual(present_create_recovery(Input(R.UNEXPECTED_ENABLEMENT, True, True, False)).body_id, 33005)
        for verified in (False, True):
            for enabled in (None, False, True):
                for original in (None, False, True):
                    body = present_create_recovery(Input(R.UNEXPECTED_ENABLEMENT, verified, enabled, original)).body_id
                    self.assertEqual(body, 33005 if verified and enabled is True and original is False else 33006)
        for reason in R:
            if reason is not R.UNEXPECTED_ENABLEMENT:
                self.assertNotEqual(present_create_recovery(Input(reason, True, True, False)).body_id, 33005)
        for original in (0, 'false'):
            with self.assertRaisesRegex(ValueError, '^invalid Create presentation input$'):
                Input(R.UNEXPECTED_ENABLEMENT, True, True, original)

    def test_hold_pending_released_and_unknown_are_distinct(self):
        views = [present_create_recovery(Input(r)).body_id for r in (
            R.ORDINARY_RECOVERY_POTENTIAL, R.TERMINAL_FINALIZATION_PENDING,
            R.TERMINAL_NO_CAPTURE_HOLD, R.OBSERVATIONS_UNVERIFIABLE)]
        self.assertEqual(len(set(views)), 4)

    def test_untyped_private_payload_is_generic_and_never_rendered(self):
        payload = {'reason': 'UNEXPECTED_ENABLEMENT', 'path': 'SECRET/private/profile'}
        view = present_create_recovery(payload)
        self.assertEqual(view.body_id, 33007)
        self.assertNotIn('SECRET', repr(view))
        with self.assertRaisesRegex(ValueError, '^invalid Create presentation$'):
            CreateRecoveryView(33000, 'SECRET/private/path')

    def test_presenter_imports_only_pure_presentation_dependencies(self):
        source = (Path(__file__).parents[1] / 'resources/lib/ui/create_recovery_view.py').read_text()
        imports = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.module in {'enum', 'dataclasses'} for n in imports))
