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
`open -g "/Applications/Kodi Build Manager Test.app" --args -p`, which requests
background launch but does not guarantee unchanged foreground focus. Use the
tracked `tools/bm_test_app_window.swift` utility for foreground PID/window
inspection as specified in `AGENTS.md`. Do not hide/minimize Kodi to restore
focus. A specific validation task may explicitly require foreground activation.

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


## D-029 — Advanced interrupted-Create recovery is post-beta (2026-10-13)

Eric removed advanced Create failure recovery from initial macOS beta prerequisites. The beta still requires an ordinary supported Create Build UI workflow, safe failure with no BM-caused loss of existing user data, honest failure/status presentation, and the already-required Install/Update/Repair restart/resume and recovery evidence. No private/Red Light Create path may silently use unproven external-operation exclusion or restart proof.

The post-beta recovery goal can be a **known safe Kodi state** rather than exact restoration of every pre-failure setting. Prefer a truthful diagnostic of the last confirmed operation phase, incomplete or uncertain work, and safe manual steps; do not invent observations, delete held transaction evidence, disclose private values, or present an unknown state as restored. More sophisticated durable failure reporting and automatic Create recovery are not initial-beta gates.

The independently accepted offline BM reservation and synthetic macOS witness are preserved as research, not runtime authority. Production protected Create admission remains NO-GO on supported Kodi mechanisms for external operation exclusion; do not weaken the fail-closed competing_operation() and verify_restart() contracts, P5, D2 Option A, or existing activation holds. This decision does not authorize normal Kodi/device access, a push, release, or integration to matrix. Consult BUILD_MANAGER_PROJECT_PLAN.md for the exact amended eight-item beta exit checklist.

## D-030 — Live restart/resume demonstrations for Install, Update and Repair are post-beta (2026-10-16)

Eric approved deferring live native end-to-end restart/resume demonstrations for supported Install, Update and Repair operations when they require a genuine Kodi process restart. The qualification state for each such lifecycle must be reported exactly as **NOT YET LIVE-QUALIFIED — DEFERRED TO POST-BETA**. These restart-producing demonstrations are not initial-beta exit prerequisites and, while deferred, must never be reported as tested, PASS, complete, operationally qualified, or proven through native Test.app execution. The deferral does not apply to ordinary non-restart Install, Update or Repair operations; their supported native workflows and truthful results and errors remain initial-beta requirements. Offline or synthetic evidence must not be presented as live qualification.

Explicit approval record: On October 16, 2026, in Eric's ChatGPT Supervisor conversation, the Supervisor asked, "Do you explicitly approve deferring live native restart/resume testing for restart-producing Install, Update, and Repair operations until post-beta?" Eric replied verbatim, "Yes, I approve all three operations being deferred". This explicit confirmation authorizes deferring only the live restart/resume demonstrations for restart-producing supported Install, Update and Repair operations described above.

This changes beta acceptance scope only for live native demonstrations of restart-producing Install, Update and Repair operations. The existing restart/resume implementation, automated coverage, offline validation requirements, accepted offline validation evidence, and runtime safety safeguards remain unchanged. Initial beta still requires the existing implementation and accepted offline evidence, plus all existing fail-closed behavior and protections. A broken supported operation or discovered safety defect remains an initial-beta blocker. A restart-required path must not be bypassed to satisfy qualification or falsely marked successful. Only the live native restart/resume demonstrations for those restart-producing operations are deferred.

D-030 supersedes D-029's earlier initial-beta requirement only to the extent that it required live native restart/resume demonstrations for supported Install, Update or Repair operations that require a genuine Kodi process restart. All other required Install/Update/Repair evidence remains in scope. D-029 remains in force for protected Create restrictions, including the prohibition on weakening `competing_operation()`, `verify_restart()`, P5, D2 Option A, or existing activation holds.

After beta, the deferred obligation is to validate each applicable genuine product-supported restart-producing lifecycle through its native Install, Update or Repair path, as applicable, including a durable transaction, complete Kodi process exit, portable relaunch, startup continuation, private verification and activation safeguards, hold release, truthful validation, final association/status, and finalization. Do not invent successful completion or restored state. No synthetic restart evidence may substitute for that lifecycle. The prospective runtime preconditions and STOP conditions in `docs/ITEM8_AUTHORED_FIXTURE.md` remain mandatory for any separately authorized future live use; they do not reinstate these deferred demonstrations as initial-beta prerequisites. This decision authorizes no Test.app/runtime operation, normal Kodi or household-device access, repository publication, push, release, or integration to protected `matrix`. The documentation change requires independent review and a separate deliberate integration decision before promotion to `matrix`.

## D-031 — Narrow BM-023A adapter version 0.0.17 exception for the xbmc.metadata diagnostic (2026-11-14)

The 2026-11-14 manual relay task authorized one bounded exception to the BM-023A diagnostic-version freeze in `BUILD_MANAGER_PROJECT_PLAN.md` (the freeze sentence at line 79). The BM-023A adapter version advances from `0.0.16` to `0.0.17` in authoritative source (`tools/bm023a_adapter_support.py`) and packaging metadata (`tools/bm023a_adapter/addon.xml.in`).

