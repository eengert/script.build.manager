"""BM-UI-002C: the native Review Changes page is human-readable, review-only and secret-blind."""
import json
import re
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resources.lib import plan as plan_module
from resources.lib.plan import BuildPlanService, PlanTarget, plan_provider
from resources.lib.plan_model import (
    BlockerCode, BuildPlan, DecisionChoice, PlanBlocker, PlanState, PrivatePlan, PrivatePlanKind,
    RestartPlan, SettingsPlan, SettingsPlanKind, SkinPlan, SkinPlanKind, SoftwareAction,
    SoftwareRow,
)
from resources.lib.redlight_resource import REDLIGHT_ADDON_ID
from resources.lib.status_model import CheckGap
from resources.lib.status import default_status_owners
from resources.lib.ui import plan_view
from resources.lib.ui.native_dialogs import NativeDialogs
from resources.lib.ui.plan_view import PLAN_TEXT_IDS, ReviewViewModel, Text
from tests.test_plan import (
    EXTRA, PLUGIN_TYPE, REPOSITORY, REPO_TYPE, FrozenInstallPolicyMode, PlanBase, PlanHarness,
)
from tests.test_status import DB_SECRET, DEMO, MODULE, NOW, SECRET, SKIN
from tests.test_status_ui import STRINGS, Addon

ROOT = Path(__file__).resolve().parents[1]


class Dialog:
    """A native Kodi dialog stand-in: records everything, and has no way to confirm an operation."""

    def __init__(self, choices=()):
        self.choices, self.selects, self.details = iter(choices), [], []

    def select(self, heading, labels, preselect=0):
        self.selects.append((heading, list(labels), preselect))
        return next(self.choices)

    def textviewer(self, heading, text):
        self.details.append((heading, text))

    def yesno(self, *args, **kwargs):
        raise AssertionError("Review Changes asked for a confirmation")

    ok = yesno

    @property
    def everything(self):
        return json.dumps([self.selects, self.details])


def review(provider, choices=()):
    addon, dialog, waits = Addon(), Dialog(choices), []
    NativeDialogs(addon, dialog, waits.append).review(provider)
    return dialog


NAMES = {DEMO: "Demo Video", MODULE: "Demo Module", SKIN: "Arctic Fuse 3",
         REDLIGHT_ADDON_ID: "Red Light", REPOSITORY: "Demo Repository", EXTRA: "Extra Videos",
         "plugin.example": "plugin.example"}


class ReviewBase(PlanBase):
    def named(self, h):
        return h.plan_service(status=h.owners(name_resolver=lambda addon_id: NAMES.get(addon_id, "")))

    def body(self, dialog):
        self.assertEqual(len(dialog.details), 1)
        return dialog.details[0]


