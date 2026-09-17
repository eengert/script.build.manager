# Handoff

## Latest — 2026-09-17 BM-001 in progress; Claude is primary agent

Codex is temporarily unavailable. Claude is acting as primary development agent
until Codex rejoins. Current task: BM-001 (project skeleton).

See `.agent/CURRENT_TASK.md` for scope and acceptance criteria.
See `BUILD_MANAGER_SUPERVISOR_HANDOFF.md` for project state.
See `BUILD_MANAGER_PROJECT_PLAN.md` for the full phased plan.

**Note for Codex when rejoining**: Codex was unavailable during BM-001.
Claude will commit the skeleton to `agent/claude`. When Codex rejoins, it
should fast-forward `agent/codex` to the `matrix` commit that includes
BM-001 (once the supervisor merges it) before beginning new work.

## Previous — 2026-09-17 Bootstrap complete; awaiting first development task

Project initialized. All bootstrap files committed to `matrix`; `agent/codex`
and `agent/claude` fast-forwarded to the same commit. No production code
existed yet — repository scaffold only.

No open code task remained. Next task: BM-001 — now in progress.
