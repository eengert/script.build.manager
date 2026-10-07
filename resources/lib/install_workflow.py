"""Confirmed library Install orchestration; lifecycle remains with frozen owners."""
from dataclasses import replace

from resources.lib.build_library import LibraryInstallTarget
from resources.lib.frozen_resolution import ResolutionChoice
from resources.lib.plan_model import DecisionChoice, PlanState
from resources.lib.repository_preparation import PreparationCode
from resources.lib.status_model import OperationKind
from resources.lib.ui.plan_view import ReviewViewModel


class InstallWorkflow:
    def __init__(self, library, plan, preparation, coordinator_provider, operation_provider):
        self.library = library
        self.plan = plan
        self.preparation = preparation
        self.coordinator_provider = coordinator_provider
        self.operation_provider = operation_provider

    def run(self, ui):
        operation = self.operation_provider()
        if operation.kind is not OperationKind.NONE:
            ui.install_message({OperationKind.RESTART_REQUIRED: 32810,
                                OperationKind.NEEDS_ATTENTION: 32812}.get(operation.kind, 32811))
            return
        entries = self.library.list_builds()
        if not entries:
            ui.install_message(32802)
            return
        entry = ui.choose_install_build(entries)
        if entry is None:
            return
        profile = ui.choose_install_profile(entry.device_profiles)
        if profile is None:
            return
        target = self.library.plan_target(entry.entry_id, profile)
        while True:
            plan = self.plan.preview(target)
            model = ReviewViewModel.from_plan(plan, fully_listed=True, repository_current=tuple(
                aid for aid, choice in target.choices if choice is DecisionChoice.INSTALL_CURRENT))
            if plan.state is PlanState.DECISION_REQUIRED:
                if not model.decisions:
                    ui.install_message(32814)
                    return
                for prompt in model.decisions:
                    # A provider ignoring a prior answer cannot spin or bypass review.
                    if prompt.addon_id in dict(target.choices):
                        ui.install_message(32814)
                        return
                    choice = ui.choose_install_decision(prompt)
                    if choice is None or choice is DecisionChoice.CANCEL:
                        return
                    if choice not in prompt.choices:
                        ui.install_message(32814)
                        return
                    target = target.with_choice(prompt.addon_id, choice)
                continue
            if plan.state is PlanState.RESOLUTION_REQUIRED:
                if target.prepared_resolution is not None or not any(
                        c is DecisionChoice.INSTALL_CURRENT for _, c in target.choices):
                    ui.install_message(32804)
                    return
                result = ui.prepare_install(lambda: self.preparation.prepare(target))
                if result.code is not PreparationCode.READY:
                    ui.install_message(32804)
                    return
                target = replace(target, prepared_resolution=result.prepared)
                continue
            if plan.state is not PlanState.CHANGES_READY:
                ui.show_install_review(model)
                return
            if plan.review is None:
                ui.install_message(32814)
                return
            if not ui.confirm_install(entry, profile, model):
                return
            check = self.plan.validate(target, plan.review)
            if not check.is_current:
                ui.install_message(32808)
                continue  # fresh preview and a new explicit confirmation, never silent approval
            install_target = LibraryInstallTarget.from_plan_target(target)
            result = ui.execute_install(lambda: self.coordinator_provider().install_target(
                install_target, prepared_resolution=target.prepared_resolution,
                resolution_choices={aid: ResolutionChoice(c.value) for aid, c in target.choices},
                interactive=False))
            ui.install_message(result_message(result, target))
            return


def result_message(result, target):
    if result.outcome == 'complete':
        return 32816 if target.choices else 32809
    return {'awaiting_restart': 32810, 'active': 32811,
            'needs_attention': 32817, 'cancelled': 32813,
            'user_resolution_required': 32814}.get(result.outcome, 32814)


def runtime_install_workflow():
    """Called only when Install opens; constructing execution owners waits for Apply."""
    from resources.lib.build_library import default_build_library
    from resources.lib.plan import BuildPlanService, default_plan_owners
    from resources.lib.status import BuildStatusService
    from resources.lib.repository_preparation import RepositoryPreparationService
    from resources.lib.frozen_install import (FrozenInstallCoordinator, FrozenInstallStore,
        KodiRuntimeFrozenArtifactBackend, default_frozen_install_root, _default_policy_backend)
    from resources.lib.artifacts import ArtifactStore
    from resources.lib.restart_coordinator import RestartCoordinator
    owners = default_plan_owners()
    def coordinator():
        return FrozenInstallCoordinator(store=FrozenInstallStore(),
            artifact_store=ArtifactStore(default_frozen_install_root() / 'frozen-artifacts'),
            policy_backend=_default_policy_backend(), installer=KodiRuntimeFrozenArtifactBackend(),
            configuration_runner=RestartCoordinator().reconcile)
    class Preparation:
        def prepare(self, target):
            return RepositoryPreparationService(
                ArtifactStore(default_frozen_install_root() / 'frozen-artifacts')).prepare(target)
    return InstallWorkflow(default_build_library(), BuildPlanService(owners), Preparation(),
        coordinator, lambda: BuildStatusService(owners.status).inspect_operation([]))
