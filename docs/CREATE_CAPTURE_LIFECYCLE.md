# Create private capture lifecycle — Stages 1 and 2A

This is an **offline foundation**, addressing the private Create blocker under
macOS Beta exit item 8. It is not wired to native Create, service startup, or
Kodi runtime operations. `runtime_create_workflow()` still constructs the
default, unsafe-for-capture Red Light adapter and fails closed; its lifecycle
protections have not been weakened. Item 8 acceptance remains open.

`CaptureLifecycleCoordinator` has no Install/Apply/reconciliation capability,
resource initializer, private-setting writer, default seeder, updater-policy
setter, or restart executor. Its one permitted mutation capability is an
injected setter for the exact audited owner's enabled state. Stage 1 admits
`plugin.video.redlight` 2.6.8 with the trusted catalog declaration.

## Durable identity and authority

`create_capture_transaction.json` is a versioned Create-only record in the same
profile-local directory as frozen-install and restart state. It binds a fresh
operation UUID, phase, a canonical SHA-256 digest of **every field of the exact
Create request**, owner/version, original enabled state, originating session,
creation/expiration times, and the verified capture session. Stage 2A persists
validated request metadata **in the same atomic record as the hold**, alongside
the full-request digest. The metadata contains these exact categories:

- Build ID, version, free-text `build_name` and `description`.
- Platform and device profile identifiers and their labels.
- Root add-on IDs, the include-active-skin flag, and expected active skin ID.
- Configuration package ID; public setting declaration identities (add-on ID,
  key, setting type and target kind); and declared public file destinations.
- Private setting declaration identities (add-on ID, key, setting type,
  required flag, sensitivity classification and target kind), **not values**.
- Trusted private resource catalog IDs (`redlight.settings`), reconstructed from
  the catalog rather than treating persisted resource definitions as authority.
- Private overlay ID, **not private overlay contents**.

Captured public/private resource values, credentials read from resources,
capture results and private overlay contents are not persisted in the lifecycle
record. User-provided free text is persisted verbatim after request validation;
validation does not guarantee that a name, description or label contains no
secret. Callers must keep sensitive values out of those fields. `safe_dict()`
exposes only operation ID, phase, hold and outcome; errors omit metadata and
exception text.

A caller can reconstruct the exact typed request read-only using the operation
UUID and request fingerprint. Reconstruction validates record schema, metadata,
full-request digest, owner/version and trusted catalog identities, and rereads
the record to detect change. It creates no directories or lock files and invokes
no operations callbacks. Missing/legacy metadata remains retained and blocks
reconstruction and lifecycle transitions; it does not release an active hold.
Normal reconstruction remains expiry-bound. Recovery-purpose reconstruction
may occur after expiry, but still rejects clock rollback and mismatched
identity. It grants no capture, restart, restoration or release authority:
explicit `recover()` must independently pass the locked transition checks.
Persisted owner/version identifies the audited resource; reconstruction is not
fresh verification of the installed owner. Mutating transitions separately
check the installed owner through the injected operations capability.
Private setting declarations are not scoped to root add-ons at Stage 2A admission.
Stage 2A does not persist a UI form or implement UI/startup resume composition.
A changed request or an old operation UUID never acquires authority over a
newer record. Lifecycle `COMPLETE` is not build registration.

The profile filesystem is trusted, and the profile root is trusted application
input, using the existing restart store's canonical-profile model. Capture canonicalizes ancestor directories
(including legitimate symlinked profile ancestors), retains the final state
directory as a no-follow component, and requires the restart store to identify
the same canonical root. The frozen store used by the coordinator receives that
root. Opened canonical directory components are bound by device/inode identity;
missing directories are created only by mutating transitions. Alias drift,
replacement or loss of an already-bound component fails closed within that
CaptureStore instance. This detection does not persist across independent
operations or sessions that construct a new store. Replacing or deleting durable
state can defeat new-instance discovery; cross-session state-tampering recovery
is deferred.

Capture reads, competing frozen-install/restart record reads, locks, temporary
writes, replacement, directory sync and temporary cleanup use opened directory
descriptors, so a pathname swap cannot redirect them to another root. Competing
reads during locked transitions use the same authoritative descriptor as the
three locks, without reopening the path for record admission. Observation pins
its own canonical descriptor and creates no directories or locks. Competing
records use the existing bounded no-follow reader and their original typed
validators; stable absence permits admission. The pinned directory's
`st_mtime_ns` and `st_ctime_ns` are compared immediately before and after both
competing-record reads. Any detected directory timestamp change during that bounded
observation fails closed, regardless of the returned record values. Unsafe,
unreadable, corrupt and unsupported records also fail closed.

This timestamp-based check depends on the trusted profile filesystem reporting
those changes at sufficiently fine timestamp resolution. It was verified for
immediate synthetic record moves on macOS/APFS and is not guaranteed for
coarse-resolution filesystems. It does not detect movement before or after the
observation window or establish cross-process or cross-session tamper detection.
It is not a filesystem integrity monitor. CaptureStore/coordinator composition
remains single-threaded; the transition descriptor is sampled once per competing
observation, retained by the existing lock scope, and cleared on exit. This does
not add shared-store threading support or lock reentrancy.
All three operation locks keep their existing filenames and OS flock semantics;
lock substitution is rejected. Final state-file symlinks, nonregular/oversized
files and malformed records remain refused. A symlinked final state directory
also fails closed and may block profile-wide admission and activation; Stage 2A
does not change that policy. Reconstruction only opens and reads.

