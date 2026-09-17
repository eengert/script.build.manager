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

**Phase**: Bootstrap — repository initialized, no implementation yet.

- Bootstrap files committed to `matrix` (commit `c0032f1`).
- Agent branches fast-forwarded to bootstrap commit.
- `BUILD_MANAGER_PROJECT_PLAN.md` is a placeholder pending supervisor-approved
  plan.
- No Kodi addon code, tests, or configuration files exist yet.

## Next Task

**BM-001: Project skeleton**

Create the standard Kodi addon directory layout:
- `addon.xml` (metadata, platform declarations)
- `default.py` (entrypoint)
- `service.py` (background service stub, if needed)
- `resources/` tree (`lib/`, `settings.xml`, `language/`, `images/`)
- Empty test suite (`tests/`)
- `tools/` (packaging, test runner)

This task has not been assigned. Assign it to an agent branch when ready.

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
| 2026-09-17 | Repository initialized; bootstrap files committed to `matrix` |
