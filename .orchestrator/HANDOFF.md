# Current Handoff — Build Manager Manual Mode (refreshed 2026-10-04)

## Operating mode

Build Manager is intentionally in **manual relay mode**.

Active loop:

`ChatGPT plans/supervises -> Eric runs a bounded Codex/Claude prompt -> Eric pastes the report back -> ChatGPT reviews/chooses the next task`.

Normal future work happens in the two Agent Handoff endpoints described below (Codex and Claude), each task naming the exact worktree/branch it may use, with ChatGPT supervising.

Do not start, resume, reinstall, or depend on ai-supervisor unless Eric explicitly decides to resurrect that separate framework project. Relay-v1 is deferred.

The previous Relay-v1 scheduled automation has been disabled.

## Current milestone

The current outcome remains **Build Manager macOS Beta Qualification**. Use the eight exit items in `BUILD_MANAGER_PROJECT_PLAN.md` as the finish line.

Do not turn unfinished ai-supervisor provenance, planner, trusted-action pinning, Relay-v1, or framework cleanup into Build Manager prerequisites.

Backend qualification alone does not satisfy product beta readiness. Normal/live Mac Kodi and Shield testing begins only after item 8 is accepted. Acceptance of item 8 does not itself authorize live access: a subsequent task must explicitly name the target and permitted actions. Accepted backend criteria 1-7 remain complete; item 8 remains unimplemented/unqualified.

## Current product candidate

The reviewed BM 0.0.15 product candidate is carried by the Codex and Claude Agent Handoff endpoints (next section), whose product trees outside `.agent/**` are identical. They were restored on 2026-10-04 from the former working worktree:

- `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-beta-recovery`, branch `agent/beta-recovery`, last verified HEAD `e57a5b6d47a7ed53d3f8bd526de300960d9f7e32`
- reviewed substantive BM 0.0.15 commit: `8789329054b77815c6f9548fd4ce9beacbe1d348`
- reviewed product/tracking identity includes `16435a892b4ad2cf54c34d3b049c28ed3f1703eb`
- independent product review work: `4ef22b35-da05-454a-99c4-0ae08aea4882`

beta-recovery is retained as a historical/safety reference for that candidate, not as a normal working endpoint. It intentionally still has uncommitted manual bookkeeping edits under `.agent/**` from the ai-supervisor shutdown cleanup; they are not product changes and should be left alone.

`matrix` currently carries the guidance/orchestration documents but not the BM 0.0.15 product source. Integrating the product candidate into `matrix` is a later, deliberate step and has not been done. `matrix` also has a newer `resources/images/icon.png` than the endpoints; whether that icon belongs in the candidate is an open product/asset decision, separate from guidance synchronization.

Before any new implementation, re-run read-only Git status/identity checks on the endpoint the prompt names; current live Git always wins over this snapshot. Endpoint HEADs are deliberately not recorded here.

## Agent Handoff endpoints (restored 2026-10-04)

The endpoint architecture is recorded as decision D-026 in `.orchestrator/DECISIONS.md`. Agent Handoff is retained as the mechanism for maintaining the two manual agent worktrees and switching ownership between them. Its source is `/Users/eengert/Documents/Kodi/agent-handoff`; the installed `Agent Handoff.app` matches that source and includes the macOS `USAGE_HISTORY` union fix.

- Codex endpoint: worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`, branch `agent/codex`
- Claude endpoint: worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude`, branch `agent/claude`
- Only these two endpoints are configured for Build Manager. Antigravity is retired from the Build Manager Agent Handoff configuration and must not be recreated.
- Which agent is current is determined live, not assumed: Agent Handoff records the active worker, and it changes only through a real handoff or the supported `set-active-agent` recovery command. At the 2026-10-04 refresh it was Codex.
- At this refresh Agent Handoff `status` reported Codex as the current agent with both endpoints clean and containing `origin/matrix`. Re-verify live before relying on it:

  `AGENT_HANDOFF_PROJECT=build-manager "/Applications/Agent Handoff.app/Contents/Resources/agent_handoff_controller.sh" status`

  This is read-only apart from a bounded fetch of `origin/matrix`.
- A real handoff (`continue <agent>`) merges the outgoing endpoint into the incoming one and pushes the incoming branch to `origin`. Run one only when Eric has explicitly asked the Supervisor to switch agents; that request carries the narrow standing publication authorization in D-026 (that one push only: no other push, no `matrix` push, no release, no force-push, no history rewrite). As of this refresh neither endpoint has been pushed since restoration.
- Each endpoint's `.agent/**` is endpoint-specific; do not copy `matrix` `.agent/**`. The `.orchestrator/**`, `AGENTS.md`, `CLAUDE.md` and `BUILD_MANAGER_PROJECT_PLAN.md` copies on the endpoints are path-level snapshots of `matrix`; after changing them here, re-sync them with an explicit-path history-preserving copy (see `.orchestrator/WORKFLOW.md`), never a wholesale merge. `matrix` remains the canonical guidance and protected integration lane.

## Product evidence already established

The 0.0.15 candidate corrected the two defects raised by independent review:

- finite product status-code allowlists/sanitization;
- safe bounded transaction-record reads that reject non-regular objects/races and avoid blocking FIFOs.

Recorded validation before the manual-mode switch included focused and full offline product test passes and an independent PASS. Preserve that accepted product evidence unless source content actually changes.

Do not repeat review merely because retired ai-supervisor checkpoint/provenance mechanics are no longer being used.

## Historical ai-supervisor candidates — preserved, not Build Manager blockers

At retirement, ai-supervisor production main was:

`cb32c8edbffd32beb07e04aa6041e7636e7dd28b`

Two intentionally dirty framework/action candidates were preserved into cold storage:

### Provenance-reconcile candidate

- historical worktree: `/Users/eengert/.codex/worktrees/ai-supervisor-provenance-reconcile/ai-supervisor`
- branch: `codex/provenance-reconcile`
- HEAD: `a004294654e09233943ad0dc6c1b419356384882`
- large uncommitted source-only reconciliation candidate
- intentionally unfinished; no longer a BM prerequisite

### BM-023A trusted-action bridge

- historical worktree: `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions`
- branch: `action/bm023a-trusted`
- HEAD: `9950ca51709d3799af9b5487ef3867088afe62cc`
- retained four reviewed dirty paths
- security PASS review: `55d39236-dd93-4731-9e8b-54212556a0b0`

These states are archived for possible ai-supervisor resurrection. Do not finish their checkpoint/pin/provenance mechanics merely to continue Build Manager manually.

## ai-supervisor cold storage

Cold-storage archive created and verified at:

`/Users/eengert/Documents/Kodi/archives/ai-supervisor-cold-storage-2026-10-03.zip`

SHA-256:

`654403c5815841ab5d3eb2a47c8dd3f69e98ae8b3b338fea3d845eeaa7c5c008`

The archive contains:

- a self-contained Git bundle of all committed ai-supervisor refs/history;
- tracked patches and untracked-file archives for the two dirty candidates above;
- durable BM ai-supervisor checkpoint records;
- sanitized project configuration;
- historical launch/usage ledger;
- LaunchAgent/install inventory;
- Relay-v1 context summary;
- restore guide;
- SHA-256 manifest.

Stale controller/operator tokens, provider session caches, transient runtime/test logs, and running process state were intentionally not preserved.

A fuller `Relay-v1_Plan_and_Context.md` was exported separately for Eric.

**Retirement completed after archive verification:** all ai-supervisor LaunchAgents/services, stale controller-broker processes, menu-bar app copies, CLI symlink, framework repository, linked framework worktrees, and the old Build Manager supervisor worktree were removed. No ai-supervisor process/service remains active.

Build Manager frozen artifact data was relocated on 2026-10-04 to `/Users/eengert/Documents/Kodi/archives/build-manager-frozen-artifacts-2026-10-04`. The 61 preserved payload files were verified byte-for-byte by SHA-256 before the retired `~/.local/state/ai-supervisor` copy was removed. This is product/qualification evidence, not active framework runtime state.

The uncommitted state of the retired `supervised-codex` and `supervised-claude` worktrees (plus a stale non-worktree directory found at the old Codex endpoint path) was preserved before those worktrees were removed, at `/Users/eengert/Documents/Kodi/archives/build-manager-supervised-worktrees-retirement-2026-10-04` (with a `.zip` beside it; zip SHA-256 `57862288421f67346181da2bbc30dda1d2c38e90a1a79af769f670f9885d063c`). The branches of those and the other retired historical worktrees (`bm023a-reviewed-0.0.9/-0.0.10`, `outcome-driven-supervision`, `stage-source-reconcile`) were kept; only the worktree directories were removed.

## Safety boundaries that still apply

- Never access normal `/Applications/Kodi.app` for BM validation.
- Never access `/Users/eengert/Library/Application Support/Kodi`, including read/probe access.
- Authorized macOS runtime target is only `/Applications/Kodi Build Manager Test.app` in portable `-p` mode.
- Real Apple TV / Shield / Fire TV mutation requires Eric's explicit named-device/named-action authorization.
- Do not expose credentials, private overlay values, tokens, or secrets.
- No push, release, force-push, destructive history rewrite, or evidence-destroying cleanup without Eric's explicit authorization (the only standing exception is the agent-switch publication push in D-026).

## Manual Test.app work

Eric's standing authorization for routine Build Manager validation against the disposable portable Test.app remains valid.

In manual mode, ChatGPT must put the exact operation and safety scope into each Codex/Claude prompt.

Do not assume historical ai-supervisor named actions/brokers exist. If a required Test.app operation needs credential isolation or a helper that is not already available outside ai-supervisor, stop and design/verify a small safe manual helper rather than exposing credentials or reviving the whole framework.

## Smallest next manual step

**BM-UI-001 native-dialog foundation is complete and portable-Test.app validated.** The rejected custom full-screen WindowXML shell was removed. The accepted foundation uses native Kodi dialogs: the six-item Build Manager main menu, H01-H10 Help via native selection/text dialogs, and direct native Settings with focus restored to Settings on return. Focused UI tests passed and no backend mutation occurred.

Eric visually accepted the native-dialog model. BM-UI-002A (Help rewrite + package baseline) rewrote H01-H10 in plain scannable language, replaced stale skeleton addon.xml wording and recorded the Beta Candidate phase exit in `BUILD_MANAGER_PROJECT_PLAN.md` (Eengert Repository publication, custom icon, repository-distributed qualification). `resources/images/icon.png` is still the old generic icon: `CUSTOM_ICON_ASSET_REQUIRED` remains a hard package-exit check. Item 8 stays open.

Next bounded step: truthful read-only Status / plan interfaces. Do not begin G1-G6, Create/Install/Repair backends or publication without an explicit task.

The approved backend baseline remains `4a02b833178f5cb29e2b596985f1a8641ed3fa25`; accepted backend qualification evidence remains intact. BM-UI-001 adds frontend product changes above that baseline and is not yet a complete beta frontend.

## Historical files

`BUILD_MANAGER_SUPERVISOR_HANDOFF.md`, old `.agent/**` records (the endpoints' current `.agent/**` notes are endpoint-specific, not project policy), ai-supervisor state/checkpoints, and the cold-storage archives are historical evidence.

They do not override current Git plus this manual-mode `.orchestrator` guidance.