The phase atomically owns the activation hold: all nonterminal phases retain
it, including interrupted preparation, capture and restoration. There is no
independent release flag that can drift from the operation phase. Shared
`active_activation_hold_ids()` includes Create holds, so existing activation
guards and private-resource hold readers see them. Corrupt capture state, or
a competing durable transaction while capture is held, fails closed.

Install admission and frozen/restart transaction creation reject a held
capture. Restart coordination and direct BuildManager reconciliation reject
capture before invoking their mutating owners. Capture takes the existing
frozen-install and restart OS locks, plus its own OS lock, throughout a
transition and its callbacks. It rejects busy locks, pending Install or restart
transactions detected by its bounded competing-record observation, and an
injected in-flight-operation conflict. This guarantee applies only when their
records are present during that observation; a record moved away before
observation begins is outside it. It does not borrow a `RestartTransaction`,
`ReconcileRequest`, or transaction-access capability to gain Install/Apply
authority.

## Transitions and recovery

1. Explicit `confirmed=True` admits `PREPARING`. Persist original enablement
   and the hold before disabling; verify disabled state, then durably enter
   `AWAITING_RESTART`. An originally disabled owner still requires restart.
   An exact confirmed same-session preparation retry reuses the operation and
   original enablement, verifies any partial disable, and never repeats a
   completed disable. An awaiting-restart retry returns the same record.
2. Capture requires an exact request/operation/owner match, a nonexpired
   record, disabled state, an intact hold, a different current session, and
   an explicit verified complete-process-restart boundary. A changed Kodi
   session property alone never grants eligibility.
3. Persist `CAPTURING` with the new session before invoking a trusted read-only
   callback. The callback receives a revalidation function; the coordinator
   also verifies the boundary before and after the callback. Private results
   stay in memory. `COMPLETE` means the capture lifecycle completed, not that
   a build was registered, installed, or accepted in Test.app.
4. Persist `RESTORING` and the intended outcome before restoring precisely the
   original enabled state. Verify owner/version, record identity and enabled
   state before entering `COMPLETE`, `CANCELLED`, or `FAILED`, releasing the
   hold. Originally disabled owners remain disabled.
5. Explicit `recover()` cancels or records failure, including after process
   interruption. It never replays capture or guesses original enablement.
   `PREPARING` may still have original enablement; `RESTORING` may already
   reflect the owned setter's effect when acknowledgment was lost. Those
   tolerate original enablement before release. Explicit recovery also accepts
   already-restored original enablement without another setter call, persisting
   RESTORING and the terminal outcome before releasing the hold. Capture
   completion still rejects unexpected enablement, including after its callback.
   Recovery may finish after ordinary expiry; preparation/retry and capture
   admission remain expiry-bound. Clock rollback remains blocked. Recovery
   grants neither capture nor restart authority.
   Repeating recovery for an exact terminal operation returns its record only
   while original enablement still matches; it performs no lifecycle mutation.

Missing/corrupt/replaced state, clock rollback, owner drift, unexpected
enablement, competing operations, and lost restart proof cannot produce a
capture result or automatic restoration/release. An interrupted read is not
automatically replayed. If the original-state setter fails or its effect cannot
be verified, retain the record/hold for explicit recovery. A persistence error
may occur after replacement: retain the published record, never erase evidence
or roll back blindly. Corrupt records require a separately designed safe
recovery policy; these stages provide no override or force-release path.

## Injected operations and remaining runtime work

All operations are mandatory trusted application capabilities:

- `session_id()` returns the existing process-session identity format.
- `owner_version(owner)` and `enabled(owner)` verify exact installed ownership
  and state; unknown enabled state is never coerced to false.
- `set_enabled(owner, bool)` only changes that owner's enablement. Future
  runtime composition must give restoration narrowly owned permission while
  shared activation remains held; generic activation bypasses are prohibited.
- `competing_operation()` must positively establish the absence of in-flight
  Install/restart/activation operations, beyond just inspecting record files.
- `verify_restart(operation_id, old_session, new_session)` must independently
  establish the complete Kodi-process restart boundary for this operation.
  A new session UUID is necessary but insufficient. There is no default
  implementation that returns true.

Future bounded stages must supply verified Kodi lifecycle operations, persist
the confirmed UI request for reconstruction, present confirmation/restart and
recovery states, preserve original desired enablement in captured build output,
compose an existing-resource capture adapter without initialization, handle
registration outcomes, and qualify the exact candidate in authorized portable
Test.app. Startup must never hand a Create record to Install/Apply resume.
None of these runtime/UI/startup actions is authorized or enabled by Stage 1.

## Evidence

`tests/test_capture_lifecycle.py` uses temporary profiles and synthetic
operations. It exercises durable reconstruction, original-state restoration,
crash/partial-effect recovery, shared guards, corruption/staleness/identity
drift, competing records and locks, restart proof loss, and persistence errors.
One test calls the real Red Light adapter against a disposable existing WAL
SQLite resource, forbids initialize/Apply, and compares database/sidecar bytes.
This is offline evidence only; no Kodi, Test.app, household profile or device
is accessed.
