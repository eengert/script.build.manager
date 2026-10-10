# Create private capture lifecycle — Stage 1

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
creation/expiration times, and the verified capture session. Request values,
resource values, private overlays, filesystem paths and exception text are not
serialized. `safe_dict()` exposes only operation ID, phase, hold and outcome.

A caller reconstructing the coordinator after a process exit must resupply the
exact confirmed request. Stage 1 does not persist a UI form or implement a UI
resume affordance. A changed request or an old operation UUID never acquires
authority over a newer record.

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
transition and its callbacks. It rejects busy locks, any pending Install or
restart record, and an injected in-flight-operation conflict. It does not
borrow a `RestartTransaction`, `ReconcileRequest`, or transaction-access
capability to gain Install/Apply authority.

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
   are the only phases that tolerate original enablement before release.
   Repeating recovery for an exact terminal operation returns its record only
   while original enablement still matches; it performs no lifecycle mutation.

Missing/corrupt/replaced/stale state, clock rollback, owner drift, unexpected
enablement, competing operations, and lost restart proof cannot produce a
capture result or automatic restoration/release. An interrupted read is not
automatically replayed. If the original-state setter fails or its effect cannot
be verified, retain the record/hold for explicit recovery. A persistence error
may occur after replacement: retain the published record, never erase evidence
or roll back blindly. Stale/corrupt records require a separately designed safe
recovery policy; Stage 1 provides no override or force-release path.

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
