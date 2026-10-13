# Create runtime dependencies (Item 8, offline inventory)

Source baseline: `5fb47fcf7dc9f0a98a55dc65747bb223a948fa17`.
P5, D2 Option A, and Stage 2B1A (including B3) are independently accepted
offline. This inventory grants no runtime authority and does not establish
beta qualification.

## Existing capabilities and limits

| Capability | Source contract | Trust and limitation |
| --- | --- | --- |
| Create record and hold | `capture_lifecycle.py`: `CaptureStore.read`, `competing_records_present`, `capture_activation_holds`, `require_no_capture` | Typed, pinned/no-follow reads; held and pending terminal records protect the owner. Missing records establish only absence at observation. File inspection cannot establish that work is idle. |
| Coordinated Create transition | `CaptureLifecycleCoordinator._exclusive`, `_checked`, `_eligible` | Locks Create, frozen-install and restart stores in that order; rechecks identity, exact request, owner version, strict competition and restart proof. Injected operations remain mandatory; locks alone do not cover all Kodi work. |
| Install/restart admission | `frozen_install.py`: `FrozenInstallStore.create`, `FrozenInstallCoordinator.install`; `transaction.py`: `TransactionStore._create_unlocked`; `restart_coordinator.py`: `_pending_before_reconcile` | Existing Create holds block these admission points. Store locks serialize cooperating record writers, not the full duration of all install, activation or Kodi background execution. |
| Activation guard | `activation.py`: `reject_held_activation`; `frozen_install.py`: `active_activation_hold_ids`; `addons.py`: `KodiRuntimeAddonBackend.invoke_install`, `set_addon_enabled`; `KodiRuntimeFrozenArtifactBackend.set_addon_enabled` | Shared Install/Create holds reject protected activation/native installation; unreadable state propagates failure. These guards do not authorize a generic restoration bypass or certify external work is absent. |
| Owner observation | `KodiRuntimeFrozenArtifactBackend.get_addon_details` | Read-only `Addons.GetAddonDetails`, exact returned addon ID, string version and Boolean enabled state. Missing/refused/malformed observations are not disabled. Version equality is not artifact provenance, generation or enablement history. |
| Session observation | `session.py`: `peek_current_kodi_session_id`, `get_current_kodi_session_id` | Peek is creation-free; get may write a process window property. A UUID difference does not independently prove a complete process restart or bind that boundary to the Create operation. |
| Create advisory assessment | `capture_recovery_assessor.py`: `assess_capture_recovery` | Repeated record/owner/competition observations detect disagreement; no atomic external snapshot or action eligibility. Even ordinary recovery potential does not certify expiry or restart proof. |
| Native Create composition | `create_workflow.py`: `runtime_create_workflow`, `CreateBuildWorkflow.execute`; `create_capture.py`: `CreateBuildCaptureEngine.capture` | Confirmed execution performs capture and registration; runtime construction uses the default Red Light adapter, not the lifecycle coordinator. The offline lifecycle has no accepted production composition here. |
| Private existing-resource capture | `redlight_resource.py`: `RedLightSettingsAdapter.capture`; `capture_lifecycle.py`: `capture` | Lifecycle supplies a repeated eligibility verifier around read-only capture. Runtime must use the accepted existing-resource capture contract, never initialization/Apply or copied device data. |
| Install startup | `startup.py`: `classify_startup_transaction`, `run_startup` | Consumes restart records and may resume Install/Apply. It is not a read-only Create startup service; never feed Create records into it. `create_status.py.observe_create_state` already classifies Create held/pending/released/unverifiable records without mutation, but is part of the pending status chain. |

## Missing trusted competition evidence

`competing_operation()` must return exact `False` only when trusted evidence
positively establishes no in-flight conflicting Install, restart, activation or
other relevant operation. An exception, missing provider, incomplete observation
or uncertain state must refuse admission. `True` reports competing work.

No production provider implementing this contract was found in the inspected
composition. Inspecting `restart_transaction.json`, frozen-install and Create
records is necessary evidence for recorded work, but insufficient: native install
or activation can execute before/after publication, and external Kodi work need
not publish a Build Manager record. `addons.py` performs synchronous backend
calls without a shared full-operation activity reservation. No durable-record
absence or process-local flag closes these intervals across processes.

