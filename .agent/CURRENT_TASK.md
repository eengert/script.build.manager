# Current Task

- Task: Platform-provided bundled add-on core, Phase 1 (no assigned ID). D-028: Kodi application-bundled add-ons are platform-provided requirements, never artifacts or managed roots.
- State: product commit `bddbe6f` pending independent review. **Not claimed CLOSED.** Item 8 OPEN. Restart/resume OPEN.
- Start: `agent/claude` at `20b5477`, worktree clean.
- Commits: D-028 guidance `d1ebfa0` (`.orchestrator/DECISIONS.md` only); product `bddbe6f` (resources and tests); this bookkeeping commit (`.agent/**` only).
- Evidence: `.qualification-evidence/platform-provided-core-20261009/` (gitignored; summaries, compressed logs, probes, SHA256SUMS).
- Current blockers: independent review of `bddbe6f`; live Kodi proof of builtin `xbmc.python` evidence and the trusted origin read (not authorized in this task); bundled-skin decision (Phase 2).
- Boundaries kept: no Test.app launch or staging, no private overlay or portable-profile access, no PIL ZIP construction or import, no fixture registration, no normal Kodi or device access, no push, no release, no publication, no Agent Handoff switch.
- Next: independent review of `bddbe6f`.
- Usage: see the appended row in `.agent/USAGE_HISTORY.md`.
