# Handoff — BM-UI-REPO-PREP

## Result and provenance

- Starting branch/worktree: `agent/codex`, requested Codex endpoint.
- Starting HEAD: `ca57a6b520beaec2b85eabfb009c1549ec363c28`; clean.
- Verified accepted bridge `dc7f256` remained the product base; subsequent starting commits were `.agent/**` only.
- Product candidate: `0c16688d8c5891c907a436c6cf48eb8e1e1f98e4`.
- Removes the demonstrated pre-Apply Repository Current review blocker to beta exit item 8. This is backend evidence only.

## Done

- Added `resources/lib/repository_preparation.py`: typed serializable preparation identity, safe result codes, captured-repository ZIP authority, bounded index/package acquisition, dependency/private/hold preflight, immutable ArtifactStore import. No Kodi owners, transactions, updater mutation or selection changes.
- Extended `resources/lib/plan.py`: separate prepared input, exact source/profile/build/policy/artifact binding, actual resolved version, dependency reconstruction, fresh ReviewIdentity and fail-closed validate. Preview remains read-only.
- Extended `resources/lib/frozen_install.py`: library Apply requires prepared Repository Current records and consumes the approved ZIP without re-fetching current. Preflight rereads binding and dependency compatibility before transaction creation. Existing frozen/BM-020 owners retain records/fingerprints/library identity through restart.
- Added 25 tests in `tests/test_repository_preparation.py` and integration/API notes in `docs/REPOSITORY_PREPARATION.md`.

## Validation

- Baseline Plan: 102 PASS; confirms chosen/unprepared Repository Current remains RESOLUTION_REQUIRED with unknown version and no review.
- Related suites: `python3 -m unittest tests.test_repository_preparation tests.test_plan tests.test_frozen_resolution tests.test_frozen_install tests.test_library_install tests.test_build_manager tests.test_transaction tests.test_repository tests.test_addon_manager` — 588 PASS.
- Final full suite: `python3 -m unittest discover` — 2995 PASS, 144.893s, permitted host execution with disposable process/loopback fixtures.
- Initial `discover -s tests` run: 2995 executed, 8 failures/15 errors from sandbox-denied process/loopback checks and duplicate-module fixture imports. Unchanged-source rerun used package-aware discovery and permitted execution; no tests weakened.
- In-memory parse checks and `git diff --check` PASS.
- Tests prove actual prepare -> review -> validate -> Apply -> existing restart/resume, remote version changes ignored, mismatches/corruption rejected before mutation, incompatible dependency/private/held cases blocked, no false review token or preparation lifecycle mutation. All evidence is offline; no live-proven claim.

## Limits / not done

- Supports one unambiguous plain repository directory with ZIP datadir. Multiple/version-conditioned directories, compressed/ambiguous indexes and unsafe metadata fail closed; no repository substitution.
- Preserves the existing Repository Current restriction when activation holds exist.
- Preparation persists only immutable artifacts; callers can serialize the typed identity if needed. Partial successful imports may remain after a later failure; they are not approval/transaction state.
- No frontend/native-dialog changes, Test.app/runtime qualification, real Kodi/profile/device access, private platform store access, push, matrix integration, packaging, publication or release.

## Next / human input

- STOP. Independent backend review requires a separately assigned task. Do not resume frontend implementation or begin review from this handoff.
- No human input needed to complete this backend task. Later unsupported-metadata extensions or runtime actions require their own scope.
- Usage: only an end desktop allowance reading was available/captured (65% five-hour and 83% weekly remaining); start/delta unknown. Exact model variant and effort were not exposed, so recorded unavailable without inferred labels.
