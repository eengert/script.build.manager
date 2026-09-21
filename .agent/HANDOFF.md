# Agent Handoff — BM-020A integrated Codex worker

## BM-020C — post-restart resume orchestration complete

BM-020C is complete on `agent/codex` in implementation commit `69b8e6f` and
remains intentionally unintegrated to protected `matrix`.

The implementation adds the read-only `BuildManager.preview()` seam,
`resources/lib/resume.py`, expected-state transaction transitions and bounded
status diagnostics, automatic `service.py` delegation for `READY_FOR_RESUME`,
focused resume tests, and the disposable `validate-build-manager-resume` gate.

The coordinator re-reads the persisted record, verifies a new session,
previews the desired state before mutation, requires an exact fingerprint
match, atomically claims `RESUMING`, and runs the normal BuildManager
reconciliation from the beginning. It clears only an unchanged `RESUMING`
record after success + matching final fingerprint + `NONE`. Failures,
fingerprint drift, repeated restart requirements, claim conflicts, and clear
conflicts fail closed into preserved `NEEDS_ATTENTION` state. Existing
`RESUMING` and `NEEDS_ATTENTION` records are not retried automatically.

Evidence: focused tests **465/465**, disposable BM-020C gate **8/8** with AF3
closure **18/18**, full suite **1536/1536**, and `git diff --check` clean. The
live gate proved automatic service-driven resume after a harness-only Kodi
restart, normal reconciliation with matching fingerprint and
`RestartRequirement.NONE`, automatic transaction clear, all 16 managed AF3
settings, no second handoff, and later `NO_TRANSACTION`. The unmanaged AF3
probe is covered by the BM-020A gate because this runtime normalizes that
schema entry across process restart. The real Kodi profile, Apple TV, and all
devices remained untouched.

BM-020C and BM-020 overall are complete on the worker. Current supported
platforms still require a manual full-Kodi restart; Build Manager does not
automatically relaunch Kodi. BM-017 and family-room distribution/source work
remain deferred. The next step is supervisor integration only.

## BM-020C1 — typed capability model and manual restart handoff complete

BM-020C1 is complete and integrated on protected `matrix`; its substantive
implementation commit is `bcaf2ca` (worker implementation `a6bf902`). The implementation adds
`resources/lib/restart_coordinator.py`, focused coverage in
`tests/test_restart_coordinator.py`, the disposable
`validate-build-manager-manual-restart` gate, and the BM-020B/C1 transaction
documentation.

The capability resolver maps macOS, Android/Shield, Fire OS, Apple TV/tvOS,
and unknown platforms to `MANUAL_APP_RESTART_REQUIRED`. A successful typed
`KODI_RESTART` result creates and read-backs `AWAITING_RESTART` with attempt
count `0`, returns `MANUAL_RESTART_REQUIRED`, and leaves Kodi running. Failed
reconciliation and `NONE` are fail-closed/no-transaction paths. A matching
same-session call reuses the durable record without a second reconciliation;
a changed session is `READY_FOR_RESUME` with count `0`, while BM-020C resume is
not implemented. Automatic capability selection fails closed because no
approved automatic adapter exists.

Evidence: focused BM-020C1/BM-020B/BM-020A/BM-019 tests **63/63**,
disposable manual gate **8/8**, full suite **1517/1517**, and
`git diff --check` clean. The gate used the real BM-020A fixture and
fingerprint, with only the restart requirement synthesized to exercise this
contract. It used only `.kodi-test`; the real Kodi profile, Apple TV, and all
devices remained untouched. The gate also proved AF3's disposable dependency
closure, same-process manual behavior, new-session classification, no resume,
and explicit clear.

Remaining BM-020C work is pre-resume fingerprint validation, `RESUMING`,
resumed reconciliation, success clear, restart-loop prevention, and recovery
after resume failure. Do not begin that work, BM-017, or device work as part
of this handoff. The smallest next step is supervisor direction on the later
resume contract.

## BM-020C audit stop — production restart primitive not established

