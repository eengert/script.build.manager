# Item 8 unattended offline queue — Tasks 2–8

October 12, 2026. COMPLETE within this finite offline scope; Item 8 remains OPEN.
Starting/ending HEAD: `38c9910d936c6b9d8bc2357ecbe188c12478ebcc`, `agent/codex`.
Task 1 was already committed by the supervisor and was not repeated. No new
commits were attempted; separate local commits are deferred to the supervisor.
The four existing dirty `.agent` files were preserved without edits by this run.
This document is the Task 8 handoff, avoiding changes to that prior bookkeeping.

## Exact future commit groups

All paths below are repository-relative. Each group is disjoint.

| Task | Status | Added/modified files | Validation | Suggested separate commit |
| --- | --- | --- | --- | --- |
| 2 | COMPLETE | Add `resources/lib/create_owner_observation.py`, `tests/test_create_owner_observation.py` | 6 tests PASS | `Item 8: add standalone read-only owner observation` |
| 3 | COMPLETE | Add `tests/test_create_startup_isolation.py` | 4 new + 9 existing observer tests PASS | `Item 8: verify Create startup namespace isolation offline` |
| 4 | COMPLETE | Add `resources/lib/ui/create_recovery_view.py`, `tests/test_create_recovery_view.py`; modify `resources/language/resource.language.en_gb/strings.po` | 5 final presentation tests PASS; 21 existing assessor tests PASS | `Item 8: add non-actionable Create recovery presentation` |
| 5 | COMPLETE | Add `tests/test_create_admission_matrix.py` | 3 new + 101 existing lifecycle tests PASS | `Item 8: expand Create hold admission regression matrix` |
| 6 | SKIPPED | None | Existing workflow/capture 162 tests PASS | None; existing coverage adequate for named priorities |
| 7 | COMPLETE | Add `docs/ITEM8_PACKAGE_READINESS_AUDIT.md` | Metadata/assets/settings checks PASS; icon 512×512, approved digest; 288 unique localization IDs | `Item 8: record source package readiness audit` |
| 8 | COMPLETE | Add `docs/ITEM8_OFFLINE_QUEUE_HANDOFF.md` | Combined focused 311 tests PASS; exact-baseline comparisons below | `Item 8: record offline queue qualification handoff` |

New code/test/doc candidates remain UNACCEPTED pending independent review.
Task 4 consumes a standalone typed presentation contract (stdlib imports only),
not lifecycle objects. Its caller must supply trusted supported-owner identity
and strict enabled/original-enabled observations. Manual-disable guidance requires
all evidence of the specific unexpected-enabled condition. No reason string alone
can authorize it. No callbacks, action buttons or production wiring exist.
Task 2 accepts only bounded numeric dotted versions; unsupported version syntax is
UNKNOWN. Matching versions do not prove package provenance or enablement history.

## Evidence and remaining problems

- Accepted offline backend: P5, strict D2 Option A, and Stage 2B1A including B3,
  per current supervisor update and the committed Task 1 document. B3 reviewed
  commit is `5fb47fcf7dc9f0a98a55dc65747bb223a948fa17`.
- New offline evidence: 18 new test methods plus existing related suites, final
  combined command below: **311 PASS**. Snapshot/classification tests do not run
  production startup or recovery. Admission tests use synthetic profiles and
  injected/suppressed runtime capabilities; no real APIs execute.
- Demonstrated baseline failures: candidate and disposable exact-HEAD source
  export both reproduce `NativeFoundationTests.test_no_engine_imports` at existing
  `ui/plan_view.py`, and `tests.test_plan.ImportPolicy.test_the_presentation_modules_import_no_engine`
  for the unchanged presentation import set including `typing`. Two failures in
  each identical six-test probe; its other four injected keychain client tests PASS.
- Demonstrated baseline runner/fixture problem: targeted discovery of
  `test_bm_test_app_keychain.py` runs 31 tests in both candidate and exact baseline;
  four identical TypeError error reports across two SharedMinimumCredentialPolicy
  methods (one minimum-item test and three short-item subtests). Error text is
  `TypeError: expected string or bytes-like object`. This is synthetic fixture
  initialization/discovery behavior, not real keychain evidence or a product change.
- No new regression or permission restriction reproduced in this queue. Initial
  new-test failures were invalid RESTORING fixture construction and an overly
  narrow expected exception type for fail-closed guards; reconciled without any
  production authority changes. No full-suite rerun or unrelated fixes.
- Untested runtime dependencies: trusted positive idle/competition evidence
  covering in-flight work, coordinated admission ownership, operation-bound full
  Kodi-process restart proof, narrowly owned restoration under retained guards,
  reviewed Create lifecycle composition and explicitly confirmed recovery wiring.
- Actual beta evidence: none added by this queue. Preserve earlier accepted
  backend/runtime records; full exact-candidate frontend qualification remains open.
- Operator authorization still required for named runtime operations, repository
  publication/install/update qualification and integration. No such work is implied
  by these offline candidates. Do not mark Item 8 complete.

Final related command:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_create_owner_observation tests.test_create_startup_isolation tests.test_create_recovery_view tests.test_create_admission_matrix tests.test_create_status tests.test_capture_recovery_assessor tests.test_capture_lifecycle tests.test_create_workflow tests.test_create_capture -q
```

## Safety, usage, cleanup and next step

No global safety stop occurred after resumption. All task changes are disjoint.
No repository Git metadata writes, staging/commit attempts, permission changes,
push/release/merge, Agent Handoff, ai-supervisor, device/profile access, Test.app
operation, live Kodi RPC, owner mutation, installation or recovery execution.
Synthetic fixture effects are confined to temporary paths and injected backends.
Protected B3, lifecycle/P5/D2, startup/service and installer source stayed unchanged.
No private backend exception strings reach observation/presentation output.
Tracked diff checks and new-file syntax/whitespace checks PASS.

Usage: Codex / GPT-6 session identity; exact model tier and effort unavailable.
No current reliable remaining-usage reading was established; start/end/delta are
unavailable. No inference-producing usage command or quota polling was used.

Cleanup: temporary baseline exports and all disposable test fixtures self-cleaned;
bytecode writes disabled. No task logs/screenshots retained. New candidates and the
two reports intentionally remain for review/commit; prior qualification evidence
and four dirty `.agent` histories remain preserved.

Smallest next step: supervisor reviews exact groups, obtains independent review of
new code/tests (especially owner observation and advisory presentation), then makes
separate local commits. No Git permission repair is needed in this Codex session.
Further runtime contract implementation needs a new bounded authorization.
