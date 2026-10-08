"""BM-UI-002B: the native Build Status page is human-readable and secret-blind."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib.status_model import (
    AreaLevel, BuildStatus, CheckGap, ConfigurationStatus, OperationCode, OperationKind,
    OperationStatus, OverallStatus, PrivateItem, PrivateItemKind, PrivateStatus, SkinStatus,
    SoftwareItem, SoftwareItemState, SoftwareStatus,
)
from resources.lib.status import BuildStatusService
from resources.lib.ui import status_view
from resources.lib.ui.controller import ROUTES, Route
from resources.lib.ui.native_dialogs import NativeDialogs
from resources.lib.ui.status_view import StatusViewModel, STATUS_TEXT_IDS, Text
from tests.test_status import (
    DB_SECRET, DEMO, MODULE, NOW, SECRET, SESSION_A, Harness, snapshot_tree,
)

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROUTES.index(Route.STATUS)
PO = ROOT / "resources/language/resource.language.en_gb/strings.po"


def strings():
    text = PO.read_text(encoding="utf-8")
    return {int(m.group(1)): m.group(2).replace("\\n", "\n").replace('\\"', '"')
            for m in re.finditer(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"', text)}


STRINGS = strings()


class Addon:
    def __init__(self):
        self.opened = 0

    def getLocalizedString(self, identifier):
        return STRINGS[identifier]

    def openSettings(self):
        self.opened += 1

    def getSetting(self, *args):
        raise AssertionError("private settings read")


class Dialog:
    def __init__(self, choices):
        self.choices, self.selects, self.details = iter(choices), [], []

    def select(self, heading, labels, preselect=0):
        self.selects.append((heading, labels, preselect))
        return next(self.choices)

    def textviewer(self, heading, text):
        self.details.append((heading, text))

    @property
    def everything(self):
        return json.dumps([self.selects, self.details])


def status(**overrides):
    values = dict(
        overall=OverallStatus.CURRENT, checked_at=NOW, build_selected=True,
        software=SoftwareStatus(AreaLevel.CURRENT, (SoftwareItem(DEMO, SoftwareItemState.CURRENT),)),
        skin=SkinStatus(AreaLevel.CURRENT, "skin.demo", "skin.demo", True),
        configuration=ConfigurationStatus(AreaLevel.CURRENT, 4),
        private=PrivateStatus(AreaLevel.CURRENT, (
            PrivateItem("private-settings", PrivateItemKind.SETTINGS, AreaLevel.CURRENT),
            PrivateItem("redlight.settings", PrivateItemKind.RESOURCE, AreaLevel.CURRENT))),
        operation=OperationStatus(), gaps=())
    values.update(overrides)
    return BuildStatus(**values)


def changes_needed():
    return status(
        overall=OverallStatus.CHANGES_NEEDED,
        software=SoftwareStatus(AreaLevel.CHANGES_NEEDED, (
            SoftwareItem("plugin.video.alpha", SoftwareItemState.MISSING, "Alpha Videos"),
            SoftwareItem("script.module.beta", SoftwareItemState.WRONG_VERSION),
            SoftwareItem(DEMO, SoftwareItemState.CURRENT))),
        configuration=ConfigurationStatus(AreaLevel.CHANGES_NEEDED, 4, 1, 0))


def not_checked():
    return status(
        overall=OverallStatus.INCOMPLETE, build_selected=False,
        software=SoftwareStatus(AreaLevel.UNAVAILABLE), skin=SkinStatus(AreaLevel.UNAVAILABLE),
        configuration=ConfigurationStatus(AreaLevel.UNAVAILABLE),
        private=PrivateStatus(AreaLevel.UNAVAILABLE), gaps=(CheckGap.NO_BUILD_SELECTED,))


def run(provider, choices):
    addon, dialog, waits = Addon(), Dialog(choices), []
    ui = NativeDialogs(addon, dialog, waits.append, provider)
    ui.run()
    return addon, dialog, waits


def open_status(provider, *then):
    return run(provider, [STATUS, *then, -1, -1])


def rows(dialog, index=0):
    return dialog.selects[1 + index][1]


class FirstScreen(unittest.TestCase):
    def test_current_status_matches_the_suggested_layout(self):
        calls = []
        _, dialog, _ = open_status(lambda: calls.append(1) or status())
        heading, labels, preselect = dialog.selects[1]
        self.assertEqual(heading, "Build Status")
        self.assertEqual(labels, [
            "Overall: Healthy", "Add-ons: Current", "Skin: Current", "Settings: Current",
            "Private settings: Current", "Check Again", "Help", "Close"])
        self.assertEqual((preselect, len(calls)), (0, 1))

    def test_changes_needed_gives_a_short_plain_summary(self):
        _, dialog, _ = open_status(changes_needed, 0)
        self.assertEqual(rows(dialog)[:5], [
            "Overall: Changes Needed", "Add-ons: 2 need attention", "Skin: Current",
            "Settings: Needs updating", "Private settings: Current"])
        heading, text = dialog.details[0]
        self.assertEqual(heading, "Overall")
        self.assertEqual(text.splitlines()[:5], [
            "Some parts of this device don't match your build.",
            "• 2 add-ons need attention", "• Skin is current",
            "• Settings need updating", "• Private settings are current"])
        self.assertTrue(text.splitlines()[-1].startswith("Checked at "))

    def test_one_addon_uses_the_singular(self):
        one = changes_needed().software.items[:1] + (changes_needed().software.items[2],)
        _, dialog, _ = open_status(lambda: status(
            overall=OverallStatus.CHANGES_NEEDED,
            software=SoftwareStatus(AreaLevel.CHANGES_NEEDED, one)))
        self.assertEqual(rows(dialog)[1], "Add-ons: 1 needs attention")

    def test_not_checked_is_never_presented_as_healthy(self):
        _, dialog, _ = open_status(not_checked, 0)
        self.assertEqual(rows(dialog)[:5], [
            "Overall: Not Fully Checked", "Add-ons: Not checked", "Skin: Not checked",
            "Settings: Not checked", "Private settings: Not checked"])
        self.assertIn("No build has been applied on this device yet", dialog.details[0][1])
        self.assertIn("not a healthy result", dialog.details[0][1])

    def test_a_build_that_lists_nothing_says_so_and_is_not_healthy(self):
        empty = status(
            overall=OverallStatus.INCOMPLETE, gaps=(CheckGap.NOTHING_TO_COMPARE,),
            skin=SkinStatus(AreaLevel.NOT_APPLICABLE), configuration=ConfigurationStatus(AreaLevel.NOT_APPLICABLE),
            private=PrivateStatus(AreaLevel.NOT_APPLICABLE), software=SoftwareStatus(AreaLevel.NOT_APPLICABLE))
        _, dialog, _ = open_status(lambda: empty, 0)
        self.assertEqual(rows(dialog)[0], "Overall: Not Fully Checked")
        self.assertIn("This build does not list anything to compare.", dialog.details[0][1])

    def test_unreadable_progress_is_explained_once(self):
        unreadable = status(
            overall=OverallStatus.INCOMPLETE, gaps=(CheckGap.OPERATION_STATE_UNAVAILABLE,),
            operation=OperationStatus(OperationKind.UNAVAILABLE, OperationCode.TRANSACTION_UNREADABLE))
        _, dialog, _ = open_status(lambda: unreadable, 0)
        self.assertEqual(dialog.details[0][1].count("could not read its saved progress"), 1)

    def test_restart_and_attention_are_stated_plainly(self):
        restart = status(overall=OverallStatus.RESTART_REQUIRED, operation=OperationStatus(
            OperationKind.RESTART_REQUIRED, OperationCode.AWAITING_RESTART, protection_active=True))
        _, dialog, _ = open_status(lambda: restart, 0)
        self.assertEqual(rows(dialog)[0], "Overall: Restart Required")
        self.assertIn("Fully close Kodi and open it again", dialog.details[0][1])
        self.assertIn("protection stays on", dialog.details[0][1])
        attention = status(overall=OverallStatus.NEEDS_ATTENTION, operation=OperationStatus(
            OperationKind.NEEDS_ATTENTION, OperationCode.RESUME_PENDING))
        _, dialog, _ = open_status(lambda: attention, 0)
        self.assertEqual(rows(dialog)[0], "Overall: Needs Attention")
        self.assertIn("Kodi was restarted, but Build Manager has not finished",
                      dialog.details[0][1])

    def test_every_overall_state_has_the_label_help_documents(self):
        help_text = STRINGS[32304]
        for state, expected in ((OverallStatus.CURRENT, "Healthy"),
                                (OverallStatus.CHANGES_NEEDED, "Changes Needed"),
                                (OverallStatus.RESTART_REQUIRED, "Restart Required"),
                                (OverallStatus.NEEDS_ATTENTION, "Needs Attention"),
                                (OverallStatus.INCOMPLETE, "Not Fully Checked")):
            self.assertEqual(STRINGS[status_view.OVERALL_LABEL[state]], expected)
            self.assertIn(expected, help_text)
        self.assertIn("Use Check Again to look again", help_text)
        self.assertIn("older result is not the same as a fresh check", help_text)


class Details(unittest.TestCase):
    def test_addon_details_list_names_then_ids_with_plain_states(self):
        _, dialog, _ = open_status(changes_needed, 1)
        heading, text = dialog.details[0]
        self.assertEqual(heading, "Add-ons")
        self.assertEqual(text.splitlines(), [
            "• Alpha Videos — Not installed",
            "• script.module.beta — Different version"])

    def test_long_lists_are_bounded(self):
        many = tuple(SoftwareItem("plugin.video.a%02d" % i, SoftwareItemState.MISSING)
                     for i in range(40))
        _, dialog, _ = open_status(lambda: status(
            overall=OverallStatus.CHANGES_NEEDED,
            software=SoftwareStatus(AreaLevel.CHANGES_NEEDED, many)), 1)
        lines = dialog.details[0][1].splitlines()
        self.assertEqual(len(lines), status_view.MAX_LISTED_ADDONS + 1)
        self.assertEqual(lines[-1], "…and 25 more")
        self.assertEqual(rows(dialog)[1], "Add-ons: 40 need attention")

    def test_skin_settings_and_private_details(self):
        _, dialog, _ = open_status(changes_needed, 2, 3, 4)
        skin, settings, private = (d[1] for d in dialog.details)
        self.assertEqual(skin.splitlines(), ["Your build uses the skin: skin.demo",
                                             "The skin in use now: skin.demo"])
        self.assertEqual(settings.splitlines(), [
            "Settings and files checked: 4", "Needing an update: 1"])
        self.assertEqual(private.splitlines(), [
            "• Private settings: Current", "• Private add-on data: Current"])

    def test_not_part_of_the_build_is_said_so(self):
        _, dialog, _ = open_status(lambda: status(
            overall=OverallStatus.INCOMPLETE, gaps=(CheckGap.NOTHING_TO_COMPARE,),
            skin=SkinStatus(AreaLevel.NOT_APPLICABLE, "", "skin.demo", None),
            configuration=ConfigurationStatus(AreaLevel.NOT_APPLICABLE),
            private=PrivateStatus(AreaLevel.NOT_APPLICABLE),
            software=SoftwareStatus(AreaLevel.NOT_APPLICABLE)), 1, 2, 3, 4)
        self.assertEqual([d[1] for d in dialog.details], [
            "This build does not manage add-ons.", "This build does not set a skin.",
            "This build does not manage any settings.",
            "This build does not use private settings."])
        self.assertEqual(rows(dialog)[1:5], ["Add-ons: Not part of this build"] * 1 + [
            "Skin: Not part of this build", "Settings: Not part of this build",
            "Private settings: Not part of this build"])

    def test_details_return_to_the_row_that_opened_them(self):
        _, dialog, _ = open_status(changes_needed, 2)
        self.assertEqual([s[2] for s in dialog.selects[1:-1]], [0, 2])


class Navigation(unittest.TestCase):
    def test_check_again_performs_exactly_one_new_read(self):
        calls = []
        _, dialog, _ = open_status(lambda: calls.append(1) or status(), 5, 5)
        self.assertEqual(len(calls), 3)               # one on entry, one per Check Again
        self.assertEqual([s[2] for s in dialog.selects[1:-1]], [0, 5, 5])
        self.assertFalse(dialog.details)

    def test_check_again_shows_the_new_result(self):
        results = iter([changes_needed(), status()])
        _, dialog, _ = open_status(lambda: next(results), 5)
        self.assertEqual(rows(dialog, 0)[0], "Overall: Changes Needed")
        self.assertEqual(rows(dialog, 1)[0], "Overall: Healthy")

    def test_help_opens_the_build_status_section_and_returns(self):
        _, dialog, waits = open_status(status, 6)
        self.assertEqual(dialog.details, [(STRINGS[32204], STRINGS[32304])])
        self.assertEqual([s[2] for s in dialog.selects[1:-1]], [0, 6])
        self.assertEqual(set(waits), {200})

    def test_help_does_not_check_again(self):
        calls = []
        open_status(lambda: calls.append(1) or status(), 6, 6)
        self.assertEqual(len(calls), 1)

    def test_close_back_and_cancel_return_to_the_menu_with_status_selected(self):
        for leave in (7, -1, 99):
            with self.subTest(leave):
                _, dialog, _ = run(status, [STATUS, leave, -1])
                self.assertEqual(dialog.selects[-1][0], STRINGS[32000])
                self.assertEqual(dialog.selects[-1][2], STATUS)

    def test_settings_and_help_routes_are_unchanged(self):
        addon, dialog, _ = run(status, [4, -1])
        self.assertEqual(addon.opened, 1)
        _, dialog, _ = run(status, [5, 4, -1, -1])
        self.assertEqual(dialog.details, [(STRINGS[32204], STRINGS[32304])])

    def test_no_provider_or_a_failing_provider_shows_not_checked(self):
        for provider in (None, lambda: (_ for _ in ()).throw(RuntimeError(SECRET)),
                         lambda: "not a status", lambda: None):
            with self.subTest(provider):
                _, dialog, _ = open_status(provider, 0)
                self.assertEqual(rows(dialog)[0], "Overall: Not Fully Checked")
                self.assertEqual(rows(dialog)[1:5], ["Add-ons: Not checked", "Skin: Not checked",
                                                     "Settings: Not checked",
                                                     "Private settings: Not checked"])
                self.assertIn("The check could not finish.", dialog.details[0][1])
                self.assertNotIn(SECRET, dialog.everything)
                self.assertNotIn("RuntimeError", dialog.everything)

    def test_failed_check_again_replaces_a_good_result_with_not_checked(self):
        results = [status(), RuntimeError(SECRET)]

        def provider():
            value = results.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        _, dialog, _ = open_status(provider, 5)
        self.assertEqual(rows(dialog, 0)[0], "Overall: Healthy")
        self.assertEqual(rows(dialog, 1)[0], "Overall: Not Fully Checked")

    def test_other_workflows_remain_placeholders(self):
        for index in range(3):
            _, dialog, _ = run(status, [index, 0, -1, -1])
            self.assertEqual(dialog.details, [(STRINGS[32100 + index], STRINGS[32120 + index])])


class Language(unittest.TestCase):
    BANNED = ("reconcil", "lifecycle", "transaction", "adapter", "schema", "manifest",
              "fingerprint", "artifact", "activation hold", "quarantine", "durable",
              "private-resource", "validation report", "exact-version", "desired state", "owner",
              "structured", "configuration", "frozen", "overlay", "sqlite", "inspector")
    RAW = ("traceback", "exception", "sha256", "password", "token", "secret", "api_key", "/users/")

    def test_every_status_string_exists_and_is_plain(self):
        for identifier in sorted(STATUS_TEXT_IDS):
            self.assertIn(identifier, STRINGS, identifier)
        for identifier in range(32401, 32541):
            if identifier not in STRINGS:
                continue
            lowered = STRINGS[identifier].lower()
            for term in self.BANNED + self.RAW:
                self.assertNotIn(term, lowered, (identifier, term))

    def test_the_status_blocks_are_all_used(self):
        defined = {i for i in STRINGS if 32401 <= i <= 32540}
        self.assertEqual(defined, set(STATUS_TEXT_IDS) & set(range(32401, 32541)))

    def test_every_view_text_renders_without_falling_back_to_a_raw_template(self):
        ui = NativeDialogs(Addon(), Dialog([]), lambda ms: None)
        statuses = [status(), changes_needed(), not_checked(),
                    status(overall=OverallStatus.NEEDS_ATTENTION, operation=OperationStatus(
                        OperationKind.NEEDS_ATTENTION, OperationCode.OPERATION_NOT_FINISHED,
                        protection_active=True))]
        for gap in CheckGap:
            statuses.append(status(overall=OverallStatus.INCOMPLETE, gaps=(gap,),
                                   software=SoftwareStatus(AreaLevel.UNAVAILABLE),
                                   skin=SkinStatus(AreaLevel.UNAVAILABLE, "", "", None)))
        for code in OperationCode:
            if code is OperationCode.NONE:
                continue
            statuses.append(status(overall=OverallStatus.NEEDS_ATTENTION, operation=OperationStatus(
                OperationKind.NEEDS_ATTENTION, code)))
        models = [StatusViewModel.from_status(s) for s in statuses] + [StatusViewModel.unavailable()]
        for model in models:
            for row in model.rows:
                for text in (row.label, row.state, *row.detail):
                    rendered = ui.render(text)
                    self.assertNotIn("%", rendered, text)
                    self.assertTrue(rendered.strip(), text)
                self.assertNotIn("%", ui.row_text(row))

    def test_view_texts_only_reference_allowlisted_strings(self):
        for bad in (99999, 32000, "32420", True, None):
            with self.assertRaises(ValueError):
                Text(bad)
        for kwargs in (dict(count=-2), dict(count="3"), dict(name=SECRET * 10),
                       dict(refs=(99999,)), dict(refs=(32420, 32421, 32422))):
            with self.assertRaises(ValueError):
                Text(32420, **kwargs)

    def test_a_translated_string_without_placeholders_cannot_break_the_page(self):
        class Bare(Addon):
            def getLocalizedString(self, identifier):
                return "plain %d text" if identifier == status_view.S_CFG_TOTAL else "x"
        dialog = Dialog([STATUS, 3, -1, -1])
        NativeDialogs(Bare(), dialog, lambda ms: None, changes_needed).run()
        self.assertEqual(dialog.selects[1][1][0], "x: x")


class SecretBlind(unittest.TestCase):
    def test_real_status_through_the_real_dialogs_never_shows_a_secret(self):
        for arrange in (lambda h: None,
                        lambda h: h.save_overlay(resource_value=DB_SECRET + "-changed"),
                        lambda h: h.config_backend.settings.update({(DEMO, "api_token"): "x"}),
                        lambda h: h.overlay_store.path_for("status-overlay").unlink()):
            h = Harness(self)
            h.save_overlay()
            arrange(h)
            provider = lambda: h.service().check(h.target())
            _, dialog, _ = run(provider, [STATUS, 0, 1, 2, 3, 4, 5, 6, -1, -1])
            self.assertEqual(len(dialog.details), 6)
            for secret in (SECRET, DB_SECRET, "SENTINEL_BACKEND_ERROR_TEXT", "/Users", "Traceback"):
                self.assertNotIn(secret, dialog.everything)
            self.assertNotIn(SECRET, "\n".join(h.logs))
            self.assertNotIn(DB_SECRET, "\n".join(h.logs))

    def test_view_model_repr_is_secret_blind(self):
        h = Harness(self)
        h.save_overlay()
        h.config_backend.settings[(DEMO, "api_token")] = "changed"
        model = StatusViewModel.from_status(h.check())
        self.assertNotIn(SECRET, repr(model))
        self.assertNotIn(DB_SECRET, repr(model))
        self.assertNotIn("changed", repr(model))

    def test_check_again_through_the_real_service_reads_once_and_changes_nothing(self):
        h = Harness(self)
        h.save_overlay()
        h.restart_transaction()
        service = h.service()
        before = snapshot_tree(h.profile)
        with h.instrumented():
            _, dialog, _ = run(lambda: service.check(h.target()), [STATUS, 5, 5, -1, -1])
        self.assertEqual(h.kodi.calls, 3)             # entry + two Check Again presses
        self.assertEqual(h.touched, [])
        self.assertEqual(h.config_backend.mutations, [])
        self.assertEqual(h.deps.mutations, [])
        self.assertEqual(snapshot_tree(h.profile), before)
        self.assertEqual(rows(dialog)[0], "Overall: Restart Required")


class Entry(unittest.TestCase):
    def test_default_py_wires_a_lazy_read_only_provider_and_logs_only_safe_text(self):
        import ast
        import default
        logs = []
        xbmc = SimpleNamespace(log=lambda message, level=0: logs.append(message), LOGINFO=1)
        sentinel = status()
        with patch("resources.lib.status.check_build_status") as check:
            check.side_effect = lambda log: (log("Build Status check: current"), sentinel)[1]
            self.assertIs(default.status_provider(xbmc)(), sentinel)
        self.assertEqual(logs, ["[script.build.manager] Build Status check: current"])
        tree = ast.parse((ROOT / "default.py").read_text())
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(top_level, [])          # the engine is imported only when asked

    def test_production_wiring_runs_end_to_end_without_kodi_and_changes_nothing(self):
        from resources.lib import status as status_module
        h = Harness(self, with_private=False, with_resource=False)
        # Library authority rejects ancestor symlinks, including macOS /var.
        # Canonicalize only this disposable fixture before runtime translation.
        profile = h.profile.resolve()
        window = SimpleNamespace(
            getProperty=lambda key: SESSION_A,
            setProperty=lambda *a: self.fail("a Kodi window property was written"))
        xbmcvfs = SimpleNamespace(translatePath=lambda path: str(
            profile / path.replace("special://profile/", "").lstrip("/")))
        modules = {"xbmcvfs": xbmcvfs, "xbmcgui": SimpleNamespace(Window=lambda _id: window)}
        before = snapshot_tree(profile)
        with patch.dict(sys.modules, modules):
            clean = status_module.check_build_status(log=h.logs.append)
            self.assertEqual(snapshot_tree(profile), before)        # no directory, no lock file
            h.restart_transaction()
            pending_before = snapshot_tree(profile)
            pending = status_module.check_build_status(log=h.logs.append)
        self.assertEqual((clean.overall, clean.build_selected),
                         (OverallStatus.INCOMPLETE, False))
        self.assertEqual(clean.gaps, (CheckGap.NO_BUILD_SELECTED,))
        self.assertEqual(pending.overall, OverallStatus.RESTART_REQUIRED)
        self.assertEqual(snapshot_tree(profile), pending_before)
        self.assertEqual(h.logs, ["Build Status check: incomplete",
                                  "Build Status check: restart_required"])


if __name__ == "__main__":
    unittest.main()
