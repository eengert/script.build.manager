"""Skin-owned dialogs. Create uses an injected confirmed workflow; Status and
Review Changes retain their read-only providers."""
from resources.lib.ui.controller import ROUTES, TITLE_IDS, CONTEXT_HELP, Route
from resources.lib.ui.help_content import SECTIONS
from resources.lib.ui.models import PageModel, Semantic, SEMANTIC_LABELS
from resources.lib.ui.plan_view import CHOICE_LABEL, ReviewViewModel, S_CONFIRMATION_SUMMARY
from resources.lib.ui.plan_view import Text as PlanText
from resources.lib.ui import repair_view as repair
from resources.lib.ui.status_view import (
    S_CHECK_AGAIN, S_CHECKED_AT, S_CLOSE, S_ROW, StatusViewModel,
)

class NativeDialogs:
    def __init__(self, addon, dialog, settle, status_provider=None, create_provider=None, busy=None, install_provider=None, repair_provider=None):
        self.addon = addon
        self.dialog = dialog
        self.settle = settle
        self.status_provider = status_provider
        self.create_provider = create_provider
        self.busy = busy
        self.install_provider = install_provider
        self.repair_provider = repair_provider
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

    def create(self):
        from resources.lib.create_workflow import CreateValidationError
        try:
            workflow = self.create_provider()
            session = workflow.open(self.text(32703))
        except Exception as exc:
            self.dialog.ok(self.text(32100), self.text(exc.string_id if isinstance(exc, CreateValidationError) else 32722))
            return
        focus = 0
        while True:
            labels = [self.text(32700) + ': ' + session.name,
                      self.text(32701) + ': ' + session.version,
                      self.text(32702) + ': ' + session.device_label,
                      self.text(32704) % (len(session.selected), len(session.components)),
                      self.text(32705) + ': ' + self.text(32706 if session.include_private else 32707),
                      self.text(32708), self.text(32112), self.text(32113)]
            choice = self.select(self.text(32100), labels, focus)
            if not 0 <= choice < 7:
                return
            focus = choice
            try:
                if choice in (0, 1, 2):
                    prior = (session.name, session.version, session.device_label)[choice]
                    value = self.dialog.input(self.text((32700, 32701, 32702)[choice]), defaultt=prior)
                    self.settle(200)
                    if not value:
                        continue
                    if choice == 0:
                        version = workflow.suggest_version(value)
                        session.name, session.version = value, version
                    elif choice == 1:
                        from resources.lib.create_workflow import version_tuple
                        version_tuple(value)
                        session.version = value
                    else:
                        from resources.lib.create_workflow import identity
                        identity(value)
                        session.device_label = value
                elif choice == 3:
                    rows = [c.label + (' — ' + self.text(32709) if c.current_skin else '') for c in session.components]
                    indices = self.dialog.multiselect(self.text(32710), rows,
                        preselect=[i for i,c in enumerate(session.components) if c.addon_id in session.selected])
                    self.settle(200)
                    session.choose(indices)
                elif choice == 4:
                    session.include_private = not session.include_private
                elif choice == 6:
                    self.detail(CONTEXT_HELP[Route.CREATE])
                else:
                    preview = workflow.preview(session)
                    request = preview.request
                    roots, excluded, public_settings, public_files, private_settings, private_resources = preview.counts
                    body = '\n'.join([self.text(32700) + ': ' + request.build_name,
                        self.text(32701) + ': ' + request.build_version,
                        self.text(32702) + ': ' + request.device_label,
                        self.text(32711) % (roots, excluded),
                        self.text(32712 if request.include_active_skin else 32713),
                        self.text(32714) % (public_settings, public_files),
                        self.text(32715) % (private_settings, private_resources) if preview.private_enabled else self.text(32716)])
                    preview_focus = 0
                    while True:
                        action = self.select(self.text(32708), [self.text(32717), self.text(32718), self.text(32112), self.text(32113)], preview_focus)
                        if action == 1:
                            self.viewer(self.text(32718), body + ('\n\n' + self.text(32719) + '\n' + '\n'.join(preview.excluded_labels) if preview.excluded_labels else ''))
                        elif action == 2:
                            self.detail(CONTEXT_HELP[Route.CREATE])
                        elif action == 0:
                            confirmed = self.dialog.yesno(self.text(32100), body,
                                nolabel=self.text(32113), yeslabel=self.text(32717))
                            self.settle(200)
                            if not confirmed:
                                break
                            if self.busy:
                                self.busy(True)
                            try:
                                terminal = workflow.execute(preview)
                            finally:
                                if self.busy:
                                    self.busy(False)
                            message = self.text(terminal.string_id)
                            if terminal.string_id in (32735, 32736):
                                message += '\n' + request.build_name + ' ' + request.build_version
                                message += '\n' + self.text(32737) % terminal.addon_count
                                message += '\n' + self.text(32712 if terminal.skin_included else 32713)
                                message += '\n' + self.text(32738 if terminal.private_included else 32739)
                            self.dialog.ok(self.text(32100), message)
                            self.settle(200)
                            return
                        else:
                            break
                        preview_focus = action
            except Exception as exc:
                self.dialog.ok(self.text(32100), self.text(exc.string_id if isinstance(exc, CreateValidationError) else 32732))
                self.settle(200)

    # Install presentation keeps all target/review/lifecycle state in the workflow.
    def install_message(self, string_id):
        self.dialog.ok(self.text(32101), self.text(string_id))
        self.settle(200)

    @staticmethod
    def install_label(value):
        from resources.lib.status_model import is_plain_name
        # Catalog identity is internal. Only bounded plain friendly metadata is shown.
        return value if is_plain_name(value) and value else '—'

    def choose_install_build(self, entries):
        labels = [self.install_label(e.display_name) + ' ' + self.install_label(e.build_version)
                  + ' — ' + ', '.join(self.install_label(p) for p in e.device_profiles)
                  for e in entries]
        selected = self.select(self.text(32800), labels, 0)
        return entries[selected] if 0 <= selected < len(entries) else None

    def choose_install_profile(self, profiles):
        selected = self.select(self.text(32801), [self.install_label(p) for p in profiles], 0)
        return profiles[selected] if 0 <= selected < len(profiles) else None

    def choose_install_decision(self, prompt):
        selected = self.select(self.render(prompt.heading),
            [self.text(CHOICE_LABEL[c]) for c in prompt.choices], 0)
        return prompt.choices[selected] if 0 <= selected < len(prompt.choices) else None

    def prepare_install(self, prepare):
        # Visible preparation label; this is retrieval, never an installation claim.
        self.viewer(self.text(32101), self.text(32803))
        return self.execute_install(prepare)

    def execute_install(self, execute):
        if self.busy:
            self.busy(True)
        try:
            return execute()
        finally:
            if self.busy:
                self.busy(False)

    def show_install_review(self, model):
        self.viewer(self.render(model.title), self.review_body(model))

    def install_confirmation_body(self, entry, profile, model):
        summary = model.confirmation_summary
        if summary.single_change is not None:
            change_line = self.render(summary.single_change)
        else:
            change_line = self.text(S_CONFIRMATION_SUMMARY) % (
                summary.change_count, summary.accepted_skip_count)
        return '\n'.join((
            self.install_label(entry.display_name) + ' ' + self.install_label(entry.build_version),
            self.text(32801) + ': ' + self.install_label(profile),
            change_line,
            self.text(32815),
        ))

    def confirm_install(self, entry, profile, model):
        body = self.install_confirmation_body(entry, profile, model)
        focus = 0
        while True:
            action = self.select(self.text(32101),
                [self.text(32806), self.text(32807), self.text(32112), self.text(32113)], focus)
            if action == 0:
                self.viewer(self.render(model.title), self.review_body(model))
            elif action == 1:
                confirmed = self.dialog.yesno(self.text(32805), body,
                    nolabel=self.text(32113), yeslabel=self.text(32807))
                self.settle(200)
                return bool(confirmed)
            elif action == 2:
                self.detail(CONTEXT_HELP[Route.INSTALL])
            else:
                return False
            focus = action

    # Update / Repair presentation. The workflow owns every decision and transition.

    def repair(self):
        try:
            self.repair_provider().run(self)
        except Exception:
            self.repair_message(repair.S_NOT_APPLIED)

    def repair_message(self, string_id):
        self.dialog.ok(self.text(repair.S_TITLE), self.text(string_id))
        self.settle(200)

    def repair_prepare(self, prepare):
        # Visible preparation label; retrieval only, never an Update or Repair claim.
        self.viewer(self.text(repair.S_TITLE), self.text(repair.S_PREPARE))
        return self.execute_install(prepare)

    def repair_choose_action(self, summary):
        """Read-only applied and desired revisions, then the next step.

        Returns 'check' or 'revision'; None means the user went back.
        """
        details = [(self.text(repair.S_APPLIED_ROW) % (summary.applied_name, summary.applied_version, summary.profile),
                    self.text(repair.S_APPLIED_DETAIL) % (summary.applied_name, summary.applied_version, summary.profile))]
        if summary.changed:
            details.append((self.text(repair.S_DESIRED_ROW) % (summary.desired_name, summary.desired_version),
                            self.text(repair.S_DESIRED_DETAIL) % (summary.desired_name, summary.desired_version)))
        actions = ((repair.S_CHECK_FOR_CHANGES, 'check'), (repair.S_CHOOSE_REVISION, 'revision'),
                   (repair.S_HELP, 'help'), (repair.S_BACK, 'back'))
        count, focus = len(details), 0
        while True:
            rows = [label for label, _ in details] + [self.text(string_id) for string_id, _ in actions]
            selected = self.select(self.text(repair.S_TITLE), rows, preselect=focus)
            if 0 <= selected < count:
                self.viewer(self.text(repair.S_TITLE), details[selected][1])
            elif count <= selected < count + len(actions):
                action = actions[selected - count][1]
                if action in ('check', 'revision'):
                    return action
                if action == 'help':
                    self.detail(CONTEXT_HELP[Route.REPAIR])
                else:
                    return None
            else:
                return None
            focus = selected

    def choose_repair_revision(self, entries, applied_entry_id):
        labels = [self.install_label(e.display_name) + ' ' + self.install_label(e.build_version)
                  + (' ' + self.text(repair.S_APPLIED_MARK) if e.entry_id == applied_entry_id else '')
                  for e in entries]
        selected = self.select(self.text(repair.S_REVISION_HEADING), labels, 0)
        return entries[selected] if 0 <= selected < len(entries) else None

    def repair_show(self, model, notes=()):
        """A review with no Apply: blocked, incomplete, or a limit that stops Apply."""
        parts = [self.review_body(model)] + [self.text(string_id) for string_id in notes]
        self.viewer(self.render(model.title), '\n\n'.join(part for part in parts if part))

    def repair_show_healthy(self, model):
        parts = (self.text(repair.S_HEALTHY_BODY), self.review_body(model))
        self.viewer(self.text(repair.S_HEALTHY_TITLE), '\n\n'.join(part for part in parts if part))

    def repair_approve(self, summary, model):
        """Reviewed changes only. Apply Changes must be chosen, then explicitly confirmed."""
        self.viewer(self.render(model.title), self.review_body(model))
        selected = self.select(self.render(model.title),
            [self.text(repair.S_APPLY_CHANGES), self.text(repair.S_BACK)], preselect=1)
        if selected != 0:
            return False
        confirmed = self.dialog.yesno(self.text(repair.S_CONFIRM_APPLY),
            self.repair_confirmation_body(summary, model),
            nolabel=self.text(repair.S_BACK), yeslabel=self.text(repair.S_APPLY_CHANGES))
        self.settle(200)
        return bool(confirmed)

    def repair_confirmation_body(self, summary, model):
        change = model.confirmation_summary
        if change.single_change is not None:
            change_line = self.render(change.single_change)
        else:
            change_line = self.text(S_CONFIRMATION_SUMMARY) % (change.change_count, change.accepted_skip_count)
        return '\n'.join((summary.desired_name + ' ' + summary.desired_version, summary.profile,
                          change_line, self.text(repair.S_CONFIRM_RESTART)))

    def install(self):
        try:
            self.install_provider().run(self)
        except Exception:
            self.install_message(32814)

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
            elif route == Route.CREATE and self.create_provider is not None:
                self.create()
            elif route == Route.INSTALL and self.install_provider is not None:
                self.install()
            elif route == Route.REPAIR and self.repair_provider is not None:
                self.repair()
            elif route == Route.STATUS:
                self.status()
            else:
                self.foundation(route)
