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

## Restrictions

- Do not push or merge to `matrix` for normal implementation work.
- Do not modify Eric's real Kodi profiles or any Apple TV.
- Do not make large speculative refactors.
- Do not invent a project plan — use `BUILD_MANAGER_PROJECT_PLAN.md` as the
  authoritative source once it is populated.
