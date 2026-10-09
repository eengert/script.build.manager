# Build Manager Settled Decisions

These decisions are considered settled unless new contradictory evidence appears. A future ChatGPT supervisor should not reopen them merely because a new chat lacks the original discussion.

## Current execution-mode override

**D-025 (2026-10-03) supersedes D-013 and the ai-supervisor/autonomy execution-mechanism portions of D-016 through D-023.** Those older entries remain below as historical design/decision evidence. Product architecture, safety boundaries, reviewed product facts, Test.app scope, no-push/no-release rules, and truthful-evidence requirements remain in force.

The active Build Manager workflow is manual ChatGPT -> Codex/Claude relay. ai-supervisor and Relay-v1 are retired to cold storage unless Eric explicitly resurrects them.

**D-026 (2026-10-04)** records the current manual endpoint architecture (Codex and Claude Agent Handoff endpoints, Antigravity retired) and the narrow standing authorization for the push that completes an explicitly requested agent switch.

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

The authorized target is `/Applications/Kodi Build Manager Test.app`, launched
in portable mode with the mandatory `-p` flag. The durable default command is
`open -g "/Applications/Kodi Build Manager Test.app" --args -p`, which keeps
Test.app in the background. A specific validation task may explicitly require
foreground activation.

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

The exact eight-item exit checklist and critical-path admission rule are in `BUILD_MANAGER_PROJECT_PLAN.md`. Nonessential orchestration/framework work is outside the Build Manager critical path.

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

## D-026 — Manual Codex/Claude Agent Handoff endpoints and switch authorization

As of 2026-10-04, Build Manager's manual working lanes are two Agent Handoff endpoints. This builds on D-025 and does not reopen it.

- **Endpoints.** Codex: worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`, branch `agent/codex`. Claude: worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude`, branch `agent/claude`. They are manual working endpoints, not autonomous supervisor workers: nothing runs in them unless Eric launches Codex or Claude with a bounded prompt, and each prompt still names the exact worktree/branch it may use.
- **Agent Handoff is retained** (`/Users/eengert/Documents/Kodi/agent-handoff`, installed as `Agent Handoff.app`) as the supported mechanism for switching ownership between the two endpoints. Which agent is current is recorded by Agent Handoff and determined live with its read-only status check, not assumed from documents or chat memory.
- **Antigravity is retired** from Build Manager Agent Handoff and must not be recreated (worktree, branch endpoint, or configuration entry) unless Eric explicitly changes this decision.
- **ai-supervisor remains retired** and cold-stored (D-025).
- **`matrix` is the canonical guidance and protected integration lane.** Product candidate work continues in the endpoints; integrating that candidate into `matrix` is a separate deliberate decision. Endpoint copies of guidance are synchronized explicitly by path from `matrix` (path-level restore plus a local commit; see `.orchestrator/WORKFLOW.md`), never by merging `matrix` wholesale into the candidate branches, and `matrix` `.agent/**` is never copied.
- **Standing agent-switch publication authorization.** When Eric explicitly tells the Build Manager Supervisor to switch from one configured agent to another, that request also authorizes Agent Handoff to perform the normal publication push of the target (incoming) agent branch that is required to complete that specific handoff. The authorization covers only that push, for only that requested switch. It does not authorize any unrelated push, any push of `matrix`, any release, any force-push, any history rewrite, or any push not required to complete the requested switch. A handoff Eric has not explicitly requested is not covered. This is the only standing exception to D-025's no-push rule.

## D-027 — Complete frontend is required for product beta readiness (2026-10-06)

Eric approved the UI design at `.qualification-evidence/ui-design-20261006T113406Z/UI_DESIGN.md`, subject to the adopted completion/library/help/status/visual-review amendments. The authoritative milestone now has eight exit items. Criteria 1-7 and their accepted backend evidence remain unchanged; item 8 requires complete user-facing workflow implementation and manual qualification in portable Test.app. Backend qualification alone does not satisfy product beta readiness.

Normal/live Mac Kodi and Shield testing begins only after item 8 is accepted. Acceptance of item 8 does not itself authorize live access: a subsequent task must explicitly name the target and permitted actions.

BM-UI-001 must pass focused tests and interactive Test.app validation, then STOP for Eric/ChatGPT visual UX review before the presentation foundation is used for remaining major workflows. Adopt persistent unacknowledged terminal results, one internal Build Library with a separate Build Transfer Folder, contextual navigation-only Help, and consistent success/exception/incomplete/warning/blocked/validation-failure/NEEDS_ATTENTION semantics. These reuse Backup Pro principles without copying its UI.

## D-028 — Kodi application-bundled add-ons are platform-provided requirements (2026-10-09)

Kodi application-bundled add-ons proven through Build Manager's trusted application-root authority are platform-provided requirements. They are not Build Manager-managed software. Capture records their observed identity, version, type, observed enabled/usable condition, and dependency metadata without acquiring, importing, or manufacturing a ZIP artifact. The captured platform version is source observation and fingerprint evidence. It is not an exact target install requirement and is not an implicit minimum. The platform target requirement is the strictest actual minimum carried by the incoming dependency edges of the frozen graph, compared with fail-closed strict version rules.

Target verification must prove, before meaningful mutation and again before successful completion: trusted application origin; presence; supported, enabled, usable and unbroken state; identity and type coherence; dependency-version compatibility; and a compatible required dependency closure read from the target's own trusted metadata. Unsupported, missing, home-shadowed, broken, disabled, unreadable, version-unknown, or otherwise unverifiable required platform components block execution.

Build Manager never downloads, installs, replaces, downgrades, enables, disables, offers repository fallback for, or offers Skip for a platform-provided node. Platform nodes remain real vertices of the frozen dependency graph: their outgoing edges, cycles and missing managed children are validated, and their managed children remain ordinary exact-artifact nodes.

D-003 continues to govern Build Manager-managed exact-artifact software. Platform-provided requirements are not BM-managed payloads. They do not create a source-tree packaging provenance class, and locally packaging official Kodi source into a substitute artifact is not a permitted route.

The frozen manifest carries this meaning as schema version 2, emitted only when a platform-provided node is present. Schema version 1 keeps its exact prior meaning and fingerprints and cannot represent a platform-provided node. Presentation of platform rows is a separate follow-up and does not change this policy.
