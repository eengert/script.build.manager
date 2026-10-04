# Endpoint restored — manual Agent Handoff workflow (2026-10-04)

Status: idle. No task is assigned.

## What this branch is

- The Agent Handoff **Claude** endpoint for project `build-manager`:
  branch `agent/claude`, worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude`.
  Restored by hand on 2026-10-04 after ai-supervisor was retired. This was a manual git
  merge plus this metadata commit, not an Agent Handoff engine run.
- Content: the current Build Manager candidate `agent/beta-recovery`
  e57a5b6d47a7ed53d3f8bd526de300960d9f7e32 (BM 0.0.15 product state), merged by commit
  764929f into the historical `agent/claude` tip 98750fc (first parent). Outside `.agent/**`
  the product tree is identical to e57a5b6; the restoration changed no product source.
- Guidance sync: commit 59ef609 copied the nine manual-mode guidance files listed below from
  local `matrix` cee9d0b7a2cc4a2ce2fa657c6a46d28dbc899fe3 (a path-level copy, not a merge of
  `matrix`). It changed documentation only.
- Guidance re-sync: commit b576ce0 refreshed six of those files (`.orchestrator/{HANDOFF,PROJECT,WORKFLOW}.md`,
  `AGENTS.md`, `CLAUDE.md`, `BUILD_MANAGER_PROJECT_PLAN.md`) from `matrix`
  a5fbadfa96cc0d44e4742717b7a1ab05e79d20b6 (again a path-level copy, documentation only).
- Guidance re-sync: commit 32baa8f refreshed six files (`.orchestrator/{BOOTSTRAP,CHATGPT_PROJECT_INSTRUCTIONS_MANUAL,DECISIONS,HANDOFF,WORKFLOW}.md`,
  `AGENTS.md`) from `matrix` 299cf81dce75363966cd363c6bfdc58e3a97dcce (path-level copy, documentation
  only). It adds decision D-026 and removes the retired Antigravity notes from `AGENTS.md`.
- Not pushed: `origin/agent/claude` is still 98750fc.

## Read before starting work

- The manual-mode repository guidance on this branch is a path-level copy of `matrix`:
  `.orchestrator/{BOOTSTRAP,CHATGPT_PROJECT_INSTRUCTIONS_MANUAL,DECISIONS,HANDOFF,PROJECT,WORKFLOW}.md`,
  `AGENTS.md`, `CLAUDE.md` and `BUILD_MANAGER_PROJECT_PLAN.md`, all identical to `matrix` 299cf81.
  Start from `.orchestrator/BOOTSTRAP.md`. Local `matrix` in
  `/Users/eengert/Documents/Kodi/script.build.manager` remains the canonical copy: later `matrix`
  changes are not propagated automatically, and the `.orchestrator/HANDOFF.md` here is a snapshot as
  of 299cf81. `BUILD_MANAGER_SUPERVISOR_HANDOFF.md` and older `.agent/**` records are historical,
  not current instructions.
- The `.agent/**` records that were here described ai-supervisor-era work and were replaced
  by this note. They remain in history: 98750fc (previous Claude endpoint) and e57a5b6
  (candidate, second parent of 764929f). Uncommitted shutdown notes about the same era remain
  untouched in the `agent/beta-recovery` worktree.
- ai-supervisor is retired to cold storage. Do not start or depend on it.
