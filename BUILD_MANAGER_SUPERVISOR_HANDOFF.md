# Build Manager — Supervisor Handoff

Living project-state document. Update this after each integration milestone.

## Project Identity

| Field | Value |
|---|---|
| Name | Build Manager |
| Addon ID | `script.build.manager` |
| Repository | `eengert/script.build.manager` |
| Integration branch | `matrix` (protected) |
| Agent branches | `agent/codex`, `agent/claude` |

## Target Platforms

- tvOS (Apple TV)
- Android / Shield TV
- Fire TV
- macOS (local Kodi)

## Architecture Principle

Build Manager uses **desired-state provisioning** rather than backup/restore
cloning. Each device's configuration is expressed declaratively; the addon
applies that declaration to reach the desired state. It is not a backup tool
and does not clone device state by copying files from one device to another.

## Current State

**Phase**: BM-001 — project skeleton, in progress.

- Bootstrap commit: `a970e83` on `matrix`.
- Codex temporarily unavailable; Claude is primary agent for BM-001.
- BM-001 work committed to `agent/claude` (not yet merged to `matrix`).
- `BUILD_MANAGER_PROJECT_PLAN.md` is populated with the full phased plan.

## Active Task

**BM-001: Project skeleton** — `agent/claude`

Creating `addon.xml`, `default.py`, `resources/lib/build_manager.py` stub,
`resources/settings.xml`, `resources/language/`, `tests/`, `changelog.md`,
`LICENSE.txt`. No provisioning logic. See `.agent/CURRENT_TASK.md`.

## Worktree Paths

| Branch | Worktree |
|---|---|
| `agent/codex` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex` |
| `agent/claude` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude` |

## Agent Workflow

Normal implementation work happens on `agent/codex` or `agent/claude`.
Completed, reviewed work is merged to `matrix` by the supervisor.
Agents do not push or merge to `matrix` directly except for explicitly
authorized bootstrap or housekeeping operations.

## History

| Date | Milestone |
|---|---|
| 2026-09-17 | Repository initialized; bootstrap files committed to `matrix` (`a970e83`) |
| 2026-09-17 | BM-001 in progress on `agent/claude`; project plan populated |
