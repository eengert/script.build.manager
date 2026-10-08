# Current Task

- Task: BUILD MANAGER TEST.APP PACKAGE METADATA / CUSTOM ICON LIVE SMOKE (no assigned ID).
- State: PASS (12-point standard). Test.app is stopped. Local only.
- Start: `agent/claude` at `ba11e48035e5f8af2b2a405b7c9a4a93d684abd2`, worktree clean; live Agent Handoff reported claude current, `agent/claude` clean and ahead.
- Product candidate: `a2b1ffcf77123d269d0e21452a316186950eec1a` (no product changes this task). Installed previously: `53f221986b6c76d5d13652421ac62f999c0c6aab`.
- Validation: standalone Git-bound verify `ok`, `installed_equals_candidate: true`, before and after the run. Installed `addon.xml` is byte-identical to `a2b1ffc`, version `0.1.0`, corrected summary present, stale phrases absent. Icon SHA-256 `207c44a0…628d23`, 512x512, byte-identical to the candidate. Kodi UI showed the custom icon, the corrected summary, and the six-item native menu. Durable pre/post comparison: zero differences.
- Boundaries: Test.app portable `-p` only, via `test_app_*` MCP tools for Kodi interaction. No normal Kodi, profile, device, direct JSON-RPC, push, release, Agent Handoff, or matrix activity. No Build Manager workflow entered.
- Evidence: `.qualification-evidence/bm-testapp-package-icon-smoke-20261008T225641Z/` (git-excluded).
- Next: none pre-selected. Open items are in `.orchestrator/HANDOFF.md` and `.agent/HANDOFF.md`.
- Usage: see the appended row in `.agent/USAGE_HISTORY.md`.