The future provider and callers need one coordinated admission boundary covering
both the idle observation and acquisition of operation ownership, maintained
through the protected effect. Every participating operation must register before
its first effect and retain ownership until completion; scope must include any
Kodi work whose absence is asserted. If Kodi cannot supply trustworthy evidence
for that scope, the provider must remain unknown. Read-only repeated observations
are advice, not an atomic reservation. Existing store lock order must be preserved;
a new parallel lock order or uncoordinated check-then-act is unsafe.

## Missing restart and composition evidence

`verify_restart(operation_id, old_session, new_session)` must positively bind a
complete Kodi process boundary to the exact Create operation. `_eligible` requires
strict `True` as well as a new session, matching owner version, disabled owner,
exact request and retained hold. Session strings, elapsed time, startup execution,
a GUI relaunch claim or transaction phase alone cannot replace the proof.
There is no default trusted Create restart-proof provider in the inspected source.

Runtime restoration also needs narrowly owned enablement authority while the
shared activation hold remains enforced. Never weaken the shared guard. D2 must
never automatically disable unexpectedly enabled Red Light: manual owner
restoration followed by validated, explicitly confirmed P5 recovery remains the
policy. Terminal pending is still protected until accepted finalization.

## Smallest future slices

1. Standalone exact owner/version/strict-enabled observation with injected
   backends and unknown/error sanitization; no composition or setter.
2. Offline regression coverage for Create-only startup classification and shared
   admission/hold behavior; preserve current lifecycle and startup authority.
3. Pure localized advisory recovery presentation, with no executable actions.
4. Separately authorize a bounded operation-admission provider covering the
   demonstrated in-flight intervals and cross-process coordination; prove strict
   unknown refusal and ownership retention before wiring it into Create.
5. Separately establish operation-bound restart proof, then review narrow
   restoration authority and confirmed native lifecycle composition. Registration,
   partial failures and original desired enablement need their existing contracts
   preserved. Independent review precedes specifically authorized runtime evidence.

Unsafe shortcuts: constant `False` competition, UUID-only restart proof, default
safe-for-capture assertions, owner-ID substitution, Boolean coercion, generic
activation bypass, automatic D2 disable, automatic startup recovery, or assuming
B3/self-tests establish independent acceptance.

## macOS restart-witness feasibility prototype (2026-10-13)

This is **offline, synthetic-only feasibility evidence**, based on
`agent/codex` at `5e42ea99d1bb204d47b786119a143ef3e7baf587`.
Independent review on 2026-10-13 accepted only the stated synthetic feasibility,
conditional on the NB-1/NB-2 wording corrections included here (plus NB-3).
It is **not** a production `verify_restart()` provider, Item 8 completion,
or Create runtime eligibility. Existing Create holds and unresolved BM
reservations remain authoritative; external Kodi operations remain
uncoordinated. Nothing here establishes global Kodi inactivity.

### Public API/toolchain result

The installed Swift toolchain reports Apple Swift **6.3.2**, target
`x86_64-apple-macosx26.0`. `tools/create_restart_witness.swift` compiled with
`-warnings-as-errors` and `-lbsm`. No private API declarations, token-layout
decoding, platform preferences, keychain access, production imports, service
installation or native lifecycle composition are used.

The prototype uses SDK-declared public APIs:

- `kqueue` / `kevent`, `EVFILT_PROC`, `NOTE_EXIT`, `NOTE_EXEC`, and `EV_RECEIPT`
  (`sys/event.h`). An explicit successful registration receipt, matching live
  start identity before/after registration, and no queued pre-readiness event
  precede the readiness output. This synchronous approach was chosen instead
  of DispatchSource to make registration acknowledgement explicit. A subsequent
  genuine `NOTE_EXIT` is required; any observed `NOTE_EXEC`, including a flag
  coalesced with exit, refuses the binding. Timeout, registration failure,
  invalid event, failed identity lookup, and detected registration race refuse.
  There is no polling-based positive process-exit proof. `poll` is used only
  to bound socket acceptance.
