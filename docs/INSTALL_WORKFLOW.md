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
resolution fingerprint through the existing frozen lifecycle owner. After final
validation, it persists resolution evidence, restores the updater and creates a
bounded PENDING journal from the exact still-live durable COMPLETE transaction.
It then clears that transaction, publishes schema-2 `applied.json`, verifies its
bytes, and atomically advances the journal to ACKNOWLEDGED. Success requires the
ACK file and directory durability barriers. Readback after failed fsync cannot
prove completion. PENDING masks candidate bytes with the previous verified
association (or none); ACKNOWLEDGED exposes the exact candidate and is nonblocking.

Failures retain PENDING, visible ambiguous ACK, or the exact COMPLETE transaction
when initial creation failed. The existing frozen startup/resume owner revalidates
and re-fsyncs evidence without software/configuration mutation or current selection.
Recovery of an observed journal never recreates it if another owner consumed it.
An already completed candidate resolves idempotently; superseded recovery is a
successful no-op, leaving newer authority untouched. Another pending identity
conflicts without mutation. Retained terminal journals do not intercept another
active/restart owner. Optional cleanup follows positively durable ACK and is never
the success proof; cleanup ambiguity or reappearing ACK cannot reverse authority.
Invalid or unresolved pending evidence remains attention and blocks Install.

Accepted Skip and Repository Current choices remain attached to associated
Status/Plan through the exact completed resolution manifest. `awaiting_restart`,
cancellation, failure, active work and other noncomplete outcomes preserve the
prior association. Schema-4 restart/resume keeps the original typed target;
legacy path installs and schemas 1-3 do not guess library identity.

Offline tests cover native selection/confirmation, approval freshness, safe
errors, deferred runtime composition, and real disposable library -> Plan ->
repository preparation -> reviewed saved-package execution. Runtime/remote
focus, restart UI qualification, and beta acceptance require separate work.
