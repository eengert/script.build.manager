# Current Task — D-028 builtin authority correction

- Implementation COMPLETE; STOP for independent review, before restaging.
- Product 233bf87a245010de7830395789117bc81478c1ac; baseline 3ad2ffc (guidance-only descendant of requested 8480a25).
- 24 new regressions / 235 subsystem PASS; full 3430 vs 3406 with only two matching baseline failures.
- Actual bundled Python API 3.0.1 / ABI 3.0.0 authority proven through supported APIs and pinned XML.
- Test.app stopped; accepted 9a77068 still staged; public fixtures/durable census unchanged.
- Next: independent correction-delta review, then separately authorized runtime admission.
- Evidence/cleanup: .qualification-evidence/d028-builtin-authority/RUN-SUMMARY.md.

---

# Preserved earlier task record

# Current Task

- Task: WF-testapp-launch-background-correction.
- State: COMPLETE; guidance-only commit `3ad2ffc`.
- Worktree/branch: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`, `agent/codex`.
- Files: `AGENTS.md`, `.orchestrator/WORKFLOW.md`; exact Test.app launch/focus policy added.
- Validation: `git diff --check` passed; no tests run for this documentation-only change.
- Boundaries: no Test.app/device interaction, product code, matrix/Claude worktree access, or push.
- Next: no follow-up for this guidance task. D-028 runtime admission remains stopped pending separately authorized builtin-authority correction; prior evidence remains in `.agent/HANDOFF.md` and `.qualification-evidence/d028-runtime-9a77068/RUN-SUMMARY.md`.
- Cleanup: no task-created scratch; preserved prior D-028 evidence.
