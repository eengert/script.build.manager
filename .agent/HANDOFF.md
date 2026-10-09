# Handoff — Red Light quiet-WAL production read correction

- State: product correction committed for independent review: `e5a18a5` ("Read Red Light settings through a stable private copy"), local on `agent/claude`, not pushed. **Not claimed closed.** Independent review is required before the defect is accepted as closed. Item 8 and restart/resume stay OPEN. Publication stays unauthorized.
- Start: `agent/claude` at `fb94dde`, worktree clean. Product source identical to candidate `7b625cc`. Test.app `not_running`, no Kodi process.
- Defect (reproduced first, on the affected runtime): on SQLite 3.51.0 (Apple Python 3.9.6), a read-only open of a WAL database whose `-wal` file is absent fails. A cleanly closed, populated Red Light `settings.db` therefore failed closed in production verify, existing-resource initialize, the non-empty row check, and the capture snapshot.
- Fix: one shared production read path over a private stable copy of the store's committed bytes (main file plus `-wal`, never `-shm`), with the existing two-read identity checks and an empty `-wal` placeholder when none exists. The copy is opened read-only through normal SQLite WAL reading, so committed frames are read. The store is never opened or written by production reads. Status/inspect keeps its immutable, fail-closed probe. The unquoted read-only URI and the unused `_open_read_only` helper are removed.
- Tests: `QuietWalReadCompatibilityTests` (10 synthetic tests). On the parent `fb94dde` product they fail 9 of 10 (Status passes), as expected. They pass on `/usr/bin/python3` 3.9.6/3.51.0, `python3` 3.10.9/3.51.0, and `/usr/local/bin/python3` 3.14.5/3.53.1.
- Focused modules pass on all three runtimes (42, 57, 102, 48, 16, 19 tests).
- Full suite: dev Python candidate 3234 vs parent 3224, with identical failing and erroring names (2 known import-policy failures, 4 known keychain errors). Apple Python: identical names to the parent, which also has 2 interpreter-version errors (`assertNoLogs` and `staticmethod` callability, 3.10+), so they predate this change.
- Not done: no Test.app staging or launch, no live Red Light database or private overlay access, no PIL sourcing, no push, no release, no publication, no Agent Handoff.
- Risks and follow-ups:
  1. Independent review of `e5a18a5` is required. Review the quiet-WAL semantics, the private-copy path, and the capture seam change in `tests/test_create_capture.py`.
  2. Production verify now writes a private copy to the platform temp directory. That is 0700 and removed on exit, the same requirement capture already has.
  3. Still open from the stop: fixture E needs `script.module.pil` 1.1.7, which is absent from Test.app, the public store, and the local repository. That decision is unchanged.
- Usage: start unknown (not captured for this task; previous task ended at 5-hour 19%, weekly 56%). End 5-hour 32%, weekly 58%. Session reported `claude-haiku-5-5` at effort `xhigh`.
- Evidence (gitignored): `.qualification-evidence/redlight-quiet-wal-correction-20261009/`.
- Smallest next step: independent review of `e5a18a5`. Then decide the `script.module.pil` path for the Item 8 fixture.
