"""Skin-owned native dialogs. Foundation routes never invoke product operations."""
from resources.lib.ui.controller import ROUTES, TITLE_IDS, CONTEXT_HELP, Route
from resources.lib.ui.help_content import SECTIONS
from resources.lib.ui.models import PageModel, Semantic, SEMANTIC_LABELS

class NativeDialogs:
    def __init__(self, addon, dialog, settle):
        self.addon = addon
        self.dialog = dialog
        self.settle = settle
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
            else:
                self.foundation(route)
