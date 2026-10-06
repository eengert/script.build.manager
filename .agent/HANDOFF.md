# BM-UI-003C Persistence Correction — PASS offline; STOP

## Identity and outcome
- Authorized worktree/branch: script.build.manager-codex / agent/codex.
- Clean starting HEAD: 212618a35d1685b4a581befb6c7f00415578ffd7.
- Corrected product: db8ffe803a3e5350407f70f7618fc4c494dc3d17.
- Correction commit: 9ee7f86fd5c2e3db6e53b00f7f3e6ee103886c7b.
- Advances beta exit item 8 by removing the three demonstrated Create persistence blockers. No qualification claim.

## Pre-fix evidence (disposable real capture/library/store, before source edits)
- A: registered exact public bundle with controlled identical timestamp, removed only its overlay, changed private setting, retried: 32736 success and replacement persisted.
- B: registration published its registry, then injected loss of builds/ and raised: registered_bundle returned None, terminal 32734, newly created private overlay deleted despite indexed authority.
- C: fault-injected COMPLETE with structurally valid undeclared private setting: 32736 success and undeclared setting persisted.
- One B fixture initially used Path arithmetic on a string root; corrected the fixture before obtaining the above reproduction. No private values emitted.

## Changes
- resources/lib/create_workflow.py: independent PreparedPublicBundle/manifest/resolver/private validation against confirmed request and exact public frozen software fingerprint before store/staging/select; exact-public check inside existing private Create lock; existing authority requires matching existing private content.
- resources/lib/private_overlay.py: read-only require_exact; absent/different conflict, unsafe/malformed/unreadable fail closed, no replacement.
- resources/lib/build_library.py: narrowed missing-root handling; only valid readable registry/key absence returns None; missing registry at present root and all indexed-content errors fail closed.
- resources/language/resource.language.en_gb/strings.po: 32734 says existing content was preserved and permits choosing next version if this version exists.
- tests/test_create_workflow.py and tests/test_build_library.py: 38 added regressions; retained prior accepted tests. Recovery-read fault now follows the new prepublication authority query.
- docs/CREATE_WORKFLOW.md and docs/BUILD_LIBRARY.md: exact-private requirement, COMPLETE validation, absence/ambiguity, rollback and orphan limitations.

## Validation
- Focused: 634 PASS (create_workflow, build_library, private_overlay, create_capture, ui_foundation, private_resource, config, frozen, frozen_resolution, frozen_install, frozen_registry_readiness).
- Full suite ONCE: python3 -m unittest discover tests, 2903 PASS in 127.419s. Permitted disposable subprocess/loopback fixtures; no live target.
- git diff --check PASS. All 8 product/test/documentation files SHA-256 matched their pre-full-run snapshots afterward; no subsequent changes to them.
- Exact public/private match reuses entry without registration/private inode rewrite. Missing, different, malformed, FIFO and injected unreadable overlays fail closed. Matching orphan continues; differing orphan conflicts.
- Missing root/key prove absence; missing builds/envelope, corrupt content, digest/metadata disagreement, permission error and missing registry fail closed. Actual indexed-missing-builds and registry-loss recovery preserve private data.
- Private file/directory fsync, entry publication, post-registry error, recovery read, rollback unlink/fsync, selection and concurrent same-overlay writer coverage PASS. Losing concurrent writer fails safely; later exact retry succeeds.
- Undeclared setting/resource, missing required setting/resource, wrong ID/type/source, altered public software identity/declarations/ref/version: zero workflow persistence. Capture artifact acquisition retains its existing behavior.
- Privacy sentinels absent from safe dictionaries/repr, terminals/native dialogs, logs, public manifest/config/frozen bundle, staging/envelopes and safe conflict/recovery results.
- Disposable configuration mutation recorder stayed empty; existing native/busy/public-only/incomplete/failed behavior PASS. No Kodi managed-state operations added.

## Limits / not done
- Stores remain separate: crash after private publication can leave a non-authoritative orphan/staging inode; ambiguous authority may intentionally retain private state. No repair/delete API added.
- External deletion can damage a published build; Create now refuses silent reconstruction. Fresh timestamps may conflict at same version.
- No independent approval or live UX qualification claimed. No push, publication, matrix merge, Test.app staging/launch, normal Kodi/profile or household device access/mutation. No Install/Update/Repair/G6/version/icon work.
- Only local correction and bookkeeping commits. Model observed as GPT-6; exact tier/effort unavailable. Usage start/end/delta unavailable per AGENTS.md; no estimated telemetry.

## Next step / human input
Independent correction-delta review of 212618a35d1685b4a581befb6c7f00415578ffd7..9ee7f86fd5c2e3db6e53b00f7f3e6ee103886c7b, limited to A/B/C and 32734. Eric/ChatGPT supplies that bounded review task. Stop here; do not begin Test.app qualification.