BM-020C was started on Codex and stopped at its mandatory read-only restart
mechanism audit before the later BM-020C1 capability/manual-handoff work.
That audit remains historical context; the integrated BM-020C1 endpoint does
not claim that resume/re-entry is complete.

Kodi Omega's official built-in reference lists `RestartApp` as implemented
only under Windows and Linux. `Quit` is an application exit, not an automatic
relaunch. JSON-RPC provides quit/restart notifications, not a supported
add-on/Python operation that guarantees a new Kodi process. Kodi's Android
source contains internal restart-exit handling, but that does not establish a
public add-on/Python restart contract; no equivalent supported primitive was
established for macOS, Fire OS, Shield, or Apple TV/tvOS.

The required BM-020C lifecycle cannot safely claim a new session without a
genuine new Kodi process. Host shell/process management, GUI automation,
`System.Exec`, or a `Quit` plus assumed external relaunch would violate the
task boundary. The disposable harness may control Kodi externally, but that
cannot substitute for the missing production mechanism.

Recommended smallest next step: supervisor approval of an explicit platform
capability model and relaunch authority. Until then, do not add a restart
coordinator, alter BM-020A/B, or run the BM-020C process-level gate.

BM-020C and BM-020 overall remain incomplete. BM-017, the remaining resume
implementation, and all device/family-room work remain deferred. The real Kodi
profile and devices remain untouched.

## BM-020B complete and synchronized on Codex

BM-020B is complete and integrated on protected `matrix`; the substantive
commit is `f3ccf2a`. The implementation stores only a versioned safe
`ReconcileRequest`, desired fingerprint, typed restart requirement, originating
Kodi session UUID, phase, and bounded diagnostics under the Kodi profile.
Writes are validated and atomic; locking uses OS-backed `fcntl.flock` and fails
closed if unavailable. Kodi's global home-window property supplies a process
session identity, and `service.py` performs one startup classification pass.

The service fast path reports no transaction without reconciliation. Same-
session `AWAITING_RESTART` remains intact and ineligible for resume. A
different Kodi process is classified `READY_FOR_RESUME` while the transaction
remains durable for BM-020C. Corruption, unsupported versions, invalid fields,
and persistence/lock failures fail closed; clear is explicit only.

Disposable BM-020B validation passed 9/9 across an external Kodi stop/relaunch;
the service ran automatically in both processes, distinguished session IDs,
and never restarted Kodi or invoked `BuildManager.reconcile()`. Focused
transaction/session/service tests passed 32/32, the full suite passed
1504/1504, and `git diff --check` passed. Codex is synchronized/idle/ready
for BM-020C; BM-020C, BM-017, and family-room distribution/source work remain
outside scope.

## BM-020C1 integration complete

BM-020C1 is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive commit is `bcaf2ca`. Codex worker metadata was not
copied.

The integration adds the typed capability resolver and manual restart
coordinator, with current and unknown platforms conservatively mapped to
`MANUAL_APP_RESTART_REQUIRED`. Successful `KODI_RESTART` handoff preparation
persists and read-backs `AWAITING_RESTART` with attempt count `0`, never
restarts or quits Kodi, and returns structured manual guidance. Failed runs
create no transaction, `NONE` completes without one, same-session requests do
not re-run reconciliation, and a new session with count `0` is ready for the
later resume phase. No automatic adapter or resumed reconciliation is
claimed.

Matrix validation passed focused tests **63/63**, disposable manual gate
**8/8** with AF3 closure **18/18**, full suite **1517/1517**, and
`git diff --check`. The gate used only `.kodi-test`; the real Kodi profile,
Apple TV, and all devices remained untouched.

BM-020C resume work remains incomplete: fingerprint revalidation, `RESUMING`,
resumed reconciliation, success clear, loop prevention, and failure/recovery
semantics. Do not begin that work, BM-017, or family-room distribution/source
work as part of this integration record.

## BM-020B integration complete

BM-020B is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive integration commit is `f3ccf2a`. Worker-specific
Codex metadata was not copied.

