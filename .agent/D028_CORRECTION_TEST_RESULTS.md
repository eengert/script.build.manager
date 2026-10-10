# D-028 review corrections — offline implementation checkpoint

- Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex; branch `agent/codex`.
- Clean starting HEAD: `23a426809c93bb2f914bc047343acfe59e4628a0`; reviewed product: `bddbe6f511caaa54914d9cbca8100653fe4938ec`.
- Correction product: `06bde801502395b6d0738e8757cf2b2c331b5314`. Independent correction-delta review remains pending.
- Baseline-to-start differences were `.agent/**` only; no product drift.
- Outcome: corrections to beta frozen-install truth, safe configuration, final validation and restart/reconciliation blockers. No beta or live acceptance claimed.

## Findings corrected and primary regression proofs

1. Runtime root authority remains pinned across reads; root replacement and symlink escape fail closed (`test_runtime_rejects_replaced_root_after_first_read`, `test_runtime_rejects_symlink_escape_after_first_read`).
2. Required target metadata edges contribute graph ordering/cycle validation; managed children cannot be missing, skipped or left disabled (`test_target_mandatory_child_is_installed_before_consuming_managed_parent`, `test_target_edges_cannot_create_cycle_through_managed_node`, `test_target_mandatory_child_cannot_be_left_disabled`, preserved missing-child tests).
3. Platform mutation preflight covers public/private settings, files, structured resources, software state, all public-bundle layers/packages, reconciliation and runtime execution (`test_frozen_install_rejects_platform_configuration_before_runner_or_mutation`, `test_library_rejects_platform_setting_file_and_layer_targets`, `test_reconciliation_rejects_platform_addon_state_before_execution`, configuration ownership regression).
4. Required platform verification blocks Plan and Healthy Repair when evidence is missing (`test_missing_platform_requirement_blocks_plan_and_no_changes`, `test_missing_platform_requirement_never_reports_healthy_repair`).
5. Dependency-free trusted platform add-ons capture and install as requirements (`test_zero_dependencies_capture_and_install`).
6. Optional minima are not mandatory; absent optional-only platform nodes do not block; optional closure flags propagate (`test_optional_incoming_minimum_is_not_mandatory`, `test_optional_only_platform_node_can_be_missing`).
7. Verified target versions/edges flow through repository preparation, Plan freshness and restart restoration. A mandatory repository edge can promote its previously optional source node (`RepositoryPlatformCorrections`, `RepositoryOptionalPlatformCorrections`, `test_verified_platform_version_binds_review_and_change_is_stale`).
8. Shared resolved-software fingerprint, identity binding and prepared binding reject platform artifact-resolution records (`test_platform_record_rejected_by_shared_fingerprint`, `test_identity_binding_rejects_platform_artifact_record`).

## Validation

- Final correction regression module: **70 tests, PASS**. It contains 20 new test methods, inherited compatibility cases, and two additional repository variants with an optional source node.
- Reproduction on archived exact `bddbe6f511caaa54914d9cbca8100653fe4938ec`: 70 tests, 21 failing assertions and 3 errors. Two errors are the original restart-restoration unverified-platform exception; the third imports the newly added helper absent from the baseline and is supplementary, not a claimed original defect. Primary existing-API regressions reproduce all eight findings.
- Related subsystem run: **541 tests**, only the existing Plan import-policy failure and sandbox-denied disposable Unix socket error. The final permitted full run covers these same subsystems and has no socket error.
- Exact baseline full suite: **3318 tests; 2 failures; 5 compiler-related skips**. Supplementary unchanged-baseline fake-process class: **6 tests PASS**, resolving those skips.
- Final permitted candidate full suite: **3388 tests; 2 failures; 0 errors; 0 skips**.
- Failure identities compared, not counts: identical to baseline:
  - `tests.test_plan.ImportPolicy.test_the_presentation_modules_import_no_engine`
  - `tests.test_ui_foundation.NativeFoundationTests.test_no_engine_imports`
- Both failures are the unchanged UI import-policy checks. Their assertion causes also match the baseline. No correction regression or new full-suite failure remains.
- Schema-v1 serialization/fingerprint, D-003 exact artifact, capture authority, frozen install/resolution, library install, configuration and restart/repair tests remain passing apart from those baseline failures.
- `git diff --check`: PASS.
- Full-suite sandbox process/loopback/socket failures were reproduced on both trees; permitted execution removed them. No source was weakened for the environment.
- Archive adapter changes only the package harness's Git tracked-file inventory to `git ls-tree bddbe6f`; no baseline product/test file was changed. New regression tests were copied into the archive only for RED reproduction.

## Boundaries and next step

No real Test.app staging/launch, private-data or keychain access, PIL payload construction, normal Kodi/device access, agent switch, matrix merge, push, release, publication, or history rewrite. Runtime claims are unit/disposable-fixture proofs only.

**STOP after implementation.** Claude independently reviews `23a4268..06bde801502395b6d0738e8757cf2b2c331b5314` (product delta also equals `bddbe6f..06bde801502395b6d0738e8757cf2b2c331b5314` outside `.agent/**`). No review PASS claimed; Item 8 and live qualification remain open.

## Cleanup

Task-owned archived source, raw logs, harness and transient output files removed after retaining checksummed evidence. Only this minimum compressed validation evidence, its adapter/summary/checksums, and tracked `.agent/**` bookkeeping remain intentionally. Pre-existing evidence and 133 older repository cache files are preserved; this task created no repository bytecode caches.

Evidence: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/d028-review-corrections-20261009-06bde80`.
