# Update / Repair Build — supported beta workflow

Owner: `resources/lib/update_repair_workflow.py`. Presentation: `resources/lib/ui/repair_view.py`
and the Update / Repair windows in `resources/lib/ui/native_dialogs.py`. Shared decision and
preparation steps: `settle_library_plan()` in `resources/lib/install_workflow.py`.

## Starting point

- The only starting point is the verified applied association
  (`BuildLibrary.associated_plan_target()`). Saved selection is never used, and nothing is
  guessed from it.
- With no verified applied association the page says so and points to Install Build. It
  starts no plan, no transaction, and no installation.

## Overview

- Shows the applied build (name, version, device profile) read-only.
- `Check for Changes` compares Kodi with the desired revision (initially the applied one).
- `Choose Different Revision...` lists only registered revisions of the same `build_id` that
  support the applied device profile. Choosing one changes only this visit's desired target.
  It does not write the applied association, the saved selection, or `applied.json`, and it
  previews nothing until `Check for Changes` runs.
- `Help` opens H04. `Back` closes the page.

## Check for Changes

Uses `BuildPlanService.preview()` on the exact desired target. It never uses
`BuildManager.preview()`.

| Plan state | What the user sees | Apply offered |
|---|---|---|
| `NO_CHANGES` | Current / Healthy, checked time, nothing needed | No |
| `CHANGES_READY` | Reviewed changes | Yes, after review and explicit confirmation |
| `DECISION_REQUIRED` | Only the choices the plan permits; Cancel does no work | Through a fresh plan |
| `RESOLUTION_REQUIRED` | Repository-current package is retrieved for review, not applied | Through a fresh plan |
| `BLOCKED` | Blockers, with supported-scope notes | No |
| `INCOMPLETE` | What could not be checked | No |

Pending restart, needs-attention, and unavailable operation states arrive as `BLOCKED` or
`INCOMPLETE` from the plan and never offer Apply.

## Apply

1. The reviewed plan must carry a review identity.
2. The user chooses `Apply Changes` and then explicitly confirms.
3. `BuildPlanService.validate()` runs immediately before mutation. Anything other than
   `CURRENT`, including `UNVERIFIABLE`, applies nothing. The user sees a message and a fresh
   plan, and must approve again. Approval never carries over.
4. The exact `LibraryInstallTarget.from_plan_target()` runs through
   `FrozenInstallCoordinator.install_target()` with `interactive=False`. The prepared
   resolution is carried exactly as Install carries it.
5. `resolution_choices` contain the answers reviewed in this visit plus each accepted skip
   recorded for the applied build. A recorded skip is carried as `SKIP` and reported as an
   exception.

Completion is reported from the frozen lifecycle's outcome. Update / Repair never writes the
applied association. A `complete` outcome means the frozen publication path has recorded the
new association. Restart-required, active, needs-attention, cancelled, and user-resolution
outcomes are not success.

## Supported-scope limits (G6 and related)

These are blocked before Apply and are never worked around:

- A managed add-on with a different installed version (`DIFFERENT_VERSION_INSTALLED`). Update /
  Repair cannot change installed versions yet.
- A broken installed managed add-on (`INSTALLED_ADDON_BROKEN`). Update / Repair cannot repair
  it yet.
- A repository package recorded for the applied build. The installer needs a fresh package
  choice for that record, and the reviewed plan cannot bind it, so Apply is refused. Checks
  still run and show Current / Healthy when nothing needs changing.

Known residual limit: `RepositoryPreparationService.prepare()` refuses a target that already
carries an applied install resolution. Choosing the repository-current package for a missing
add-on on an applied build therefore stops with the safe "could not be prepared" message.

## Not in this workflow

- Uninstalling, deleting, or overwriting an installed add-on's live directory.
- Calling `install_exact` on a version change or broken repair.
- Silently using a repository version.
- Writing `applied.json`, the applied association, or the saved selection directly.
- Any live Kodi, Test.app, device, or push activity: this module is offline and fully
  dependency-injected in its tests.