Justification: on 2026-11-13 the A15 native Create returned 32730. The selected public root requires `xbmc.metadata`. Current production verification refuses it. The existing `0.0.16` adapter cannot collect the native evidence needed to evaluate safe support. The fixed `xbmc_metadata_observe` diagnostic (commit `1f025cf`) has independent source-security review PASS. That review did not establish native functionality or production support for `xbmc.metadata`.

Scope: this exception covers only the version advance for this diagnostic-only beta blocker, the version-dependent source and packaging metadata, and the active tests and helper gates that must match the current version. The helper's exact-version branches in `tools/bm_test_app.py` (candidate build argument, `PLATFORM_SOURCE_BINDING` expectation and driver version checks) now match `0.0.17`, so the platform source binding stays required for the new adapter. Historical `0.0.16` evidence and `.agent` histories are preserved unchanged.

It does not authorize general observability work, new diagnostic modes, production `xbmc.metadata` support, allowlist changes or production trust changes. The general version freeze remains in force for every other diagnostic, cleanup, ergonomics or theory change. No staging, adapter installation, Test.app launch, GUI/RPC, Create, Install, Update or Repair was performed under this decision.

## D-032 — Pinned xbmc.metadata passive support and practical A15 preservation criteria (2026-11-15)

Eric approved two bounded changes for practical personal beta readiness. This decision accepts neither Item 8, A15 nor any native lifecycle, and it changes no accepted safety mechanism.

**1. Pinned xbmc.metadata passive support.** Commit `7f83134` adds `xbmc.metadata` 2.1.0, ABI 1.0, descriptor SHA-256 `95082198599c695a91d2aefb072f0457e9ffd5eb3f2dc1587fa58159750db1b6`, build `20251031-a3a448d26b`, to the existing trusted passive-builtin mechanism (`_PASSIVE_BUILTINS`) beside `xbmc.core`, `xbmc.gui` and `kodi.resource`. The pin keeps the exact build, descriptor, version and ABI checks, home-shadow exclusion, enabled-state and constructor verification, freshness rechecks, source binding and fail-closed refusal on every mismatch. A mandatory `xbmc.core` dependency is required in capture and admission. No general scraper allowlist is created, and no other provider is weakened. The diagnostic adapter, its platform identities and the D-031 version freeze are unchanged.

**Limited passive compatibility standard.** Passive registration proves registration, enabled state, identity, origin, build, descriptor bytes and the declared dependency closure. It does not prove independent functional usability of any scraper extension point or any Python API. The observed type `unknown` and the JSON-RPC omission are expected. Excerpts of Kodi source at revision `a3a448d26b`, fetched for this review and not byte-verified, show three things. `CAddonInfoBuilder::ParseXML` derives a type only from `<extension point=...>` children and never reads `<extension-point>`, and xbmc.metadata declares only extension points, so its type falls back to UNKNOWN. `CAddonsOperations` removes UNKNOWN-typed add-ons from listings and rejects them in `GetAddonDetails`. `CAddonMgr::GetAddon` returns enabled UNKNOWN-typed installs, which is the path the pinned read uses. The descriptor fixture was copied read-only from the bundled Test.app add-on and matches the pinned digest. No application was launched.

**2. Practical A15 preservation criteria.** Beta acceptance of preservation is judged by the practical contract in `docs/A15_NATIVE_PRESERVATION_RUNBOOK.md` ("Practical beta preservation contract (D-032)"), not by whole-session byte equality. The contract covers nine scopes: saved builds and library; artifacts and associations; configuration and meaningful settings; supported add-on resources and private settings; relevant databases; unmanaged add-ons and unrelated configuration; transaction and recovery safety; source installation during capture; and receiving installation during application. It accepts only two closed ordinary-maintenance classes, the uptime counter and texture cache metadata, and only through a reviewed in-memory comparator. That comparator is defined but not implemented. The contract defines PASS, FAIL and INCONCLUSIVE with their evidence requirements. The N6 strict comparison and its results are retained unchanged and are never rewritten. Unwitnessed scopes are reported as limitations and are not silently excluded.

**Retained strict requirements.** Transaction, recovery, activation-hold, `competing_operation()`, `verify_restart()`, P5, D2 Option A, the D-028 platform-authority rules, D-029, D-030 and D-031 are unchanged. Exact identity, credential isolation, private-value protection and truthful failure reporting remain required.

**Personal beta versus public-product qualification.** D-032 supports Eric's personal beta readiness. It does not establish broad public-product qualification. Whole-profile preservation, complete Addons33 and unmanaged add-on verification, full writer attribution, the D-030 deferred lifecycles, Eengert Repository publication and macOS beta acceptance remain separate and open.

**Independent review and native evidence.** The production change `7f83134` and this documentation change require independent review before any promotion to `matrix`. The accepted 2026-11-14 native observation binds to candidate `b71b408` and does not cover `7f83134`. A representative native Create to Install to Verify run on the exact reviewed candidate is therefore required before xbmc.metadata support is relied on in any qualification claim. A practical A15 verdict requires the reviewed comparator, a separate authorized scenario, sealed native evidence and independent review of that evidence.

