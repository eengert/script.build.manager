# ChatGPT Local Agent Guidance — Build Manager

Read `AGENTS.md` first. This file adds guidance for normal ChatGPT when it is
acting as a local coding agent through the Kodi Local Developer MCP app.

This mode is distinct from ChatGPT's supervisor role.

## Hard boundary

Do **not** use ChatGPT Work mode for this workflow. The purpose of this agent is
to remain usable when the Codex usage pool is exhausted.

Use only the custom local MCP app connected to the dedicated
`agent/chatgpt` worktree.

## Before starting a coding task

1. Call `workspace_info` and verify the branch/worktree is `agent/chatgpt`.
2. Read `BUILD_MANAGER_SUPERVISOR_HANDOFF.md`.
3. Read `.agent/CURRENT_TASK.md`.
4. Read `.agent/HANDOFF.md`.
5. Read `AGENTS.md`.
6. Read the relevant implementation/tests before changing anything.
7. If the task is a handoff from Codex or Claude, verify the repository state
   rather than trusting prose alone.

## Working rules

- Stay in the bounded task assigned by the supervisor.
- Read an existing file immediately before replacing it and pass the returned
  SHA-256 to `write_file`.
- Prefer `apply_patch` for localized edits.
- Run targeted tests during development and the full suite before completion.
- Use only disposable Kodi harness commands unless the human explicitly
  authorizes a separately implemented real-device tool.
- Do not ask for or attempt arbitrary shell access as a shortcut.
- Do not push, merge to `matrix`, rewrite history, or remove files through
  unexposed means.
- Commit only coherent reviewed work to `agent/chatgpt`.

## Handoff

At completion, follow the same shared handoff contract as Codex and Claude:

- update `.agent/HANDOFF.md`
- update `.agent/CURRENT_TASK.md`
- update `.agent/AGENT_STATUS.json`
- append a row to `.agent/USAGE_HISTORY.md`

For normal ChatGPT, usage readings should be recorded as `unavailable` unless
ChatGPT exposes an actual reliable allowance metric for the current session.
Do not infer usage from message count, token count, or another agent's quota.

Clearly distinguish:

- unit-tested behavior
- disposable-Kodi live validation
- anything not live-tested
- any human gate still required

## Supervisor vs coding-agent role

Normal ChatGPT may be both project supervisor and the active coding agent, but
those roles must remain explicit. When ChatGPT has implemented a material or
high-risk change itself, prefer independent Codex or Claude review when quota
becomes available rather than self-approving the change into `matrix`.
