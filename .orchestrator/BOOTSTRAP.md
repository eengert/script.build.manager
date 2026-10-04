# Build Manager Manual Workflow Bootstrap

This file is the canonical first-read for any new ChatGPT session helping Eric finish Build Manager.

## Current execution model

Build Manager is in **manual relay mode** as of 2026-10-03.

Eric works with ChatGPT as the human-facing planner/supervisor. ChatGPT prepares bounded, copy-ready prompts for Codex or Claude. Eric runs those prompts in separate agent chats/sessions and pastes the resulting report back to ChatGPT. ChatGPT reviews the result, reconciles Git/repository state when needed, and chooses the next bounded task.

The previous local `ai-supervisor` autonomous orchestration framework is retired to cold storage. Do **not** start, resume, reinstall, or depend on ai-supervisor unless Eric explicitly asks to resurrect it.

The manual working lanes are two **Agent Handoff** endpoints, Codex (`agent/codex`) and Claude (`agent/claude`). Agent Handoff is retained as the supported mechanism for switching ownership between them; Antigravity is retired. Endpoint paths, the live status check, and the rules for switching agents are in `.orchestrator/PROJECT.md`, `.orchestrator/HANDOFF.md`, and decision D-026 in `.orchestrator/DECISIONS.md`.

Remain in normal Chat mode. Do not hand Build Manager work to ChatGPT Work unless Eric explicitly changes this rule.

## Read order

At the start of a new Build Manager chat, read:

1. `.orchestrator/BOOTSTRAP.md` — this file.
2. `.orchestrator/PROJECT.md` — stable project facts and safety boundaries.
3. `.orchestrator/WORKFLOW.md` — the manual implementation/review workflow.
4. `.orchestrator/DECISIONS.md` — settled decisions and historical overrides; D-025 (manual relay) and D-026 (Agent Handoff endpoints) are the current execution decisions.
5. `.orchestrator/HANDOFF.md` — current project checkpoint and next manual task.
6. `BUILD_MANAGER_PROJECT_PLAN.md` only as needed for the current milestone/checklist.
7. `AGENTS.md` plus the provider-specific file for the agent being used.

Then reconcile current Git/worktree state and the live, read-only Agent Handoff status (command in `.orchestrator/HANDOFF.md`) before issuing a mutation prompt.

## Source authority

When sources disagree, prefer:

1. Current Git/worktree state and live Agent Handoff status.
2. Current `.orchestrator/HANDOFF.md`.
3. `.orchestrator/PROJECT.md`, `WORKFLOW.md`, and `DECISIONS.md`.
4. The current project plan and implementation docs.
5. Current manual agent reports that can be tied to exact paths/SHAs/diffs.
6. Historical `.agent/**`, supervisor handoffs, or archived ai-supervisor evidence.
7. Conversation memory.

Never let an old ai-supervisor state file, planner instruction, archived handoff, or conversation recollection override fresh Git and current manual-mode guidance.

## Role split

### ChatGPT

ChatGPT should:

- understand the current product state and the beta exit evidence still missing;
- choose the smallest useful next task;
- give Eric a self-contained prompt with exact repo/worktree/branch/scope/safety constraints;
- recommend the appropriate provider/model/effort outside the prompt when useful;
- review pasted reports critically rather than accepting claims at face value;
- request independent review for material/high-risk code changes;
- reconcile contradictory evidence before moving on;
- maintain this handoff at meaningful boundaries.

ChatGPT should not create busywork merely to keep an agent active.

### Eric

Eric is the relay between ChatGPT and Codex/Claude. He chooses when to run a task and pastes the resulting report back into ChatGPT.

### Codex / Claude

The coding agent executes exactly the bounded prompt it receives. It does not autonomously invent the next project task. Each task ends with a concise report containing exact files/SHAs/tests/results/open issues.

Use a separate persistent agent chat when changing provider/model/effort conventions if doing so preserves context/cache quality.

## Manual task loop

For each substantive step:

1. Reconcile current Git/worktree state and the latest handoff.
2. Identify the specific beta exit item or demonstrated blocker being advanced.
3. Select the implementation/review agent.
4. ChatGPT writes one bounded copy-ready prompt.
5. Eric runs it manually.
6. Eric pastes the report back.
7. ChatGPT checks the report against the expected scope/evidence.
8. If substantive source changed, obtain independent review when warranted.
9. Correct only review findings; re-review the correction when needed.
10. Integrate only after accepted evidence and run proportionate validation.
11. Update the handoff when project state materially changes.

There is no autonomous planner, queue, runway, worker lease, controller turn, provider failover, or automatic continuation in manual mode.

## Current outcome

The current milestone remains **Build Manager macOS Beta Qualification**. The authoritative seven-item exit checklist is in `BUILD_MANAGER_PROJECT_PLAN.md`.

Every task should materially advance one exit item or remove a demonstrated blocker to one. Do not spend time finishing retired ai-supervisor infrastructure unless Eric explicitly resurrects that project.

## Safety boundaries

These remain in force regardless of execution model:

- Normal `/Applications/Kodi.app` is off-limits for Build Manager validation.
- Never access `/Users/eengert/Library/Application Support/Kodi`, including read/probe access.
- The authorized macOS runtime target is only `/Applications/Kodi Build Manager Test.app` in portable `-p` mode.
- Real Apple TV / Shield / Fire TV devices are non-mutating unless Eric explicitly authorizes a named action on a named device.
- Do not expose credentials, private overlay values, tokens, or secrets.
- No push, release, force-push, destructive history rewrite, or destructive cleanup unless Eric explicitly authorizes it. The only standing exception is the narrow agent-switch publication authorization in D-026.
- Preserve exact reviewed evidence and do not fabricate provenance, test results, or review status.

Manual mode removes ai-supervisor's machinery; it does not remove these safeguards.

## Test.app work in manual mode

Eric's standing authorization for routine Build Manager validation against the disposable portable Test.app remains in force.

A manual agent prompt may authorize a precise Test.app staging/configuration/restart/read/write operation within that standing scope. Every such prompt must name the exact target and prohibit normal Kodi/profile/device access.

Do not assume old ai-supervisor named actions or brokers are available. If a safe manual helper/path does not already exist for a required operation, stop and design/verify that helper rather than bypassing credentials or safety checks.

## Handoff maintenance

After a material implementation/review/integration/runtime-validation result, or before retiring a chat, refresh `.orchestrator/HANDOFF.md`.

Keep stable policy here and in `PROJECT.md`/`DECISIONS.md`; keep volatile SHAs/status in `HANDOFF.md`.

The archived ai-supervisor/Relay-v1 material is historical reference only unless Eric explicitly decides to resurrect it.
