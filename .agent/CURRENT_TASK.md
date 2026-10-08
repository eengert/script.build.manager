# Current Task

- Task: BUILD MANAGER UPDATE / REPAIR TEST.APP MISSING EXACT ADD-ON (bounded live qualification; no assigned ID).
- State: PASS (19-point standard). Build Manager was exited normally before Test.app quit; the previous run's deviation was not repeated.
- Start: `agent/claude` at `cc0911d`, worktree clean. Test.app `not_running`. Candidate `53f221986b6c76d5d13652421ac62f999c0c6aab` verified Git-bound before and after (`installed_equals_candidate` true). No restage.
- Precheck: saved exact artifact `5a0ee9bf…` (562 bytes) validated before uninstall with the product validator; resolution record exact, installed, desired enabled.
- Drift: `repository.eengert` 1.0.0 uninstalled through the Test.app Kodi UI (one Uninstall, one Yes). Missing state proven in the UI and on the host (installed count 40 → 39, only that add-on removed).
- Repair: Update / Repair → Check for Changes showed only "Install repository.eengert 1.0.0". Apply confirmed once; result "Build applied and verified."
- Verification: `repository.eengert` 1.0.0 enabled after the repair; restored `addon.xml` SHA-256 `15c1410f…` equals the saved ZIP member; second Check for Changes returned `Current / Healthy`.
- Evidence: `.qualification-evidence/update-repair-missing-exact-addon-20261008T211207Z/` (gitignored), with `runtime-qualification-report.md` and `EVIDENCE_SHA256.txt`.
- Boundaries: no push, no `matrix`, no Agent Handoff operation, no product or source commit, no normal Kodi/profile/device access, no direct JSON-RPC, no Computer Control, no port 9090, no helper `run`/`quit`/`stage`.
- Next: no further action from this task. Product next steps are a separate decision by Eric or ChatGPT.
- Usage: last row of `.agent/USAGE_HISTORY.md`.