The durable foundation is profile-local and schema-versioned. It records only
the safe request, desired fingerprint, restart requirement, originating Kodi
session UUID, and transaction phase. Writes are staged in the same directory,
flushed and fsynced, atomically replaced, read back, and rejected if corrupt
or unsupported. An explicit clear removes the record safely. A profile-local
sidecar uses nonblocking `fcntl.flock`; lock ownership is released by the OS
when the process exits. The current Kodi session UUID is held in the home
window property `script.build.manager.kodi_session_id`.

`service.py` is a thin `xbmc.service` startup entrypoint. It classifies the
record and publishes the bounded result without restarting Kodi, reconciling,
resuming, or claiming a transaction. BM-020C owns actual resume/re-entry
execution.

The integrated disposable gate passed **9/9**: service fast path, session
identity, production preparation without restart, same-session protection,
external process boundary, automatic ready-for-resume classification, clear,
returned fast path, and real-profile immutability. Transaction tests passed
**32/32**, the full suite passed **1504/1504**, and `git diff --check` passed.
The first gate invocation observed only a startup-readiness race and was not
used as evidence of a code failure; the unchanged retry passed all 9 checks.
The real Kodi profile, Apple TV, and all devices remained untouched.

BM-020C and BM-017 remain unstarted. No next milestone was started. The
smallest next step is supervisor direction on BM-020C's resume/re-entry
policy; no worker handoff is implied by this matrix record.

## Prior integrated state

## BM-020A integration complete

BM-020A is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive commits are `eeafc1c`, `0ed2c35`, `821e69e`,
`0fb0bd5`, and `1ad0fdb`. Worker-specific Codex metadata was not copied.

The callable contract now available to BM-020B is
`BuildManager.reconcile(ReconcileRequest) -> ReconcileResult`. It owns the
load/inspect/resolve/preflight/plan/ordered execution/post-validation flow,
returns the safe request, deterministic desired fingerprint, ordered action
results, structured failure, validation report, and aggregated BM-019
`RestartReport`. It does not restart Kodi, persist transactions, resume after
restart, lock, or handle restart loops.

The integrated disposable `validate-build-manager` gate passed using the
self-contained AF3 fixture and production `af3-common` package: 18/18 AF3
closure entries healthy, `SET_SKIN` → `SkinActivator`, `CONFIGURE` →
`ConfigurationManager`, all 16 settings read back, `files=[]`, and
`RestartRequirement.NONE`. The second identical request retained the same
fingerprint and made no mutations. Managed `Navigation.OnBack` drift was
repaired; unmanaged `TMDbHelper.Corner.Radius` was preserved; invalid selector
failed closed before mutation. The `kodi.resource` system-dependency fix was
minimal and regression-tested.

Codex worker synchronization completed by normal merge from protected matrix;
the worker remains idle/ready for BM-020C and the external active-worker
pointer remains `build-manager -> codex`.

Focused integrated validation passed 1458/1458; full suite passed 1472/1472;
`git diff --check` passed. The family-room production source/distribution gap
remains a separate pending concern and is not claimed by BM-020A. The real
Kodi profile, Apple TV, and all devices remained untouched. BM-020B/C and
BM-017 were not started.

- Normal composition reached manifest/profile resolution, production package
  resolution, planner, `SET_SKIN` through BM-018A, `CONFIGURE` through
  ConfigurationManager, and post-validation through BM-014.
- The real `af3-common` descriptor applied and read back all 16 typed settings;
  its effective file target list was empty. First pass required no restart.
- Exact second request kept the same fingerprint and made zero mutations.
- A deliberate managed `Navigation.OnBack` drift was repaired, while the
  unmanaged `TMDbHelper.Corner.Radius` probe remained unchanged.
- Invalid device selector failed closed during resolve without state change.
- The disposable AF3 closure was healthy; `kodi.resource` is now correctly
  treated as a Kodi system dependency, with focused regression coverage.

Focused tests passed 1391/1391 and the full suite passed 1472/1472.
`git diff --check` passed. BM-020B/C and BM-017 remain unstarted. The real
Kodi profile, Apple TV, and all devices remained untouched. Family-room
distribution/source work remains separate and was not started.