class ReviewPage(ReviewBase):
    def test_a_ready_plan_reads_like_the_review_in_plain_language(self):
        h = self.current()
        del h.kodi.addons[REDLIGHT_ADDON_ID]                          # to install
        h.kodi.addons[DEMO] = ("1.0.0", False)                        # to enable
        h.kodi.skin = "skin.estuary"                                  # to change
        h.config_backend.settings[(DEMO, "quality")] = "SENTINEL_LOW"
        h.config_backend.files["userdata/keymaps/demo.xml"] = b"<other/>"
        h.save_overlay(value="SENTINEL_NEW_PRIVATE")                  # to restore
        service = self.named(h)
        with h.instrumented():
            dialog = review(lambda choices: service.preview(h.plan_target()))
        h.assert_untouched()
        heading, body = self.body(dialog)
        self.assertEqual(heading, "Review Changes")
        self.assertEqual(body.split("\n\n")[:5], [
            "Add-ons\n• Install Red Light 2.6.8\n• Enable Demo Video\n"
            "• 3 add-ons are already up to date",
            "Skin\n• Change to Arctic Fuse 3",
            "Settings\n• 2 settings will be updated",
            "Private settings\n• Settings will be restored",
            "Restart\n• Kodi will need to be closed and reopened",
        ])
        self.assertEqual(dialog.selects, [])

    def test_disabled_installed_repository_name_flows_into_plan_and_review_text(self):
        addon_id = "repository.eengert"
        h = self.current()
        h.set_graph(extra=[(addon_id, "1.0.0", REPO_TYPE, ())], without=(REPOSITORY,))
        h.kodi.addons.pop(REPOSITORY)
        h.deps.installed.pop(REPOSITORY)
        h.kodi.addons[addon_id] = ("1.0.0", False)
        h.deps.installed[addon_id] = ("1.0.0", False)
        h.save_overlay()
        requests = []
        name_available = [True]

        def execute_json_rpc(request):
            body = json.loads(request)
            requests.append(body)
            requested_id = body["params"]["addonid"]
            if requested_id not in h.kodi.addons:
                return json.dumps({"error": {"code": -32602}})
            result = {"addonid": requested_id}
            if requested_id != addon_id or name_available[0]:
                result["name"] = ("Eengert Repository" if requested_id == addon_id
                                  else requested_id)
            return json.dumps({"result": {"addon": result}})

        with patch.dict("sys.modules", {"xbmc": SimpleNamespace(executeJSONRPC=execute_json_rpc)}):
            production_owners = default_status_owners()
            service = h.plan_service(status=h.owners(name_resolver=production_owners.name_resolver))
            with h.instrumented():
                plan = service.preview(h.plan_target())
            name_available[0] = False
            with h.instrumented():
                fallback_plan = service.preview(h.plan_target())
        h.assert_untouched()

        row = next(row for row in plan.software if row.addon_id == addon_id)
        self.assertEqual((row.addon_id, row.action, row.display_name),
                         (addon_id, SoftwareAction.ENABLE, "Eengert Repository"))
        dialog = review(lambda _choices: plan)
        body = dialog.details[0][1]
        self.assertIn("Enable Eengert Repository", body)
        self.assertNotIn("Enable repository.eengert", body)
        self.assertIn(addon_id, {request["params"]["addonid"] for request in requests})

        fallback_row = next(row for row in fallback_plan.software if row.addon_id == addon_id)
        self.assertEqual((fallback_row.display_name, fallback_row.label), ("", addon_id))
        fallback_body = review(lambda _choices: fallback_plan).details[0][1]
        self.assertIn("Enable repository.eengert", fallback_body)

    def test_a_blocked_plan_says_what_is_in_the_way_in_simple_words(self):
        h = self.current()
        h.set_graph(extra=[("plugin.example", "1.0.0", PLUGIN_TYPE, ())])
        h.kodi.addons["plugin.example"] = ("2.0.0", True)
        h.save_overlay()
        dialog = review(lambda choices: self.named(h).preview(h.plan_target()))
        heading, body = self.body(dialog)
        self.assertEqual(heading, "Build Manager can't continue yet")
        content, _, checked = body.partition("\n\n")
        self.assertEqual(content, "\u2022 plugin.example has a different version installed. "
                                  "Build Manager can't safely replace it yet.")
        self.assertRegex(checked, r"^Checked at \d\d:\d\d$")

    def test_nothing_to_change_and_not_fully_checked_are_both_plain(self):
        h = self.current()
        heading, body = self.body(review(lambda c: self.named(h).preview(h.plan_target())))
        self.assertEqual((heading, body.split("\n")[:2]),
                         ("Nothing needs to change", ["Add-ons", "• Everything already matches this build."]))
        h.kodi.skin = ""
        heading, body = self.body(review(lambda c: self.named(h).preview(h.plan_target())))
        self.assertEqual(heading, "Build Manager couldn't check everything")
        self.assertIn("Build Manager could not tell which skin is active.", body)
        self.assertNotIn("add-on list", body)

    def test_every_view_string_exists_and_takes_the_arguments_it_is_given(self):
        for string_id in PLAN_TEXT_IDS:
            self.assertIn(string_id, STRINGS, string_id)
        for string_id in sorted(set(plan_view.SOFTWARE_LINE.values()) | {32626, 32640, 32630}):
            self.assertRegex(STRINGS[string_id], r"%[sd]")
        for string_id in set(plan_view.BLOCKER_LINE.values()) - {
                STRINGS and plan_view.BLOCKER_LINE[c] for c in plan_view.NAMED_BLOCKERS}:
            self.assertNotIn("%", STRINGS[string_id])
        for code in plan_view.NAMED_BLOCKERS:
            self.assertIn("%s", STRINGS[plan_view.BLOCKER_LINE[code]], code)
        for code in BlockerCode:
            self.assertIn(code, plan_view.BLOCKER_LINE)

    def test_no_developer_terminology_hash_path_or_enum_name_reaches_the_page(self):
        h = self.current()
        pages = []
        for arrange in (lambda: None, lambda: h.kodi.addons.__setitem__(MODULE, ("2.0.1", True)),
                        lambda: h.kodi.addons.pop(MODULE), lambda: h.restart_transaction(),
                        lambda: setattr(h.kodi, "skin", "")):
            arrange()
            dialog = review(lambda c: self.named(h).preview(h.plan_target()))
            pages.append(" ".join(dialog.details[0]))
        text = " ".join(pages) + " ".join(STRINGS[i] for i in PLAN_TEXT_IDS)
        self.assertFalse(re.search(r"[0-9a-f]{32}", text))
        for forbidden in ("sha256", "fingerprint", "manifest", "frozen", "transaction", "overlay",
                          "JSON", "Traceback", "Exception", "/Users", "special://", "BLOCKED",
                          "CHANGES_READY", "DECISION_REQUIRED", "INCOMPLETE", "NO_CHANGES",
                          "different_version", "DIFFERENT_VERSION", "enum", "G6", "WindowXML"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_review_never_offers_to_apply_anything(self):
        h = self.current()
        del h.kodi.addons[MODULE]
        dialog = review(lambda c: self.named(h).preview(h.plan_target()))
        shown = (dialog.everything + " ".join(STRINGS[i] for i in PLAN_TEXT_IDS)).lower()
        for word in ("apply", "start the", "begin", "proceed", "confirm", "install now", "go ahead"):
            self.assertNotIn(word, shown, word)
        self.assertEqual(dialog.selects, [])                    # no selectable action at all
        self.assertEqual(len(dialog.details), 1)                # one native viewer, closed with its own Close

    def test_private_values_and_paths_never_reach_the_page(self):
        h = self.current()
        h.config_backend.settings[(DEMO, "api_token")] = SECRET
        h.save_overlay(value=SECRET + "-new", resource_value=DB_SECRET + "-new")
        dialog = review(lambda c: self.named(h).preview(h.plan_target()))
        self.assertSecretFree(dialog.everything, "\n".join(h.logs))
        self.assertNotIn("/build.json", dialog.everything)

    def test_a_hostile_display_name_cannot_inject_markup_into_the_page(self):
        h = self.current()
        del h.kodi.addons[MODULE]
        hostile = {MODULE: "[B]Boom[/B] $INFO[Window.Property(x)]‮"}
        service = h.plan_service(status=h.owners(name_resolver=lambda i: hostile.get(i, "")))
        dialog = review(lambda c: service.preview(h.plan_target()))
        page = " ".join(dialog.details[0])
        for dangerous in ("[B]", "[/B]", "$INFO", "‮", "["):
            self.assertNotIn(dangerous, page)
        self.assertIn("Install", page)

    def test_a_provider_that_fails_shows_the_not_checked_page_without_error_text(self):
        def broken(choices):
            raise RuntimeError("SENTINEL_BACKEND_ERROR_TEXT " + SECRET)
        dialog = review(broken)
        heading, body = self.body(dialog)
        self.assertEqual(heading, "Build Manager couldn't check everything")
        self.assertSecretFree(dialog.everything)
        self.assertIn("The check could not finish.", body)

    def test_a_provider_that_returns_something_else_is_not_trusted(self):
        for bogus in (None, {}, "ready", object()):
            dialog = review(lambda c, bogus=bogus: bogus)
            self.assertEqual(dialog.details[0][0], "Build Manager couldn't check everything")


class Decisions(ReviewBase):
    def missing_package(self):
        h = PlanHarness(self, with_resource=False)
        h.set_graph(extra=[(EXTRA, "1.0.0", PLUGIN_TYPE, ())],
                    policies=[h.policy(EXTRA, FrozenInstallPolicyMode.EXACT_FIRST_REPOSITORY_OR_SKIP)])
        h.forget_package(EXTRA)
        del h.kodi.addons[MODULE]
        h.save_overlay()
        return h

    def provider(self, h, seen):
        def provide(choices):
            seen.append(dict(choices))
            target = h.plan_target()
            for addon_id, choice in choices.items():
                target = target.with_choice(addon_id, choice)
            return self.named(h).preview(target)
        return provide

    def test_a_missing_package_is_asked_about_before_the_review_and_the_answer_is_used(self):
        h, seen = self.missing_package(), []
        dialog = review(self.provider(h, seen), [1])                  # "Skip this add-on"
        heading, labels, _ = dialog.selects[0]
        self.assertEqual(heading, "The saved copy of Extra Videos is missing")
        self.assertEqual(labels, ["Install the current version", "Skip this add-on", "Cancel"])
        self.assertEqual(seen, [{}, {EXTRA: DecisionChoice.SKIP}])
        title, body = self.body(dialog)
        self.assertEqual(title, "Review Changes")
        self.assertIn("Skip Extra Videos (you chose not to install it)", body)
        self.assertIn("Install Demo Module 2.0.0", body)

    def test_choosing_the_current_version_is_described_without_promising_a_version(self):
        h, seen = self.missing_package(), []
        dialog = review(self.provider(h, seen), [0])
        title, body = self.body(dialog)
        self.assertEqual(title, "Repository version needed")
        self.assertIn("before you can review the final changes", body)
        self.assertNotIn("Install the current version of Extra Videos", body)

    def test_cancelling_the_choice_explains_why_nothing_can_continue(self):
        h, seen = self.missing_package(), []
        dialog = review(self.provider(h, seen), [2])
        title, body = self.body(dialog)
        self.assertEqual(title, "Build Manager can't continue yet")
        self.assertIn("You chose to cancel because of Extra Videos.", body)

    def test_going_back_from_a_question_decides_nothing_and_shows_nothing(self):
        h, seen = self.missing_package(), []
        dialog = review(self.provider(h, seen), [-1])
        self.assertEqual((dialog.details, seen), ([], [{}]))

    def test_a_provider_that_ignores_a_choice_cannot_trap_the_user(self):
        h = self.missing_package()
        plan = self.named(h).preview(h.plan_target())               # always undecided
        self.assertEqual(plan.state, PlanState.DECISION_REQUIRED)
        dialog = review(lambda choices: plan, [1, 1, 1, 1])
        self.assertEqual(len(dialog.selects), 1)
        self.assertEqual(len(dialog.details), 1)

    def test_the_explicit_target_provider_applies_choices_to_a_fresh_plan_each_time(self):
        target = PlanTarget("/b.json", "d", "/f.json")
        calls = []
        with patch.object(plan_module, "preview_build_plan",
                          lambda chosen, log=None: calls.append(chosen) or "plan"):
            provide = plan_provider(target)
            self.assertEqual(provide(), "plan")
            self.assertEqual(provide({"plugin.video.a": DecisionChoice.SKIP}), "plan")
        self.assertEqual(calls[0].choices, ())
        self.assertEqual(calls[1].choices, (("plugin.video.a", DecisionChoice.SKIP),))
        self.assertEqual(target.choices, ())                         # the caller's target is untouched


class ViewModel(unittest.TestCase):
    def test_text_can_only_name_an_allowlisted_string(self):
        for kwargs in (dict(string_id=99999), dict(string_id="32600"), dict(string_id=32600, count=-5),
                       dict(string_id=32600, name="x" * 141), dict(string_id=32600, name=3),
                       dict(string_id=32600, refs=(99999,)), dict(string_id=32600, refs=(1, 2, 3))):
            with self.subTest(kwargs), self.assertRaises(ValueError):
                Text(**kwargs)
        Text(32620, name="Red Light 2.6.8")

    def test_a_long_list_is_capped_with_a_count(self):
        rows = tuple(SoftwareRow("plugin.video.a%03d" % i, SoftwareAction.ENABLE) for i in range(40))
        plan = BuildPlan(PlanState.CHANGES_READY, NOW, rows, SkinPlan(SkinPlanKind.NOT_APPLICABLE),
                         SettingsPlan(SettingsPlanKind.NOT_APPLICABLE), PrivatePlan(PrivatePlanKind.NOT_USED),
                         RestartPlan())
        lines = ReviewViewModel.from_plan(plan).sections[0].lines
        self.assertEqual(len(lines), plan_view.MAX_LISTED + 1)
        self.assertEqual(lines[-1], Text(plan_view.S_MORE_ITEMS, 25))

    def test_every_blocker_and_state_has_text(self):
        blockers = [PlanBlocker(code, "plugin.video.a" if code in plan_view.NAMED_BLOCKERS else "")
                    for code in BlockerCode]
        rows = (SoftwareRow("plugin.video.a", SoftwareAction.BLOCKED),)
        plan = BuildPlan(PlanState.BLOCKED, NOW, rows, SkinPlan(SkinPlanKind.UNAVAILABLE),
                         SettingsPlan(SettingsPlanKind.UNAVAILABLE), PrivatePlan(PrivatePlanKind.UNAVAILABLE),
                         RestartPlan(), tuple(blockers[:14]), ())
        model = ReviewViewModel.from_plan(plan)
        self.assertEqual(len(model.sections[0].lines), plan_view.MAX_LISTED if len(blockers) > 15 else 14)
        for gap in CheckGap:
            if gap in plan_view.GAP_TEXT:
                self.assertIn(plan_view.GAP_TEXT[gap], PLAN_TEXT_IDS)
        for state in PlanState:
            self.assertIn(plan_view.TITLE[state], PLAN_TEXT_IDS)

    def test_the_menu_routes_still_start_nothing_and_do_not_open_the_review(self):
        from resources.lib.ui.controller import ROUTES, Route
        addon, dialog, waits = Addon(), Dialog([ROUTES.index(Route.INSTALL), -1, -1]), []
        ui = NativeDialogs(addon, dialog, waits.append)
        with patch.object(NativeDialogs, "review", side_effect=AssertionError("review opened")):
            ui.run()
        self.assertEqual(dialog.details, [])


if __name__ == "__main__":
    unittest.main()
