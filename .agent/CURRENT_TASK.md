# Current Task

- Task: Trusted add-on root authority correction (narrow correction after independent review of `b8d7a06`; no assigned ID).
- State: product commit `ace8b77` pending independent re-review. **Not claimed closed.** The bundled-capture defect stays open until re-review passes. Item 8 OPEN. Restart/resume OPEN.
- Accepted earlier and not reopened: Red Light quiet-WAL correction `e5a18a5` (CLOSED IN SOURCE after independent review).
- Start: `agent/claude` at `b0835a2`, worktree clean.
- Commits: product `ace8b77` (`resources/lib/frozen.py`, `tests/test_frozen.py`); this bookkeeping commit (`.agent/**` only). `b8d7a06` and `b0835a2` were not amended.
- Evidence: `.qualification-evidence/bundled-addon-root-authority-correction-20261009/` (gitignored, compact summaries and SHA256SUMS).
- Current blockers: independent re-review of `ace8b77`; exact `script.module.pil` 5.1.0 ZIP artifact pending afterward (not sourced; never 1.1.7).
- Boundaries: no Test.app staging or launch, no live Red Light database or private overlay access, no PIL sourcing, no normal Kodi or device access, no push, no release, no publication, no Agent Handoff switch.
- Next: independent re-review of `ace8b77`.
- Usage: see the appended rows in `.agent/USAGE_HISTORY.md`.
