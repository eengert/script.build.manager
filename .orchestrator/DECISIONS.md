# Build Manager Settled Decisions

These decisions are considered settled unless new contradictory evidence appears. A future ChatGPT supervisor should not reopen them merely because a new chat lacks the original discussion.

## Current execution-mode override

**D-025 (2026-10-03) supersedes D-013 and the ai-supervisor/autonomy execution-mechanism portions of D-016 through D-023.** Those older entries remain below as historical design/decision evidence. Product architecture, safety boundaries, reviewed product facts, Test.app scope, no-push/no-release rules, and truthful-evidence requirements remain in force.

The active Build Manager workflow is manual ChatGPT -> Codex/Claude relay. ai-supervisor and Relay-v1 are retired to cold storage unless Eric explicitly resurrects them.

## D-001 — Desired-state product, not backup/restore

Build Manager is declarative desired-state provisioning/reconciliation. It is not Backup Pro and does not clone arbitrary filesystem/profile snapshots.

## D-002 — Protected integration branch

`matrix` is the protected integration branch. Manual implementation happens on an explicitly named task branch/worktree and is reviewed as appropriate before matrix integration.

## D-003 — Exact frozen artifacts

Frozen software uses immutable exact ZIP artifacts identified by SHA-256. Installed add-on directories are not repackaged to manufacture missing frozen artifacts.

## D-004 — Explicit fallback for unavailable exact artifacts

An unavailable exact artifact is handled by explicit per-add-on fallback policy. Optional dependency edges do not imply that an installed managed node is automatically skippable.

The historical YouTube `7.4.4+unofficial.2` gap remains intentional; do not silently substitute another version.

## D-005 — Red Light private state is a structured resource

Red Light 2.6.8 private/auth state is managed through the `redlight.settings` structured private-resource adapter rather than ordinary settings-copy semantics.

Its required lifecycle is configure-before-activation, including hold/restart/initialization/apply/verify/release ordering.

BM-017F proved this lifecycle in a disposable environment and is complete.

## D-006 — Private overlay values never enter public artifacts/logs/chat

Only sanitized metadata/identity/fingerprints may be recorded. Actual private values remain protected outside Git/public manifests and are never printed in diagnostics or chat.

## D-007 — macOS live validation uses only the authorized portable Test.app

The authorized target is `/Applications/Kodi Build Manager Test.app`, launched with `-p`.

Normal `/Applications/Kodi.app` and the normal profile under `~/Library/Application Support/Kodi` are prohibited for this validation.

## D-008 — Test.app authentication stays host-side

Coding agents and chat never receive the Kodi HTTP remote-control password or other Test.app credentials.

The former ai-supervisor Keychain-backed target/actions are historical implementations of this rule. In manual mode, use only a bounded host-side helper/mechanism that preserves the same credential isolation; if none is available for a required operation, stop and design/verify one rather than exposing credentials.

## D-009 — Kodi `Addons.ExecuteAddon` result `OK` is not product success

For BM-023A adapter runs, success/evidence comes from the fresh sanitized adapter result file and matching `adapter_mode`, not merely Kodi accepting `Addons.ExecuteAddon`.

## D-010 — Supported BM-023A recovery

Recovery uses only:

`FrozenInstallCoordinator.abandon(acknowledge_restore_failure=False)`

Do not manually delete frozen transaction state or lock files to recover.

## D-011 — AF3 activation is not the current BM-023A blocker

The latest meaningful live evidence proved Arctic Fuse 3 activation succeeded and reconciliation reached CONFIGURE. Do not reopen the historical SET_SKIN/Timers.xml theories without new evidence.

## D-012 — One bounded diagnostic attempt before code changes

For a specific reproduced live failure, first capture sanitized current evidence, then allow at most one bounded supported repair/retry that current state justifies. Verify its result and stop on failure or contradiction. Do not repeat the same operation or change code inside a diagnostic attempt.

## D-013 — Historical: ai-supervisor was the execution/control plane

This was the prior operating model and is superseded by D-025. It remains here only as historical context.

## D-014 — Human intervention should be discriminating, not busywork

Ask Eric promptly for a tiny manual observation when it is the fastest safe discriminator. Manual relay is intentional, but do not turn Eric into a shell operator for repetitive steps that a bounded Codex/Claude task can safely perform.

## D-015 — Conversation memory is helpful but not authoritative

Cross-project Kodi memory may inform investigation, but repository `.orchestrator` files and current Git/worktree state are the durable/authoritative Build Manager sources. Archived ai-supervisor state is historical evidence only.

## D-016 — Orchestrator execution is non-blocking and outcome-driven

Each active project has one explicit current outcome and exit evidence. Progress means a material product/candidate change or new acceptance evidence; worker count, planner activity, review/checkpoint count, framework commits, and continuation count are not success measures. The Orchestrator does not keep a ChatGPT response open merely to poll workers, and Eric is not the scheduler for predictable internal steps. Use one bounded outcome-level runway when safe and foreseeable; leave genuine human/safety/quota gates in place.

Ordinary design, implementation, testing, and review continue only while they materially advance the current outcome. At a genuine human/safety/quota gate, milestone completion, or unexpected ambiguity that makes the next safe step unknowable, return control.

## D-017 — Local autonomous continuation is policy-aware and fail-closed

