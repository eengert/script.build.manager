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

A successful library Install records the exact entry/profile in the separate
Build Library `applied.json` record. The existing frozen lifecycle owner writes it
only at its validated terminal completion boundary, after resolution evidence,
updater restoration and transaction cleanup succeed. Reviewed missing-package
choices retain that same target identity. `awaiting_restart`, cancellation,
failure, active work and attention never advance the association. Restart/resume
uses the original typed `library_target` persisted in the frozen transaction,
independently of the current selection. Legacy path installs do not guess identity.
Association persistence failure produces a stable attention result rather than
claiming completion; the prior record remains when publication fails before
replacement. The completed transaction has already been cleared at this point,
so a later retry uses the normal reviewed Install path.

Offline tests cover native selection/confirmation, approval freshness, safe
errors, deferred runtime composition, and real disposable library -> Plan ->
repository preparation -> reviewed saved-package execution. Runtime/remote
focus, restart UI qualification, and beta acceptance require separate work.
