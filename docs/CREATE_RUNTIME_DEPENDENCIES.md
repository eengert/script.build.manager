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