- `proc_pidinfo(PROC_PIDTBSDINFO)` (`libproc.h`, `sys/proc_info.h`) returns PID
  and start seconds/microseconds; partial reads, PID disagreement, invalid
  timestamps and zombies are refused. A mismatching expected start identity
  was rejected while the disposable process was alive; lookup after its exit
  was rejected. **Actual forced PID reuse was not exercised.** PID plus start
  time demonstrably rejects a stale timestamp, but timestamp resolution alone
  is not a demonstrated collision-free identity mechanism. No arbitrary-process
  or all-permissions reliability claim is made.
- UNIX stream-socket `getsockopt(LOCAL_PEERPID/LOCAL_PEERTOKEN)` (`sys/un.h`),
  with `audit_token_to_pid`, `audit_token_to_pidversion` and
  `audit_token_to_euid` (`bsm/libbsm.h`, linked through libbsm), identifies the
  connector using kernel credentials read at the time of each call, not an
  immutable connection snapshot. In the independent synthetic review,
  LOCAL_PEERTOKEN changed across exec and returned ENOTCONN after peer exit
  and reap. Repeated token and start observations reject detected changes,
  but descriptor delegation can preserve a connection after the original
  connector exits; general liveness is not proven. Token internals are not
  decoded. Unavailable/refused credential APIs have no asserted-PID fallback.

### Genuine event and endpoint evidence