This decision authorizes no Test.app launch or staging, no native workflow, no normal Kodi or household-device access, no push, merge, release or integration to `matrix`, and no change to accepted evidence.

**D-032 clarification (2026-11-17): M2 sizes-row lifecycle authorization (additive; the D-032 text above is unchanged).** The M2 wording of D-032 names texture and sizes values and "cache row creation and eviction", but it does not explicitly name sizes-row creation or eviction. Eric has now explicitly approved the two maintenance classes `M2_CACHE_SIZES_CREATE` and `M2_CACHE_SIZES_EVICT`, subject to this restriction: sizes-row creation or eviction is ordinary M2 cache maintenance **only when its parent texture row is created or evicted in the same comparison**. Sizes rows added or removed beneath a retained texture row remain MEANINGFUL. M2 is not extended to any other rows, fields, relationships or lifecycle behavior. This clarification authorizes no native run, no comparator integration into a driver and no qualification-gate change.

**D-032 clarification (2026-11-17): retention of offline evidence wiring (additive; the D-032 text and the M2 clarification above are unchanged).** Eric explicitly approved retaining the offline wiring implemented in commit `a4509a5`, subject to the corrections recorded here. Approved scope: the same-session, in-memory comparison of the five projections by `AcquisitionSession.finish()`; sanitized per-file classifications with closed class names and integer counts; validation of that block in A15 evidence by the driver, with the strict gate, `state`, `reason` and per-file statuses unchanged; and the practical verdict remaining `NOT_DECIDED`. Correction approved with this retention: the driver's practical validator accepts a maintenance class only on the file it belongs to. `M1_UPTIME` is valid on guisettings only, the approved M2 classes on Textures13 only, and no maintenance class on Addons33, the Estuary settings or the keyboard settings. A cross-file or otherwise malformed block refuses the finish. This explicitly supersedes only the restriction against comparator integration into a driver stated in the M2 clarification above. It does not authorize native execution, any practical PASS, any weakening of the strict N6 gates, publication, or integration to `matrix`. The M2 sizes-row authorization above is preserved unchanged.

## D-033 — Controlled local capture as the last-resort artifact acquisition step (2026-11-16)

Eric approved a narrowly controlled exception to the last sentence of D-003 ("Installed add-on directories are not repackaged to manufacture missing frozen artifacts"). The D-003 text above is preserved as history. **D-033 supersedes only that sentence, and only for the case defined here.** D-003's immutable SHA-256 artifacts, D-004's explicit per-add-on fallback principle, the "no silent version substitution" rule and the D-028 platform-provided rule (no ZIP is ever manufactured for a Kodi-bundled add-on, and local packaging of official Kodi source stays forbidden) are unchanged.

**Acquisition order (final).** (1) A verified ArtifactStore ZIP for the exact ID and version. (2) An exact original package-cache ZIP. (3) The exact original ZIP from the official repository, via the accepted provider. (4) Only when step 3 has proven the exact original is unavailable, and only for an add-on the user has approved individually, a controlled package of the installed add-on's own files. Step 4 is a fallback, not a normal method.

**Trigger.** Step 4 is reachable only through `RepositoryArtifactUnlisted`: the checksum-verified official index was read and does not list the exact ID and version. Checksum or size mismatch, changed installed content, an unsafe or unreadable installed tree, TLS or network failure, DNS or address refusal, a malformed or ambiguous index, a listed archive that cannot be fetched, and every other integrity refusal never fall back. The user must approve each add-on separately in Create; nothing is captured locally without that approval, and an add-on the user declines leaves the build incomplete.

**Package rules.** Exact installed ID and version only; never a platform-provided add-on. The scan reuses the trusted add-ons root, no-follow traversal, bounded reads, per-file identity and the freshness stamps; the packaged bytes are read once and the whole tree must be identical on a second scan. The ZIP is deterministic, bounded to 64 MiB and written through the existing SHA-256 ArtifactStore. Included: every distributable file, including Python source. Dropped and counted: regenerable `__pycache__` bytecode whose source ships, `.DS_Store`, `Thumbs.db`, `*.log`. Refused: any symlink or special file, unsafe names, sourceless or loose bytecode, native binaries or libraries and any add-on that declares a platform other than `all` or `library_*` entries (compatibility cannot be established), private or local-state content (`addon_data`/`userdata`/VCS directories, a root `settings.xml`, databases, keys, credential-like data files). `userdata` and `addon_data` are never put in a software ZIP; configuration and private-resource capture remain separate.

**Provenance.** The artifact is stored with source `installed_local_capture` and is never described as an original or repository-verified archive. Create shows a per-add-on consent dialog and reports how many saved add-ons are local copies. Local copies are claimed to be neither original nor portable beyond their checked content.

D-033 authorises no Test.app launch, Kodi or device access, push, merge or release. Native qualification of this step is a separate task after independent review.
