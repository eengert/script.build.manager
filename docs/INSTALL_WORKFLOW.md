# Native Install Build

`InstallWorkflow` owns a single selection/review/apply session. `NativeDialogs`
handles presentation and user input; `default.py` supplies a lazy runtime factory.
No runtime owners are constructed merely by importing the entrypoint.

The library's read-only `plan_target(entry_id, device_profile_id)` validates the
explicit entry/profile without reading or changing the saved selection. The
session retains that exact source while collecting only Plan-offered choices.
Cancel before Apply abandons the session without starting an installation.

Repository Current is explicitly prepared before review. A READY result is
attached to the same source/profile/choices and followed by a fresh preview.
Install's review shows every change and accepted Skip, without list truncation.
Prepared Repository Current rows show their resolved version and explain that
it may differ from capture. The shared view model remains engine-independent.

Only CHANGES_READY with a review identity offers Apply. The final confirmation
repeats build/version/profile, the complete review, and temporary protection.
Back is the default. After explicit approval, validate the exact target/review.
STALE or UNVERIFIABLE produces another preview and requires new user approval.
CURRENT permits `LibraryInstallTarget.from_plan_target(target)` followed by
`install_target(target, prepared_resolution=..., resolution_choices=...,
interactive=False)`. There is no policy override, path installation, saved
selection lookup, or post-review repository fetch.

Opening Install checks existing operation state read-only before selection.
Terminal result dialogs map stable outcomes to localized text and ignore raw
backend messages. Restart required and needs attention never imply success.
The existing frozen/BM-020/startup owners retain restart/resume responsibility;
this frontend neither resumes manually nor modifies their durable records.
Update / Repair remains unavailable.

A successful library Install records the exact entry/profile and completed
resolution through the existing frozen lifecycle owner. After final validation,
resolution persistence and updater restoration, the owner atomically fences its
exact COMPLETE transaction as PUBLICATION_PENDING. Abandon, generic clear and
phase transitions cannot discard this fence; another Install cannot replace it.
The owner then creates durable PENDING evidence, positively acknowledges the
journal BEFORE publishing candidate applied bytes, verifies/durably materializes
the candidate, and clears the fence only against matching independent ACK/applied
evidence. Frozen and library writer locks are never held together.

PENDING masks candidate with previous or none. Visible ACK plus previous applied
is unresolved: readers retain previous, Status is non-idle and Install is blocked.
Failed ACK durability cannot report complete or newly expose candidate bytes.
Fresh recovery positively re-fsyncs ACK before materialization. ACK plus matching
candidate establishes association authority; a materialization durability failure
retains ACK and the frozen fence for recovery. Optional terminal journal cleanup
requires independently durable matching applied state, and cleanup ambiguity
cannot reverse authority.

Crash before journal creation recovers from the exact durable fence, without
software/configuration replay or selection. Existing COMPLETE records first acquire
the same fence. Recovery of an observed journal never recreates it after loss;
same-candidate completion is idempotent and newer authority supersedes stale owners.
Invalid or unresolved publication remains attention/non-idle until its owner
recovers. Retained terminal evidence does not intercept a different active/restart
owner. Read-only Status never fences, fsyncs, materializes or cleans evidence.

Accepted Skip and Repository Current choices remain attached to associated
Status/Plan through the exact completed resolution manifest. `awaiting_restart`,
cancellation, failure, active work and other noncomplete outcomes preserve the
prior association. Schema-4 restart/resume keeps the original typed target;
legacy path installs and schemas 1-3 do not guess library identity.

Offline tests cover native selection/confirmation, approval freshness, safe
errors, deferred runtime composition, and real disposable library -> Plan ->
repository preparation -> reviewed saved-package execution. Runtime/remote
focus, restart UI qualification, and beta acceptance require separate work.