Command (run from the repository root; test-owned cache/socket directories are
removed automatically):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_create_restart_witness -v
```

Final source/test run: **14 tests passed in 13.530 seconds**. Each native test
uses fresh disposable subprocesses and temporary sockets. Clients wait for the
harness to receive readiness before exiting naturally; no signals are sent.
The witness is a separate subprocess and remains running across the old
process's exit. It emits the actual kernel-observed exit and exits naturally.
There is no daemon persistence claim. The witness and old client are siblings
under the harness; survival across a parent-process exit was not tested.

One retained positive observation from that run:

| Observation | Value |
| --- | --- |
| Synthetic operation | `4deeeedd-a7d3-44c5-8cea-766676312f07` |
| Witness PID at readiness and exit | `36738` |
| Old kernel-observed PID/start | `36739 / 1791904782.319886` |
| Old socket audit PID version | `892536` |
| Caller-asserted PID | `999999` (ignored as authority) |
| Exit event | `kernel_note_exit: true`, same old incarnation and witness PID |
| Exit callback observation time | `1791904782.364658` |
| Replacement kernel-observed PID/start | `36741 / 1791904782.380181` |
| Replacement socket audit PID version | `892540` |

Native Swift source SHA-256:
`96bb268047d27cabae1d16445329115c9860c0f974e728e95063bd2cfca4ed0e`.
Test source SHA-256:
`effb97dba87cf39c681db85f59931f24291bcd86b2bcf68256543efc49e45d55`.
The test prints the full synthetic observation on rerun; these PIDs/times are
historical evidence, never live target identifiers or reusable authority.

### Prospective operation binding and adversarial results

`ProspectiveBinding` is located only in the test file. It pins an immutable
synthetic tuple in memory after checking the native readiness/exit observations
and replacement peer observation. It matches the operation UUID, request
fingerprint, profile identifier, originating session, old incarnation,
witnessed exit, replacement incarnation and replacement session. Three checks
of the same verified binding succeed without permitting a different operation.

Passing native/policy cases include:

- Genuine kernel exit after confirmed readiness; actual connector PID differs
  from its asserted PID; replacement uses a separately observed endpoint.
- Wrong operation, fingerprint, profile, either session, old incarnation or
  replacement incarnation rejects, both on initial binding and repeated checks.
  Replay into a different operation rejects.
- An unrelated real endpoint supplying identical strings rejects when compared
  with the pinned replacement incarnation. A same-process session change rejects,
  even when its test-controlled input asserts an exit.
- A replacement actually alive alongside the old client rejects. The synthetic
  temporal gate conservatively requires its start time to be later than the
  recorded exit callback observation, not merely later than the actual exit.
- Genuine exec refuses with `exec_is_not_exit`; an absent exit event refuses
  with `exit_evidence_missing` while the old client is still alive; lookup after
  exit refuses with `incarnation_unavailable`; stale expected start refuses with
  `stale_incarnation`. Missing/corrupt/incomplete readiness, exit or peer evidence
  and witness-identity disagreement reject in the policy experiment.
- Invalid PID, absent connector, and an occupied socket path refuse. The occupied
  path's sentinel remains intact. Specific OS permission denials, unsupported-API
  hosts, and a forced mid-registration PID-reuse race were not induced; their
  source paths refuse instead of fabricating evidence.
- A synthetic unresolved-reservation file remained byte-identical after the
  witnessed exit. The witness and matcher neither read nor write that file,
  so this is an isolation check, **not** a behavioral test of the production
  BM reservation implementation. Source inspection, not the byte-equality
  assertion, establishes that this prototype implements no reservation
  clearing, takeover, capability transfer or recovery mechanism.

### Trust boundaries and production gaps

The `authenticated` JSON section contains native observations. Socket PID,
audit PID version and effective UID come from kernel peer credentials; process
start time comes from a separate kernel process lookup. In these tests the
connector stays alive while both observations are collected. The observations
are **not an atomic kernel attestation binding that audit token to the separately
read start time**. This limitation prevents claiming general trustworthy
incarnation verification against adversarial exit/reuse races. A socket token
identifies the original connector, not necessarily a later holder of an inherited
or transferred descriptor. Neither process start identity nor audit PID version
is application/code-signing identity. Exec disqualifies the observed
binding when detected by a changed peer token or NOTE_EXEC, but exec after
the last token read and before EV_ADD may go unnoticed. General exec
exclusion remains unproven.

The `asserted` section, including canonical-profile identifier, operation UUID,
request fingerprint, sessions and application name, is entirely test-controlled.
Exact matching does not authenticate those values. Claiming `application=Kodi`,
a different profile, or another PID does not authenticate Kodi, that profile,
or a Create operation. The Python matcher and Swift stdout are not durable,
authenticated receipts; editing/replaying their dictionaries is outside any
proven receipt trust boundary. No untrusted JSON should be used as production
restart authority.

Further production prerequisites remain unresolved:

1. Trusted origin registration binding a real Create operation, exact request,
   canonical profile and originating session to an independently verified process
   incarnation, with race-safe readiness acknowledgement and endpoint ownership.
2. A supported, reviewed incarnation mechanism binding peer credentials to the
   monitored incarnation atomically or through a trustworthy protocol, including
   PID reuse, exec and descriptor delegation. Start time is useful corroboration
   here, not sufficient universal proof.
3. Race-safe replacement admission and non-overlap proof. This harness uses
   wall-clock start/callback comparison; clock changes are not covered, and
   legitimate starts between actual exit and callback observation are rejected.
   The observation timestamp is not the kernel's exit timestamp. A production
   temporal proof needs a trustworthy ordering mechanism.
4. Durable receipt authentication, protected storage and witness identity,
   operation-scoped replay controls that preserve repeat checks, schema and
   tamper/incomplete-evidence refusal, and explicit fail-closed witness-loss
   behavior. Durable resumption after witness loss was not implemented.
5. Separately authorized lifecycle composition, process/application and
   profile/session authentication, owner enablement authority, and the existing
   coordinated reservation/hold checks. No exit event transfers or releases an
   unresolved reservation, and no evidence here coordinates external Kodi work.

**Feasibility result:** this host supports the native kernel exit-event and
kernel-authenticated connector primitives for a disposable synthetic witness.
The full operation-bound durable restart provider remains unproven. Further
work requires a separately authorized slice establishing race-safe incarnation,
process ordering and durable receipt trust boundaries. No runtime work follows
from this prototype.

Cleanup: task-owned binaries, initial compiler-probe source, module caches,
sockets and scratch directories were removed; only the three allowed source/doc
files and this minimal historical observation remain. The four pre-existing
dirty `.agent` files were preserved without handoff or usage edits, as explicitly
required by this task. No staging, commits, full suite, Kodi harness, Test.app,
normal profile/device access, push, merge, release or deployment occurred.
