# Current Handoff — Build Manager Manual Mode (2026-10-03)

## Operating mode

Build Manager is now intentionally in **manual relay mode**.

Active loop:

`ChatGPT plans/supervises -> Eric runs a bounded Codex/Claude prompt -> Eric pastes the report back -> ChatGPT reviews/chooses the next task`.

Do not start, resume, reinstall, or depend on ai-supervisor unless Eric explicitly decides to resurrect that separate framework project. Relay-v1 is deferred.

The previous Relay-v1 scheduled automation has been disabled.

## Current milestone

The current outcome remains **Build Manager macOS Beta Qualification**. Use the seven exit items in `BUILD_MANAGER_PROJECT_PLAN.md` as the finish line.

Do not turn unfinished ai-supervisor provenance, planner, trusted-action pinning, Relay-v1, or framework cleanup into Build Manager prerequisites.

## Current product candidate

Manual continuation should begin by reconciling this exact worktree:

- worktree: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-beta-recovery`
- branch: `agent/beta-recovery`
- last verified HEAD before manual-mode transition: `e57a5b6d47a7ed53d3f8bd526de300960d9f7e32`
- reviewed substantive BM 0.0.15 commit: `8789329054b77815c6f9548fd4ce9beacbe1d348`
- reviewed product/tracking identity includes `16435a892b4ad2cf54c34d3b049c28ed3f1703eb`
- independent product review work: `4ef22b35-da05-454a-99c4-0ae08aea4882`

The worktree intentionally has manual bookkeeping edits under `.agent/**` from the shutdown/resumability cleanup. They are not product changes.

Before any new implementation, re-run read-only Git status/identity checks; current live Git always wins over this snapshot.

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

## Safety boundaries that still apply

- Never access normal `/Applications/Kodi.app` for BM validation.
- Never access `/Users/eengert/Library/Application Support/Kodi`, including read/probe access.
- Authorized macOS runtime target is only `/Applications/Kodi Build Manager Test.app` in portable `-p` mode.
- Real Apple TV / Shield / Fire TV mutation requires Eric's explicit named-device/named-action authorization.
- Do not expose credentials, private overlay values, tokens, or secrets.
- No push, release, force-push, destructive history rewrite, or evidence-destroying cleanup without Eric's explicit authorization.

## Manual Test.app work

Eric's standing authorization for routine Build Manager validation against the disposable portable Test.app remains valid.

In manual mode, ChatGPT must put the exact operation and safety scope into each Codex/Claude prompt.

Do not assume historical ai-supervisor named actions/brokers exist. If a required Test.app operation needs credential isolation or a helper that is not already available outside ai-supervisor, stop and design/verify a small safe manual helper rather than exposing credentials or reviving the whole framework.

## Smallest next manual step

Start with a **read-only manual reconciliation** of the beta-recovery worktree and the current beta exit checklist.

The first new Codex/Claude task should answer, from current Git and repository tooling:

1. Is the reviewed BM 0.0.15 product candidate still byte-identical to the accepted snapshot?
2. Which macOS Beta Qualification exit items remain genuinely unproven?
3. What is the smallest safe path to stage/identify the reviewed candidate in the portable Test.app **without depending on retired ai-supervisor infrastructure**?
4. Does the repository already contain a safe host-side/manual staging/auth helper; if not, what minimal helper is actually required?

That task should not change product source. It should produce a concrete manual qualification sequence, then return to ChatGPT for the next bounded prompt.

## Historical files

`BUILD_MANAGER_SUPERVISOR_HANDOFF.md`, old `.agent/**` records, ai-supervisor state/checkpoints, and the cold-storage archive are historical evidence.

They do not override current Git plus this manual-mode `.orchestrator` guidance.
