"""Skin-owned native dialogs. No route starts a product operation; Build Status
and Review Changes call only an injected read-only provider."""
from resources.lib.ui.controller import ROUTES, TITLE_IDS, CONTEXT_HELP, Route
from resources.lib.ui.help_content import SECTIONS
from resources.lib.ui.models import PageModel, Semantic, SEMANTIC_LABELS
from resources.lib.ui.plan_view import CHOICE_LABEL, ReviewViewModel
from resources.lib.ui.plan_view import Text as PlanText
from resources.lib.ui.status_view import (
    S_CHECK_AGAIN, S_CHECKED_AT, S_CLOSE, S_ROW, StatusViewModel,
)

class NativeDialogs:
    def __init__(self, addon, dialog, settle, status_provider=None):
        self.addon = addon
        self.dialog = dialog
        self.settle = settle
        self.status_provider = status_provider
        self.main_selection = 0
        self.help_selection = 0

    def text(self, identifier):
        return self.addon.getLocalizedString(identifier)

    def select(self, heading, labels, preselect):
        selected = self.dialog.select(heading, labels, preselect=preselect)
        # Let the closing native dialog consume key/mouse release before
        # opening another one; otherwise an event can reach the new dialog.
        self.settle(200)
        return selected

    def viewer(self, heading, body):
        self.dialog.textviewer(heading, body)
        self.settle(200)

    def detail(self, section):
        item = SECTIONS[section]
        model = PageModel(item.title_id, item.body_id)
        self.viewer(self.text(model.title_id), self.text(model.body_id))

    def help(self):
        while True:
            selected = self.select(self.text(32105),
                [self.text(s.title_id) for s in SECTIONS], preselect=self.help_selection)
            if not 0 <= selected < len(SECTIONS):
                return
            self.help_selection = selected
            self.detail(selected)

    def foundation(self, route):
        index = ROUTES.index(route)
        model = PageModel(TITLE_IDS[index], 32120 + index, Semantic.UNAVAILABLE)
        # A native choice menu exposes contextual Help without a mutation prompt.
        heading = self.text(model.title_id) + ' — ' + self.text(SEMANTIC_LABELS[model.semantic])
        selection = 0
        while True:
            selected = self.select(heading,
                [self.text(32150), self.text(32112), self.text(32113)], preselect=selection)
            if selected == 0:
                self.viewer(self.text(model.title_id), self.text(model.body_id))
            elif selected == 1:
                self.detail(CONTEXT_HELP[route])
            else:
                return
            selection = selected

    def render(self, text):
        """Localized text with its constrained arguments; never raises."""
        template = self.text(text.string_id)
        args = ([text.name] if text.name else []) + [self.text(r) for r in text.refs]
        if text.count >= 0:
            args.append(text.count)
        if not args:
            return template
        try:
            return template % tuple(args)
        except (TypeError, ValueError):
            return template

    def row_text(self, row):
        label, state = self.render(row.label), self.render(row.state)
        try:
            return self.text(S_ROW) % (label, state)
        except (TypeError, ValueError):
            return label + ': ' + state

    def check_status(self):
        """One fresh read-only check; any failure becomes the not-checked view."""
        try:
            return StatusViewModel.from_status(self.status_provider())
        except Exception:
            return StatusViewModel.unavailable()

    def status(self):
        model = self.check_status()
        count = len(model.rows)
        selection = 0
        while True:
            rows = [self.row_text(r) for r in model.rows]
            selected = self.select(self.text(TITLE_IDS[3]),
                rows + [self.text(S_CHECK_AGAIN), self.text(32112), self.text(S_CLOSE)],
                preselect=selection)
            if 0 <= selected < count:
                row = model.rows[selected]
                self.viewer(self.render(row.label), '\n'.join(self.render(t) for t in row.detail))
            elif selected == count:
                model = self.check_status()
            elif selected == count + 1:
                self.detail(CONTEXT_HELP[Route.STATUS])
            else:
                return
            selection = selected

    # -- Review Changes (read-only) -------------------------------------------------------

    def check_plan(self, plan_provider, choices):
        """One fresh read-only plan; any failure becomes the not-checked view."""
        try:
            return ReviewViewModel.from_plan(plan_provider(dict(choices)))
        except Exception:
            return ReviewViewModel.unavailable()

    def review_body(self, model):
        parts = []
        for section in model.sections:
            if section.heading is not None:
                parts.append(self.render(section.heading))
            parts.extend('\u2022 ' + self.render(line) for line in section.lines)
            parts.append('')
        if model.check_time:
            parts.append(self.render(PlanText(S_CHECKED_AT, name=model.check_time)))
        return '\n'.join(parts).strip()

    def review(self, plan_provider):
        """Review Changes. It shows what would change and what is in the way, asks
        for any missing-package choice, and offers nothing that starts work: the
        page ends with the native viewer's own close action."""
        choices = {}
        while True:
            model = self.check_plan(plan_provider, choices)
            if not model.decisions or model.decisions[0].addon_id in choices:
                break           # nothing to decide, or a provider that ignores a choice already made
            prompt = model.decisions[0]
            selected = self.select(self.render(prompt.heading),
                [self.text(CHOICE_LABEL[c]) for c in prompt.choices], preselect=0)
            if not 0 <= selected < len(prompt.choices):
                return          # Back: nothing was decided and nothing was started
            choices[prompt.addon_id] = prompt.choices[selected]
        self.viewer(self.render(model.title), self.review_body(model))

    def run(self):
        while True:
            selected = self.select(self.text(32000),
                [self.text(i) for i in TITLE_IDS], preselect=self.main_selection)
            if not 0 <= selected < len(ROUTES):
                return
            self.main_selection = selected
            route = ROUTES[selected]
            if route == Route.HELP:
                self.help()
            elif route == Route.SETTINGS:
                self.addon.openSettings()
                self.settle(200)
            elif route == Route.STATUS:
                self.status()
            else:
                self.foundation(route)
