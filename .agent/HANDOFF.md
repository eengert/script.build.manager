# Handoff — Item 8 evidence consolidation (read-only audit)

- State: complete. Verdict: **ITEM 8 EVIDENCE CONSOLIDATION: LIVE GAP REMAINS** (a recommendation to ChatGPT and Eric, not acceptance). Item 8 stays OPEN. Eengert Repository publication stays blocked and unauthorized.
- Start: `agent/claude` at `286aa709e17b5d8b5b743a2f45a42880493e1172`, worktree clean, ahead of origin by 22. Agent Handoff not run.
- Done:
  - Verified by ancestry that the Create (`9ee7f86`), Install (`37258ad`), Update/Repair (`53f2219`) and backend (`4a02b83`) candidates are all ancestors of `a2b1ffc`.
  - Verified that `53f2219` → `a2b1ffc` changes only `addon.xml` and `resources/images/icon.png` in the distributable paths. Only test `.py` files changed in that range.
  - Mapped each accepted live result to its exact candidate and to the implementing paths. Decided each row TRANSFERABLE, NOT TRANSFERABLE, DIRECT or MISSING (22 requirements, 28 sub-rows).
  - Wrote the minimal remaining live scope: Phase A (restart, resume, several builds, private rendering on the exact candidate) and Phase B (blocked presentation).
- Files and commits:
  - Evidence (gitignored): `.qualification-evidence/item8-evidence-consolidation-20261008T232026Z/` with `item8-evidence-consolidation-report.md`, outputs `01`–`06`, and `tools-used/item8_audit.py`.
  - Guidance-only: `.orchestrator/HANDOFF.md`, commit `0f026ed`.
  - This bookkeeping commit: `.agent/HANDOFF.md`, `.agent/CURRENT_TASK.md`, `.agent/USAGE_HISTORY.md` (one row).
- Tests: none run. The task was read-only and changed no product code.
- Live-proven in this task: nothing new. No Test.app launch or staging.
- Not done: no Test.app, Kodi, profile, device, push, release, Agent Handoff, publication, or product change.
- Risks and human decisions:
  1. Phase A needs a Red Light structured private resource to drive the restart. Eric or ChatGPT must authorize its use in Test.app, and private values must never be rendered.
  2. Whether Repository Current / Skip decisions and Update's Choose Different Revision are required for Item 8 acceptance, or deferrable.
  3. Build Status does not name the selected build. The design asks for associated and selected builds to be shown distinctly. Decide whether to fix that before acceptance.
  4. BM-UI-001 evidence is blob-identical to `404f080` but was run from an uncommitted worktree, so it is not Git-bound.
- Usage: start reading not captured for this task. End reading 5-hour 68% used, weekly 43% used. Session reported `claude-haiku-5-5` at effort `xhigh`.
- Smallest next step: one bounded Test.app task with two ordered phases, A and B (report section 7). It needs the decisions above first.
