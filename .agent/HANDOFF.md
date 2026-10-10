# D-028 builtin authority P1 correction — STOP for independent re-review

Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex
Branch: agent/codex; verified starting HEAD ebdd221b77e1d37a541c3ad24074fdfe3b3067db.
Correction commit: 1feea9f (only frozen.py, frozen_install.py, test_d028_builtin_authority.py).
Admission: fixes demonstrated D-028 runtime-admission blockers to beta exit item 8; no beta closure claimed.

## Corrections
- Filesystem: hold original builtin directory and XML descriptors through verification;
  bind safe-reader bytes to the held XML object; reject changed device/inode/mode/size/
  mtime/ctime, reacquire current pinned application root and no-follow builtin directory,
  and recheck current XML binding and pinned home-shadow absence before success.
  Equal-byte replacement cannot substitute for filesystem identity.
- Registry: after parsing/checking XML identity/version/ABI, construct a fresh
  xbmcaddon.Addon("xbmc.python"). Recheck exact id/version/path/type against the already
  validated evidence and current boolean available/enabled state. Do this while the
  filesystem descriptors are held, before final filesystem admission checks.
  Unavailable fresh authority or disagreement returns false.

## Reproduction / validation
- Test-first on unchanged product: all six new adversarial tests failed as assertions:
  root replacement, root symlink substitution, atomic ABI4 XML replacement, equal-byte
  XML replacement, snapshot-handle registry 3.0.1->3.0.2, and the registry substitution
  through verify_platform_requirements. Each previously admitted stale authority.
- After correction: all six reject within the same attempt. Snapshot fake copies fields
  at construction to model retained pAddon, rather than exposing a shared live dictionary.
- Added three further tests: fresh identity/type/path/enabled disagreement; unavailable
  fresh constructor; XML substitution during fresh constructor. All pass.
- All original 24 builtin regressions preserved: module now 33 PASS.
- Requested 235 focused tests + nine = 244 PASS, plus registry readiness/resolution 43:
  combined 287 PASS (5.603s). Command: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest
  tests.test_d028_builtin_authority tests.test_d028_corrections
  tests.test_d028_target_closure tests.test_frozen tests.test_frozen_install
  tests.test_frozen_registry_readiness tests.test_frozen_resolution.
- Final host full suite: 3447 run, 3445 PASS, two failures, zero errors/skips (163.610s).
  Command: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t .
  Same documented baseline failures: tests.test_plan.ImportPolicy.test_the_presentation_modules_import_no_engine
  and tests.test_ui_foundation.NativeFoundationTests.test_no_engine_imports.
  Both still concern unchanged resources/lib/ui/plan_view.py; prior baseline logs preserved.
- Sandbox full run: same two failures plus eight failure cases/two errors, all extra
  cases caused by process_listing_failed in disposable real-process tests. Unchanged
  host rerun resolves every environment failure. An earlier preliminary full run was
  terminated after the final held-descriptor regular-file/size guard was added;
  final full validation uses unchanged final correction source.
- git diff --check PASS. Product diff only the two admitted methods plus stat import;
  no D-003 artifact, schema-v1/fingerprint, ordinary metadata-read, or other-platform
  implementation changed. Prior closure/protection tests remain intact and pass.

## Boundaries / next step
Offline fixtures only. No normal Kodi/profile access, Test.app launch/stage/install/
restart/alteration, device interaction, Agent Handoff, integration, push, release,
history rewrite, or runtime acceptance. Other builtin interfaces remain fail closed.
Smallest next step: independent correction-delta review of ebdd221..1feea9f.
No additional human input needed for that review. Runtime admission requires a later
explicit task after independent acceptance. STOP here.

## Cleanup
Removed temporary /private/tmp full logs after retaining both validation logs with
SHA256SUMS in .qualification-evidence/d028-builtin-authority-rereview/.
Removed the interrupted run's exact disposable fixture/test directories
bm-test-app-fixture-uhmnq_ja and bm-test-app-test-e80_x2yg after ancestor validation.
Completed suites clean their own fixtures; bytecode disabled for all test runs.
Prior qualification evidence and older uncertain-ownership scratch were preserved.
No screenshots or new runtime/profile artifacts. Retained non-source evidence: two
full logs and their checksum file, plus required .agent bookkeeping.