Build Manager uses ai-supervisor's fresh read-only/offline continuation planner. The planner itself has no external authority, but a validated `continue` decision may reuse only the exact capabilities present in the current machine-local autonomy envelope. The Orchestrator must reconcile that live envelope before proposing a step; durable prose cannot add capabilities. A short preconditioned runway advances one outcome and promotes later steps only after exact prior success. Anything outside the envelope, malformed output, a genuine human choice, contradictory evidence, or the configured quota floor stops at a gate rather than expanding authority.

Generic `resume` must not blindly clear an autonomy gate. Quiet internal `review_required` gates are for Orchestrator reconciliation; genuine human/safety gates remain protected.

## D-018 — Quota and provider policy come from fresh runtime state

Quota floors, provider routing, and reset state are machine-local runtime policy. Reconcile their current values from authoritative live state before a control-plane decision; do not copy old percentages, reset dates, or provider overrides from handoff/history into stable guidance. Never switch providers or bypass a floor unless the live policy explicitly authorizes it.

## D-019 — Portable Test.app validation has standing authorization

Eric has explicitly authorized ongoing staging, testing, installation, configuration, JSON-RPC interaction, temporary adapter updates, restart/quit/relaunch, and other Build Manager validation work against `/Applications/Kodi Build Manager Test.app` and its portable data. These routine Test.app interactions are not human authorization gates and may be performed autonomously through the established safe control plane.

The standing authorization does not extend to `/Applications/Kodi.app`, the normal Kodi profile, real Apple TV/Shield devices, push/release, credential disclosure, unrelated network/LAN targets, destructive Git operations, or other production resources. Existing fail-closed state/identity checks remain mandatory.

## D-020 — User notifications mean user action or decision is actually required

Do not notify Eric for internal technical review, `review_required`, deterministic evidence reconciliation, malformed planner output, safety/LAN preflight blocks, reviewed-checkpoint mismatches, or other conditions that the Orchestrator/framework can inspect or resolve without his input. Those states remain fail-closed and visible in status/logs, but are quiet.

User-facing notifications are reserved for genuine interaction/decision boundaries: explicit questions requiring Eric's answer, a new permission/approval not already granted, quota decisions, a manual observation/action that cannot be automated, or an unrecoverable condition whose smallest next intervention must be performed by Eric. Autonomy must resolve deterministically checkable facts (including Git revision abbreviation equality) before considering a human gate.

## D-021 — ChatGPT controller turns are explicitly bounded

Build Manager uses ai-supervisor's controller-turn governor. Each post-onboarding interaction is classified as `direct-side-task` or `supervised-work`. Tiny file-side tasks must pass the exact-path side-task conflict check and return immediately after verification; substantive work is dispatched and launch-verified once. `CONTROLLER_YIELD` is the durable instruction to stop polling/broadening the ChatGPT turn and return control to Eric. Soft turn budgets do not revoke authority during safety-critical operations.

## D-022 — BM-023A host actions use a dedicated pinned action worktree

The fixed BM-023A validation actions execute from `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions`, whose exact Git HEAD is pinned in machine-local action configuration. Framework `main` may advance independently; never weaken exact-HEAD/clean-worktree checks. Advance the trusted action pin only after risk-appropriate review and validation. A staging action must bind to an exact reviewed product candidate and matching expected adapter version; never build from a moving or dirty worker branch. The fixed `bm-test-app-relaunch` action may control only `/Applications/Kodi Build Manager Test.app` in portable `-p` mode, uses graceful termination only, and fails closed on ambiguous process identity.

## D-023 — Outcome-Driven Supervision is the default

Every project task must materially change the target product/candidate, produce missing acceptance evidence, or remove a demonstrated blocker to one. A repeated unchanged blocker is escalated once to the Orchestrator/controller layer; a second probe requires a materially different discriminating hypothesis. Framework work, independent review, and validation are admitted by concrete outcome impact and risk, not ceremony or sunk cost. See `.orchestrator/BOOTSTRAP.md` and `.orchestrator/WORKFLOW.md`.

## D-024 — macOS Beta Qualification is the current Build Manager milestone

The exact seven-item exit checklist and critical-path admission rule are in `BUILD_MANAGER_PROJECT_PLAN.md`. Nonessential orchestration/framework work is outside the Build Manager critical path.

## D-025 — Manual relay is the active execution model

As of 2026-10-03, Eric chose to finish Build Manager with the simpler manual workflow that preceded ai-supervisor:

`ChatGPT plans/supervises -> Eric runs a bounded Codex/Claude prompt -> Eric pastes the report back -> ChatGPT reviews/chooses the next step`.

Consequences:

- ai-supervisor is not a Build Manager prerequisite;
- the autonomous planner, queue/runway, controller-turn, provider-routing, quota-failover, checkpoint/provenance, trusted-action pinning, and Relay-v1 mechanisms are inactive unless Eric explicitly resurrects them;
- unfinished ai-supervisor framework/provenance work must not block Build Manager beta qualification;
- material product changes still receive proportionate independent review;
- ordinary Git identity/diff/review evidence is sufficient for the manual workflow;
- the existing product/device/security safety boundaries remain unchanged;
- normal Kodi and its normal profile remain prohibited;
- portable Test.app standing authorization remains, with each manual task explicitly bounded by its prompt;
- no push/release/destructive history rewrite without Eric's explicit authorization.

The ai-supervisor/Relay-v1 design is preserved in cold storage for possible later reuse rather than completed now.
