"""Update / Repair Build for the build verified as applied to this Kodi installation.

The verified applied association is the only starting point; saved selection is
never used. Check for Changes uses the same read-only plan as Install. Apply runs
only after an exact CHANGES_READY plan is reviewed, explicitly confirmed, and
validated CURRENT immediately before mutation, and then through the existing
frozen lifecycle. This module never writes the applied association, the saved
selection, or applied.json; completion and publication belong to the frozen
owners. Unsupported version changes and broken-add-on repair (G6) are reported
as blocked before Apply and never worked around.
"""
from resources.lib.build_library import LibraryInstallTarget
from resources.lib.frozen_resolution import InstallResolution, ResolutionChoice
from resources.lib.install_workflow import result_message, runtime_library_services, settle_library_plan
from resources.lib.plan_model import PlanState
from resources.lib.ui import repair_view as view


class _RepairDecisions:
    """Presents the shared decision and preparation steps in Update / Repair windows."""

    def __init__(self, ui):
        self._ui = ui

    def install_message(self, string_id):
        self._ui.repair_message(string_id)

    def choose_install_decision(self, prompt):
        return self._ui.choose_install_decision(prompt)

    def prepare_install(self, prepare):
        return self._ui.repair_prepare(prepare)


class _Session:
    """One Update / Repair visit. Choosing a revision never persists anywhere."""

    def __init__(self, applied, applied_entry):
        self.applied = applied              # PlanTarget carrying the verified association
        self.applied_entry = applied_entry  # LibraryEntry of the applied revision
        self.desired = applied              # what Check for Changes compares Kodi with
        self.desired_entry = applied_entry

    def adopt(self, applied, applied_entry, complete):
        """Re-read after an apply attempt; only a completed publication moves desired."""
        self.applied, self.applied_entry = applied, applied_entry
        if complete:
            self.desired, self.desired_entry = applied, applied_entry

    def summary(self):
        applied, desired = self.applied_entry, self.desired_entry
        return view.RepairSummary(
            applied_name=view.friendly(applied.display_name),
            applied_version=view.friendly(applied.build_version),
            profile=view.friendly(self.applied.device_profile_id),
            desired_name=view.friendly(desired.display_name),
            desired_version=view.friendly(desired.build_version),
            changed=desired.entry_id != applied.entry_id)


def _accepted_exceptions(target):
    """Whether the applied outcome carries an accepted skip, which is an exception too."""
    if target.install_resolution is None:
        return False
    return any(record.resolution is InstallResolution.SKIPPED for record in target.install_resolution.records)


def _limit_notes(plan):
    """Supported-scope limits. A non-empty result means no Apply is offered. Only the
    blockers Update / Repair cannot change yet (G6) qualify; a recorded outcome never does."""
    return tuple(dict.fromkeys(
        view.NOTE_FOR_BLOCKER[b.code] for b in plan.blockers if b.code in view.NOTE_FOR_BLOCKER))


def _session_choices(target):
    """The answers reviewed in this visit. A recorded outcome is never answered again:
    the prior accepted resolution is handed to the engine whole, and it binds there."""
    return {addon_id: ResolutionChoice(choice.value) for addon_id, choice in target.choices}


class UpdateRepairWorkflow:
    def __init__(self, library, plan, preparation, coordinator_provider):
        self.library = library
        self.plan = plan
        self.preparation = preparation
        self.coordinator_provider = coordinator_provider

    def run(self, ui):
        applied = self._applied()
        if applied is None:
            ui.repair_message(view.S_NO_VERIFIED_BUILD)
            return
        session = _Session(*applied)
        while True:
            action = ui.repair_choose_action(session.summary())
            if action == 'check':
                result = self._check(ui, session)
                if result is not None:
                    applied = self._applied()
                    if applied is None:
                        ui.repair_message(view.S_NO_VERIFIED_BUILD)
                        return
                    session.adopt(*applied, complete=result.outcome == 'complete')
            elif action == 'revision':
                self._choose_revision(ui, session)
            else:
                return

    def _applied(self):
        """(PlanTarget, LibraryEntry) of the verified applied association, or None."""
        target = self.library.associated_plan_target()
        if target is None:
            return None
        return target, self.library.get(target.library_source.entry_id)

    def _check(self, ui, session):
        """Compare Kodi with the desired revision; Apply only after review and confirmation.

        Returns the installer result when an apply was attempted, otherwise None.
        """
        target = session.desired  # answers made during this check survive a stale re-review, as Install's do
        while True:
            settled = settle_library_plan(_RepairDecisions(ui), self.plan, self.preparation, target)
            if settled is None:
                return None
            target, plan, model = settled
            if plan.state is PlanState.NO_CHANGES:
                ui.repair_show_healthy(model)
                return None
            notes = _limit_notes(plan)
            if plan.state is not PlanState.CHANGES_READY or notes:
                ui.repair_show(model, notes)
                return None
            if plan.review is None:
                ui.repair_message(view.S_NOT_APPLIED)
                return None
            if ui.repair_approve(session.summary(), model) is not True:
                return None
            check = self.plan.validate(target, plan.review)
            if not check.is_current:
                ui.repair_message(view.S_STALE)
                continue  # fresh preview and a new explicit approval, never silent approval
            install_target = LibraryInstallTarget.from_plan_target(target)
            choices = _session_choices(target)
            result = ui.execute_install(lambda: self.coordinator_provider().install_target(
                install_target, prepared_resolution=target.prepared_resolution,
                prior_resolution=target.install_resolution,
                resolution_choices=choices, interactive=False))
            message = result_message(result, target)
            if result.outcome == 'complete' and (choices or _accepted_exceptions(target)):
                # Accepted skips carried from the applied outcome are exceptions too.
                message = view.S_COMPLETE_WITH_EXCEPTIONS
            ui.repair_message(message)
            return result

    def _choose_revision(self, ui, session):
        """Another registered revision of the same build for the applied profile.

        Only this session's desired target changes. Nothing is previewed, applied,
        selected, or written until Check for Changes is run and approved.
        """
        applied_entry = session.applied_entry
        profile = session.applied.device_profile_id
        entries = tuple(entry for entry in self.library.list_builds()
                        if entry.build_id == applied_entry.build_id
                        and profile in entry.device_profiles)
        if not any(entry.entry_id != applied_entry.entry_id for entry in entries):
            ui.repair_message(view.S_NO_OTHER_REVISION)
            return
        chosen = ui.choose_repair_revision(entries, applied_entry.entry_id)
        if chosen is None:
            return
        if chosen.entry_id == applied_entry.entry_id:
            session.desired, session.desired_entry = session.applied, applied_entry
            return
        # A different revision starts without any prior install resolution.
        session.desired = self.library.plan_target(chosen.entry_id, profile)
        session.desired_entry = chosen


def runtime_update_repair_workflow():
    """Called only when Update / Repair opens; no mutating owner is built before Apply."""
    from resources.lib.build_library import default_build_library
    _owners, plan, preparation, coordinator = runtime_library_services()
    return UpdateRepairWorkflow(default_build_library(), plan, preparation, coordinator)
