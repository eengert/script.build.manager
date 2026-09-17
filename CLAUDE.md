# Claude-Specific Guidance — Build Manager

Read `AGENTS.md` first. This file adds Claude-specific notes that complement
the shared agent guidance.

## Before Starting Any Task

1. Read `BUILD_MANAGER_SUPERVISOR_HANDOFF.md` for current project state.
2. Read `.agent/CURRENT_TASK.md` for the assigned task scope.
3. Read `.agent/HANDOFF.md` for the latest handoff from the previous session.
4. Read `AGENTS.md` for shared rules.

Do not begin implementation until you understand the task scope and any open
human gates.

## Task Scope

Stay within the assigned task. Do not:
- Refactor code outside the task's stated file list.
- Implement features mentioned in passing but not in scope.
- Make speculative architectural changes.
- Bump version numbers or prepare releases unless the task explicitly
  authorizes it.

If you discover a real issue outside scope, note it in the handoff under
"Out of scope — noticed" and do not fix it in the current task.

## Reporting

Your handoff must include:
- Files created or modified (with commit SHA)
- Test results (pass count, any failures)
- What was live-proven versus unit-tested only
- Any risks or human decisions required before the next step
- The usage row you appended to `.agent/USAGE_HISTORY.md`, or an explicit
  statement that no reliable usage reading was available

## Restrictions

- Do not push or merge to `matrix` for normal implementation work.
- Do not modify Eric's real Kodi profiles or any Apple TV.
- Do not make large speculative refactors.
- Do not invent a project plan — use `BUILD_MANAGER_PROJECT_PLAN.md` as the
  authoritative source once it is populated.

## Usage Tracking (Claude)

Read the shared `## Usage Tracking` section in `AGENTS.md` first. This section
documents the Claude-side mechanism and terminology.

### Available usage source

Claude Code **does** have a reliable usage source, unlike the `claude` CLI
itself (`claude --help` exposes no usage/quota command).

**Preferred — Claude Code desktop app (this is where Build Manager work runs):**

Call the session-management MCP tool:

```text
mcp__ccd_session_mgmt__get_usage   with   session_id: "self"
```

It returns, for the account:

- `plan.plan` — plan name
- `plan.windows[]` — each limit window (`5-hour limit`, `Weekly · all models`,
  and any per-model weekly window) with `percentUsed`, `resetsAt`, `resetsIn`
- `plan.extraUsage` — extra-usage spend, when enabled

and, for the session, `context.tokensUsed` / `context.percentUsed` against the
context window. The **plan windows** are the usage metric to record; the
context figure describes the conversation, not the allowance.

If `plan.status` is `unavailable` or `not_applicable`, there is no reliable
reading — record it as unavailable. Do not substitute the context-window
number for a plan reading; they measure different things.

**Interactive terminal sessions:** `/usage` shows the same plan card. It opens
an interactive panel, so it is not usable from a non-interactive or desktop
session — use the MCP tool there instead.

### Recording model and effort

Read the actual session configuration rather than trusting the task prompt:

```text
mcp__ccd_session_mgmt__get_session   with   session_id: "self"
```

Record the `model` and `effort` fields **exactly as reported**. Task prompts
have specified a model that did not match the session that actually ran; the
observed value is the one that belongs in the history.

Claude models are **Sonnet** and **Opus**. Claude's reasoning setting is
reported by Claude Code as `effort`, on its own scale.

> Claude Code's effort scale and Codex's effort scale are unrelated systems
> that happen to share some label spellings. Record whatever Claude Code
> reports for a Claude session, and never translate a Claude value into a
> Codex one (or the reverse). Luna, Sol, and Astra are Codex model names and
> are never Claude models.

### When to check

- Once near **task start**, before substantive work.
- Once near **task completion**, before the final commit.

Do not poll during normal work — each check consumes the allowance being
measured. Repeated checks are appropriate only when the usage behavior itself
is what you are troubleshooting.

### If no reliable reading is available

Record usage as `unavailable` in `.agent/USAGE_HISTORY.md` and say so in the
handoff. Do not estimate, extrapolate, or reconstruct usage from memory.

If the start reading was missed but an end reading exists, record
`start = unknown`, `end = <actual value>`, `delta = unknown`.

### Where it goes

One row per task in `.agent/USAGE_HISTORY.md`. Never paste raw usage output
into `BUILD_MANAGER_PROJECT_PLAN.md` or `BUILD_MANAGER_SUPERVISOR_HANDOFF.md`.
