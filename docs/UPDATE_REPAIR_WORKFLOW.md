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
5. The applied outcome is passed whole as `prior_resolution`: the same validated
   `FrozenInstallResolutionManifest` the reviewed plan used. The answers reviewed in this visit
   are passed as `resolution_choices`. A published applied outcome covers every installable
   add-on, so it never needs a new answer. A reused accepted skip is reported as an exception.

Completion is reported from the frozen lifecycle's outcome. Update / Repair never writes the
applied association. A `complete` outcome means the frozen publication path has recorded the
new association. Restart-required, active, needs-attention, cancelled, and user-resolution
outcomes are not success.

## Applied outcome reuse

A prior accepted outcome is evidence of what was accepted, never permission to fetch a newer
package. `FrozenInstallCoordinator.install_target(prior_resolution=...)` binds it again, library
installs only, before any mutation:

- It must bind exactly to this build, frozen manifest, and current install policies
  (`bind_resolutions`). The source, plan, and resulting-software fingerprints must match.
- It must still be the verified applied association for this library entry and device profile
  at execution time. A changed association is refused.
- Every record must satisfy the terminal rules that restart restoration uses:
  - exact: the captured artifact identity, in the installed state;
  - repository-current: the recorded repository, the exact saved package, and its dependency
    semantics. The saved bytes are required and must match. The repository is never queried,
    and a newer package is never fetched;
  - skipped: still skipped, with the skip policy and no installed copy.
- An installed managed add-on must already match its recorded version and be healthy. A
  different installed version or a broken installed add-on is refused (G6 stays blocked).
- The transaction durably records the prior fingerprint. A retry or resume with a different
  prior outcome is a different operation and is refused, never treated as equivalent.

Check for Changes reads the same recorded outcome. A recorded package that is gone, or whose
bytes do not match, blocks with `PACKAGE_MISSING` even when the add-on is installed, because
execution needs those bytes.

## Decision invariant

A published applied outcome records a terminal resolution for every installable add-on. The
executor records each one at completion, and restart restoration checks that coverage.
Check for Changes therefore never asks for a new decision or a new repository package on the
applied revision. `RepositoryPreparationService` keeps refusing targets that carry an applied
resolution, and nothing widens it. Only a partial bound outcome, which publication never
produces, can reach a decision. The plan tests in `tests/test_recorded_resolution.py` document
that boundary.

Different revisions carry no prior outcome. They keep the ordinary decision, preparation, and
fresh-review path.

## Supported-scope limits (G6)

These are blocked before Apply and are never worked around:

- A managed add-on with a different installed version (`DIFFERENT_VERSION_INSTALLED`). Update /
  Repair cannot change installed versions yet.
- A broken installed managed add-on (`INSTALLED_ADDON_BROKEN`). Update / Repair cannot repair
  it yet.

## Not in this workflow

- Uninstalling, deleting, or overwriting an installed add-on's live directory.
- Calling `install_exact` on a version change or broken repair.
- Silently using a repository version.
- Writing `applied.json`, the applied association, or the saved selection directly.
- Any live Kodi, Test.app, device, or push activity: this module is offline and fully
  dependency-injected in its tests.
