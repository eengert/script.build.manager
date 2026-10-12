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

The phase and strictly validated `commit_pending` Boolean atomically own the
activation hold in one record: all nonterminal phases retain it, including
interrupted preparation, capture and restoration. A terminal phase retains the
hold while `commit_pending=True`; only a terminal with `commit_pending=False`
releases it. True is valid only with a terminal phase and its matching outcome.
Malformed types or inconsistent combinations fail closed. There is no separate
transaction sidecar. Shared
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
   state before entering `COMPLETE`, `CANCELLED`, or `FAILED` using the two
   terminal publications below. Originally disabled owners remain disabled.
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
   Repeating recovery for an exact released terminal operation returns its record
   only while original enablement still matches; it performs no lifecycle mutation.

### D2 Option A: strict safety with manual owner restoration

The approved Option A policy supersedes the unaccepted automatic D2 consent /
disable authority in commits `2d446946` and `98509f8`. For a transaction with
`original_enabled=False` and current Red Light enablement True, Build Manager
must refuse recovery and retain the activation hold. This condition requires
operator attention. It must never automatically disable the owner: Kodi 21.3
provides neither a trusted enablement generation nor an atomic conditional
setter. A stale confirmation can otherwise overwrite a newer enablement action,
including a complete external True -> False -> True sequence. Timestamps,
checksums, confirmation consumption, polling and retries cannot grant authority.

The compatibility names `prepare_d2_confirmation()` and `recover_d2()` now
unconditionally fail before locks, lifecycle writes or owner setters, even with
a valid historical `D2Confirmation`. The snapshot type remains strictly validated
for compatibility; it grants no action authority. No new D2 receipts are emitted.
Normal Create restoration for originally enabled owners remains supported.

The operator must manually disable Red Light in Kodi. Manual owner restoration
does not release transaction protection. Install, Restart and activation remain
blocked until explicit `recover(operation_id, request)` verifies the exact held
transaction, request, audited owner/version, Boolean original disabled state and
absence of competing operations. It finalizes without an owner setter, capture
or restart replay, using the accepted P5 pending-terminal commitment and release
below. A recorded RESTORING outcome remains unchanged, including COMPLETE or
FAILED; recovery does not silently replace it with CANCELLED. Already released
recovery is idempotent, and pending-terminal recovery never calls a setter.

Strict schema-version-1 decoding is retained for historical receipts:
`d2_consent_id`, `d2_source_digest` and `d2_binding`. The binding checksum retains
its historical fixed proposal and phase/commit normalization so valid records
can finalize through P5 without erasing their evidence. All three absent fields
remain legacy-compatible. Receipts still require original False, validated request
metadata, RESTORING or CANCELLED phase and outcome `cancelled`. Partial, malformed
or contradictory evidence refuses; valid receipts grant no owner mutation authority. If current state is enabled,
recovery refuses regardless of receipt validity. If already disabled and all
checks pass, explicit recovery can complete the established cancellation without
a setter. Persistence failures retain protection subject to P5's accepted
post-commit release exception. Expired recovery remains supported; clock rollback
remains blocked. No automatic recovery is authorized.

The read-only assessor retains its accepted classifications and advisory recovery
information for unexpected enablement. A future Needs Attention workflow should
explain the retained hold, direct the operator to manually disable Red Light,
then offer explicit transaction recovery after re-observation. UI/status/startup
composition is deferred; an advisory never authorizes owner mutation.

Remaining assumptions: the profile filesystem and cooperating locked writers are
trusted, receipt checksums are integrity bindings rather than authentication,
and matching owner/version strings do not prove installed package-byte provenance.
The injected operations must target the audited owner. Observation and external
owner actions are not atomic; races cannot be eliminated by these observations.
P5's filesystem and durability assumptions remain as stated below.

### P5 terminal commitment and release

All three outcomes use the existing capture/frozen/restart locks, CAS, pinned
directory, no-follow IO and lock-identity checks throughout both publications:

1. After verifying the exact request/operation, audited owner/version, and
   original enabled-state postcondition, publish the terminal outcome with
   `commit_pending=True`. The temporary file is written, flushed and synced,
   then atomically replaces the transaction. Readers still see an activation
   hold. Complete the directory durability barrier and identity/readback checks
   successfully before proceeding.
2. Revalidate identity and original enablement, then publish the same terminal
   outcome with `commit_pending=False`. Release becomes visible at this second
   atomic replacement. Perform the final directory durability barrier and
   identity/readback checks. No owner mutation occurs between publications.

Temporary write/sync failure or first replacement failure leaves the preceding
protected record. First directory-barrier failure or second replacement failure
leaves a protected pending terminal. Publication alone does not prove durability.

**Approved post-commit exception:** once the first barrier succeeds, the terminal
outcome is committed. If release is published but its final directory sync fails,
the caller reports the sanitized `CAPTURE_LIFECYCLE_BLOCKED` persistence error
even though independent readers can already see release. Keep the published
evidence; do not blindly restore the hold or repeat enablement changes. Following
a crash the filesystem may retain the released record or the previously committed
pending terminal. The caller's error does not itself identify which remains.

Explicit recovery treats a pending terminal as protected work requiring
finalization. It validates exact request/operation binding, installed owner/version,
and enabled state equal to the recorded original. Drift or ambiguous observations
refuse finalization and preserve the hold; no setter, capture or restart is called.
The recorded outcome and all operation identity/evidence remain unchanged, even
if recovery's `cancelled` argument requests another outcome. Recovery freshly
republishes the pending record and completes its directory barrier before freshly
publishing release and completing the final barrier. This also handles an unknown
or failed first barrier from an earlier attempt; retrying fsync alone cannot repair
that failure. Repeated recovery of the released terminal is a read-only no-op.

Schema-version-1 records missing `commit_pending` decode as False, preserving
legacy released-terminal behavior and the existing missing-metadata limitations.
Read-only guards and observers create no directories, records or locks. The
recovery assessor reports a verified pending terminal as
`TERMINAL_FINALIZATION_PENDING` with advisory `REVIEW_EXPLICIT_RECOVERY`, after
the existing corruption, competing-operation, identity, observation, legacy-request
and enablement-mismatch checks. This advice grants no mutation authority.

Missing/corrupt/replaced state, clock rollback, owner drift, unexpected
enablement, competing operations, and lost restart proof cannot produce a
capture result or automatic restoration/release. An interrupted read is not
automatically replayed. If the original-state setter fails or its effect cannot
be verified, retain the record/hold for explicit recovery. A persistence error
may occur after replacement: retain the published record (including the approved
post-commit released record), never erase evidence
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

P5 tests inject write, file-sync, replacement and directory-barrier failures,
observe both terminal publications from independent processes, and terminate
synthetic writer processes immediately before/after both replacements and barriers.
They verify protected pending state, explicit finalization without setters, and
the approved post-commit error behavior. Process exit and injected failures are
deterministic synthetic evidence, not real power-loss durability proof. The protocol
assumes atomic replacement, successful file and directory fsync providing the
required persistence ordering, a trusted filesystem, and cooperating locked writers.
Storage hardware, operating-system crash recovery and filesystem durability on
actual supported profile storage remain unqualified by these tests.

Option A tests cover unconditional retirement of old D2 APIs before locks or
writes, the external True -> False -> True regression, continued shared guards,
manual restoration followed by setter-free explicit recovery, historical receipt
and legacy decoding, established outcome preservation, pending-terminal crash /
persistence recovery and invalid identity/evidence or competing operations.
