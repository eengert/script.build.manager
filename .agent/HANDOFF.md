# Endpoint restored — manual Agent Handoff workflow (2026-10-04)

Status: idle. No task is assigned.

## What this branch is

- The Agent Handoff **Codex** endpoint for project `build-manager`:
  branch `agent/codex`, worktree `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`.
  Restored by hand on 2026-10-04 after ai-supervisor was retired. This was a manual git
  merge plus this metadata commit, not an Agent Handoff engine run.
- Content: the current Build Manager candidate `agent/beta-recovery`
  e57a5b6d47a7ed53d3f8bd526de300960d9f7e32 (BM 0.0.15 product state), merged by commit
  c56a06e into the historical `agent/codex` tip 19ee48f (first parent). Outside `.agent/**`
  the tree is identical to e57a5b6; the restoration changed no product source.
- Not pushed: `origin/agent/codex` is still d8ab24b.

## Read before starting work

- Manual-mode guidance (`.orchestrator/BOOTSTRAP.md`, `PROJECT.md`, `WORKFLOW.md`,
  `DECISIONS.md`, `HANDOFF.md`) exists only on local `matrix` in
  `/Users/eengert/Documents/Kodi/script.build.manager`; it is not on this branch. This
  branch's `AGENTS.md` and `CLAUDE.md` are the older ai-supervisor-era versions. Where they
  disagree, the `.orchestrator` guidance and the exact task prompt win.
- The `.agent/**` records that were here described ai-supervisor-era work and were replaced
  by this note. They remain in history: 19ee48f (previous Codex endpoint) and e57a5b6
  (candidate, second parent of c56a06e). Uncommitted shutdown notes about the same era remain
  untouched in the `agent/beta-recovery` worktree.
- ai-supervisor is retired to cold storage. Do not start or depend on it.
