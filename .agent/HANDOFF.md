# Current Handoff - BM-023A stage action pinned to reviewed adapter 0.0.14 (2026-09-29; lease dd9d527e-38c4-44ac-99e2-7ee53e3fd5fe)

**Result:** `PINNED_TO_EXACT_REVIEWED_0_0_14_SOURCE; OFFLINE_TESTED; STAGING_NOT_RUN`. Work ID `53dba719-2837-4874-8412-3f8f1e3fa55b`. Agent: Codex (`GPT-6` runtime label; effort unavailable). Usage readings unavailable per `AGENTS.md`.

- In the authorized `ai-supervisor-bm023a-actions` checkout, the fixed `bm023a-stage-adapter` action now builds only from source commit `bdfb916976a8b141b8925a328ef8b1af21da1fef`. It verifies the adjacent tracking commit `733ddbf911e1120e5e359cc2482eb714ca26d195`, review checkpoint `01825057-69fc-45ac-8ddc-910ee126d3a6`, snapshot `d1ee22d79e13e12495a85f931a1c95483e414addaddae74e6c349444e650edcd`, exact three-file source diff, and adapter version 0.0.14. It archives the full pinned SHA, disables Git replace refs during source reads, and isolates `tools` module imports so a cached module cannot redirect the builder.
- The source-work trailer on the reviewed Git pair says `bd30d7e0-8a56-4839-bb2e-cf9cc228e6ce`, differing from the prior adapter task ID `930ce877-b902-4c0f-92bf-5380acfac610`. The action binds to the exact source/tracking commit pair and matching review/snapshot trailers in Git; it does not infer source from branch HEAD. This attribution difference is recorded for supervisor review.
- Checks: focused upgrade tests **39/39**; seven pin-specific cases **7/7**; read-only validation against the supervised checkout resolved the pinned commit and loaded builder version 0.0.14; `git diff --check` passed. Full action suite ran **436** tests with **3 failures and 41 errors**, in unrelated process-recovery/soak/configured-Codex-path checks and loopback tests denied by the offline sandbox. No failure was in the changed action module.
- Not done: no staging action, Test.app, Kodi/profile/device access, host validation action, network operation, or product-source edit. The action diff remains uncommitted in the authorized secondary root.
- Smallest next step: supervisor review of the action diff and source-work attribution, then a separate directive before staging. No user input is required.

---

# Review Required - BM-023A 0.0.14 checkpoint source mismatch (2026-09-29; lease 907ebfdf-a332-48da-aaa0-acc7f329ce3d)

**Result:** `REVIEW_REQUIRED_CHECKPOINT_NOT_ARMED_FOR_930CE877`. Work ID `d9944558-57b0-4ea2-b87f-e2ca0a11d6e4`. Agent: codex (`gpt-6-luna`, `xhigh`). Usage start snapshot: 5h 87% and 7d 66% remaining from supervisor app-server state; end reading unavailable.

- Independently reviewed the committed 0.0.14 diff at `bdfb916` and confirmed the checkout was clean before this handoff. The only product files in that snapshot are `tools/bm023a_adapter_support.py`, `tools/bm023a_adapter/addon.xml.in`, and `tests/test_bm023a_adapter.py`. The retry exception maps to the fixed `retry_invocation_failed` category with exception chaining suppressed; the regression test checks sentinel/path redaction and preserves the held transaction and activation hold. Version markers are 0.0.14.
- The source handoff records focused tests **80/80**, full offline suite **1927/1927**, and `git diff --check` passing. I did not rerun them. No adapter staging, Test.app, Kodi/profile/device access, network, retry, or product change occurred.
- Checkpoint handling is internally inconsistent: HEAD's existing `AI-Supervisor-Source-Work` trailer names `bd30d7e0-8a56-4839-bb2e-cf9cc228e6ce`, while this directive names `930ce877-b902-4c0f-92bf-5380acfac610`. The current supervisor state has no `review_checkpoint`, an empty queue, and `armed_checkpoint=null`. I did not fabricate or commit a checkpoint for the mismatched source work.
- Smallest next step: supervisor should arm/reissue the reviewed-work checkpoint bound to source work `930ce877-b902-4c0f-92bf-5380acfac610` (or correct the source-work attribution). No user input is required.

---

# Current Handoff - BM-023A retry exception diagnostics (2026-09-29; lease ea05f10f-26bc-437b-b1b3-45160154cd47)

**Result:** `OFFLINE_RETRY_DIAGNOSTIC_ADDED_TESTED; REVIEW_REQUIRED_BEFORE_STAGING`. Work ID `930ce877-b902-4c0f-92bf-5380acfac610`. Agent: codex (`gpt-6-luna`, `xhigh`). Usage readings unavailable per `AGENTS.md`.

- Offline source review found a plausible historical explanation for the earlier `INVOKE_RETRY` failure: a cached production module could retain a retry method from stale source. The failed run retained no module-cache state or traceback, so that explanation cannot be confirmed. Adapter 0.0.13 now guards module cache and installed source identity before import; its retry call arguments match the current method signature. The product retry method converts expected recovery failures into structured results, while an exception escaping the invocation remains source-unexplained.
- The retry invocation catch now emits the fixed allowlisted category `retry_invocation_failed`. No exception text, path, credential, or private value is added. Adapter source and package template are versioned 0.0.14. The regression test injects a private sentinel exception, confirms it is absent from serialized diagnostics, and verifies exactly one call with the original held transaction and unreleased activation hold unchanged.
- Checks: focused `tests.test_bm023a_adapter` **80/80**; full offline suite **1927/1927**; `git diff --check` clean. Changes are limited to `tools/bm023a_adapter_support.py`, `tools/bm023a_adapter/addon.xml.in`, and `tests/test_bm023a_adapter.py` plus tracking metadata.
- Not done: no staging, Test.app, Kodi/profile/device access, retry, network, or commit. Staged Test.app adapter remains 0.0.13; 0.0.14 is only an offline candidate.
- Smallest next step: independent review of the exact diff, then a separate directive for any staging or retry. No user input is required.

---

# Current Handoff - BM-023A retained artifact set validated (2026-09-29; lease 1ee2482c-8fb5-40a0-8a7e-037cf45879a1)

**Result:** `ARTIFACT_SET_COMPLETE_NO_REACQUISITION_REQUIRED`. Work ID `4fb39036-682f-4427-80d5-bdcbe9b1db52`. Agent: codex (`gpt-6-luna`, `xhigh`). Usage readings unavailable per `AGENTS.md`.

- The retained manifest parses with fingerprint `8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`. Its retained artifact store contained all 30 declared ZIPs when inspected. All 30 passed exact SHA-256 and size checks, `validate_addon_zip` ID/version validation, and stored metadata identity checks. This includes the four artifacts identified in the earlier scan; none were modified.
- No download or import was needed. The earlier handoff recorded the store as empty; this run observed the exact artifact set already present. No recovery/retry, Test.app, Kodi profile, or device was accessed.
- Full offline suite: **1926/1926 passed**. No code or tests changed. No product commit.
- Smallest next step: supervisor may issue a separate directive for the supported held-quiescence retry, if still needed. No user input required.

---

# Review Required - BM-023A retained-artifact repopulation: no route inside the authorized envelope (2026-09-29; lease 64a5f73e-857a-4885-be47-951355af7e40)

**Result:** `REVIEW_REQUIRED_NO_ARTIFACT_BYTE_SOURCE`. Work ID `11eaf317-8480-4c8a-9218-d28fc1de446e`. Agent: claude. Usage readings unavailable. No code, test or product file was changed; only this note.

## What exists
- The retained manifest survives at `/private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json`. `FrozenBuildManifest.from_json` parses it, and `fingerprint()` starts `8ce7d2daf131`, so it matches the frozen manifest. It declares 37 nodes, 30 of them non-system nodes with an exact artifact (sha256 + size).
- The retained artifact store at `/private/tmp/bm022v-familyroom.ygB0t5/artifact-store/artifacts` exists but is **empty**. `packages/`, `repository-candidates/` and every `source/<addon>/` directory in that tree are empty too (purged by macOS temp cleanup on 2026-09-27).

## What is missing (exactly)
- **The bytes of 26 of the 30 declared artifacts.** A read-only scan for any regular file whose size and SHA-256 match a declared artifact covered `~/Documents` (including all of `~/Documents/Kodi` and its worktrees), `~/Downloads`, `~/Desktop` and `/private/tmp`, and excluded Test.app, Kodi.app and the normal profile. It matched only 4 of 30:
  `repository.eengert` 1.0.0, `script.backup.pro` 0.9.36, `service.af3.topupaction` 1.3.7 and `service.skinsettings.backup` 1.0.16 (from `~/Documents/Kodi/repository.eengert/omega/zips/`, which is not a dedicated retained store).
  The other 26 (including Red Light 2.6.8, the AF3 skin and their module closure) exist nowhere reachable.
- No "BM-017F asset copy" exists at any recorded or discoverable path. The `.bm023a-test-runtime/evidence/portable_data.pre_retry/` copy that `docs/BM023A_MACOS_TEST_RUNTIME.md` mentions is not present in any worktree.
- **A fixed named action mode that can carry a source.** The adapter's `install`, `retry` and `recover` modes only read `ARTIFACT_ROOT`. The generated `adapter_config.py` has exactly six keys (`CONFIG_KEYS`) and no key for a byte-source location. Reading artifacts from anywhere would therefore need a new adapter config key or a new action, and the directive forbids new actions or capabilities.

## Why nothing was implemented
The only remaining ways to obtain the 26 ZIPs are forbidden here: the network (repository or CDN download), reading Test.app or Kodi.app or the normal profile (`packages`, `portable_data`, installed add-ons), and zipping installed add-on directories. A repopulate step written now would have no input to run on and could not be exercised end to end. I did not build a tool that has to stay unused, and I did not weaken any check.

## Smallest next step (needs supervisor authority, no user input)
Supply one of these under a separate directive, then re-issue this one:
1. An authorized, verified byte source for the 26 missing ZIPs, for example a directory of ZIPs or an `ArtifactStore` layout that lives inside a granted root. This can come from a networked run that downloads them from the recorded repository sources and checks each against the manifest's sha256 and size, or from an existing read-only copy that the supervisor can name.
2. Authority for one fixed way to reach that source from an existing named action. The smallest fit is a new allowlisted `adapter_config.py` key (for example `ARTIFACT_SOURCE_ROOT`) read in `retry`/`install` before `require_retained_inputs`. It would verify sha256 and size against the manifest for all 30 artifacts before the first write, then use `ArtifactStore.import_zip` only, fail closed on any mismatch, and emit counts and booleans only. That needs the builder's `CONFIG_KEYS`, `--reuse-config-from` and the stage action's file-set checks updated, and re-staging, so it is a capability change.

The `install`/`retry` retained-input check (`retained_artifacts_missing`) still fails closed correctly in the meantime. Transaction, hold, lock, `frozen_install.py` and `FrozenInstallCoordinator.abandon`/held-rejection behavior are untouched.

---

# Current Handoff - BM-023A adapter 0.0.13 staged and verified (2026-09-29)

**Result:** `STAGE_ADAPTER_0_0_13_VERIFIED`. Work ID `d08b9420-195f-4d73-9fbc-81dc9dc97fd3`. Agent: claude. Usage readings unavailable.

- Preflight `--expected-version 0.0.13` at HEAD `7982471`: `ok:true`, stage source `e2f9327b1137`.
- `bm023a-stage-adapter` run once: `ok:true`, `already_current:true`, `files_verified:5`, version_before = version_after = 0.0.13.
- Read-only `test-app-kodi` `Addons.GetAddonDetails`: `script.build.manager.bm023a_driver` version 0.0.13, enabled.
- No other action, no commits. Next step: separate directive for the supported held-retry route (retained inputs must be repaired first). No user input required.

---

# Current Handoff - BM-023A adapter 0.0.13 offline preflight PASSED; stage-source OK (2026-09-29; lease 37d67c36-92ba-4ad2-a0f3-b45b90bb45fd)

**Result:** `ADAPTER_0_0_13_PREFLIGHT_OK`. Work ID `c849bcea-fe50-4ed7-ae20-37f09f855750`. Agent: claude. Usage readings unavailable.

- State: the 0.0.13 snapshot (identity binding `00a9412` + held needs_attention regression test `e2f9327`) was already checkpointed as reviewed commits; worktree clean, no product change made by this worker. `FrozenInstallCoordinator.abandon` untouched.
- Checks: `tests.test_bm023a_adapter` 79/79; `tests.test_frozen_install` 36/36; full offline suite **1926/1926**; compileall OK; 7 tracked JSON files parse; `git diff --check` clean.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py --expected-version 0.0.13` at HEAD `7982471` -> exit 0, `ok:true`, stage_source `e2f9327b11371dc1bc9dc4ce4f23d7ead88f8e0b`, tree `409fb3ea97a8b988ae35e800d6e375fdbab06141`, adapter_version 0.0.13, `product_changes_to_head []`.
- Not done: no staging, Test.app, Kodi, network, or commit. Smallest next step: separate directive to stage 0.0.13, then the supported held-retry route. No user input required.

---

# Review Required - BM-023A held needs_attention transaction has no supported abandon path (2026-09-29; lease 594c6bf3-1af5-4144-8c02-64edc829180e)

**Result:** `REVIEW_REQUIRED_HELD_TRANSACTION_CANNOT_BE_ABANDONED_SAFELY`. Work ID `1311b839-8d10-4354-ace5-8d38cadf14cc`. Agent: claude. Usage readings unavailable. No product or adapter behavior was changed; adapter stays 0.0.13 with identity binding intact.

## Analysis (read-only, offline)
- **What rejected the state:** not `FrozenInstallStore.inspect` (`frozen_install.py:644`). It only reads and parses the durable transaction, and the live transaction parsed fine. The adapter's own precondition in `recover_frozen_install` (`tools/bm023a_adapter_support.py:310`) raises `unsupported_recovery_state` when `activation_hold_ids` is non-empty and `activation_hold_released` is false. `FrozenInstallStore.inspect` is only the reported label for that guard (all `CHECK_RECOVERY_PRECONDITIONS` failures use it). It runs after the phase check and the 0.0.13 identity check, so the identity binding passed.
- **Why it rejects held transactions:** it mirrors the product. `FrozenInstallCoordinator.abandon` (`frozen_install.py:2937`) returns `needs_attention` / `HELD_LIFECYCLE_CANNOT_BE_ABANDONED` ("the activation hold remains authoritative until private verification and final activation") for any transaction with an unreleased hold, before touching updater policy or the store. Without the adapter guard, `abandon` would make the same refusal (zero mutation) and the adapter would report `operation_failed`. The guard just fails earlier with a sharper category.
- **The hold has no separate representation.** `active_activation_hold_ids` (`frozen_install.py:824`) derives holds solely from the durable transaction: none if the transaction is absent or `activation_hold_released`. The only code that sets `activation_hold_released=True` is `_finalize` (`~3197-3211`), and only after `lifecycle_stage is PRIVATE_VERIFIED` (private resource verification). So clearing a held transaction (what `abandon` does after restoring policy) would silently release the Red Light activation hold without private verification, which is the exact guarantee the hold exists for. A hold-release-on-abandon change to product code, or an adapter path that pre-releases the hold, would weaken fail-closed safety. Per the directive, I did not implement either.
- **What the product does define for this exact state:** `_is_held_quiescence_retry_snapshot` (`frozen_install.py:487`) plus `FrozenInstallCoordinator.retry_held_quiescence` / `FrozenInstallStore.rearm_held_quiescence` is the only supported transition out of `needs_attention` + `quiescence_awaiting_restart` + unreleased hold (Red Light owner, restart count 1, updater guard required, original policy AUTOMATIC). It re-arms to `awaiting_restart` and resumes toward private verification and final activation, which releases the hold and restores updater policy normally. `test_held_retry_rejects_same_session_and_preserves_generic_abandon_rejection` (`tests/test_frozen_install.py:1562`) pins that generic `abandon` must keep rejecting held transactions. D-010 forbids manual deletion; no doc in this repo defines D-010 beyond the directive text.

## Change made
- Only `tests/test_bm023a_adapter.py`: added `test_held_redlight_quiescence_needs_attention_is_rejected_without_abandon`. It uses the live shape (Red Light hold, `quiescence_awaiting_restart`, restart count 1, guard required, matching identity) and asserts `unsupported_recovery_state` at `CHECK_RECOVERY_PRECONDITIONS`, zero `abandon` calls, unchanged transaction, policy and restart record, and a sanitized failure payload. Existing tests already cover matching identity -> exactly one `abandon(acknowledge_restore_failure=False)`, each identity mismatch/absent field/malformed or unsupported state -> zero calls, and sanitized identity diagnostics.
- Checks: `tests.test_bm023a_adapter` **79/79**; `tests.test_frozen_install` **36/36**; full offline suite **1926/1926**; `python3 -m compileall -q resources tools tests` OK; all **7** tracked JSON files parse; `git diff --check` clean. Change left uncommitted for the reviewed-checkpoint process.
- Not done: no Test.app, Kodi, profile, named action, network, transaction/hold/lock edit, or commit.

## Decision for review (no user input needed to start)
Recovery of the live transaction should use the supported held-retry route (`retry_held_quiescence`; the adapter has a retry mode that calls it), not abandon. The retry needs the retained manifest/artifact inputs repaired first (see the 0.0.12 follow-up (b) below). If the supervisor instead wants held transactions to be abandonable, that is a product-semantics change (define a safe hold-release/quarantine rule, with tests) and needs an explicit design decision. Do not weaken `abandon`'s held rejection otherwise.

---

# Current Handoff - BM-023A recovery identity binding (2026-09-29; lease 8c01966e-7ce0-4657-820a-0f96d5ac7ea1)

**Result:** `RECOVERY_IDENTITY_BOUND; OFFLINE_VALIDATION_PASSED`. Work ID `7f3b6bfc-8763-4098-ab3c-2e303b1305da`. Agent: codex (`gpt-6-luna`, `max`). Usage readings unavailable per `AGENTS.md`.

- The checkout already contained intentional edits in `tools/bm023a_adapter_support.py`, `tools/bm023a_adapter/default.py.in`, `tools/bm023a_adapter/addon.xml.in`, and `tests/test_bm023a_adapter.py`; they were preserved. The support module now shares the retry identity helper with recovery. Recover mode loads the retained manifest and compares the durable transaction's manifest path, build ID, manifest fingerprint, configuration manifest path, device profile ID, and private overlay ID to reviewed manifest data and adapter constants before `abandon`. The mismatch category is fixed and sanitized. The temporary adapter is 0.0.13; package member-set coverage remains in place.
- Adapter tests cover a valid foreign transaction ID with mismatched durable identity, each tuple-field mismatch, absent/malformed transactions, sanitized diagnostics, and the generated entrypoint. A matching identity records exactly one `abandon(acknowledge_restore_failure=False)`; mismatches record zero.
- Validation: focused adapter tests **78/78**; frozen-install tests **36/36**; full offline suite **1,925/1,925**; `python3 -m compileall -q resources tools tests`; all **7** tracked JSON files parsed; `git diff --check` passed.
- No commit, Test.app/Kodi/profile/device access, network, LAN, staging, or live recovery was performed. The four product files remain dirty for the separate reviewed-checkpoint process. No user input is required.

Smallest next step: independent review of the exact dirty snapshot and its checkpoint handling.

---

# Current Handoff - BM-023A action retained-input result sanitization (2026-09-28; lease 0b2f87ed-5c45-4412-a1c6-e38d853de09a)

**Result:** `ACTION_RETAINED_INPUTS_ALLOWLIST_UPDATED; FULL_SUITE_SANDBOX_LIMITED`. Work ID `84b5e3b3-e76e-466b-b741-fb4c0f3e4e38`. Agent: codex (`gpt-6-luna`, `xhigh`). Usage readings unavailable per `AGENTS.md`.

- In `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions` on `action/bm023a-trusted` at base `7142246`, changed only `ai_supervisor/kodi_action.py` and `tests/test_kodi_action.py`. Retry/install results now retain `retained_inputs` with its five documented keys; the action allowlists the adapter's static failure categories, including `retained_manifest_missing`, `retained_manifest_unreadable`, and `retained_artifacts_missing`. Unknown nested keys, malformed records, and unknown failure categories are dropped.
- Checks: focused `python3 -m unittest tests.test_kodi_action` passed **15/15**; `git diff --check` passed. Full offline suite `python3 -m unittest discover -s tests` ran **428 tests: 3 failures, 41 errors**. The 41 errors include loopback HTTP server binds rejected by this offline sandbox (`PermissionError`) and a subprocess timeout; the three failures are in monitor-control recovery, portability's configured Codex binary check, and synthetic soak recovery. No failure was in the changed module. The initial `discover -s tests -t .` attempt stopped before collection because `tests` is not a package; the directory-based run above is the completed full-suite attempt.
- Not done: no commit, named validation action, staging, Test.app, Kodi/profile/device access, or network operation.

Smallest next step: supervisor review and checkpoint of the two action-worktree files. Any staging remains under a separate directive. No user input required.

---

# Current Handoff - BM-023A adapter 0.0.12 independent review PASSED; stage-source preflight OK (2026-09-28; lease 47555dc3-833e-4c65-8266-969c112d9a18)

**Result:** `ADAPTER_0_0_12_REVIEW_PASSED_PREFLIGHT_OK`. Work ID `a9306a57-eda3-4dc1-9fea-1127c13348c8`. Agent: claude. Usage readings unavailable.

- State note: the directive called the diff uncommitted, but it was already checkpointed as a trailered pair before this worker started: substantive `b3a4e59` (`AI-Supervisor-Part: substantive`) and tracking `f96eb98` (same review `d7482260-...`, source work `7e891152-...`, snapshot `0aa896b3...`). `git diff 2af330e b3a4e59` is exactly the four named files. The worktree was clean and this worker created no commits before this note. This is not contradictory evidence.
- Review confirmed (read-only): `resources/lib/frozen_install.py` and all of `resources/**` are untouched (`git diff 2af330e HEAD` lists only the four files plus `.agent/HANDOFF.md`). `inspect_retained_inputs` returns only 4 booleans and 1 int, with OS errors swallowed and no path or exception text. `require_retained_inputs` raises a fixed `AdapterBootstrapError` category. Recover mode has no diff hunk, and both new calls sit only in the retry and install `LOAD_FROZEN_MANIFEST` blocks. Allowlists are complete: `LOAD_FROZEN_MANIFEST` and `pathlib.Path` were already in `ADAPTER_STAGES` and `ADAPTER_CALLABLES`, and the 3 categories, `FileNotFoundError`, `PermissionError` and `RETAINED_INPUTS_KEYS` were added. `retained_inputs` is set before the raise, so it appears on both success and failure. `AdapterBootstrapError` maps to `Exception`, and other errors go through the `SAFE_ERROR_TYPES` filter.
- Checks: `python3 -m unittest tests.test_bm023a_adapter` 75/75 OK; full `python3 -m unittest discover -s tests -t .` **1922/1922 OK**; `git diff --check 2af330e HEAD` clean.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py --expected-version 0.0.12` at HEAD `f96eb98` -> exit 0, `ok:true`, stage_source `b3a4e59451a6a53eb2c257b4e626f2d36e81f567`, tree `52ba92aca017fcc20f80afda64ddd2ef1430dba9`, `adapter_version 0.0.12`, `product_changes_to_head []`.
- Not done: no named action, Test.app, Kodi.app, normal profile, network, push or staging.

## Follow-ups (separate directives)
- (a) The action worktree's `kodi_action.py` result-key allowlist needs `retained_inputs` (and its 5 sub-keys) plus the new failure categories `retained_manifest_missing`, `retained_manifest_unreadable` and `retained_artifacts_missing`, so the new diagnostics are not dropped.
- (b) The retained manifest and artifact store must be repaired at the exact original path from the BM-017F asset copy (fingerprint `8ce7d2daf131`) before any retry or install. Otherwise the new check fails closed with `retained_manifest_missing` or `retained_artifacts_missing`.

Smallest next step (supervisor): handle (a) and (b), then stage 0.0.12 under a separate directive. No user input required.

---

# Current Handoff - BM-023A adapter 0.0.12 retained-input diagnostics (2026-09-28; lease 9efffb21-5020-43d9-b16c-59b7a1a7ec43)

**Result:** `OFFLINE_ADAPTER_RETAINED_INPUT_DIAGNOSTICS_ADDED_UNCOMMITTED`. Work ID `7e891152-4216-4272-a891-722846df804e`. Agent: claude. Usage readings unavailable.

- Root cause being diagnosed (work `ea97dd40`): `MANIFEST_PATH` under `/private/tmp` was purged by macOS temp cleanup, so `Path(MANIFEST_PATH).read_text` raised `FileNotFoundError` at `LOAD_FROZEN_MANIFEST` and the artifact store was empty.
- `ADAPTER_VERSION` is now **0.0.12** (`tools/bm023a_adapter_support.py`, `tools/bm023a_adapter/addon.xml.in`). Changes are uncommitted for the armed review checkpoint. `resources/lib/frozen_install.py` and all transaction, hold and lock semantics are untouched.
- New in `tools/bm023a_adapter_support.py`: `inspect_retained_inputs(manifest_path, artifact_root)` returns only `manifest_present`, `manifest_readable`, `artifact_store_present`, `artifact_store_readable` (booleans) and `artifact_entry_count` (int, direct entries of `ARTIFACT_ROOT/artifacts`). `require_retained_inputs(record)` raises `AdapterBootstrapError` at stage `LOAD_FROZEN_MANIFEST` / callable `pathlib.Path` with a distinct category, in priority order: `retained_manifest_missing` (absent or not a regular file), `retained_manifest_unreadable` (exists but cannot be opened), `retained_artifacts_missing` (store directory absent or zero entries). The record keeps all facts even when an earlier category wins.
- Allowlists: `FAILURE_CATEGORIES` gained the 3 categories; `SAFE_ERROR_TYPES` gained `FileNotFoundError` and `PermissionError`; new `RETAINED_INPUTS_KEYS` names the 5 record keys.
- `default.py.in`: in **retry and install** modes only, both calls run immediately before `Path(MANIFEST_PATH).read_text`. Recover mode is unchanged and not checked. The result gains `retained_inputs: {...}` (the record above) whenever the check ran, on success and failure. No paths or exception text are emitted.
- Behavior note: an empty artifact store now fails closed at `LOAD_FROZEN_MANIFEST` with `retained_artifacts_missing`. Previously a missing store in retry mode failed later at `CHECK_RETRY_PRECONDITIONS` with `path_missing_or_unreadable`; that subtest's expectation was updated. Test fixtures now place one placeholder entry in the artifact store.
- Tests (`tests/test_bm023a_adapter.py`): version assertions moved to 0.0.12; new `TestBm023aRetainedInputsDiagnostics` (11 tests: present, missing, directory-as-manifest, unreadable, empty store, absent store, precedence, sanitized record, sanitized failure payload, `FileNotFoundError`/`PermissionError` safe types, allowlist completeness by scanning support and entrypoint sources for stages, callables and categories); the generated-entrypoint test gained subtests for missing manifest, unreadable manifest, empty store and absent store in retry and install modes, an unchanged-success check with the manifest present in both modes, and recover mode not checking. The unreadable-manifest cases skip if permissions are not enforced (root).
- Checks: `python3 -m unittest tests.test_bm023a_adapter` 75/75 OK; full `python3 -m unittest discover -s tests -t .` **1922/1922 OK**; `git diff --check` clean.
- Not done: no commit, push, network, named action, Test.app, Kodi.app or normal profile access. The staged Test.app adapter is still 0.0.10/0.0.11 until a separate staging directive.

## Follow-ups outside this task
- (a) The action worktree's `kodi_action.py` result-key allowlist (around lines 49-56) needs matching keys: `retained_inputs` (and its 5 sub-keys, plus the new failure categories) so the action does not drop the new diagnostics. Not touched here.
- (b) Retained inputs need repairing at the exact original path from the BM-017F asset copy (fingerprint `8ce7d2daf131` verified) plus artifact repopulation, before retry or install can pass the new check.

Smallest next step (supervisor): checkpoint this diff as a substantive/tracking pair, run `python3 tools/check_bm023a_stage_source.py --expected-version 0.0.12`, then handle follow-ups (a) and (b) under separate directives. No user input required.

---

# Previous Handoff - BM-023A action tolerates untrailered .agent-only commits (2026-09-28; lease 50e6079c-028b-443e-b1a0-348e89bff178)

**Result:** `ACTION_UNTRAILERED_AGENT_TOLERANCE_COMMITTED_LOCAL`. Work ID `d1cd48c5-53b4-49b2-9794-cde2de3e762e`. Agent: claude. Usage readings unavailable.

- Action worktree `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions` (`action/bm023a-trusted`) was clean at `ef9aa37`. New local-only commit: **`7142246d5c73ec56eb8e4edf069900d72023dfb2`**, touching `ai_supervisor/bm023a_adapter_upgrade.py` and `tests/test_bm023a_adapter_upgrade.py`.
- Fix: in the bounded first-parent walk of `_latest_reviewed_source_commit`, a commit with NO `AI-Supervisor-*` line is tolerated only if it has exactly one parent and a non-empty path set that is entirely `.agent` or under `.agent/`. It neither sets nor resets `child_tracking_metadata`, and it counts toward the 64-commit bound. Anything with a partial, ambiguous or empty-valued trailer still goes through `_checkpoint_metadata` and fails closed as before. Merges/roots, untrailered commits with any other path, tracking commits with non-`.agent` paths, a missing or mismatched pair, and uncommitted product drift all still fail closed. `_checkpoint_metadata` gained an optional `message` argument and a `_commit_message` helper was extracted; there is no other behavior change.
- Tests: the old `test_malformed_tracking_metadata_fails_closed` used an untrailered `.agent` commit as its bad case, which is now legitimately tolerated. It was replaced by `test_partial_tracking_metadata_fails_closed` (only `Part:` trailer). 11 new tests cover: a scratch-repo reproduction of `2af330e` atop a trailered pair (selects the substantive commit), stacked untrailered and tracking commits, and rejection of an untrailered product commit, a mixed `.agent`+product commit, an `.agentx` lookalike, nested `docs/.agent`, an empty-path commit, an untrailered commit as the only child of the substantive commit, an untrailered merge, exceeding the bound, and uncommitted product drift. Module: 33/33 OK. Full action suite: 424 tests, 2 failures (`partial_legacy_config`, `must_be_git_worktree`), the same 2 pre-existing unrelated ones. `git diff --check` clean.
- Read-only check: `_latest_reviewed_source_commit` against this product worktree (HEAD `2af330e`) now returns `5220cf1782016c7206405d6661a7602a80d6ce1e`.
- Design note for review: the product preflight `tools/check_bm023a_stage_source.py` resets `child_tracking` on an untrailered commit, so it requires the tracking commit to be the immediate child of the substantive one. Per this directive, the action does NOT reset. A layout of substantive <- untrailered `.agent` commit <- tracking commit is therefore accepted by the action but rejected by the (stricter) preflight. The two agree on the real `2af330e` layout. Supervisor may want the action to reset as well.
- Not done: no named action invoked, no Test.app, network or push. The supervisor pin config still needs review/update to `7142246`. Restaging 0.0.11 is a later, separate step.
- Smallest next step (supervisor): review `7142246`, update the pin config, then re-issue the 0.0.11 staging directive. No user input required.

---

# Current Handoff - BM-023A stage action allowlist updated for bundled_frozen_install.py (2026-09-28; lease 26ef01d2-c72e-4ae2-9774-f801daf15178)

**Result:** `ACTION_ALLOWLIST_UPDATED_COMMITTED_LOCAL`. Work ID `ee83fb40-f6f0-4e8c-bf8b-264c7fc3d0b0`. Agent: claude. Usage readings unavailable.

- Action worktree `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions` (branch `action/bm023a-trusted`) was clean at `ab05818`. `git grep` confirmed `bundled_frozen_install.py` was absent from the allowlist before editing.
- New action commit: **`ef9aa378ac52cbf7b9fec52befe4287e5483499e`** (local only, not pushed). `ai_supervisor/bm023a_adapter_upgrade.py` `_EXPECTED_FILES` now lists the four prior files plus `bundled_frozen_install.py`. `_hashes` still requires an exact file-set match, so missing or extra files fail closed. Identity, clean-tree, checkpoint-pair, downgrade and rollback logic are unchanged.
- `tests/test_bm023a_adapter_upgrade.py`: the fake builder now emits the bundle, and 9 tests were added (22 total, all pass). They cover the expected file set, installing 5 files, already-current, tampered installed bundle, generated package missing the bundle or another file, an extra file (all fail closed with the install untouched), `_hashes` missing/extra/hash change, and an installed-hash mismatch after swap that rolls back.
- Checks: focused module 22/22 OK. The full offline action suite ran 413 tests with 2 failures (`test_portability...partial_legacy_config` and `test_workspaces...must_be_git_worktree`). Both fail identically on a clean clone of `ab05818` (404 tests, same 2 failures), so they are pre-existing and unrelated. `git diff --check` clean.
- Not done: no named action invoked, no supervisor pin config change (the pin still needs updating to `ef9aa37`), no Test.app, network or push. The only product-worktree change is this note.
- Smallest next step (supervisor): review `ef9aa37`, update the pin configuration, then re-issue the 0.0.11 staging directive. No user input required.

---

# Review Required - BM-023A 0.0.11 staging action failed (2026-09-28; lease f38ed84d-a534-4582-bc35-e40e58b0a0dd)

**Result:** `REVIEW_REQUIRED_STAGE_ACTION_FAILED`. Work ID `29205f7f-4334-467b-8003-c54f77660004`. Agent: codex (`gpt-6-luna`, high). Usage readings recorded as unavailable per `AGENTS.md` Codex usage rules.

- Read the prescribed `AGENTS.md`, handoff, and supervisor state. Worktree is on `agent/supervised-codex`; existing `.agent/HANDOFF.md` edits were preserved. HEAD is the reviewed pair `5220cf1` / `0b6f796`; no product changes to HEAD.
- Pinned-source preflight passed: `PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py --expected-version 0.0.11` -> exit 0, source `5220cf1782016c7206405d6661a7602a80d6ce1e`, tree `4419f4c7a362f4c1255c898f033f3cb68a0c2570`, version `0.0.11`, `product_changes_to_head: []`.
- Requested `bm023a-stage-adapter` once through the authorized supervisor validation-action command. The action failed with sanitized `ValidationActionFailed` / `AdapterUpgradeError`: `temporary adapter upgrade failed` (return code 1). Staging is not claimed. No second action was requested.
- No tests, install, retry, recover, network, push, or Test.app action. No changes besides this handoff update.
- Smallest next step: supervisor review of the staging action failure and its pinned-source/staging checks; any retry requires a new directive. No user input is required.

---

# Current Handoff - BM-023A 0.0.11 stage-source preflight PASSED at reviewed checkpoint (2026-09-28; lease c8d34987-dd94-4371-8d5a-f88d9b445e27)

**Result:** `STAGE_SOURCE_PREFLIGHT_OK_0_0_11`. Work ID `b16c33b4-89c2-44ae-9cbd-94061b2bdea1`. Agent: claude. Usage readings unavailable.

- The 0.0.11 change was already committed by the armed checkpoint as a trailered pair: substantive `5220cf1` and tracking `0b6f796` (review `af02835d-...`, source work `eff03242-...`). The worktree was clean; this worker created no commits before this note.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py --expected-version 0.0.11` -> exit 0, `ok:true`, stage_source `5220cf1782016c7206405d6661a7602a80d6ce1e`, tree `4419f4c7a362f4c1255c898f033f3cb68a0c2570`, `adapter_version 0.0.11`, `product_changes_to_head []`.
- `python3 -m unittest tests.test_bm023a_adapter`: 64/64 OK.
- No stage, install, retry, recover, push, network, or Test.app action. Next step: separate directive to stage 0.0.11. No user input required.

---

# Current Handoff - BM-023A 0.0.11 adapter bundles pinned frozen_install.py and repairs a mismatched install (2026-09-28; lease 430725af-e77e-47c3-992c-0964fd57f678)

**Result:** `OFFLINE_ADAPTER_REPAIR_ADDED_UNCOMMITTED`. Work ID `eff03242-8487-4e56-88f7-7ed00cda9295`. Agent: claude. Usage readings unavailable.

- `ADAPTER_VERSION` is now **0.0.11** (`tools/bm023a_adapter_support.py`, `tools/bm023a_adapter/addon.xml.in`). Changes are uncommitted for the armed review checkpoint; no `resources/**` change.
- `tools/build_bm023a_adapter.py` now writes and zips `bundled_frozen_install.py`, a byte copy of `resources/lib/frozen_install.py`. Its SHA-256 is the existing `EXPECTED_FROZEN_INSTALL_SHA256` pin.
- New `repair_frozen_install_source(addon_root, pin, backup_dir, bundled_path=None)` in `tools/bm023a_adapter_support.py`, called from `default.py.in` after `verify_build_manager_source` and before `verify_frozen_install_source` and any `resources.lib.frozen_install` import:
  - Hash matches the pin: untouched, with no bundle read and no backup.
  - Hash differs: the bundled bytes must hash to the pin (`bundled_source_mismatch`). The addon root must be absolute, free of `..`, unchanged by resolution and named `script.build.manager`. The target must be a regular non-symlink file that resolves to exactly `<addon>/resources/lib/frozen_install.py` (`source_target_invalid`). The original is backed up to `<profile>/addon_data/script.build.manager.bm023a_driver/frozen_install_backups/frozen_install.<hash16>.py.bak` (never the Build Manager `addon_data`). Then a same-directory temp file is fsynced and `os.replace`d over that one file, and the hash is re-verified. Failures use `source_replace_failed` (original untouched) or `source_reverify_failed` (original restored best-effort). Error text is never included.
  - The result gains `frozen_install_source: {sha256_before, sha256_after, replaced}`. It carries hashes only and is present whenever the repair step ran, including later failures.
- `verify_frozen_install_source` is unchanged and still runs after the repair, so the mismatch/missing/unreadable behavior is otherwise identical. It is exercised by a regression test.
- Four new failure categories were added to the allowlist. No transaction, lock, hold, settings or private file is read or written, and no Kodi.app or normal profile path is involved.
- Tests (`tests/test_bm023a_adapter.py`): new `TestBm023aFrozenInstallRepair` (12 tests covering mismatch->replaced with backup, match->untouched, bundled hash mismatch and missing bundle->fail closed, symlinked file/directory/root, traversal, wrong add-on name, replace failure->original preserved, reverify failure->restored, only sanitized hash keys, invalid pin, and `verify_frozen_install_source` unchanged). The builder test now expects the bundle and 0.0.11. The generated-entrypoint mismatch subtest now expects repair success with recorded hashes (previously fail closed), plus a match subtest that expects no replacement.
- Checks: focused `tests.test_bm023a_adapter` 64/64 OK; full `python3 -m unittest discover -s tests -t .` **1911/1911 OK**; `git diff --check` clean.
- Not done: no stage, install, retry, recover, commit, push, network, Test.app or action-worktree change. The staged Test.app adapter is still 0.0.10 until a separate directive stages the new reviewed source.
- Next step (supervisor): review and checkpoint this diff as a substantive/tracking pair, run `python3 tools/check_bm023a_stage_source.py --expected-version 0.0.11`, then stage under a separate directive. No user input required.

---

# Current Handoff - BM-023A 0.0.10 adapter stage action (2026-09-28; lease 90f0bd81-4f4b-4ccb-9d45-33c2152cf7dc)

**Result:** `STAGE_ADAPTER_VERIFIED_ALREADY_CURRENT`. Work ID `1292f688-574b-48ce-b350-e6897e4234a4`. Agent: claude. Usage readings unavailable.

- Preflight (`--expected-version 0.0.10`) at HEAD `b332847`: exit 0, `ok:true`, stage source `d4bf04e7`, adapter_version 0.0.10, no product changes to HEAD.
- `bm023a-stage-adapter` action: `ok:true`, `already_current:true`, `files_verified:4`, `reviewed_source d4bf04e7fe97`, `version_before` = `version_after` = 0.0.10.
- Read-only `test-app-kodi`: Ping-equivalent `Application.GetProperties` OK (Kodi 21.3); `Addons.GetAddonDetails script.build.manager.bm023a_driver` = version 0.0.10, enabled.
- Process check: `/Applications/Kodi Build Manager Test.app/Contents/MacOS/Kodi -p` is running (portable mode).
- No install/retry/recover, no Kodi.app or normal profile access, no push, no commits. Next step: separate directive for any further Test.app action. No user input required.

---

# Current Handoff - stage-source preflight PASSED at reviewed checkpoint (2026-09-28; lease bdc97fb8-a0d2-4581-919d-9027b3cf37ac)

**Result:** `STAGE_SOURCE_PREFLIGHT_OK`. Work ID `00ce97af-b91b-4adf-a68a-f25f2d980822`. Agent: claude. Usage readings unavailable.

- HEAD `b3328476e8c8cfd291cb29f11020576300d47c9a` is a trailered tracking commit (review checkpoint `74086c8d-...`) paired with substantive `d4bf04e`. Worktree was clean; no commits created by this worker before this note.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py --expected-version 0.0.10` -> exit 0, `ok:true`, stage_source commit `d4bf04e7fe97925770b2699ec7147ce9aceaaf65`, tree `14144c9caf3b344078806983a9a28feec5c921dc`, `adapter_version 0.0.10`, `product_changes_to_head []`. Preflight was not narrowed.
- Note: the stage source is now `d4bf04e`, not the older pin `72e327e`. Adapter inputs are unchanged, so the version remains 0.0.10.
- No push, network, Test.app, or action-worktree change. Next step: a separate directive for staging. No user input required.

---

# Current Handoff - stage-source preflight regression tests for the untrailered-.agent tolerance (2026-09-28; lease 6aa0c474-7e24-4267-8c79-f52ae42028ea)

**Result:** `OFFLINE_REGRESSION_TESTS_ADDED_UNCOMMITTED`. Work ID `cf9d111f-9ccb-4d85-875b-c84537b7d074`. Agent: claude. Usage readings unavailable.

- Changed only `tests/test_check_bm023a_stage_source.py` (uncommitted, for the armed review checkpoint). `tools/check_bm023a_stage_source.py` is unchanged; acceptance semantics are not narrowed or weakened.
- Added 2 tests: `test_untrailered_commit_tolerance_rejects_non_agent_only_changes` (untrailered commits that mix `.agent` and product paths, product-only, `.agentx/` lookalike, and nested `docs/.agent/` are all rejected as `untrailered_product_commit`, with `main` exit 1) and `test_untrailered_empty_commit_is_rejected` (an untrailered commit with no paths is rejected).
- Checks: focused module 18/18 OK; full `python3 -m unittest discover -s tests -t .` **1898/1898 OK**; `git diff --check` clean.
- No commit, push, network, Test.app, or action-worktree change.
- Next step (supervisor): let the armed checkpoint trailer this diff as a substantive/tracking pair, then rerun `python3 tools/check_bm023a_stage_source.py --expected-version 0.0.10`. Note that `76b0c3c` itself remains an untrailered committed product commit and this pair does not retro-review it; the earlier review-required note below still applies. No user input required.

---

# Review Required - 76b0c3c review PASSED, but the armed checkpoint cannot produce a substantive/tracking pair (2026-09-28; lease 193a69d6-255f-4a50-946b-a72c831d058c)

**Result:** `REVIEW_REQUIRED_CHECKPOINT_MECHANISM_CANNOT_PAIR_COMMITTED_SOURCE`. Work ID `80ef275a-d2bb-4303-ad5e-170e29ff7995`. Agent: claude (`claude-opus-5-5`). Usage readings unavailable. No commit was created and the preflight was NOT narrowed.

## Step 1 - independent read-only review of 76b0c3c..897a9fc: PASS
- `tools/check_bm023a_stage_source.py` fails closed on: untrailered product commits (`untrailered_product_commit`), partial trailers (`checkpoint_metadata_incomplete`), merges/roots (`lineage_ambiguous`), missing pair (`tracking_pair_missing`/`head_not_tracking`), mismatched pair trailers, committed drift after the source (`product_changes_after_source`), uncommitted non-`.agent` changes including untracked (`uncommitted_product_changes`), version mismatch, and missing version. The `.agent`-only tolerance requires every changed path to be `.agent` or `.agent/**`; a commit with no paths or any other path is rejected, and a tolerated untrailered commit resets the tracking-child slot so it can never serve as the tracking half of a pair.
- Only `tools/check_bm023a_stage_source.py`, `tests/test_check_bm023a_stage_source.py` and `.agent/HANDOFF.md` differ across 1c8e89b..897a9fc.
- Focused module 16/16 OK; full suite `python3 -m unittest discover -s tests -t .` **1896/1896 OK**; `git diff --check` clean.

## Step 2 - blocked (contradiction)
- `ai_supervisor/review_checkpoint.py` `apply_review_checkpoint` creates a substantive commit only `if captured_substantive:`, i.e. from paths that are dirty in the worktree when the review launches. Here the only dirty path is `.agent/HANDOFF.md` (pre-launch). `76b0c3c` and `897a9fc` are already committed, so the mechanism would create just ONE trailered `tracking` commit and no substantive partner. The mechanism cannot retro-review already-committed commits.
- Simulated in a scratch clone (removed): `897a9fc` + one trailered tracking commit of the handoff, then the preflight: still `ok:false`, `untrailered_product_commit` (76b0c3c is untrailered product source, nearest substantive `72e327e`). So the directive's expected end state (`ok:true`, `0.0.10`) cannot be reached by letting the armed checkpoint run.
- Also, the checkpoint snapshot fingerprint includes the `.agent/HANDOFF.md` diff; this note edits it, so the armed checkpoint would fail with "reviewed worktree changed after the independent review began" if the review had been allowed to complete. Yielding `review-required` (not `complete`) avoids committing anything.

## Step 3 - preflight output (not ok; no checkpoint occurred)
`PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py --expected-version 0.0.10` at HEAD `897a9fc903a44693d4a2ca555032b75335948bde` -> exit 1, `ok:false`, `category: untrailered_product_commit`; `nearest_substantive` = `72e327eb9af2c32d443b3a69fb3cd8237fa14fd2`, tree `8a15b91ecd15c966faa6ef9ab3658bafae2dcfd6`, `adapter_version 0.0.10`, `product_changes_to_head` = the two preflight files.

## Not done
No commit, push, network, Test.app, or action-worktree change. Only change: this note (uncommitted).

## Smallest next step (supervisor, no user input)
Make `76b0c3c` a reviewed substantive commit in a way the mechanism supports: e.g. `git reset --mixed 1c8e89b` (keeps files, drops the two local unpushed commits) so `tools/check_bm023a_stage_source.py` and `tests/test_check_bm023a_stage_source.py` are dirty product paths, then run the armed read-only review (this review's PASS applies to that exact content) so the framework makes the trailered substantive + tracking pair; or extend the mechanism to trailer already-committed reviewed ranges. Either needs supervisor authority; I did not rewrite history. Then rerun the preflight and expect `ok:true` / `0.0.10`.

---

# Review Required - re-verified: 76b0c3c needs an independent reviewed checkpoint; preflight NOT narrowed (2026-09-28; lease 57f6bedf-4fa6-44f9-b7de-467a05021462)

**Result:** `REVIEW_REQUIRED_PREFLIGHT_HARNESS_IS_STAGED_SOURCE`. Work ID `dd2855a5-2e40-4c3d-855d-a3107ff5b03a`. Agent: claude (`claude-opus-5-5`). Usage readings unavailable. This is the same directive as `4668b7ad` below, and the result is the same: branch (b).

- I re-checked the evidence read-only at product HEAD `897a9fc903a44693d4a2ca555032b75335948bde` and action HEAD `ab058180039c6fc7c110603be366c32bf11168bd`. In the action, `_extract_reviewed_source` runs `git archive --format=tar <reviewed_commit>`, which extracts the whole tracked tree. `git ls-tree 72e327e` lists `tools/check_bm023a_stage_source.py` (blob `34d8750…`) and `tests/test_check_bm023a_stage_source.py` (blob `78f3d63…`). Both files are therefore staged product source. They are not adapter build inputs.
- `76b0c3c` and `897a9fc` both have no `AI-Supervisor-*` trailers; each carries only `Co-Authored-By`. The action's lineage walk calls `_checkpoint_metadata` on every commit, so the live action would also fail closed at this HEAD.
- Live preflight (`--expected-version 0.0.10`, exit 1): `ok:false`, `untrailered_product_commit`. `nearest_substantive` is `72e327eb9af2c32d443b3a69fb3cd8237fa14fd2`, tree `8a15b91ecd15c966faa6ef9ab3658bafae2dcfd6`, version `0.0.10`, with `product_changes_to_head` = the two preflight files.
- No code or test changes were made, no tests ran, and nothing was committed. The action worktree was not modified. No push, network, Test.app, or host action occurred.
- **Next step (supervisor):** checkpoint `76b0c3c` as an independent reviewed substantive/tracking pair. Make HEAD end on a trailered tracking commit that includes these `.agent` handoff edits. Then rerun the preflight and expect `ok:true` / `0.0.10`. No user input is required.

---

# Review Required - 76b0c3c needs an independent reviewed checkpoint; preflight NOT narrowed (2026-09-28; lease f64ebde7-420a-4e13-a59c-81d19f09c25a)

**Result:** `REVIEW_REQUIRED_PREFLIGHT_HARNESS_IS_STAGED_SOURCE`. Work ID `4668b7ad-3732-4182-9e9c-e4f52a7df146`. Agent: claude (`claude-opus-5-5`). Usage readings unavailable. Branch (b) of the directive applies: the evidence does not prove that the two preflight paths are outside the staged source, so the guard was not weakened.

## Evidence (read-only; product HEAD `897a9fc903a44693d4a2ca555032b75335948bde`, action HEAD `ab05818`)

- **The staged source is the whole reviewed tree.** `ai_supervisor/bm023a_adapter_upgrade.py` (`_extract_reviewed_source`) runs `git archive --format=tar <reviewed_commit>` and extracts every tracked path. It then imports `tools.build_bm023a_adapter` and `tools.bm023a_adapter_support` from that extracted tree. Both `tools/check_bm023a_stage_source.py` (blob `34d8750…`) and `tests/test_check_bm023a_stage_source.py` (blob `78f3d63…`) are tracked in the reviewed tree `8a15b91ecd15c966faa6ef9ab3658bafae2dcfd6` of `72e327e`. They are therefore part of the staged product source, even though they are not adapter build inputs.
- **Narrow build inputs, for reference only.** `build_adapter` reads `tools/build_bm023a_adapter.py`, `tools/bm023a_adapter_support.py`, `tools/bm023a_adapter/{default.py.in,addon.xml.in}`, and `resources/lib/frozen_install.py`. Nothing in the builder imports or references the preflight; the only reference is from its own test.
- **The live action selector fails closed at this HEAD anyway.** Running `_latest_reviewed_source_commit(_PRODUCT_ROOT)` read-only from the action worktree gives `reviewed source checkpoint metadata is incomplete`. Both `897a9fc` (`.agent/HANDOFF.md` only) and `76b0c3c` (the two preflight files) have 0 `AI-Supervisor-*` trailers. If the preflight tolerated these commits, it would report `ok:true` while the action it predicts fails, defeating the preflight's purpose.
- **Self-certification.** `76b0c3c` rewrote the preflight's own acceptance logic. Exempting the preflight's own files from review would let an unreviewed commit certify itself.
- Live preflight output (`--expected-version 0.0.10`, exit 1): `ok:false`, `category: untrailered_product_commit`, head `897a9fc…`. `nearest_substantive`: commit `72e327eb9af2c32d443b3a69fb3cd8237fa14fd2`, tree `8a15b91e…`, `adapter_version 0.0.10`, `product_changes_to_head` = `[tests/test_check_bm023a_stage_source.py, tools/check_bm023a_stage_source.py]`.

## Not done

No code, test, or preflight changes were made and no commit was created; the only change is this handoff note, left uncommitted. No tests ran because no code changed. The action worktree was not modified (read and import only; `PYTHONDONTWRITEBYTECODE=1`). No push, Test.app, network, or host action occurred.

## Smallest next step (supervisor)

`76b0c3c` needs its own independent reviewed checkpoint: a substantive/tracking trailer pair through the reviewed-checkpoint mechanism, with HEAD ending on a trailered tracking commit. `897a9fc` and this note are untrailered `.agent` commits, which the live action `ab05818` also rejects. Fold them into the tracking half, or make sure no untrailered commit sits above the pair. After that, the preflight and the action should both report a new stage source whose adapter inputs are identical to `72e327e`, with version `0.0.10`. If staging must be pinned to exactly `72e327e`, that requires an explicit action-side authorization (see option 2 in the older note below). No user input is required.

---

# Current Handoff - BM-023A stage-source preflight tolerates untrailered .agent-only commits (2026-09-28; lease 200fce84-070d-4a29-a97d-7fc91e49638b)

**Result:** `STAGE_SOURCE_PREFLIGHT_FIX_COMMITTED_PENDING_REVIEW_CHECKPOINT`. Work ID `13b10f3d-f8c6-4f37-a646-e49f9d2889a8`. Agent: claude (`claude-opus-5-5`). Usage readings unavailable.

## Evidence (verified before changes)

- First-parent `72e327e..1c8e89b` has 6 commits and no merges, and every commit has one parent. `1c8e89b` has no `AI-Supervisor-*` trailers and changes only `.agent/HANDOFF.md`. `619a591`, `0d40d3c`, `9e2a057`, `4a8d8c7`, and `7b37576` are trailered `tracking` commits that change only `.agent/{AGENT_STATUS.json,CURRENT_TASK.md,HANDOFF.md,USAGE_HISTORY.md}`. `7b37576` pair-matches substantive `72e327e` (review `89da59a2-…`, source `50118de2-…`, snapshot `b3325efe…`). No untrailered commit touches non-`.agent` paths.
- The uncommitted change was the prior worker's review-required note at the top of `.agent/HANDOFF.md` (24 added lines, `.agent` only). It is kept below.

## Done

- Commit `76b0c3c6f6af82ef308f74c5dbde254be71990b3` on `agent/supervised-codex` (local only, not pushed):
  - `tools/check_bm023a_stage_source.py`: replaced the HEAD/HEAD^ pair check with the live action's (`ab05818`) bounded (64) first-parent lineage walk. The walk passes trailered tracking commits and, in addition, **untrailered commits whose changes are all under `.agent/**`**. An untrailered commit never serves as the tracking half of a pair. The nearest substantive commit must have a matching immediate tracking child. The report now includes the staged `tree`, and `--expected-version` was added.
  - New fail-closed categories: `uncommitted_product_changes` (dirty non-`.agent`), `untrailered_product_commit`, `checkpoint_metadata_incomplete` (partial trailers), `checkpoint_part_invalid`, `lineage_ambiguous` (merge or root), `tracking_pair_missing`, `substantive_unavailable`, and `adapter_version_mismatch`. `pair_metadata_mismatch`, `head_not_tracking`, `product_changes_after_source`, and `adapter_version_unavailable` are kept. The categories `head_metadata_incomplete`, `parent_*`, and `parent_not_substantive` are gone.
  - `tests/test_check_bm023a_stage_source.py` now has 16 tests (previously 9). Tolerated cases: stacked tracking plus untrailered `.agent` commits, including dirty `.agent`. Rejected cases: untrailered product commit, an untrailered commit as the only child of a substantive commit, uncommitted product or adapter file, version mismatch, partial trailers, merge in lineage, and tracking-commit product drift.
- Checks: focused 16/16 OK; full `python3 -m unittest discover -s tests -t .` **1896/1896 OK**; `git diff --check` clean.
- Preflight on a temporary clone detached at the reviewed HEAD `1c8e89b` (script from `76b0c3c`, `--expected-version 0.0.10`): `ok: true`, stage_source `72e327eb9af2c32d443b3a69fb3cd8237fa14fd2`, tree `8a15b91ecd15c966faa6ef9ab3658bafae2dcfd6`, `adapter_version 0.0.10`, `product_changes_to_head []`, exit 0.
- Preflight on the live worktree at HEAD `76b0c3c`: `ok: false`, `untrailered_product_commit`. `nearest_substantive` is `72e327e`/`0.0.10`, and product changes to HEAD are exactly this fix's two files. **This is the intended fail-closed behavior:** the fix is itself an unreviewed substantive commit.

## Not done

The action worktree was not touched. No push, Test.app, network, or host action occurred. The live action `ab05818` still rejects untrailered `.agent` commits; this change affects only the product preflight.

## Smallest next step (supervisor)

Review `76b0c3c` and checkpoint it through the reviewed-checkpoint mechanism as a substantive/tracking pair. The live preflight should then report `ok:true` with a new stage source. That source contains no adapter changes, so the version stays `0.0.10`, but it will not be `72e327e`. If staging must stay pinned to exactly `72e327e`, decide how that interacts with this reviewed tooling commit before the adapter update. No user input is required.

---

# Review Required - BM-023A 0.0.10 stage-adapter update not started: source preflight fails (2026-09-28; lease 8e94fc10-5624-4531-9d42-5f77c93df450)

**Result:** `REVIEW_REQUIRED_STAGE_SOURCE_PREFLIGHT`. Work ID `3fb0e2c7-f147-4691-9537-f0b201cc9297`. Agent: claude (`claude-opus-5-5`). Usage readings unavailable.

## Verified live state (read-only)

- The action worktree `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions` is clean on `action/bm023a-trusted`. Its HEAD is **`ab058180039c6fc7c110603be366c32bf11168bd`**, matching live config; the stale `68d05ae` is superseded. The worktree is writable in this lease.
- The product worktree is clean on `agent/supervised-codex`, HEAD `1c8e89bbce893e916508ceb5c8dc88b9e4f95a6e` (`docs: checkpoint worker tracking before BM-023A 0.0.10 stage-adapter work`). It changes only `.agent/HANDOFF.md` and has **no `AI-Supervisor-*` trailers**.
- `PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py` → `ok: false`, `category: head_metadata_incomplete`. The diagnostic-only `nearest_substantive` field reports `72e327eb9af2c32d443b3a69fb3cd8237fa14fd2` (tree `8a15b91ecd15c966faa6ef9ab3658bafae2dcfd6`, `ADAPTER_VERSION = "0.0.10"`, no product changes to HEAD).
- The first-parent chain is: `1c8e89b` (no trailers) → `619a591`, `0d40d3c`, `9e2a057`, `4a8d8c7`, `7b37576` (tracking checkpoints, `.agent/**` only) → `72e327e` (substantive; review `89da59a2-…`, source `50118de2-…`, pair-matched by `7b37576`).
- The identity evidence is consistent, with no contradiction. The directive's precondition fails, however: the preflight must report `ok:true`/`0.0.10`. The live action at `ab05818` would also fail closed on this HEAD, because `_latest_reviewed_source_commit` calls `_checkpoint_metadata` on every lineage commit, and `1c8e89b` lacks trailers.

## Not done

No action code or tests were changed. No action tests ran. No commits were made in the action or product worktree. No host action, Test.app, network, or snapshot access (0.0.9 or 0.0.10) occurred. The only change is this handoff note, left uncommitted.

## Smallest next step (supervisor)

Choose one of these. Neither needs user input.
1. Checkpoint the product worktree through the reviewed-checkpoint mechanism, so that HEAD is a trailer-bearing tracking commit. Then rerun the preflight (expect `ok:true`, `0.0.10`) and reissue this directive.
2. Explicitly authorize pinning `72e327eb9af2c32d443b3a69fb3cd8237fa14fd2` / tree `8a15b91e…` in the action, with the lineage from HEAD to the pin restricted to `.agent/**`-only commits whether or not they carry trailers. Update the preflight to match.

---

# Review Required - tracking checkpoint 8cde87c9 not performed (2026-09-28; lease d102c43b-c40d-4bc8-b3bd-c8756cd00401)

- Directive expected HEAD `0d40d3c` with pending `.agent/**` edits. Observed: branch `agent/supervised-codex`, HEAD `619a5912c8c8fd6bd44eb1e4f80c1823592cfeb3` (`docs: record reviewed checkpoint b111553a-669`, touches only `.agent/**`), worktree clean before this note.
- The expected tracking changes appear to be already committed in `619a591`. Per the directive's HEAD-mismatch rule, no commit was created. This handoff note is the only change, and it is uncommitted.
- Next step: the supervisor should confirm that `619a591` is the intended checkpoint and then reissue the directive.

# Current Handoff - ai-supervisor secondary writable-root control-plane maintenance (2026-09-28; lease 9208502b-4cfb-4b8b-b2b5-b749cec0c993)

**Result:** `CONTROL_PLANE_CHANGE_READY_FOR_REVIEW` (work ID `1a20bf4b-8a3c-4f3b-9a8e-6cf6b493841d`). Agent: codex (`gpt-6-luna`, `max`; observed in supervisor state). Usage readings are unavailable per `AGENTS.md`.

## Done

- Established an isolated, offline clone of the framework at `/private/tmp/ai-supervisor-codex-1a20bf4b-8a3c-4f3b-9a8e-6cf6b493841d`, based on clean `main` `6e369bf`. Work is on `codex/secondary-writable-roots`, commit `dd8b0ed`; the clone has no remote and is clean.
- Added an empty-by-default trusted `secondary_writable_roots` config allowlist and a separate per-work `writable_roots` selection exposed through `dispatch` and `queue-add` as repeated `--writable-root` options. Unselected roots and autonomy-planner requests are not passed through.
- Added canonical path and Git-root checks; rejects untrusted, broad, protected, detached/protected-branch, dirty-new-work, symlinked, and symlink-escaping roots. Codex receives only selected roots through `--add-dir`; such launches start fresh because the installed `codex exec resume` help does not accept `--add-dir`. Claude receives the same selected roots through sandbox `allowWrite`. Read-only work rejects root selections, and Codex `extra_args` cannot inject `--add-dir`.
- Read-only resolver validation of `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions` passed at its canonical path on clean branch `action/bm023a-trusted`, with no symlink escape found. The reviewed snapshot was explicitly protected during that check and remains untouched.
- Focused offline tests passed **64/64** across the new regression tests, workflow, and policy controls. `dispatch --help`, `queue-add --help`, and `git diff --check` passed.

## Not done and limits

- Full suite run: **643 tests; 597 passed, 2 failed, 44 errors**. Most errors came from loopback test servers whose `bind()` was denied by the sandbox; a synthetic subprocess recovery test timed out, and the two failures were process-identity/soak recovery checks. Focused tests pass after the final launch adjustment. No listener or network request succeeded.
- The active supervisor config and work state were not changed: `work.writable_roots` is null and the default allowlist remains empty. The framework change is not deployed, and no worker was given the secondary root in this task.
- The original framework checkout, dedicated action checkout, and reviewed snapshot were not modified. No Test.app, Kodi, LAN, network, or host validation action occurred.

## Smallest next step

Supervisor review the isolated branch/commit `dd8b0ed` and integrate it through the authorized framework route. After deployment, configure only the exact action checkout in trusted `secondary_writable_roots` and dispatch the BM-023A action update with `--writable-root /Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions`. Keep `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.9` read-only and do not repoint validation actions to framework main. No user input is required.

---

# Previous Handoff - BM-023A fixed staging action update (2026-09-28; lease c2301cf6-fb94-42b0-8179-bb7bfe38de98)

**Result:** `REVIEW_REQUIRED_ACTION_WRITE_ROUTE`.
Work ID: `5ba09aea-b318-4a27-bd49-9267648dd2d2`. Agent: codex (`gpt-6-luna`, `max`; observed in supervisor state). Usage readings are unavailable per `AGENTS.md`.

## Verified

- Product worktree is clean on `agent/supervised-codex` at `4a8d8c78ee0179bbf5fa77bcf7f2d5ef3e1873d2`; the latest commit changes only `.agent` tracking files.
- Read-only `PYTHONDONTWRITEBYTECODE=1 python3 tools/check_bm023a_stage_source.py` fails closed with `parent_not_substantive`: HEAD `4a8d8c7` is a tracking commit stacked on another tracking commit. Its diagnostic identifies reviewed source `72e327eb9af2c32d443b3a69fb3cd8237fa14fd2`, adapter `0.0.10`, and no product drift. That source resolves to tree `8a15b91ecd15c966faa6ef9ab3658bafae2dcfd6` in both the product checkout and the dedicated snapshot.
- Fixed action checkout is clean on `action/bm023a-trusted` at `68d05aead64dba1eeb8782946becd0be8fb29d21`. Its latest change requires a current matching tracking/substantive pair; it does not stage the reviewed Build Manager add-on with the adapter. The reviewed snapshot is clean but HEAD remains stale at `b0a56f67f0f6092836f2237b21fbdd55b13124bc` (tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`); the exact reviewed `72e327e` commit is present in it.
- The action checkout and canonical framework checkout exist but are not writable in this lease. Supervisor state has no `work.writable_roots`, `work.actions` is empty, and `handoff_requested=false`; the only configured writable root is this product worktree (plus temporary roots). The reviewed-source snapshot remains read-only as directed.
- The current directive explicitly says no host validation action is authorized for this work item. No Test.app action, Kodi action, network access, or device action occurred.

## Not done

No action implementation or regression tests were changed, and no action tests or full suite were run. Independent review/pinning, Test.app staging/verification, and `bm023a-recover` were not performed. The action write route is absent; the source preflight also currently rejects the stacked tracking pair. No product files outside `.agent` were changed.

## Smallest next step

Internal review should issue a new offline workspace-write lease with an exact writable root for `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions`, leaving the reviewed-source snapshot read-only. Then make the fixed action stage the exact reviewed add-on together with the adapter, preserve fail-closed identity checks, add regression coverage, and independently review/pin the exact action change. Keep all Test.app activity stopped under this work item's explicit no-host-validation restriction; recovery must remain conditional on a later authorized validation directive and passing source identity checks.

**Human input:** None. This is an internal scope/tooling blocker.

---

# Previous Handoff - BM-023A staging-precondition preflight (2026-09-28; lease 276211ae-e0ca-4d25-baae-5af012153d67)

**Result:** `OFFLINE_STAGE_SOURCE_PREFLIGHT_COMPLETE` (uncommitted, for the reviewed-checkpoint mechanism).
Work ID: `50118de2-ef3e-4b81-be18-269326b62e57`. Agent: claude (`claude-opus-5-5`).

## Done

- Added `tools/check_bm023a_stage_source.py`: read-only git preflight replicating the trusted adapter's (`ai_supervisor/bm023a_adapter_upgrade.py` at `68d05ae`) HEAD/HEAD^ checkpoint-pair selection. Prints JSON with the would-be-staged commit, its literal `ADAPTER_VERSION` (parsed via `ast`, not imported), and non-`.agent/` paths changed between it and HEAD. Exits 1 with a sanitized `category` (`head_unavailable`, `head_metadata_incomplete`, `head_not_tracking`, `parent_unavailable`, `parent_metadata_incomplete`, `parent_not_substantive`, `pair_metadata_mismatch`, `adapter_version_unavailable`, `product_changes_after_source`, `git_unavailable`). On pair failure it also reports `nearest_substantive` from a first-parent walk capped at 64 commits (diagnostic only; the trusted adapter never uses it).
- Added `tests/test_check_bm023a_stage_source.py` (9 tests, temporary git repos): valid pair, tracking-over-tracking, mismatched review/source/snapshot trailers, missing HEAD/parent trailers, HEAD substantive, tracking-commit product drift, missing adapter version, non-repository.
- Checks: new tests 9/9; adapter tests `tests.test_bm023a_adapter` 51/51; full offline suite **1,889/1,889**; `git diff --check` clean (new untracked files also checked with `--no-index --check`).
- Live read-only run on this worktree: HEAD `7f05566` (tracking) -> `parent_not_substantive`; nearest substantive `fae686b` declares `0.0.10` with no non-`.agent` product changes to HEAD. This confirms that staging fails today only because tracking commits are stacked, not because of product drift.
- Not modified: `tools/bm023a_adapter/**`, `tools/build_bm023a_adapter.py`, `tools/bm023a_adapter_support.py`, `resources/**`. No commit, rebase, network, LAN, Test.app, host, or device action.
- Note: the directive cited HEAD `d4f61f5`; actual HEAD was `7f05566` (another tracking checkpoint for work `10761739`), with a clean tree and no pending `.agent` diffs. Same failure mode, so not contradictory.

## Smallest next step

Supervisor review and checkpoint of this diff. That checkpoint makes a new substantive/tracking pair at HEAD, so staging becomes valid again. Staging that new pair still needs its own directive. Before staging, run `python3 tools/check_bm023a_stage_source.py`: it should print `ok: true` and version `0.0.10`. No user input required.

---

# Current Handoff - ai-supervisor Codex writable-root propagation (2026-09-27; lease 261bc5cf-43a7-4a49-9a4a-b87b134477bb)

**Result:** `REVIEW_REQUIRED_INTERNAL_ROOT_SOURCE_AND_WRITE_ROUTE`.
Work ID: `edad8d24-aee6-466f-ada1-f6f8f50594c0`.

## Verified state

- The product workspace is clean on `agent/supervised-codex` at `d4f61f5`. The framework checkout `/Users/eengert/Documents/Kodi/tools/ai-supervisor` is clean on `main` at `08b7689`, but `os.access(..., W_OK)` is false; it is outside this lease's writable roots.
- Active supervisor state reports work ID `edad8d24-aee6-466f-ada1-f6f8f50594c0`, mode `workspace-write`, and network `offline`. Neither the active `lease` nor `work` object contains an approved writable-root field. Their key sets were inspected; `lease.ipc_workspace` identifies only the worker workspace.
- `ai_supervisor/lease.py` constructs lease records with owner/ID/timing/process/output fields, `ipc_workspace`, and `launch_token`; it has no exact extra-root field. `ai_supervisor/launcher.py` launches Codex with the selected sandbox mode and disables sandbox network access; it adds no approved-root `--add-dir` arguments. Repository search found no approved writable-root source. Prompt text is not an authority source.
- The exact-root source prerequisite is absent. Per directive, implementation and regressions were not started and focused framework tests were not run. No source files changed.
- No network, LAN, host validation, adapter staging, Test.app, or device action occurred. Observed Codex model/effort: `gpt-6-luna` / `max`. Usage readings are unavailable per `AGENTS.md`.

## Smallest next step

Supervisor review must establish a trusted, explicit root-list field in the work/lease contract and grant this worker's sandbox write access to the framework checkout if it is an approved target. Then implement canonicalization and protected/symlink-escape rejection, pass only those roots to Codex (workspace alone when the list is empty), add offline regressions, and run focused tests. No user decision is required by this blocker.

---

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (2026-09-27; lease 2adabd6b-9169-4295-aa2b-c87ea48ead1c)

**Result:** `REVIEW_REQUIRED_INTERNAL_WRITE_ROUTE`.
Work ID: `44100602-496e-46ba-9561-e13143fe20d7`.

## Verified state

- Product checkout is `agent/supervised-codex` at `895069324bdf6de32baebfe96a32277e3e9c8871`. Reviewed commit `fae686b9c4bb84fa862232f6c388e9d00c4f9fda` is a commit object in the dedicated snapshot and resolves to expected tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`; its reviewed metadata identifies review `74da9559-1b2f-4466-866f-de3106a7005c` and source work `2d09e1df-1cbc-4f8e-96bc-a4c3c26af415`. The adapter template and support declare `0.0.10`.
- The named action worktree `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions` is clean on `action/bm023a-trusted` at `68d05aead64dba1eeb8782946becd0be8fb29d21`. Its current implementation selects a review checkpoint dynamically and derives the adapter version; it does not consume the dedicated snapshot or enforce the requested exact source, clean snapshot, and fixed `0.0.10` guards.
- The dedicated snapshot `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10` is clean and detached at stale `b0a56f67f0f6092836f2237b21fbdd55b13124bc` (tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`). The reviewed commit's identity and tree match the directive; no mismatch was found.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** at action HEAD `68d05aead64dba1eeb8782946becd0be8fb29d21`. The existing tests do not cover the requested exact-source, clean-snapshot, or fixed-version guards.
- Despite the directive naming both external targets as this lease's writable scope, `test -w` reports both paths non-writable in the actual worker sandbox. No action or snapshot files changed. No adapter was staged; Test.app, host validation, and network were not accessed.
- Observed Codex model/effort: `gpt-6-luna` / `max`. Remaining-usage readings are recorded as unavailable per `AGENTS.md`.

## Smallest next step

Internal review to restore the worker's write route for the named action worktree and dedicated snapshot. Then advance the clean snapshot to `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, implement exact-source / clean-snapshot / fixed-`0.0.10` guards with offline regressions, and rerun the focused action tests. No user decision is needed.

## Human input

None. This is an internal writable-scope/tooling blocker.

---

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (2026-09-27; lease d90e46c9-98c8-4ac4-9c83-6d68d1994326)

**Result:** `REVIEW_REQUIRED_WRITE_SCOPE`.
Work ID: `7f7985ce-0e9f-4dc4-9e4e-25e156064382`.

## Verified state

- The reviewed source checkpoint is `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`, parent `873e82530933e25dcae3ab9e83665dc35d127281`; its reviewed metadata identifies review `74da9559-1b2f-4466-866f-de3106a7005c` and source work `2d09e1df-1cbc-4f8e-96bc-a4c3c26af415`. The checkpoint declares adapter version `0.0.10`.
- Product checkout is `agent/supervised-codex` at `8685fd1eb0433088ea08f9f5c4e35ded0a1c7658`. Existing changes are confined to `.agent` tracking files; this lease made no product implementation changes.
- Canonical trusted action checkout `/Users/eengert/Documents/Kodi/tools/ai-supervisor` is clean on `main` at `107ca9869c05abc9acc01143b34d3dcf9571115d`. Current tests still cover dynamically selected reviewed checkpoints and deriving version from source; the requested exact source pin, dedicated snapshot clean-tree requirement, and fixed `0.0.10` enforcement remain absent.
- Dedicated snapshot `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10` is clean and detached at stale commit `b0a56f67f0f6092836f2237b21fbdd55b13124bc`, tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** at action HEAD `107ca986`. The action checkout and snapshot are outside this lease's writable root, which is limited to the supervised product checkout and temporary roots. This is an internal writable-scope review blocker; checkpoint and workspace identities are unambiguous.
- No action or snapshot files changed. No adapter was staged; Test.app, host validation, and network were not accessed. Observed Codex model/effort: `gpt-6-luna` / `xhigh`. Usage readings are unavailable per `AGENTS.md`.

## Smallest next step

Grant this worker writable scope to the canonical trusted action checkout and dedicated snapshot. Then pin exact source HEAD `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, require the dedicated snapshot to be clean, enforce version `0.0.10`, add fail-closed offline regression coverage, and rerun the action tests. Do not stage an adapter or interact with Test.app in this work item.

## Human input

None. Internal writable-scope review is required.

---

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (2026-09-27; lease a866c424-46f1-479f-9deb-9d341938f287)

**Result:** `REVIEW_REQUIRED_WRITE_SCOPE`.
Work ID: `7f7985ce-0e9f-4dc4-9e4e-25e156064382`.

## Verified state

- Reviewed source checkpoint identity remains exact: `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`, parent `873e82530933e25dcae3ab9e83665dc35d127281`; metadata identifies review `74da9559-1b2f-4466-866f-de3106a7005c` and source work `2d09e1df-1cbc-4f8e-96bc-a4c3c26af415`. Its adapter template is version `0.0.10`.
- Product checkout is `agent/supervised-codex` at `8685fd1eb0433088ea08f9f5c4e35ded0a1c7658`; this lease changed only `.agent` tracking files.
- Canonical trusted action checkout `/Users/eengert/Documents/Kodi/tools/ai-supervisor` is clean on `main` at `107ca9869c05abc9acc01143b34d3dcf9571115d`. Relevant commit `09f5a1a95d84cef125b1138e6ac67504a3e22146` changed selection to the current reviewed tracking/substantive pair and removed the product clean-tree gate. Current code still does not pin the exact source HEAD, require the dedicated snapshot to be clean, or enforce version `0.0.10`.
- Dedicated snapshot `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10` is clean and detached at stale commit `b0a56f67f0f6092836f2237b21fbdd55b13124bc`, tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`.
- Focused action tests were rerun: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** at action HEAD `107ca986`. Both external worktrees stayed clean. No action or snapshot files changed; no adapter was staged and Test.app, host validation, and network were not accessed.
- The action checkout and snapshot are outside this lease's writable root, limited to this supervised product checkout and temporary roots. This is an internal writable-scope review blocker; the checkpoint and workspace identities are unambiguous.
- Observed Codex model/effort: `gpt-6-luna` / `xhigh`. Usage readings are unavailable per `AGENTS.md`.

## Smallest next step

Grant this worker writable scope to the canonical trusted action checkout and dedicated snapshot. Then pin exact source HEAD `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, require the dedicated snapshot to be clean, enforce version `0.0.10`, add fail-closed offline regression coverage, and rerun the action tests. Do not stage an adapter or interact with Test.app in this work item.

## Human input

None. Internal writable-scope review is required.

---

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (2026-09-27; lease ed537aa2-f108-464f-8378-52842a8a0b42)

**Result:** `REVIEW_REQUIRED_WRITE_SCOPE`.
Work ID: `7f7985ce-0e9f-4dc4-9e4e-25e156064382`.

## Verified state

- Reviewed source commit `fae686b9c4bb84fa862232f6c388e9d00c4f9fda` has tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`, parent `873e82530933e25dcae3ab9e83665dc35d127281`, and reviewed-checkpoint metadata for review `74da9559-1b2f-4466-866f-de3106a7005c` and source work `2d09e1df-1cbc-4f8e-96bc-a4c3c26af415`. Its adapter template declares `0.0.10`.
- Product checkout remains `agent/supervised-codex` at `8685fd1eb0433088ea08f9f5c4e35ded0a1c7658`; only the existing `.agent` tracking files are modified. No product implementation files changed.
- Canonical trusted action checkout `/Users/eengert/Documents/Kodi/tools/ai-supervisor` is clean on `main` at `107ca9869c05abc9acc01143b34d3dcf9571115d`. Commit `09f5a1a` removed the fixed source HEAD and clean-tree checks and made source selection dynamic; the current action derives the version rather than pinning `0.0.10`.
- Dedicated snapshot `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10` is clean and detached at stale commit `b0a56f67f0f6092836f2237b21fbdd55b13124bc` (tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`).
- Both required targets are outside this lease's writable root, which is limited to this supervised product checkout and temporary roots. Their identities are unambiguous, so this is an internal write-scope review blocker.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** at action HEAD `107ca986`. The trusted action remained clean on `main` and the dedicated snapshot remained clean at stale `b0a56f6`. No action or snapshot files changed. No adapter was staged; Test.app, host validation, and network were not accessed.
- Observed Codex model/effort: `gpt-6-luna` / `xhigh`. Usage readings are unavailable per `AGENTS.md`.

## Smallest next step

Grant this worker writable scope to the canonical action checkout and dedicated snapshot. Then pin exact source HEAD `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, require the dedicated snapshot to be clean, and enforce version `0.0.10` with fail-closed offline regressions. Do not stage an adapter or interact with Test.app under this work item.

## Human input

None. Internal writable-scope review is required.

---

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (2026-09-27; lease 1c00cd61-c3ba-4e84-bdf1-532d65953650)

**Result:** `REVIEW_REQUIRED_WRITE_SCOPE`.
Work ID: `7f7985ce-0e9f-4dc4-9e4e-25e156064382`.

## Verified state

- The reviewed source commit is `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`, parent `873e82530933e25dcae3ab9e83665dc35d127281`. Its reviewed-checkpoint metadata identifies review `74da9559-1b2f-4466-866f-de3106a7005c`, source work `2d09e1df-1cbc-4f8e-96bc-a4c3c26af415`, and product adapter version `0.0.10`.
- Product checkout is `agent/supervised-codex` at `8685fd1eb0433088ea08f9f5c4e35ded0a1c7658`; its only changes are the existing `.agent` handoff metadata files.
- Canonical trusted action checkout `/Users/eengert/Documents/Kodi/tools/ai-supervisor` is clean on `main` at `107ca9869c05abc9acc01143b34d3dcf9571115d` (tree `85931ec309f57f7c5ddcd1ea2a7c37279a872ee3`), aligned with `origin/main`. Commit `09f5a1a` changed staging to select the current review checkpoint dynamically and removed the dirty-product-tree gate. The action derives version from source; it does not pin this reviewed HEAD, require a clean dedicated snapshot, or enforce version `0.0.10`.
- Dedicated snapshot `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10` is clean and detached at stale commit `b0a56f67f0f6092836f2237b21fbdd55b13124bc` (tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`), not the reviewed source.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** at action HEAD `107ca986`. The action checkout remained clean after the run. No action or snapshot files changed; no adapter was staged, and Test.app, host validation, and network were not accessed.
- Both requested write targets are outside this worker's writable root, which is limited to the supervised product checkout and temporary roots. The source and canonical action workspace identities are clear; this is an internal writable-scope review blocker, not a user decision. Observed Codex model/effort: `gpt-6-luna` / `xhigh`; usage readings for this lease are unavailable per `AGENTS.md`.

## Smallest next step

Grant writable scope to the canonical action checkout and dedicated snapshot. Then pin the exact reviewed source HEAD and fixed `0.0.10` version, enforce a clean dedicated snapshot and fail-closed regression coverage, and rerun the focused offline action tests. Do not stage an adapter or interact with Test.app under this work item.

## Human input

None. Internal writable-scope review is required.

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (lease 18761afb-d8aa-487a-85e7-568dfdcdaee3)

**Result:** `REVIEW_REQUIRED_WRITE_SCOPE`; adapter implementation and snapshot update were not started.
Work ID: `7f7985ce-0e9f-4dc4-9e4e-25e156064382`; supervisor lease: `18761afb-d8aa-487a-85e7-568dfdcdaee3`.

## Verified identities and validation

- Product checkout is `agent/supervised-codex` at `8685fd1eb0433088ea08f9f5c4e35ded0a1c7658`; the exact reviewed source commit is `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`, parent `873e82530933e25dcae3ab9e83665dc35d127281`. The checkpoint driver declares version `0.0.10`.
- The documented trusted action checkout is `/Users/eengert/Documents/Kodi/tools/ai-supervisor`, clean on `main` at `ca4515f` and aligned with `origin/main`. The single commit since the previous handoff HEAD `a581472` changes portability files only; the BM-023A action and test files are unchanged. Focused offline action tests `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** at `ca4515f`. Existing coverage still selects reviewed checkpoints dynamically and derives the version from source; it does not pin this exact source HEAD, require the dedicated product snapshot to be clean, or fix version `0.0.10`.
- Dedicated snapshot `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10` remains clean and detached at stale commit `b0a56f67f0f6092836f2237b21fbdd55b13124bc` (tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`), not `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`.
- The trusted action checkout and dedicated snapshot are outside this worker's writable root, which is the supervised product checkout; both were confirmed non-writable. The action remained clean after testing. No action or snapshot files changed. No adapter was staged; Test.app, host validation, network, Kodi profile, and device actions were not used. Supervisor state identified the active Codex model/effort as `gpt-6-luna` / `xhigh`; usage readings are recorded as unavailable per `AGENTS.md`.

## Blocker and next step

This is an internal writable-scope review gate; no user decision is needed. The checkpoint and canonical action checkout identities are established, and the focused offline baseline is current and passing, but the requested action and snapshot changes cannot be written from this worker's permitted scope.

**Smallest next step:** grant writable scope to the trusted action checkout and dedicated snapshot, then pin source `fae686b9c4bb84fa862232f6c388e9d00c4f9fda`, enforce exact HEAD, clean-snapshot, and fixed `0.0.10` checks fail-closed with regression coverage, and rerun the focused offline action tests. Do not stage an adapter or interact with Test.app under this work item.

**Human input:** none; this requires internal scope review.

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (lease e04bcc32-d02d-4369-80e5-3c7f93e53708)

**Result:** `REVIEW_REQUIRED_WRITE_SCOPE`; `IMPLEMENTATION_NOT_STARTED`.
Prior lease: `e04bcc32-d02d-4369-80e5-3c7f93e53708`.

## Verified identities and validation

- Product checkout: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-supervised-codex`, branch `agent/supervised-codex`, HEAD `8685fd1eb0433088ea08f9f5c4e35ded0a1c7658`. The exact reviewed source is `fae686b9c4bb84fa862232f6c388e9d00c4f9fda` (tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`), parent `873e82530933e25dcae3ab9e83665dc35d127281`; its driver `addon.xml.in` declares version `0.0.10`.
- Handoff-designated trusted action checkout: `/Users/eengert/Documents/Kodi/tools/ai-supervisor`, clean on `main` at `039a8d4b141c069230843990e117d06142a40878` (71 commits ahead of `origin/main`). A separate action branch worktree exists at `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions`, branch `action/bm023a-trusted`, HEAD `68d05aead64dba1eeb8782946becd0be8fb29d21`; it remains unselected and untouched.
- Dedicated snapshot: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10`, clean and detached at stale commit `b0a56f67f0f6092836f2237b21fbdd55b13124bc` (tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`).
- Action offline tests: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** against action commit `039a8d4`; the action checkout remained clean after the test. Its current implementation still selects a reviewed checkpoint dynamically and derives the version from source; coverage for exact source HEAD, a clean dedicated snapshot, and a fixed `0.0.10` version is not present.
- The trusted action and snapshot are outside this work item's writable roots. No implementation or test file was changed. This lease changed only `.agent/HANDOFF.md`, `.agent/CURRENT_TASK.md`, `.agent/AGENT_STATUS.json`, and `.agent/USAGE_HISTORY.md`; no commit was created. No adapter was staged, and no Test.app, host validation, network, device, or profile action occurred. Usage readings for this lease are unavailable per `AGENTS.md`; observed model/effort in supervisor state: `gpt-6-luna` / `xhigh`.

## Blocker and next step

The checkpoint and action workspace identities are established and unambiguous. The internal blocker is write scope: this worker can write only the supervised product checkout and permitted temporary roots, while the trusted action and dedicated snapshot are elsewhere. The baseline tests passed, but the requested action pin, snapshot update, and regression coverage remain unimplemented.

**Smallest next step:** provide writable scope for the trusted action checkout and dedicated snapshot, then pin the action to reviewed source `fae686b9c4bb84fa862232f6c388e9d00c4f9fda` with fail-closed exact-HEAD, clean-worktree, and fixed-`0.0.10` checks and regression coverage. Rerun the action's offline tests. Do not stage an adapter or use Test.app under this work item.

**Human input:** none; writable-scope review is the remaining internal gate.

# Previous Handoff - BM-023A dedicated 0.0.10 staging snapshot pin (lease 5686e37f-a619-4d85-9ffc-b52ad2d6b365)

**Result:** `REVIEW_REQUIRED_WRITE_SCOPE`; `IMPLEMENTATION_NOT_STARTED`.
Lease: `5686e37f-a619-4d85-9ffc-b52ad2d6b365`.

## Verified identities and validation

- Product checkout: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-supervised-codex`, branch `agent/supervised-codex`, HEAD `8685fd1eb0433088ea08f9f5c4e35ded0a1c7658`. The exact reviewed source is `fae686b9c4bb84fa862232f6c388e9d00c4f9fda` (tree `1fff8d902d9e490ddd1ef73f4d4cc3eaab288542`), parent `873e82530933e25dcae3ab9e83665dc35d127281`; it is the parent of the tracking HEAD.
- Handoff-designated trusted action checkout: `/Users/eengert/Documents/Kodi/tools/ai-supervisor`, clean on `main` at `039a8d4b141c069230843990e117d06142a40878` (71 commits ahead of `origin/main`). A separate action branch worktree exists at `/Users/eengert/Documents/Kodi/tools/ai-supervisor-bm023a-actions`, branch `action/bm023a-trusted`, HEAD `68d05aead64dba1eeb8782946becd0be8fb29d21`; it was not selected because the current handoff identifies the canonical `tools/ai-supervisor` checkout as the trusted target, and it was left untouched. The designated checkout selects reviewed checkpoints dynamically and lacks the requested exact source HEAD, clean-worktree, and fixed `0.0.10` gates; its tests permit product-tree drift and derive version from source.
- Dedicated snapshot: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-bm023a-reviewed-0.0.10`, clean and detached at stale commit `b0a56f67f0f6092836f2237b21fbdd55b13124bc` (tree `bbd68a0fdd4322af498661c3e59de79335f4f4aa`).
- Action offline tests: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm023a_adapter_upgrade -v` passed **6/6** in this lease against designated action commit `039a8d4`. The action checkout remained clean after the test. These current tests do not cover exact-source-HEAD, clean-worktree, or fixed-`0.0.10` gates; the implementation still selects a reviewed checkpoint dynamically and derives its version from source.
- The trusted action checkout and dedicated snapshot are outside this work item's writable roots. No implementation or test file was changed. This lease updated only `.agent/HANDOFF.md`, `.agent/CURRENT_TASK.md`, `.agent/AGENT_STATUS.json`, and `.agent/USAGE_HISTORY.md`; prior tracking changes were preserved and no commit was created. No adapter was staged, and no Test.app, host validation, network, device, or profile action occurred. Codex model/effort in supervisor state: `gpt-6-luna` / `xhigh`. App-server usage snapshots were 5h 93% / 7d 90% remaining at 15:46:46 and unchanged at 15:49:00; delta 0 percentage points in both windows.

## Blocker and next step

The checkpoint and handoff-designated action workspace identities are established. The internal blocker is write scope: this worker can write only the supervised product checkout and permitted temporary roots, while the trusted action and snapshot are elsewhere. Per the directive, this is review-required rather than a user-input gate. The action tests establish the current baseline only; the requested pin and regression coverage remain unimplemented. Only the action's focused offline tests were run; no full repository suite was run because no implementation change was possible and the directive limited validation to the action tests.

**Smallest next step:** provide writable scope for the trusted action checkout and dedicated snapshot, then pin the action to reviewed source `fae686b9c4bb84fa862232f6c388e9d00c4f9fda` with fail-closed exact-HEAD, clean-worktree, and fixed `0.0.10` checks and regression coverage. Rerun the action's offline tests. Do not stage an adapter or use Test.app under this work item.

**Human input:** none; writable-scope review is the remaining internal gate.

# Prior Handoff - BM-023A source mismatch observability (2026-09-27)

**Result:** `OFFLINE_SOURCE_MISMATCH_OBSERVABILITY_COMPLETE`;
`RECOVERY_NOT_INVOKED`.

## What changed

- `tools/bm023a_adapter_support.py` now carries the expected and observed
  SHA-256 values on a source fingerprint mismatch. The safe failure serializer
  includes those two values only for `VERIFY_BUILD_MANAGER_SOURCE` /
  `module_source_mismatch`, and only when both are distinct lowercase
  64-character digests.
- Missing and unreadable source now produce separate fixed categories,
  `module_source_missing` and `module_source_unreadable`. Neither category
  includes digest metadata.
- `tests/test_bm023a_adapter.py` covers matching, mismatching, missing, and
  unreadable source, as well as the generated JSON result shape and the
  no-recovery fail-closed path.

## Validation and boundaries

- Focused BM-023A adapter tests: **51/51 passed**.
- Full offline suite: **1,880/1,880 passed**.
- `git diff --check`: passed.
- No Test.app, Kodi profile, device, network, staging, or recovery action was
  accessed or invoked. Validation was offline unit testing.
- Product changes are limited to `tools/bm023a_adapter_support.py` and
  `tests/test_bm023a_adapter.py`. No commit was created.
- The supervisor state provided a task-start usage snapshot
  (`gpt-6-luna`, `max`; five-hour 96% and seven-day 94% remaining). No
  end snapshot was available; the usage row records this without estimating.

**Smallest next step:** independent read-only review of this exact offline
diff. Any staging or Test.app action requires its own directive.

**Human input:** none is required for this completed directive. The historical
staging-action input blocker is retained below for context.

---

## Historical Needs User Input - prior staging action pin (2026-09-26 state)

At that prior inspection, the requested staging action and its offline tests were in
`/Users/eengert/Documents/Kodi/tools/ai-supervisor`, outside this task's
writable root (`script.build.manager-supervised-codex`). The action then pinned
the 0.0.9 worktree and commit, and no 0.0.10 reviewed worktree existed. The
current action/snapshot findings are recorded at the top of this handoff.

The 0.0.10 source can be identified exactly: commit
`b0a56f67f0f6092836f2237b21fbdd55b13124bc`, tree
`bbd68a0fdd4322af498661c3e59de79335f4f4aa`, builder SHA-256
`26c396dc2632549d1a40e58b313e8c814ad90666935a2f0e0453c403e190384f2`, and
adapter support SHA-256
`736c4faece50656539f2db80d2f0aa45520ba015640750cb358de5df09626bdd`. The
staging action still needs a dedicated clean 0.0.10 snapshot workspace and
its matching HEAD/version checks, plus offline action coverage.

**Prior next step:** provide a work item/workspace that grants write access to
`tools/ai-supervisor` and authorizes provisioning the dedicated 0.0.10 source
snapshot, or move the action and tests into this writable repository.

# Prior Handoff - BM-023A staging action 0.0.10 source pin (2026-09-26)

**Result:** `BLOCKED_OUTSIDE_WRITABLE_WORKSPACE`; staging action unchanged.

## Findings

- The product tree was clean at inspection on HEAD
  `e7043c59cfc1c432b1d8c75394e12f386faa90af`; only `.agent` tracking files
  changed for this handoff.
- The trusted staging implementation and coverage are
  `tools/ai-supervisor/ai_supervisor/bm023a_adapter_upgrade.py` and
  `tools/ai-supervisor/tests/test_bm023a_adapter_upgrade.py`.
- The action currently pins worktree
  `script.build.manager-bm023a-reviewed-0.0.9`, HEAD
  `4791438dececcc84b3fe3aae5c3861e4d55c02da`, and version 0.0.9. Git confirms
  that no dedicated 0.0.10 worktree exists.
- The reviewed adapter source is exactly pin-able at commit
  `b0a56f67f0f6092836f2237b21fbdd55b13124bc` and tree
  `bbd68a0fdd4322af498661c3e59de79335f4f4aa`. Its builder and adapter-support
  file hashes are recorded above.

## Not done

No staging-action implementation or tests were changed or run because their
repository is outside the writable workspace. No host validation, staging,
Kodi/Test.app access, device access, or network access occurred. The
Build Manager product checkout remains unchanged; only `.agent` handoff and
tracking files were updated.

**Smallest next step:** grant the action repository as a writable workspace
and provision a dedicated clean worktree at the exact reviewed 0.0.10 commit;
then update the preserved workspace identity, clean-tree and HEAD checks,
version gate, and offline tests.

**Human input:** see “Needs User Input” above.

---

# Prior Handoff - BM-023A production module binding guard (2026-09-26)

**Result:** `OFFLINE_MODULE_SOURCE_BINDING_CORRECTION_COMPLETE`;
`LIVE_RETRY_NOT_RUN`.

## Diagnosis

- The 0.0.9 driver verified the installed `resources.lib` package file, then
  imported `resources.lib.frozen_install` and checked only whether the retry
  method was callable. `importlib.import_module` returns a cached child from
  `sys.modules` without rereading the current source. A prior module object
  retaining the retry method could therefore pass the callable guard while
  the on-disk file lacks it; an exception from that call is sanitized as
  `INVOKE_RETRY` / `operation_failed`.
- This explains the reported result, but the failed invocation's module-cache
  state was not retained, so the exact cached object's prior source cannot be
  confirmed. The trusted staging action builds and replaces only the
  temporary driver package; it does not update the installed Build Manager
  production source.

## What changed

- Adapter version is now **0.0.10**. The builder pins the SHA-256 of the
  reviewed `resources/lib/frozen_install.py` into the generated driver config.
- Before importing production children, the driver rejects any required
  child module already in `sys.modules`. It also verifies the root package
  search path, the frozen-install source fingerprint, and each imported
  child module's resolved file and loader origin beneath the installed add-on.
  Mismatch and cache failures use fixed allowlisted diagnostics without
  exception text.
- The generated-entrypoint harness now simulates fresh imports and covers a
  preloaded coordinator carrying the old callable plus an on-disk source
  fingerprint mismatch. Production lifecycle code is unchanged.

## Validation and boundaries

- BM-023A adapter tests: **51/51 passed**.
- Full offline suite: **1,880/1,880 passed**; compileall and
  `git diff --check` passed.
- No Test.app, Kodi, profile, device, network, staging action, or live retry
  was accessed or used. No commit, push, or matrix integration was made.
- Changes are uncommitted on `agent/supervised-codex` in
  `tools/bm023a_adapter_support.py`, `tools/bm023a_adapter/default.py.in`,
  `tools/bm023a_adapter/addon.xml.in`, `tools/build_bm023a_adapter.py`, and
  `tests/test_bm023a_adapter.py`. No change was made to
  `resources/lib/frozen_install.py`.

**Smallest next step:** supervisor review, then update the trusted staging
action's reviewed source/version pin to 0.0.10. Stage only under a separate
directive. Before retry, the installed Build Manager source must match the
fingerprint in the staged driver; otherwise it will fail closed at source
verification.

---

# Prior Handoff - BM-023A authorized Test.app retry (2026-09-26)

**Result:** `RETRY_ACTION_FAILED`; `STOPPED_WITHOUT_POSTFLIGHT`.

## Public preflight

- `test-app-kodi` returned `pong` from `JSONRPC.Ping`.
- Red Light `plugin.video.redlight` was version `2.6.8`, disabled, and not
  broken.
- `general.addonupdates` was `2`; `lookandfeel.skin` was
  `skin.arctic.fuse.3`.
- All required retry preflight checks passed. The supervisor directive
  accepted the prior restore revision gate; restore-config was not repeated.

## Authorized retry and stop condition

- Requested `bm023a-retry` exactly once. The final sanitized wrapper result
  was `ok=true`, `cancelled=false`, `timed_out=false`, `return_code=0`.
- The adapter result was `ok=false`, `adapter_mode=retry`,
  `adapter_stage=INVOKE_RETRY`, `error_type=Exception`,
  `failing_callable=FrozenInstallCoordinator.retry_held_quiescence`, and
  `failure_category=operation_failed`.
- The action did not return `complete`. Per the directive, no postflight,
  second retry, install/recover action, or further Kodi call was made. No
  product source was changed and no tests were run.
- Tracking metadata updated: `.agent/HANDOFF.md`, `.agent/CURRENT_TASK.md`,
  `.agent/AGENT_STATUS.json`, and `.agent/USAGE_HISTORY.md`. No Git commit was
  created; the worktree was clean before these metadata updates.
- Codex usage snapshot at task start: `gpt-6-luna`, `max`, five-hour
  remaining `98%`, seven-day remaining `100%`. The final snapshot was
  unavailable in supervisor state at handoff.

**Smallest next step:** supervisor review of the sanitized
`INVOKE_RETRY`/`operation_failed` result and a separate directive if another
Test.app action is warranted. This work item authorizes no further action.

---

# Current Handoff - BM-023A configuration restore gate (2026-09-25)

**Result:** `RESTORE_RESULT_DID_NOT_MEET_EXACT_REVISION_GATE`; `RETRY_NOT_REQUESTED`.

## Authorized preflight

- `test-app-kodi` returned `pong` from `JSONRPC.Ping`.
- Red Light was version `2.6.8`, disabled, and not broken.
- `general.addonupdates` was `2`; `lookandfeel.skin` was
  `skin.arctic.fuse.3`.
- All required public preflight checks passed.

## Restore result and stop condition

- Requested `bm023a-restore-config` exactly once through the authorized
  supervisor action. Final sanitized wrapper result: `ok=true`,
  `cancelled=false`, `timed_out=false`, `return_code=0`.
- The action result reported `ok=true`, `restored=true`, SHA-256
  `924ab96558111c1a9050592da5296d07dfbfc35520c380a554beea73fed308c4`,
  and `size=4995`. It reported `source_revision=d8ab24ba`; the directive
  requires the exact value `d8ab24b`, so the restore gate was not accepted.
- Per the strict gate, `bm023a-retry` was not requested. No postflight,
  additional Test.app call, restart, or quit was performed. No product source
  was modified and no tests were run. Only this handoff was updated.

**Smallest next step:** supervisor review of the returned revision identifier
and a fresh directive if that identifier is accepted. Do not continue the
retry under this work item.

---

# Current Handoff - BM-023A Test.app 0.0.8 staging and held retry (2026-09-25)

**Result:** `ADAPTER_STAGED_0.0.8`; `RETRY_STOPPED_AT_CHECK_RETRY_PRECONDITIONS`.

## Authorized preflight

- `test-app-kodi` responded to `JSONRPC.Ping`; Kodi reported version 21.3,
  stable build.
- Build Manager 0.1.0 was enabled and not broken. The temporary driver was
  present, enabled, and not broken; its public add-on detail reported 0.0.4.
- Red Light was exactly 2.6.8, disabled, and not broken. Arctic Fuse 3 was
  3.3.1, enabled, and not broken.
- `general.addonupdates` was 2 (`NEVER_CHECK`); `lookandfeel.skin` was
  `skin.arctic.fuse.3`.
- The stage action later reported `version_before=0.0.7`, which differs from
  the preflight driver's public 0.0.4 detail. The mismatch was not resolved;
  no public driver read was made after the retry stopped.

## Authorized actions and result

- Requested `bm023a-stage-adapter` exactly once. Final sanitized wrapper
  result: `ok=true`, `cancelled=false`, `timed_out=false`, `return_code=0`.
  Adapter result: `already_current=false`, `version_before=0.0.7`,
  `version_after=0.0.8`, `files_verified=4`.
- After stage success, requested `bm023a-retry` exactly once. The wrapper
  completed with `ok=true`, `cancelled=false`, `timed_out=false`,
  `return_code=0`; the adapter result was `ok=false`,
  `adapter_mode=retry`, `adapter_stage=CHECK_RETRY_PRECONDITIONS`,
  `error_type=Exception`, `failing_callable=pathlib.Path`, and
  `failure_category=path_missing_or_unreadable`. No outcome was returned.
- Per the directive, made no additional Test.app call after the retry result.
  No postflight, second retry, install/recover action, restart, or quit was
  performed. No tests or product-source changes were made; only task tracking
  metadata was updated.

**Smallest next step:** supervisor review of the sanitized retry precondition
failure and the temporary driver's public-version/stage-version mismatch,
then decide whether to authorize another Test.app action.

---

# Prior Handoff - BM-023A missing durable retry artifact directory (2026-09-25)

**Result:** OFFLINE_PRECONDITION_CORRECTION_COMPLETE; LIVE_RETRY_NOT_RUN.

## What changed

- The generated retry entrypoint still requires the durable profile root and
  retained source `artifacts` directory to exist. It no longer requires the
  profile-local `frozen-artifacts/artifacts` directory to pre-exist;
  `ArtifactStore` initializes that child directory.
- The temporary adapter version is now **0.0.8**, so a later authorized stage
  can carry this correction over the already staged 0.0.7 package. No adapter
  package was staged in this work item.
- The generated-entrypoint regression builds and runs the package in the
  legacy state: durable root present, durable artifacts directory absent. It
  uses the production `ArtifactStore` constructor and verifies initialization.
  Missing durable root and missing retained source store cases still fail
  closed at `CHECK_RETRY_PRECONDITIONS`.

## Validation

- Generated-entrypoint regression: **1/1 passed**.
- Focused adapter, frozen-install, transaction, and restart-coordinator suites:
  **136/136 passed**.
- Full offline suite: **1,876/1,876 passed**.
- `git diff --check`: passed.
- The first generated-entrypoint run exposed a test assertion made after its
  temporary directory had been removed. The assertion now records directory
  initialization before fixture cleanup; the rerun and all suites passed.

No Test.app, Kodi profile, device, network, or host action was accessed or
used. No live retry/recovery was attempted. The work remains uncommitted on
`agent/supervised-codex`; no push or matrix integration occurred. Smallest
next step: supervisor review, followed by a separately authorized 0.0.8 stage
before any live retry.

---

# Prior Handoff - BM-023A live staging and held retry (2026-09-25)

**Result:** ADAPTER_STAGED_0.0.7; HELD_RETRY_FAILED_PRECONDITIONS.

## Authorized actions

- Re-read supervisor state under the current lease before each action;
  `handoff_requested` was false.
- Requested `bm023a-stage-adapter` exactly once through supervisor
  validation-action IPC. Final sanitized response: `ok=true`,
  `cancelled=false`, `timed_out=false`, `return_code=0`; adapter result
  `already_current=false`, `version_before=0.0.4`, `version_after=0.0.7`,
  `files_verified=4`.
- After the required staging evidence succeeded, requested `bm023a-retry`
  exactly once. The action wrapper returned `ok=true`, `cancelled=false`,
  `timed_out=false`, `return_code=0`; its adapter result returned `ok=false`,
  `adapter_mode=retry`, `adapter_stage=CHECK_RETRY_PRECONDITIONS`,
  `error_type=Exception`, `failing_callable=pathlib.Path`, and
  `failure_category=path_missing_or_unreadable`. No completion, restart, or
  held-state recovery evidence was returned.
- No further host action was requested. `bm023a-install` and
  `bm023a-recover` were not requested; Test.app was not restarted or quit.
  No tests or product-code changes were made; this handoff is the only
  repository file changed for this work item.
- Smallest next step: supervisor review of the held-retry precondition result
  and a fresh directive before any further host action. No user input was
  requested by this bounded work item.

---

## Prior Handoff - BM-023A live staging gate (2026-09-25)

**Result:** STAGING_BLOCKED_BY_VALIDATION_WORKSPACE_COMMIT_MISMATCH;
RETRY_NOT_REQUESTED.

## Authorized action

- Re-read supervisor state under the current lease; `handoff_requested` was
  false.
- Requested `bm023a-stage-adapter` exactly once through supervisor
  validation-action IPC after the App Management permission grant.
- Final sanitized response: `ok=false`, `error_type=ValidationActionError`,
  error `trusted validation workspace HEAD does not match configured commit`.
  The required success evidence (`ok=true`, `version_after=0.0.7`,
  `files_verified=4`) was not returned.
- Per the directive, did not request `bm023a-retry` or any other host action.
  No tests or product-code changes were made; this handoff is the only
  repository file changed for this work item.
- Smallest next step: supervisor review of the validation-workspace commit
  mismatch and a fresh directive before any further host action. No user input
  was requested by this bounded work item.

---

## Prior Handoff - BM-023A live staging attempt before App Management grant

**Result:** STAGING_FAILED; RETRY_NOT_REQUESTED.

The earlier one-shot staging request returned `ok=false`,
`error_type=AdapterUpgradeError`, error `temporary adapter upgrade failed`,
`cancelled=false`, `timed_out=false`, and `return_code=1`. It did not provide
the required success evidence (`ok=true`, `version_after=0.0.7`,
`files_verified=4`). The retry was not requested under that earlier directive.

---

# Prior Handoff - BM-023A generated-entrypoint dispatch coverage (2026-09-25)

**Result:** OFFLINE_COVERAGE_COMPLETE; INDEPENDENT_REVIEW_READY;
LIVE_RETRY_NOT_RUN.

## What changed

Added one executable offline test in `tests/test_bm023a_adapter.py`. It builds
the adapter package and runs its generated `default.py` for `install`,
`recover`, and `retry` with temporary paths and stubbed Kodi/production
modules. Each invocation proves the selected branch is the only dispatch:
install calls only `coordinator.install`, recover calls only the recovery
helper, and retry calls the packaged retry helper and
`retry_held_quiescence` once.

The retry fixture uses the actual packaged `retry_held_frozen_install` checks.
Its stub coordinator invokes the configuration callback at runtime; assertions
prove the callback reaches the stub `RestartCoordinator.reconcile` with the
same manager, BM-020 store, request, and scoped `transaction_access`. No
product code change was needed. The test uses no source slicing.

## Validation

- Generated-entrypoint dispatcher test: **1/1 passed**.
- Focused adapter, frozen-install, transaction, and restart-coordinator suites:
  **136/136 passed**.
- Full offline suite: **1,876/1,876 passed**. The first run had one
  readiness-timeout failure in the unrelated transaction child-process test;
  that test passed alone and the full rerun passed.
- `python3 -m compileall -q resources tools tests`: passed.
- All **7** tracked JSON files parsed; `git diff --check` passed.

Only `tests/test_bm023a_adapter.py` has product-tree changes. Tracking is
updated in `.agent/CURRENT_TASK.md`, `.agent/AGENT_STATUS.json`,
`.agent/USAGE_HISTORY.md`, and this handoff. Work is uncommitted on
`agent/supervised-codex` at `bb5460e`; no push or matrix integration occurred.

No Kodi/Test.app was launched or accessed; no profile, device, network, LAN,
private value, host action, adapter install, or live retry/recovery was used.
All checks were offline. Smallest next step: independent review of the dirty
coverage snapshot. Live retry remains outside this work item.

---

# Current Handoff - BM-023A held-transaction retry implementation (2026-09-24)

**Result:** OFFLINE_IMPLEMENTATION_COMPLETE; LIVE_RETRY_NOT_RUN.

## What changed

- `FrozenInstallStore.rearm_held_quiescence` only accepts the reviewed held
  failure predicate and compares the complete immutable transaction snapshot
  under the store lock. It preserves the transaction, manifest, plan,
  configuration, overlay, original session, restart count, updater guard, and
  unreleased activation hold; it clears only the old safe failure diagnostic.
- `FrozenInstallCoordinator.retry_held_quiescence` requires the caller's
  reviewed transaction snapshot and accepts only `needs_attention`,
  `FROZEN_MANIFEST_INVALID`, `quiescence_awaiting_restart`, restart count 1,
  the sole `plugin.video.redlight` hold, unreleased hold, required updater
  guard, and original `AUTOMATIC` policy. It requires a post-restart session
  matching the live session provider.
- The coordinator reasserts and reads back `NEVER_CHECK`, stages each declared
  exact artifact idempotently through `ArtifactStore`, revalidates manifest,
  plan, Red Light activation graph, private overlay identity, exact healthy
  disabled Red Light version, and absence of a BM-020 restart transaction. It
  re-reads the transaction and owner state before the locked full-snapshot CAS,
  then calls the existing resume continuation once.
- Generic `abandon()` remains unchanged and still rejects unreleased holds.
  The normal resume/finalization path remains responsible for configuration,
  private verification, final validation, activation release, desired enabled
  states, updater restoration, and transaction clearance.

## Validation

- Focused frozen lifecycle tests: **34/34 passed**.
- Full offline suite: **1,862/1,862 passed**.
- `python3 -m compileall -q resources tools tests`: passed.
- `git diff --check`: passed.
- Added coverage for accepted re-arm and artifact staging, all supported-state
  predicate near misses, session matching, generic abandon rejection, BM-020
  conflicts, exact owner version and disabled state, manifest/plan/overlay and
  artifact mismatch failures, guard/readback ordering, and full-snapshot CAS
  conflicts.

## Boundaries and next step

No Kodi or Test.app was launched or accessed. No profile, device, network,
restart, adapter install/invocation, or host action was used. The live held
transaction was not inspected or changed. The new coordinator entry point is
not wired into an adapter or supervisor action; a separately named, explicitly
authorized one-shot action and its preflight/postcondition review remain a
separate step. The BM repository still has no known host-action catalog entry.

The implementation and tests are uncommitted workspace changes on
`agent/supervised-codex`; protected matrix is unchanged. Codex usage values are
recorded as unavailable per `AGENTS.md`; the supervisor state showed model
`gpt-6-luna` and effort `max`. Smallest next step: supervisor review of this
production API, then separately authorize any action wiring or live retry.

---

# Prior Handoff - BM-023A durable restart-artifact correction (2026-09-24)

**Result:** offline adapter correction complete and validated. The live Test.app
transaction remains intentionally untouched in needs_attention after the
post-quiescence restart.

### Live evidence that motivated this correction

The single authorized 0.0.4 install invocation reached
QUIESCENCE_RESTART_REQUIRED with Red Light held and updater quarantine active.
After the manually authorized full Test.app restart, startup resume failed
closed with FROZEN_MANIFEST_INVALID. Read-only reproduction proved the
retained manifest fingerprint still matched but the profile-local
frozen-artifacts store was empty, so exact artifact validation failed for the
captured package set. The temporary adapter had used the external retained
artifact store for the initial coordinator while production startup correctly
reconstructed the durable profile-local store.

The live transaction currently remains at needs_attention, lifecycle stage
quiescence_awaiting_restart, restart count 1, with the Red Light activation
hold unreleased and the updater guard still required. No retry or recovery was
performed after this diagnosis.

### Offline correction

Implementation commit: ee31e3eb3810bd167a7185694631b705c3692b5e.

Temporary adapter 0.0.5 now:
- stages every declared non-system exact artifact from the retained source
  store into the profile-local frozen-artifacts store through existing
  ArtifactStore.read_bytes / import_zip validation;
- verifies the imported SHA-256 and size against the frozen manifest;
- leaves artifact=None and system nodes unstaged so existing YouTube
  skip/repository resolution semantics remain unchanged;
- constructs the install coordinator with the durable profile-local store;
- keeps recovery dispatch separate and preserves safe, allowlisted failure
  diagnostics without paths or raw exception text.

Production resources/lib/frozen_install.py was not changed.

### Validation

- BM-023A adapter: **39/39** passed.
- Related artifact/frozen lifecycle modules: **86/86** passed.
- Full offline suite: **1,855/1,855** passed.
- compileall passed for resources, tools, and tests.
- All **7** tracked JSON files parsed.
- git diff --check passed.

### Status / next step

- BM-017F: COMPLETE.
- macOS BM-023A: BLOCKED_PENDING_HELD_TRANSACTION_RECOVERY_AND_0.0.5_LIVE_RETRY.
- tvOS: NOT VALIDATED.
- Protected matrix was not changed.
- No Kodi/Test.app mutation, recovery, install invocation, real-device access,
  normal-profile access, or private-value inspection occurred during the
  offline correction.

The existing generic bm023a-recover path must **not** be invoked blindly:
its current preconditions reject an unreleased activation hold. The next step is
a supervisor-reviewed recovery path for this specific held needs_attention
state, followed by a separately authorized adapter 0.0.5 live retry.

---

# Current Handoff — BM-023A offline CONFIGURE correction (2026-09-24)

Result: offline implementation and regression validation complete. The live
transaction remains untouched and macOS BM-023A is
BLOCKED_PENDING_RECOVERY_AND_SINGLE_RETRY.

### What changed

- resources/lib/build_manager.py: tags public and private CONFIGURE
  exceptions with a validated scope; existing safe resource/import fields stay
  available.
- resources/lib/frozen_install.py: unwraps only typed configuration results
  and persists safe nested fields. When already validated overlay metadata is
  present, the failed transaction retains its ID, fingerprint, and required
  flag.
- resources/builds/examples/eric-main.example.json: declares Red Light's
  required structured resource with configure_before_activation=true.
- Added regressions for public/private failure scope, empty CONFIGURE add-on
  identity, typed stage/cause retention, redaction, overlay identity with
  required=false, Red Light holds across restart and failed configuration,
  and unchanged unrelated resolution behavior.
- Updated .agent task tracking; prior history remains below.

### Validation

- Focused related suites: 686 tests passed.
- Full offline suite: 1,851 tests passed.
- Compileall passed for resources, tools, and tests.
- All 7 tracked JSON/schema files parsed.
- git diff --check passed.

### Not done

No Kodi was launched. No recovery, retry, updater/skin/profile mutation,
real-device access, or private overlay value inspection occurred. The historical
CONFIGURE sub-action is still unknown; online recovery and the single retry
remain separate supervisor-gated work.

### Smallest next step

Await supervisor direction before recovering the preserved needs_attention
transaction or starting the single diagnostic retry.

### Status

- BM-017F: COMPLETE.
- macOS BM-023A: BLOCKED_PENDING_RECOVERY_AND_SINGLE_RETRY.
- tvOS: NOT VALIDATED.
- Worker branch: agent/codex; protected matrix was not changed.
- Implementation commit: 6ce2947; task tracking is kept in separate metadata
  commits on the same worker branch.
- Matrix SHA: 66b0fd8a123ef778b23ba42703937b07eefc4e6f.
- Usage snapshot: start 5h 0% used / weekly 79% used; end 5h 3% used /
  weekly 80% used; observed delta 5h +3 pp / weekly +1 pp. Runtime label GPT-6;
  user-requested Luna-6/Max was not independently observable, and no
  model/effort switch was made.

---

# Historical handoff — BM-023A recovery adapter implemented offline (2026-09-24)

**Result:** `OFFLINE_IMPLEMENTATION_COMPLETE; LIVE_RECOVERY_NOT_RUN`.

Commits `c972c8a` and `f182774` add strictly allowlisted adapter modes `install` and
`recover`, bumping the temporary package to 0.0.3. Default invocation remains
the existing install path. Recovery uses the production store/coordinator and
runtime/policy/artifact backends, rejects missing/invalid/non-`needs_attention`
transactions and unreleased activation holds, and invokes exactly one
`abandon(acknowledge_restore_failure=False)`. It does not load the private
overlay or frozen manifest; it performs no manual add-on, updater, transaction,
lock, or restart-state changes. Recovery success is fail-closed on transaction
clearance, updater-policy restoration, add-on retention, and restart-record
presence being unchanged. Both success and failure output are restricted to
safe, fixed fields.

Tests: adapter **29/29**, BM harness **124/124**, full offline suite
**1837/1837**. Compilation, generated-package ZIP CRC integrity, generated
source compilation, tracked JSON parsing, and `git diff --check` passed. No
production Build Manager code changed. No Kodi app was launched; the 0.0.3
adapter was not installed or invoked, and no recovery or BM-023A retry was
performed. No normal profile, real device, or private overlay value was
accessed.

The generated ZIP in tests uses fixture-only configuration; no
machine-configured package containing private paths was built. BM-017F remains
`COMPLETE`; BM-023A live recovery/retry remain pending separate review and
authorization; tvOS remains `NOT VALIDATED`.

**Smallest next step:** supervisor review of commit `c972c8a`. Do not perform a
live adapter installation/recovery or BM-023A retry without a separate
authorization.
---

# Prior handoff — BM-023A adapter bootstrap corrected offline (2026-09-24)

BM-017F remains complete and synchronized to matrix `66b0fd8`.

BM-023A's namespace-package TypeError is corrected offline. The authoritative
source is now the tracked `tools/build_bm023a_adapter.py` generator with
templates in `tools/bm023a_adapter/` and strict source-check/diagnostic helpers
in `tools/bm023a_adapter_support.py`. The prior one-off existed only under
`/private/tmp`; no project generator was found. The one-off was intentionally
outside Git because it embeds machine-specific portable paths and the
private-overlay source path. The tracked builder preserves those values only
in generated output and carries them forward only from six allowlisted string
assignments. Adapter version advanced from 0.0.1 to 0.0.2 to ensure Kodi sees
the corrected ZIP as an upgrade; packaging retains the built-in ZIP-installer
layout.

The fixed bootstrap imports `resources.lib`, resolves its concrete `__file__`,
and requires it to be exactly the package initializer inside the canonical
installed `script.build.manager` tree. The add-on root must be the direct
child of the canonical installed add-ons root. Host/project collisions,
wrong roots, and symlink/path escapes fail closed. The namespace package's
`resources.__file__` is never dereferenced. Failures expose only allowlisted
`adapter_stage`, `failing_callable`, `failure_category`, and `error_type`;
there is no raw exception text, traceback, or path in diagnostics. The
successful result also omits private overlay ID/fingerprint.

Offline validation: adapter/bootstrap tests **16/16**, BM harness tests
**124/124**, compileall, JSON parsing, and `git diff --check` pass. The corrected
0.0.2 ZIP was regenerated under `/private/tmp` from the tracked source. No
Kodi app/profile, normal profile, real device, or private-overlay file was
accessed; no live retry was run. macOS BM-023A is **READY_TO_RETRY**, not
passed; BM-017F remains complete; tvOS is not validated. The supervisor may
authorize the separate live retry.

## Prior handoff — BM-017F complete and synchronized (2026-09-24)

**Result**: `BM-017F COMPLETE`. The reviewed substantive endpoint diff was
reconstructed onto protected matrix as `4dfd97e180d14976adec8540d5c0c93893519249`;
neutral matrix tracking brings its pushed tip to
`66b0fd8a123ef778b23ba42703937b07eefc4e6f`. The worker was synchronized by a
normal merge. No worker history was rewritten, and no unrelated product
changes or disposable profile contents entered matrix. The only follow-up
correction during matrix validation reordered test mocks so the import spy
records add-on imports rather than its own `unittest.mock` target resolution.

The supervisor-provided final disposable validation passed all eight steps
and all twenty checks. Red Light structured private-resource lifecycle is
`LIVE-VALIDATED`. The evidence was restricted to `.kodi-test`; this
integration did not launch Kodi or access a normal Kodi profile, real device,
or private overlay values.

Matrix validation: focused lifecycle/resource/import/harness modules
**499/499**; full repository suite **1782/1782**; `compileall`; all **7
tracked JSON files** parsed, including the schema; `git diff --check` passed.

BM-023A macOS is `READY_TO_RETRY`; no retry was started. tvOS remains
`NOT VALIDATED`.

**Smallest next step**: wait for the next supervisor-authorized task, the
actual macOS BM-023A retry against `/Applications/Kodi Build Manager Test.app`,
launched exactly with `open "/Applications/Kodi Build Manager Test.app" --args -p`.

The historical BM-017F pending and blocker records below are retained for
audit context and are superseded by this completion handoff.

---

# Historical Handoff — BM-017F bounded service-start poll

Implemented the narrowly scoped disposable-harness fix. After unchanged
step-[3/8] completion checks (enabled, exact Red Light version, frozen
transaction absent), the harness polls only the current disposable
`.kodi-test/home/Library/Logs/kodi.log` for `Main Monitor Service Starting`,
using a monotonic 30-second deadline and 0.25-second intervals. A timeout has
a specific Red Light service-start diagnostic. Step [4/8] still checks all
five markers and its safety order; BM-020 classification remains required
presence-only. No production lifecycle code changed.

Added nine service-start-poll regressions. BM-017F poll/resume/order tests
passed 26/26; `tests.test_kodi_harness` passed 124/124; compileall and
`git diff --check` passed. No Kodi process or live BM-017F command was run.
The complete lifecycle remains `IMPLEMENTED_PENDING_FINAL_LIVE_VALIDATION`.
The supervisor still needs to run the full disposable live gate using the
manual command below. The earlier `Unknown addon id 'plugin.video.redlight'`
exception remains an observed diagnostic only, from before release while the
add-on was disabled; it did not prompt a production change. BM-023A remains
blocked; tvOS remains not validated; no new milestone started.

# Prior offline service-start marker diagnosis

Latest disposable-run evidence supports a harness service-start race, not a
proven Red Light startup failure. Step 3 breaks as soon as the owner is
enabled and the frozen transaction is absent. It does not wait for Red
Light's asynchronous `xbmc.service` entrypoint. Step 4 reads the log
immediately; if the marker is absent, its exception path runs the `finally`
block, which stops Kodi. The marker check is before the stop, not after it.

Current-run timeline: second session `Starting Kodi` 21:41:07.403; JSON-RPC
and webserver ready by 21:41:10.800; updater guard 21:41:11.237; held Red
Light registry state registered at 2.6.8/disabled 21:41:11.591; an
`Unknown addon id 'plugin.video.redlight'` exception 21:41:12.245; private
verification 21:41:12.972; activation release 21:41:12.976; BM-020C
`no_transaction` 21:41:13.002. The service-start marker is absent from both
logs for this run. No service-specific traceback, dependency failure, or
service-start attempt was found. Kodi's final Addons33 state is enabled for
Red Light, and both durable BM transaction files are absent. Current test
updater policy is AUTOMATIC; exact equality with the in-memory original
captured by the harness was not logged because step 4 failed before that
read-back.

The pre-release Unknown addon id exception is notable but does not evidence
service startup failure: it occurred while the add-on was recorded disabled,
and BM-022 subsequently logged private verification, activation release, and
transaction completion. Kodi shutdown time was not preserved; the stop is
inferred from the harness `finally` path and absent PID file. A prior run took
205 ms from release to service marker; this run reached the BM-020 marker 26
ms after release and then checked immediately, so stopping within a plausible
asynchronous service-scheduling window is consistent with the evidence.

At diagnosis time the state was `BLOCKED_BM017F_HARNESS_SERVICE_START_RACE`.
The requested bounded poll is now implemented; it does not itself prove live
service startup. Final disposable validation remains pending.

## Prior checkpoint: step-4 ordering correction

The harness-only ordering defect is corrected and the regression suite passes.
Step [4/8] continues to require every marker but now asserts the production
safety invariant `updater guard < private verification < activation release <
service start`. The BM-020 startup-classification marker remains required but
is treated as a post-resume diagnostic with no ordering constraint. No
production lifecycle behavior changed.

Nine focused ordering regressions cover the observed order, BM-020 before
private verification, invalid safety orders, missing markers, and rejection
of the old chained classification predicate. `python3 -m unittest
tests.test_kodi_harness` passed **115/115**; targeted compileall and
`git diff --check` passed. No Kodi launch or live lifecycle validation was
performed. BM-017F is `IMPLEMENTED_PENDING_FINAL_LIVE_VALIDATION`; the
supervisor must run the manual command below. BM-023A remains blocked and
tvOS remains not validated.

Unchanged remaining gates: [5] second BM-015 reconciliation succeeds with
zero changed/failed actions; [6] stopped-Kodi read-only DB checks verify exact
schema, WAL, fake private field, unrelated-row preservation, initialized
defaults, and fake-value absence from logs/transaction; [7] exact Red Light
artifact SHA and dependency artifacts; [8] completion while inspection stays
inside `.kodi-test`. Step [3] still requires enabled exact-version Red Light
and no durable transaction. Step [4] still checks complete marker presence,
safety order, fake-value log absence, and original updater-policy restoration.
These later gates were inspected, not executed.

## Result

The following timestamps and diagnosis are the pre-correction evidence that
motivated the harness fix above; the stale ordering predicate was corrected
without changing production behavior.

The latest supervisor-run disposable log contains every step-[4/8] marker
once, but not in the order the harness requires. Its expected sequence is
`guard < BM-020 startup classification < private verified < hold released <
service start`; actual local timestamps (2026-09-23, America/New_York) show:

- Updater guard reasserted: 21:02:46.407.
- Held Red Light registry state: 21:02:46.685, registered at 2.6.8 and disabled.
- Private resource verified: 21:02:48.057.
- Activation hold released: 21:02:48.062.
- BM-020 classification `no_transaction`: 21:02:48.094.
- Red Light service start: 21:02:48.267.

Thus the exact false term is `BM-020 startup classification < private
verified`. `service.py` emits that classification after
`run_frozen_install_startup()` returns, so the observed order
`guard < private verified < hold released < BM-020 classification < service
start` is expected. The live safety invariant
`private verification < activation release < service start` held, and the
updater guard was active before resumed registry/config work.

The stage-[3] poll reached step [4/8] only after reading the owner as enabled
and the frozen transaction as absent. The settings DB exists, passes
`integrity_check`, is WAL, and has the expected schema; no setting values were
read. The final policy read-back maps to `NEVER_CHECK`; source ordering plus
transaction clear shows restore to the captured original succeeded, though
the original enum is not separately retained. No restart transaction or
`needs_attention` state remains. A separate ERROR-level `unknown addon`
diagnostic at 21:02:47.286 is outside the step-[4/8] predicate and its
producer is not identified by retained evidence.

`reset()` deletes the disposable root before each run. Kodi rotated the first
session into `kodi.old.log` (startup 21:02:31.204); the second session began
in `kodi.log` at 21:02:44.910. Step [4/8] reads only the latter. Each required
marker appears once there; the BM-020 marker in the old log belongs to the
first session and is excluded. Current fixture/result file times follow the
reset, so stale artifacts did not affect the comparison.

## Classification and next step

- BM-017F: `IMPLEMENTED_PENDING_FINAL_LIVE_VALIDATION`.
- Red Light core safety ordering: **LIVE-PROVEN**; complete eight-step gate:
  **NOT YET LIVE-VALIDATED**. Step-[4/8] harness correction passed offline
  regression tests; supervisor manual live validation remains required.
- macOS BM-023A: `STILL BLOCKED`.
- tvOS: `NOT VALIDATED`.
- No normal Kodi profile, real device, or private overlay values were accessed.

The response-shape fix was exercised by the supervisor with the command below.
This harness-ordering correction did not run it. The supervisor should run the
command below to validate the corrected step [4/8] and continue gates [5/8]
through [8/8].

```sh
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

---

# Previous Handoff — BM-017F Requests alias correction ready for live validation

## Result

Committed the verified Requests compatibility-alias correction and regression
coverage as `81e8b2c` on `agent/codex`. The provider resolver determines
ownership from canonical module source locations (`__file__`, spec origin, and
namespace `__path__`) and accepts only one matching frozen provider. Requests
2.31.0 aliases are limited to `urllib3`, `idna`, and `chardet`; each alias must
come from its matching provider in the verified dependency closure, remain
anchored under the verified Requests package, and be the identical object in
the canonical provider entry in `sys.modules`. Host packages and unrelated
cross-provider aliases fail closed.

Cleanup snapshots controlled preexisting modules and their dictionaries,
removes every newly created Requests, dependency, owner, namespace, and alias
entry under the temporary import roots on success or failure, and restores
`sys.path` and `sys.meta_path`. The regression covers ownership-check failure
followed by a successful same-process retry; legitimate preexisting Requests
and urllib3 modules and an unrelated shared module remain intact.

Ownership failures carry a safe category and validated module/provider IDs
through Red Light initialization, Build Manager action results, and the frozen
CONFIGURE transaction status. Paths, exception text, and private values are
excluded.

## Validation and limits

- Requested focused regression set: **456 passed**.
- Full repository `unittest` suite: **1,756 passed**.
- Manifest/schema suite: **50 passed**.
- `compileall` passed; all **7 tracked JSON files** parsed; `git diff --check`
  passed.
- No Kodi executable or BM-017F lifecycle harness command was run. No normal
  Kodi profile, real device, or private overlay values were accessed.

Classification: `IMPLEMENTED_PENDING_ALIAS_LIVE_VALIDATION`. The historical
`BLOCKED_RED_LIGHT_REQUESTS_ALIAS_SOURCE_MISMATCH` is corrected offline and
awaits supervisor live proof. Red Light's lifecycle remains **NOT YET
LIVE-VALIDATED**; macOS BM-023A remains **STILL BLOCKED**; tvOS remains **NOT
VALIDATED**.

## Smallest next step

The supervisor runs the following disposable lifecycle command manually from
normal Terminal. Codex did not run it:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

Required human input: supervisor review of the live stage/result before any
further BM-017F work. Do not claim completion from offline tests alone.

---

# Previous Handoff — BM-017F import-path correction implemented

## Result

Implemented the correction for `BLOCKED_RED_LIGHT_IMPORT_PATH_CONTEXT` in
`93be55a3e3a900de488d388c88fbf39aca885869` on `agent/codex`. Red Light's
temporary owner import root is derived from its verified installed
`addon.xml` module declaration and resolves to the canonical
`plugin.video.redlight/resources/lib` directory.

The import context adds only the frozen transaction's verified Python-module
dependency closure required by the audited initializer: requests 2.31.0,
urllib3 2.2.3, certifi 2023.5.7, chardet 5.1.0, and idna 3.10.0. The exact
versions and enabled registry state must match the frozen records. It rejects
unverified or colliding top-level modules, checks namespace `__path__` as well
as ordinary `__file__`, restores `sys.path` and legitimate prior modules, and
cleans up imported owner namespace modules on success and failure.

Red Light remains held disabled. Its installed package still supplies the
schema/default declarations, value converter, marker constants, and property
setter. Offline source review found no database, provider network,
authentication, service-start, or background-worker side effects in the
audited initializer import chain. No `xbmcaddon.Addon("plugin.video.redlight")`
source lookup was reintroduced.

## Validation and limits

- Focused source/import/resource/private-overlay/build/dependency/frozen
  transaction and resume suites: **354 passed**.
- Full repository suite: **1,742 passed**; manifest/schema suite: **50 passed**.
- `compileall` passed; all **7 tracked JSON files** parsed; `git diff --check`
  passed.
- BM-017F was not live-validated in this task. Kodi and the lifecycle harness
  were not run. No normal Kodi profile, real device, or private overlay values
  were accessed.

Classification: `IMPLEMENTED_PENDING_IMPORT_LIVE_VALIDATION`. The historical
`BLOCKED_RED_LIGHT_IMPORT_PATH_CONTEXT` correction awaits live proof. Red Light
clean-destination lifecycle remains **NOT YET LIVE-VALIDATED**; macOS BM-023A
remains **STILL BLOCKED**; tvOS remains **NOT VALIDATED**.

## Smallest next step

The supervisor runs the following disposable lifecycle command manually from
normal Terminal. Codex did not run it:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

Required human input: supervisor review of the live stage/result before any
further BM-017F work. Do not claim completion from offline tests alone.

---

# Previous Handoff — BM-017F stage diagnostics ready for live validation

## Work completed

Committed narrowly scoped Red Light initializer stage diagnostics and
regression coverage as deae656 on agent/codex. The current changes preserve
BM-017F lifecycle ordering and the activation hold. The prior uncommitted
offline-diagnosis tracking changes were preserved and updated below this source
commit.

The actual RedLightSettingsAdapter.initialize() sequence is covered at these
boundaries in resources/lib/redlight_resource.py:

1. Resource declaration/version validation and existing-resource inspection.
2. Quiescence, hold, and frozen installed-source context validation, including
   the immediate pre-import source revalidation.
3. Package helper imports and schema declaration loading.
4. Add-on-data directory and database-directory creation.
5. SQLite open, WAL setup, and schema execution/commit.
6. Package defaults preparation and row insertion.
7. Persisted-row, WAL, and schema validation.
8. Publication of the two existing sync markers.

## Diagnostic propagation

ResourceInitializationStage and ResourceInitializationCause provide
allowlisted typed codes. Failures preserve the high-level
PRIVATE_RESOURCE_INITIALIZATION_FAILED code and safe owner/resource identity,
plus initialization_stage, last_completed_stage, and a typed cause. The
fields pass through StructuredPrivateResourceManager, the private-overlay
boundary, Build Manager CONFIGURE result, and
FrozenInstallCoordinator._handle_configuration_result into the durable
transaction status_message.

The transaction stores only fixed stage/cause codes and validated owner,
resource, and action identifiers. Raw exception text, filesystem paths, row
contents, fake secrets, and private overlay values are excluded. New optional
action-result fields are omitted for legacy diagnostics, preserving their
serialized shape.

## Tests and checks

- Focused Red Light resource, private overlay, CONFIGURE diagnostic,
  Build Manager, and frozen transaction/readiness suites: 93/93.
- Full repository unittest suite: 1,722/1,722.
- compileall for resources, tests, and tools: passed.
- All 7 tracked JSON files parsed; git diff --check passed.
- Test harness dispatch cases are mocked. Codex did not launch Kodi or run
  validate-bm017f-lifecycle.

## Classification and next action

IMPLEMENTED_PENDING_DIAGNOSTIC_LIVE_VALIDATION. Red Light clean-destination
lifecycle remains NOT YET LIVE-VALIDATED. macOS BM-023A retry remains
STILL BLOCKED; tvOS is NOT VALIDATED. Wait for the supervisor to run the
manual disposable lifecycle command and inspect its persisted safe stage/cause.
Do not automatically rerun after a failure.

Exact next manual command, when directed by the supervisor:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

No normal Kodi profile, real device, or real private overlay values were
accessed. Preserved disposable runtime evidence was left unchanged.

---

# Previous Handoff — BM-017F Codex JSON-RPC block (superseded by Terminal evidence)

## Follow-up transport investigation — loopback blocked

With Kodi stopped, a no-Kodi Python HTTP server bind to `127.0.0.1` on an
ephemeral port failed with `PermissionError`, errno 1 (`EPERM`). No port was
selected and no HTTP listener started, so urllib, direct socket-client, and
curl requests were not attempted. This meets the environment-block condition;
no alternate host, port, or transport was tried. Classification:
`VALIDATION_ENVIRONMENT_LOOPBACK_BLOCKED`.

Historical project handoffs record that the disposable BM-022
`validate-frozen-install` gate and BM-020C `validate-build-manager-resume`
gate succeeded and exercised `JSONRPC.Ping`. The successful BM-022 source at
`27f4215` and the current harness both target
`http://127.0.0.1:8920/jsonrpc` through `urllib.request.urlopen()`. Both write
the enabled webserver setting and port 8920 to disposable `guisettings.xml`
before launch. Git history shows no request, webserver, launch command, or
launch-environment change since BM-022; the current harness's functional
changes are the BM-017F command/fixture and lexical profile-isolation check.
The old records do not state whether those successes used the same Codex
execution sandbox or record proxy variables.

During this investigation all uppercase and lowercase HTTP_PROXY, HTTPS_PROXY,
ALL_PROXY, NO_PROXY, and no_proxy variables were unset. `urllib`'s loopback
proxy-bypass checks returned false; because explicit proxy variables were
absent, no environment-proxy route was indicated. The bypass result alone does
not establish whether a system-level proxy is configured; no proxy URL/value
was printed or further inspected. A proxy cannot explain the failed server
bind; the current execution surface denies loopback listener creation. No code
was changed.

## Work completed

The preserved BM-017F implementation now places held-addon registry readiness
in BM-022's own post-restart continuation, before configuration, so it does not
depend on BM-020 having a transaction. BM-020 reuses the same readiness helper.
The helper reloads durable ownership, checks updater quarantine and the full
activation hold before and during refresh, derives exact expected versions,
uses supported `UpdateLocalAddons`, and verifies registered-disabled state with
bounded polling. Regression coverage includes BM-020 `no_transaction` with a
resumable BM-022 transaction, ordering, failure modes, exact-version state, and
hold persistence.

The retained Red Light 2.6.8 ArtifactStore object is validated at SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`. The
harness isolation check was also changed to avoid resolving or probing the
normal-profile path; it verifies only lexical disposable paths and disposable
symlink components. The implementation, regression tests, and sanitized
handoff are committed on `agent/codex` as `beff4f1`.

## Validation

- Registry/readiness/frozen-install focused suites: **48/48**.
- Full repository suite: **1,690/1,690**.
- `compileall`, schema/status JSON parsing, and `git diff --check`: passed.
- The new full-hold regression first failed with a mutable mock that changed
  the same in-memory transaction. The fixture was corrected to model durable
  transaction replacement; targeted tests and the full suite then passed.

## One authorized live run

The exact authorized `tools/kodi_test.py validate-bm017f-lifecycle` command was
run once with retained manifest
`/private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json` and
ArtifactStore `/private/tmp/bm022v-familyroom.ygB0t5/artifact-store`. Isolation
preflight verified HOME
`/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.kodi-test/home`,
`KODI_HOME` unset, configured binary
`/Applications/Kodi.app/Contents/MacOS/Kodi`, and a stopped starting state.

Kodi launched through the harness (PID 79755). Reset, fixture preparation,
Build Manager runner setup, and webserver configuration completed. Kodi did
not answer the harness JSON-RPC readiness request within 90 seconds; the last
error was `<urlopen error [Errno 1] Operation not permitted>`. The harness
stopped Kodi, and its status command confirmed `running: False`, `pid: None`.
The failure occurred before a BM-017F transaction or Red Light installation.
No restart, BM-020/BM-022 resume, registry query/refresh, resource
initialization, settings DB creation, private apply, activation release,
runtime start, or idempotence was reached. The production readiness fix was
not exercised live. Do not rerun under this approval.

Diagnostics: `/private/tmp/bm017f-continuation-readiness-failure-2026-09-23.tar.gz`,
SHA-256 `588d2f858083cf611d8b97798c07160e9acea827acbf5675864f5865f9c1a827`.

## Safety and next step

This continuation used Kodi only through `tools/kodi_test.py` and did not
access the normal Kodi profile, any real device, Kodi Build Manager Test.app,
or real private values. The earlier normal-profile metadata-only `test -e`
and separate bare `Kodi -v` invocation remain documented historical safety
deviations; do not investigate them or access that profile. No BM-023A retry
or tvOS validation was started.

Current classification: `BLOCKED_DISPOSABLE_KODI_JSONRPC_OPERATION_NOT_PERMITTED`;
Red Light clean-destination lifecycle **UNSUPPORTED**; macOS BM-023A
**STILL_BLOCKED**; tvOS **NOT VALIDATED**. The smallest next step is
supervisor direction on the disposable harness's local JSON-RPC permission,
followed by new explicit approval before another live run. Preserve all current
worker changes; do not start another milestone.

---

---

# Historical Handoff — BM-017F resumed after qualified matrix integration

BM-017F first attempt is complete as an investigation/implementation attempt.
Its historical result is `BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE`,
but that result requires revalidation: BM-023A-R1 reported Red Light 2.6.8
among 30 exact artifact-backed installed managed add-ons, with YouTube as the
single exact-artifact gap. The pinned Red Light SHA-256 is
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`.

The sanitized audit was integrated on protected `matrix` as `ad48ff4` and
qualified in `ed92808`; neutral tracking is `fedefae98aa01253e6b34ecbac1b292b80c21b6a`.
Only the audit and neutral BM-017F tracking were integrated. Worker metadata
and the worker usage row remain on `agent/codex`. The worker now synchronizes
by normal merge from this matrix tip; there is no reset, rebase, or force-push.

The audit recorded these Kodi 21.1/Omega findings: ordinary newly discovered
add-ons defaulted disabled; `UpdateLocalAddons` did not start the fake service;
the fake service started only after enable. Kodi native install/reload and
Build Manager dependency reconciliation remain activation paths that require
lifecycle coordination. The full managed-graph activation barrier is
unresolved. The prior focused suite passed **703/703**, the full suite passed
**1647/1647**, compileall and seven JSON parses passed, and `git diff --check`
passed. No production code changed in that first attempt.

A safety deviation remains recorded: `/Applications/Kodi.app/Contents/MacOS/Kodi -v`
was invoked without disposable `HOME`. A later check found no Kodi process, but
transient normal-profile access could not be ruled out. The normal Kodi profile
was not inspected and must not be inspected to investigate that deviation.

The resumed BM-017F run is now revalidating the retained frozen-manifest
reference and ArtifactStore object through production APIs. No result is claimed
yet. No Family Room/device access or real private values were used. BM-023A
retry was not started; tvOS remains NOT VALIDATED.

**Smallest next step**: finish the retained manifest and ArtifactStore lookup.
If the exact object exists, validate its pinned bytes and resume BM-017F. If it
is absent or inconsistent, record the precise retained-state blocker and stop.
Do not resume BM-023A.

---

# Agent Handoff — BM-017E audit integrated on matrix

BM-017E is complete as a static investigation with result
`BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`. Only the sanitized
`docs/BM017E_RESOURCE_LIFECYCLE_AUDIT.md` from worker commit `e94046d` was
integrated as matrix commit `7075d59`; worker `.agent/*` was excluded. Matrix
tracking remains neutral with `active_agent: none`.

The audit records the exact public Red Light 2.6.8 package hash, its own DDL and
WAL paths, the broader effects of settings synchronization and normal service
startup, and why current BM-020/BM-022 ordering cannot maintain quiescence and
resume private configuration across another restart. No Red Light code or
Kodi runtime was executed for this documentation-only integration. The audit
tracking assertions and `git diff --check` passed; no product tests were run.

BM-023A-R1 remains historically `BLOCKED_RESOURCE_NOT_INITIALIZED`; do not
resume the Mac installation. tvOS remains NOT VALIDATED.

**Smallest next step**: synchronize Codex normally, then begin the separately
authorized BM-017F lifecycle work.

---

# Agent Handoff — BM-017E investigation complete; BM-023A-R1 synchronized

## BM-017E disposition

**Complete as a static investigation** with result
`BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`.

The exact public Red Light 2.6.8 package (SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`) contains
an internal `ensure_database_tables('settings_db')` helper and a fresh-settings
sync path. The helper is called from directory-listing routing, not a standalone
initializer API. The ordinary enabled-addon service performs broad
integrity/rebuild maintenance, syncs settings, bootstraps properties, and starts
multiple background workers. Its pause flag does not stop all workers, and its
disabled notification has no worker-join/quiescence acknowledgement.

Build Manager's current frozen-install flow enforces the add-on's requested
enabled state before its configuration runner. BM-022 restart resume has a
separate updater-policy transaction and finalizes software without rerunning
configuration; BM-020 stores no resource stage and its resume path does not
accept a further restart requirement. The present ordering cannot prove that
the owner remains disabled while the internal initializer and private apply
run, and that it is re-enabled only afterward while updater quarantine remains
active. No safe production lifecycle could be established from the current
architecture, so no production code or tests were added and no Red Light code
was executed. Full static findings and the exact next step are in
[`docs/BM017E_RESOURCE_LIFECYCLE_AUDIT.md`](../docs/BM017E_RESOURCE_LIFECYCLE_AUDIT.md).

No Family Room database, protected overlay values, Kodi device, or portable Mac
test profile was accessed. BM-023A remains blocked; do not start its Mac retry
from BM-017E. tvOS remains NOT VALIDATED.

## BM-023A-R1 integration

The reviewed R1 correction was integrated onto protected matrix as substantive
commit `9f05ea748d9c15131982d6eee2cb1e9aa41a3f8e`; neutral tracking is
`9abc4724fede1a2a936be37db501d1ab24c6d5f1`. Matrix focused validation passed
**288/288** and the full suite passed **1647/1647**. Compileall, JSON parsing,
and `git diff --check` passed. The Codex worker synchronized by normal merge
`7b8fe386447fd345c3029d7c8a13f0a96cf300ce`; only the authorized branches were
pushed. BM-023A-R1 remains complete as validation with result
`BLOCKED_RESOURCE_NOT_INITIALIZED`.

The requested Luna-6 / Max setting was not observable. Runtime label was GPT-6;
effort and usage telemetry were unavailable.

**Smallest next step**: review the BM-017E audit and design a single durable
BM-020/BM-022 stage for disabling Red Light through initialization and private
application, then re-enabling it before a future BM-023A retry.

---

# Agent Handoff — BM-023A-R1 validation complete

**Result**: `BLOCKED_RESOURCE_NOT_INITIALIZED`. BM-023A-R1 is complete as a
validation task. Do not begin another milestone.

## Integration and synchronization

Starting refs matched the supplied SHAs: `origin/matrix` at
`b82885ab01fdb3c2486fff0c3e42bf33262b110e` and `origin/agent/codex` at
`68f0da5613b4d5606ba2e334d4330fbaf6889d9f`. Only substantive BM-023B commit
`1d60ed39b36a1b25ac4c0d912712a55fe9a17e8f` was cherry-picked to matrix as
`5648c6781b4567d3b2f0931fc4ed838142ed22f1`; worker `.agent/*` was excluded.
Neutral matrix tracking is `d867b8029ae35d4187ecbcecb0f3f39016673517`. The
normal worker merge is `9b16e8a5a0585a11552233071f20073af151c0b4`. Matrix and
worker substantive endpoint trees matched after integration. Matrix was pushed
only to `origin/matrix`; synchronization pushed only to `origin/agent/codex`.

Integrated BM-023B validation: focused **581/581**, full suite **1643/1643**,
compileall, JSON parsing, and `git diff --check` passed.

## Isolated macOS retry

Only `/Applications/Kodi Build Manager Test.app` was launched, using exactly
`open "/Applications/Kodi Build Manager Test.app" --args -p`. Kodi 21.3/Omega
mapped `special://home`, `special://profile`, userdata, addon_data, databases,
and packages under the app's `Contents/Resources/Kodi/portable_data` tree.
Process/open-file checks found no use of the normal Kodi profile. The portable
profile held the fresh stock baseline; it was not reset or mutated. The exact
Red Light `settings.db` path under portable userdata was absent.

The retained capture matched source fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`:
37 graph nodes, 31 installed managed non-system nodes, one absent optional
`script.module.pysocks`, five system/runtime nodes, 67 required edges, and
three optional edges. All 30 retained exact artifacts passed byte/hash,
size, ID/version, and ZIP checks. YouTube `7.4.4+unofficial.2` remains exact
unavailable and no trusted repository is established; policy permits Skip or
Cancel, with a manual-install warning.

Protected overlay safe metadata validation passed for ID
`family-room-redlight-2.6.8`, expected fingerprint
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`,
source binding, and the public Red Light declaration. YouTube Skip was
compatible according to public ownership/resource declarations. No private
values were emitted or used for the compatibility decision.

Production inspection found `PrivateOverlayManager` constructs
`RedLightSettingsAdapter` with `lifecycle=ACTIVE` and `initialized=False`.
The adapter requires an existing database and a quiesced owner; it does not
create the database, and no supported deterministic initialization/quiesce
path is wired into the production flow. The clean destination lacks the
database. The hard gate therefore stopped with
`RESOURCE_NOT_INITIALIZED` before bootstrap, prompt, updater-policy change,
frozen install, reconciliation, or profile mutation. YouTube UI choice,
restart/resume, private application, final validation, updater restoration,
and idempotence remain untested.

BM-023A-R1 generalized correction: carry the immutable source software
fingerprint through frozen reconciliation and restart-safe request metadata;
validate overlay source binding against it; declare the public Red Light
resource and overlay ID in the Family Room example. No lifecycle bypass was
added. The correction and regression tests are committed on `agent/codex` as
`a2ad39a`. Focused production regressions **288/288**, full suite **1647/1647**,
compileall, JSON parsing, and diff check passed. Runtime label was GPT-6;
requested Luna-6/Max and Codex quota data were unavailable.

No Family Room profile/device or other Kodi device was accessed. tvOS remains
NOT VALIDATED. Secret values do not appear in the source changes or tracking;
the secret-blind scan result is recorded as `leak_detected=false` after the
final scan. The exact authorized test app remains at its pristine portable
baseline and is still available to the user.

**Smallest next step**: complete the separately authorized BM-017E source audit
and lifecycle work. Keep BM-023A-R1 blocked and do not resume the Mac
installation during BM-017E.

---

# Agent Handoff — BM-023B complete

**Result**: explicit exact-first frozen install recovery is implemented and
pushed as `1d60ed39b36a1b25ac4c0d912712a55fe9a17e8f` on `agent/codex`. BM-023A-H
tracking remains on protected `matrix` at `b82885ab01fdb3c2486fff0c3e42bf33262b110e`;
the normal worker synchronization merge is `08c0fdfc9601e770c88edab5100751c04b16166d`.

**Architecture**: exact artifacts retain strict digest/size/ZIP/ID/version
validation and install first. Explicit per-addon policy selects exact-only,
exact-first repository fallback, or exact-first fallback/skip. Fallback uses
only a named repository represented by an exact captured enabled repository
package. Unknown repository provenance never triggers guessing. Skip is
explicit, cannot satisfy required dependencies, is carried into ordinary
BuildManager reconciliation, and survives BM-020 restart transaction
serialization. Unattended choice returns `USER_RESOLUTION_REQUIRED`. Source,
install-plan, resolution, and resulting-software fingerprints are separate;
the source manifest is unchanged. Private-overlay compatibility uses only
public owner/resource declarations and reads no overlay values.

**Family Room classification**: captured desired state COMPLETE; exact frozen
coverage 30/31; YouTube `7.4.4+unofficial.2` exact artifact unavailable;
trusted repository identity unknown. Current actions are Skip or Cancel Build,
with a manual-install warning. If a trusted repository is established later,
the explicit Install Current Version choice is available under policy.

**Validation**: focused group 120/120; full suite 1643/1643; `compileall`, JSON
parsing, and `git diff --check` passed. Disposable temporary artifacts and
fake backends were used. Kodi was not launched; no real profile, device, or
private-overlay value was accessed. macOS BM-023A retry is architecturally
unblocked through explicit resolution but was not resumed; tvOS is not
validated.

**Smallest next step**: stop after BM-023B. Do not perform the separate macOS
install retry without a new task authorization.

---

# Agent Handoff — BM-023A-H exact historical artifact recovery

**Result**: `EXACT_YOUTUBE_7.4.4_UNOFFICIAL_2_NOT_RECOVERED`.
**Tracking synchronization**: sanitized worker completion commit `49791ea` is recorded on protected matrix at `b82885a` and is being merged normally into `agent/codex`; the worker H record remains intact.

The matrix integration is at `a51a84d`; Codex was synchronized by normal merge
`e08fe24`. Worker history and the single existing BM-023A-R usage entry were
preserved. BM-023A-H changed only sanitized tracking.

Public exact-version searches covered the upstream v7.4.4 release and install
guide, the upstream repository-generation workflow and `nexus-unofficial`
metadata, OSMC unofficial-testing package listings and repository indexes,
public GitHub search, Panicked references, and a Wayback CDX query. The official
release assets show bare `7.4.4` and `7.4.4+unofficial.1`; checked current OSMC
testing metadata shows betas and bare `7.4.4`; the current stable unofficial
package index was also checked and has no `.2` entry:
<https://ftp.fau.de/osmc/osmc/download/dev/anxdpanic/kodi/youtube/unofficial/zips/plugin.video.youtube/>.
No public exact `.2` metadata, package URL, provider checksum, archived entry,
forked package, or `.2`-specific source commit was located. The generic source-build process is known, but it
does not identify the `.2` build. No package ZIP was downloaded; the known bare
`7.4.4` candidate was not changed or substituted.

Production validation of the unchanged retained manifest/store pair fails
exactly for the installed managed YouTube `7.4.4+unofficial.2` artifact. Graph:
37 total nodes; 31 installed managed non-system; 1 absent optional; 5 system or
runtime; 30 artifact references, all present; 67 required edges; 3 optional
edges; 1 missing managed artifact. `pysocks` remains absent/optional/artifactless
and unscheduled. Canonical fingerprint is unchanged at
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`, the
recorded private-overlay target. No overlay value was read or changed.

Focused frozen tests: **25/25**. BM-023A-R matrix validation: **25/25** frozen,
**147/147** dependency, **1607/1607** full suite, clean diff check. Family Room,
all devices, Kodi, the portable profile, and private overlay remained untouched.

**Smallest next step**: await supervisor direction on archival recovery versus
an explicitly altered desired build or later authorized recapture. BM-023A
remains historically `BLOCKED_MISSING_FROZEN_ARTIFACTS`; do not resume install.

---

# Agent Handoff — BM-023A-R matrix integration and Codex synchronization

The protected matrix started at `5a3598f565ad5b0c0164215eeefdf39b54a1d682`.
Reviewed substantive worker commit `a8d4b71` was cherry-picked as matrix
`ff5c000`; neutral tracking was committed as `a51a84d` and pushed to
`origin/matrix`. Worker implementation and tracking history were preserved by a
normal merge. Only `.agent/AGENT_STATUS.json`, `.agent/CURRENT_TASK.md`, and
`.agent/HANDOFF.md` needed semantic conflict resolution; production changes
merged without conflict. The existing BM-023A-R usage row is preserved once.

Matrix validation: frozen capture/manifest/install **25/25**, dependency
regressions **147/147**, full suite **1607/1607**, and `git diff --check` clean.
No Kodi launch, portable-profile mutation, Family Room/device access, or private
overlay access occurred.

**Checkpoint next step**: the normal worker push at `e08fe24` and BM-023A-H
recovery result are recorded above. Await supervisor direction; do not resume
BM-023A installation.

---

## Existing worker handoff — synchronized Codex worker

## BM-023A-R — Frozen input completeness reconciliation

**Result**: `MANIFEST_SEMANTICS_CORRECTED_BUT_ARTIFACT_GAP_REMAINS`.
Implementation commit: `a8d4b71` on `agent/codex`. `origin/matrix` remains
`5a3598f565ad5b0c0164215eeefdf39b54a1d682`. No protected or other worker
branch was changed.

Capture and install validation now share these rules: every installed
non-system node needs an exact artifact even if its incoming dependency edge
is optional; an absent optional dependency is recorded as `missing` with
disabled desired state and no artifact and is omitted from install order; and
system nodes remain declarations without artifacts. The installer validates
these rules independently. Schema v1 does not imply exclusion/unmanaged state
for installed optional nodes.

The retained `script.module.pysocks` graph node is absent, disabled, and
optional, reached only from YouTube through an optional edge. It exists because
capture records traversed optional imports even when absent from installed
inventory. It requires no artifact and is no longer scheduled. The previous
installer rejected it under its blanket artifact rule before returning a
schedule.

YouTube is installed as `7.4.4+unofficial.2`, desired enabled, and is an
optional dependency of `plugin.video.umbrella`. With no explicit exclusion
model, it is managed frozen software. The manifest has no configuration
packages; the protected private overlay targets Red Light only. No captured
configuration dependency on YouTube was found. Excluding it changes the
captured enabled software state. The `repository_evidence` provenance has only
the `installed_origin` placeholder `recorded`; an exact provider ID is not
present in retained evidence.

Only the retained candidate directory
`/private/tmp/bm022v-familyroom.ygB0t5` and named protected Build Manager
artifact storage were searched. No exact `plugin.video.youtube`
`7.4.4+unofficial.2` artifact was found. The retained package
`packages/plugin.video.youtube.zip` validates as `7.4.4` (SHA-256
`d744e5ba2d2b50924a9fa5624f4d209c2be95b97ef1ad1682cafbed160fb428f`,
1,093,649 bytes); production validation rejects it for the installed version.
No import, version normalization/substitution, network lookup, or recapture
occurred.

Focused frozen tests passed **25/25**, full suite **1607/1607**, and
`git diff --check` passed. No Kodi launch, portable-profile mutation, or
Family Room access occurred. BM-023A remains historically complete as a
validation task with result `BLOCKED_MISSING_FROZEN_ARTIFACTS`.

### Smallest next step

Supervisor decides whether to authorize a separate exact historical-provider
recovery step or explicitly exclude YouTube from the managed frozen state.
Do not resume frozen installation or start another milestone before that
decision.

### BM-023A preflight details (historical)

BM-017D tracking is integrated on protected matrix at `5a3598f`; Codex is
synchronized by normal merge at `bcd0fe5`. BM-023A stopped before Kodi launch
or disposable-profile mutation because the exact retained Family Room frozen
manifest/artifact-store pair is incomplete despite its top-level complete
status: 37 graph nodes, 32 non-system nodes, but only 30 artifacts. The
required `plugin.video.youtube` `7.4.4+unofficial.2` node and
`script.module.pysocks` `not-installed` node are incomplete, and
`validate_frozen_manifest` rejected the candidate.

Read-only typed validation of the protected Red Light overlay passed; its
target fingerprint matches the frozen graph and its ten field identifiers
were present. Values were not displayed. No test app launch, wipe, install,
settings/add-on mutation, reconciliation, restart, or other Kodi action was
performed. The bundled disposable profile already contains Kodi data and was
left untouched. The exact frozen artifacts must be recovered from existing
retained capture outputs; do not recapture Family Room or substitute newer
packages. If unavailable, request supervisor direction. No BM-017E or other
milestone was started.

### Smallest next step

Recover and validate the exact two missing frozen artifact nodes from the
approved capture, without accessing Family Room; otherwise stop for direction.

## BM-017D — Real Family Room structured private-resource capture complete

BM-017D is complete on `agent/codex`. Matrix remains unchanged at `2374ee5`;
the real private overlay is stored only outside Git in protected local Build
Manager storage. No other worker branch was modified.

The explicitly authorized read-only Xcode `devicectl` receive targeted only
`AppleTV - Family Room (4)`, bundle `com.eengert.koditvosnew`, and
`Library/Caches/Kodi/userdata/addon_data/plugin.video.redlight/databases/settings.db`.
The names-only directory check found no `settings.db-wal` or `settings.db-shm`
sidecars. No unrelated cache sidecars were received.

The BM-017C adapter validated the Red Light 2.6.8 contract, exact
`settings(setting_id, setting_type, setting_default, setting_value)` text
schema, WAL mode, and SQLite integrity. All ten optional reviewed fields were
captured and verified: `mdblist.refresh`, `mdblist.token`, `mdblist.user`,
`pm.account_id`, `pm.token`, `tb.token`, `trakt.expires`, `trakt.refresh`,
`trakt.token`, and `trakt.user`. No required fields were missing. Ordinary,
generated, cache, and unrelated rows were not captured.

Overlay ID: `family-room-redlight-2.6.8`. Protected storage:
`/Users/eengert/Library/Application Support/Build Manager/addon_data/script.build.manager/private_overlays/family-room-redlight-2.6.8.json`.
Overlay fingerprint:
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`.
Frozen software fingerprint:
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.

The source remained read-only: no apply operation, Red Light/Kodi setting
write, database mutation, restart/stop, add-on operation, repository refresh,
Build Manager reconciliation, Backup Pro operation, or device installation
was performed. The temporary raw database and locally generated sidecars were
deleted and verified absent. The secret-blind worktree scan reported
`leak_detected=false`.

Validation passed focused tests **27/27** and **386/386**; no production/test
code changed, so the full suite was not rerun. `git diff --check` must pass
before the tracking commit.

Frozen software is **COMPLETE**, the private overlay is **COMPLETE**, captured
desired state is **COMPLETE**, and real-device frozen installation remains
**NOT VALIDATED**.

### Smallest next step

Supervisor review of the sanitized BM-017D capture result. Do not apply the
overlay to Family Room or any destination device, and do not start another
milestone.

## BM-017C — structured private-resource foundation integrated and synchronized

Codex is synchronized with protected `matrix` through `2374ee5` by a normal
merge; matrix remains neutral, the worker identity remains `codex`, and no
other worker branch was modified. BM-017C is complete and supervisor-approved
on matrix. Its clean matrix-side substantive commit is `dce8276`, reconstructed
from worker implementation commit `8ba7bdc`; worker tracking metadata was
excluded from that substantive integration.

BM-017C provides a generic structured-private-resource protocol, exact Red
Light schema/version declarations, a quiesced row-scoped WAL adapter,
protected-overlay coexistence, restart-safe metadata, fake SQLite fixtures, and
sanitized documentation. It did not retrieve the real Family Room `settings.db`,
capture private values, create the real overlay, write to Family Room, install
on a real device, or start BM-017D/retention/scheduling.

Validation on the integrated matrix tree: structured-resource **27/27**,
focused regression group **386/386**, full suite **1604/1604**, and
`git diff --check` passed.

### Smallest next step

Stop after synchronization. Any real Red Light private capture is a separate
BM-017D authorization and must not be inferred from this foundation.

## BM-017B — Private overlay capture blocked by opaque Red Light state

BM-017B performed the authorized narrow read-only Family Room inventory using
paired-device `devicectl` against the Kodi app-data container. Device listing,
names-only relevant-directory inspection, and specifically justified metadata
and source receives succeeded. No source-profile write, Kodi control, add-on
state change, restart, repository operation, database write, Backup Pro
operation, reconciliation, installation, or unrelated profile scrape occurred.

The installed Red Light `2.6.8` source exposes a custom settings layer and its
`databases/settings.db` table is the owner of the observed private provider
state. Secret-blind schema/presence/default comparison found non-default
private-state fields in the `mdblist`, `pm`, `tb`, and `trakt` categories,
including refresh/token/account/user/expiry field IDs. Red Light's Kodi
`settings.xml` exposes only informational/action entries, so these values
cannot be represented by BM-017A's typed Kodi-setting backend. The database
also mixes ordinary preferences and generated/runtime state; copying or
replacing the whole file is explicitly unsafe.

MyAccounts `2.1.2` source exposes provider-auth setting operations for several
providers, but its Family Room addon_data directory was empty and no separate
user-state file was identified. POV and Umbrella source also contain provider
integrations, but no duplicate owner was inferred from the file evidence.

Result: frozen software capture remains **COMPLETE** with software fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
Private overlay capture is **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; no typed
declarations, required/optional overlay entries, overlay file, or overlay
fingerprint were created. Captured desired state is **INCOMPLETE** and
real-device frozen installation remains **NOT VALIDATED**.

The final targeted secret-blind leak scan returned `leak_detected=false` for
repository files. All raw received database/source/metadata evidence was
deleted from the disposable directory and its absence was verified. No real
private value appears in tracking, documentation, logs, results, or Git.

### Smallest next step

Design and review a dedicated structured private-resource boundary for Red
Light's mixed settings database, including field-level ownership and safe
lifecycle/application semantics. Do not add an arbitrary file copier, capture
real private state again, or begin destination installation without that
review.

## BM-017A — Private/auth overlay foundation complete

BM-017A is complete on `agent/codex`. The worker first synchronized current
`origin/matrix` by normal merge (`a1ceab1`); the protected matrix and other
worker branches were not modified.

The implementation adds explicit public `config.private_settings`
declarations and a version-1 local private overlay with typed values,
required/optional ownership, sensitivity classification, build/overlay
identity, canonical JSON fingerprinting, and duplicate/undeclared/type/
completeness validation. Storage is profile-local, atomically written, and
permission-restricted (`0700` directory / `0600` file where supported). It is
intentionally restrictive plaintext: there is no encryption-at-rest claim,
custom cryptography, cloud sync, or secret-bearing public artifact.

The existing BM-015 `ConfigurationManager` remains the sole typed settings
backend. Build Manager applies public settings first and validated private
settings second, with typed authoritative read-back. Private values are not
returned in results, errors, logs, manifests, packages, `.agent/*`, or
BM-020/BM-022 durable transactions. Only overlay ID, fingerprint, and
required flag cross restart/frozen-install boundaries. Required absence and
identity drift fail closed; optional absence is a safe no-op.

Tests passed: private-overlay **14/14**, combined BM-015/BM-020/BM-022
regressions **588/588**, full suite **1591/1591**, and `git diff --check`.
Disposable fixtures used temporary storage only. No real Family Room private
files, credentials, Kodi profile, Apple TV, or other device were accessed.
The software foundation is ready for a separately authorized capture/import
workflow; real private capture and real-device frozen installation were not
performed. BM-017A is complete, BM-017 remains scoped to future authorized
capture/application work, and no next milestone was started.

### Smallest next step

Supervisor review the BM-017A foundation and explicitly authorize any future
private-state capture/import task. Do not access the real Family Room profile
or begin another milestone from this handoff.

## BM-022V-R — Family Room exact-artifact blocker resolution complete

BM-022V-R is complete on `agent/codex`. The BM-022V checkpoint was published
first as `f5a4415` to `origin/agent/codex`. No BM-017 or other milestone was
started, and the Family Room remained read-only.

### Resolution

Kodi Omega source supports a package with one safe top-level folder whose
`addon.xml` declares the requested add-on ID, even when the folder name differs
from that ID. Kodi stages the extracted contents under the requested ID. The
previous Build Manager root-equality check was unnecessarily strict.

The generalized correction is limited to `resources/lib/artifacts.py` and the
shared staged extraction helper in `resources/lib/repository.py`. It accepts
one safe root and keeps exact `addon.xml` ID/version authority while preserving
rejection of multiple roots, traversal, symlinks, missing/malformed XML, ID
mismatch, and version mismatch. No package bytes are rewritten, and there is
no add-on-specific exception.

The exact official Kodi Omega Dropbox package was recovered and imported:

- ID/version: `script.module.dropbox` `10.3.1+matrix.1`
- SHA-256: `5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6`
- Size: 667,538 bytes
- Source: recorded official Kodi Omega mirror URL

The exact cached Robotocjksc ZIP now validates unchanged as
`resource.font.robotocjksc` `0.0.3`; its alternate safe root is normalized only
during staged extraction. A temporary proof confirmed the final target has
the original `addon.xml` and payload bytes.

### Final capture state

- Required frozen software capture: **COMPLETE**.
- Candidate manifest: 37 nodes; 67 required edges; 3 optional edges; zero
  required missing artifacts.
- Exact artifact-backed nodes: 30; captured artifact bytes: 194,254,227.
- Candidate fingerprint:
  `sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
- Optional YouTube remains incomplete because installed
  `7.4.4+unofficial.2` differs from cached `7.4.4`; it does not block required
  capture completion.
- BM-023A-R later established that optional incoming edges do not waive the
  artifact requirement for this installed, enabled node. The non-blocking
  classification above is preserved as historical BM-022V/R tracking and is
  superseded by the current completeness invariant.
- Ready-to-use configuration: **BLOCKED_BY_BM017 / INCOMPLETE**. Private/auth
  state was not captured.

Focused tests passed **331/331**; full suite passed **1577/1577**; and
`git diff --check` passed. No Family Room installation, update, enable/disable,
repository refresh, restart, settings write, database write, or reconciliation
was performed. Codex usage values remain unavailable.

### Smallest next step

Supervisor review the BM-022V-R correction and, separately, authorize any
future BM-017 private-state work. Do not install the candidate build or begin
another milestone from this handoff.

## BM-022V — Real Family Room frozen-capture validation complete (initial checkpoint)

BM-022V is complete on `agent/codex` as read-only evidence validation. No
production code or documentation was added; no source Kodi profile, database,
settings, package cache, or device state was mutated; and no next milestone
was started.

The authorized `Addons33.db` was received into temporary evidence storage and
parsed with a read-only SQLite connection. The requested `guisettings.xml`
could not be received because no file with that name exists at the authorized
path or elsewhere in the Kodi app-data Library; no alternate file was used.
The raw database was deleted after parsing. The candidate FrozenManifest v1
was generated only in disposable temporary storage with fingerprint
`sha256:8807efedc3814b3c460761b8dc44466ae4e6d6f5dbe099f1a3cfb0a1a192660b`.

Evidence summary:

- Graph: 37 observed nodes; 70 edges; 67 required and 3 optional.
- ArtifactStore: 28 exact validated artifacts, 28 unique identities,
  141,987,267 unique bytes, disposable only.
- Software capture: **INCOMPLETE**, blocked by two required exact artifacts:
  `script.module.dropbox` `10.3.1+matrix.1` and
  `resource.font.robotocjksc` `0.0.3`.
- The Robotocjksc cached ZIP is malformed (`resource.font.robotcjksc` top-level
  directory) and was not repaired, renamed, or repackaged.
- Optional YouTube artifact evidence is incomplete; optional metadata remains
  unresolved for `script.module.inputstreamhelper` and
  `script.module.pysocks`.
- The database showed captured add-ons enabled except
  `service.skinsettings.backup` (disabled reason `1`). No explicit broken
  state is represented in the inspected database schema, so none is claimed.
- `general.addonupdates` is **UNAVAILABLE** because the authorized settings
  file was absent.
- Ready-to-use configuration is **INCOMPLETE / BLOCKED_BY_BM017** because
  private/authenticated configuration was not captured.

Validation: relevant BM-021B artifact/frozen/frozen-install tests **30/30**;
`git diff --check` passed. Codex usage values are unavailable under the
project's documented rules. BM-017, retention, pinning, scheduling, freshness
UI, and real frozen installation were not started.

### Smallest next step

Supervisor review the BM-022V evidence report and separately authorize any
future exact-artifact recovery or BM-017 private-state work. Do not install the
candidate build or begin another milestone from this handoff.

## BM-022 — Frozen Build Installation and Transaction Lifecycle complete

BM-022 is complete on `agent/codex` in substantive commit `27f4215`. It is
not integrated to `matrix`; protected matrix remains `7ab49f1`. No worker
branch other than `agent/codex` was touched, and no next milestone was
started.

### What was done

- Added strict schema-v1 frozen-manifest loading and validation, including
  complete-capture status, exact artifact-store SHA-256/size/ZIP identity,
  system-dependency boundaries, edge validation, and deterministic
  topological installation order.
- Added a durable profile-local frozen transaction with atomic writes and
  locking; phases cover preparation, exact software installation,
  configuration, restart handoff, resume, validation, completion, and
  `needs_attention` recovery.
- Extended the existing updater guard so the original global policy is
  durably captured before mutation, `NEVER_CHECK` can be reasserted after a
  process restart, and the original policy can be restored from durable state.
- Reused the reviewed BM-011 staged-package boundary: validated ZIP content
  is atomically staged, registered with `UpdateLocalAddons`, and verified at
  the exact requested version; wrong-version replacement/downgrade is rejected.
- Added BM-020 startup precondition/resume integration and a read-only VFS
  fallback for installed dependency metadata when Kodi cannot open a freshly
  discovered disabled add-on handle.
- Added the BM-022 design document, a real ZIP/ArtifactStore disposable
  fixture, focused tests, and the `validate-frozen-install` command.

### Live and test evidence

The disposable BM-022 gate passed completely in `.kodi-test`: exact artifact
hash selection; repository → dependency → ordinary add-on ordering; durable
BM-020 handoff; restart-time updater reassertion before BM-020 startup;
existing Build Manager configuration; exact final state; original updater
policy restoration; clearing of BM-022 and BM-020 transactions; and real Kodi
profile immutability. The proof uses generated disposable runtime state only;
pristine first-ever provisioning of arbitrary add-ons is not claimed.

Focused regressions passed **639/639**. The full suite passed **1573/1573**.
`git diff --check` passed. Codex usage start/end/delta are `unavailable` per
the project rule; no telemetry was fabricated.

### What was not done

BM-022 has not been integrated to protected `matrix`. BM-017 remains deferred.
No retention, pinning, scheduling, freshness enforcement, garbage collection,
Apple TV action, real-profile mutation, or next milestone was started.

### Smallest next step

Supervisor review the BM-022 substantive commit and, if approved, perform the
normal clean integration onto protected `matrix` without copying worker
metadata wholesale.

## BM-021B capture core complete

BM-021B is complete and integrated on protected `matrix`; this worker is
synchronized, idle, and ready for BM-022. BM-021A is complete and its findings remain in
`docs/FROZEN_BUILD_CAPTURE.md`.

Implementation commit: `89525bd`. The implementation is limited to exact artifact capture, dependency-aware
inventory, manifest v1, deterministic incomplete results, and the independent
global updater guard. It does not install frozen builds or implement retention,
pinning, scheduling, freshness UI, garbage collection, BM-017, or device work.

Verified: Kodi 21.1 public add-on metadata exposes identity, version, type,
path, enabled/installed/broken state, and declared dependency edges, but not
provenance or per-addon update policy. The disposable profile's internal
database showed origin, package-cache, repository, and update-rule evidence;
the cache was bounded and did not contain every installed third-party package,
and some cached versions differed from installed versions. AF3 3.2.19's
closure was 21 nodes (18 third-party, 3 Kodi/system), with BM-020A dependency
health **18/18**. BM-011 repository/add-on validation passed **19/19**.

Decision: exact version recovery is feasible only from a verified immutable
artifact, an exact cache hit, or a still-available repository package. A ZIP
made from an installed directory is rejected as a reproducible artifact
fallback. The BM-021B manifest carries SHA-256 identity, exact ID/version,
dependency edges, enabled state, provenance confidence, and capture status;
system dependencies are constraints rather than frozen artifacts. Kodi's
global updater setting was proven through the supported Settings API; the
`NEVER_CHECK` value did not persist across restart, but deterministic guard
reassertion succeeded before capture mutation and no scheduled updater activity
appeared while guarded.

The representative disposable capture correctly returned `incomplete_artifact`
because no exact package-cache ZIP was available after reset; no installed
directory was zipped and no COMPLETE result was claimed. Evidence: BM-021B
focused tests **21/21**; combined focused tests **370/370**; full suite
**1557/1557**; updater-guard disposable proof passed. `NEVER_CHECK` did not
persist across restart, but deterministic reassertion succeeded before capture
mutation and original-policy restoration survived restart. BM-022 and BM-017
have not started. The real Kodi profile, Apple TV, devices, and other workers
remain untouched.

## BM-020C — post-restart resume orchestration complete

BM-020C is complete, supervisor-approved, and integrated on protected `matrix`.
The worker is synchronized to the integrated state; its substantive matrix
commits are `81ba44b` and `091cfe9`.

The implementation adds the read-only `BuildManager.preview()` seam,
`resources/lib/resume.py`, expected-state transaction transitions and bounded
status diagnostics, automatic `service.py` delegation for `READY_FOR_RESUME`,
focused resume tests, and the disposable `validate-build-manager-resume` gate.

The coordinator re-reads the persisted record, verifies a new session,
previews the desired state before mutation, requires an exact fingerprint
match, atomically claims `RESUMING`, and runs the normal BuildManager
reconciliation from the beginning. It clears only an unchanged `RESUMING`
record after success + matching final fingerprint + `NONE`. Failures,
fingerprint drift, repeated restart requirements, claim conflicts, and clear
conflicts fail closed into preserved `NEEDS_ATTENTION` state. Existing
`RESUMING` and `NEEDS_ATTENTION` records are not retried automatically.

Evidence: focused tests **465/465**, disposable BM-020C gate **8/8** with AF3
closure **18/18**, full suite **1536/1536**, and `git diff --check` clean. The
live gate proved automatic service-driven resume after a harness-only Kodi
restart, normal reconciliation with matching fingerprint and
`RestartRequirement.NONE`, automatic transaction clear, all 16 managed AF3
settings, no second handoff, and later `NO_TRANSACTION`. The unmanaged AF3
probe is covered by the BM-020A gate because this runtime normalizes that
schema entry across process restart. The real Kodi profile, Apple TV, and all
devices remained untouched.

BM-020C and BM-020 overall are complete. Current supported platforms still
require a manual full-Kodi restart; Build Manager does not automatically
relaunch Kodi. BM-017 and family-room distribution/source work remain
deferred. The next step is the BM-021A audit documented above.

## BM-020C1 — typed capability model and manual restart handoff complete

BM-020C1 is complete and integrated on protected `matrix`; its substantive
implementation commit is `bcaf2ca` (worker implementation `a6bf902`). The implementation adds
`resources/lib/restart_coordinator.py`, focused coverage in
`tests/test_restart_coordinator.py`, the disposable
`validate-build-manager-manual-restart` gate, and the BM-020B/C1 transaction
documentation.

The capability resolver maps macOS, Android/Shield, Fire OS, Apple TV/tvOS,
and unknown platforms to `MANUAL_APP_RESTART_REQUIRED`. A successful typed
`KODI_RESTART` result creates and read-backs `AWAITING_RESTART` with attempt
count `0`, returns `MANUAL_RESTART_REQUIRED`, and leaves Kodi running. Failed
reconciliation and `NONE` are fail-closed/no-transaction paths. A matching
same-session call reuses the durable record without a second reconciliation;
a changed session is `READY_FOR_RESUME` with count `0`, while BM-020C resume is
not implemented. Automatic capability selection fails closed because no
approved automatic adapter exists.

Evidence: focused BM-020C1/BM-020B/BM-020A/BM-019 tests **63/63**,
disposable manual gate **8/8**, full suite **1517/1517**, and
`git diff --check` clean. The gate used the real BM-020A fixture and
fingerprint, with only the restart requirement synthesized to exercise this
contract. It used only `.kodi-test`; the real Kodi profile, Apple TV, and all
devices remained untouched. The gate also proved AF3's disposable dependency
closure, same-process manual behavior, new-session classification, no resume,
and explicit clear.

Remaining BM-020C work is pre-resume fingerprint validation, `RESUMING`,
resumed reconciliation, success clear, restart-loop prevention, and recovery
after resume failure. Do not begin that work, BM-017, or device work as part
of this handoff. The smallest next step is supervisor direction on the later
resume contract.

## BM-020C audit stop — production restart primitive not established

BM-020C was started on Codex and stopped at its mandatory read-only restart
mechanism audit before the later BM-020C1 capability/manual-handoff work.
That audit remains historical context; the integrated BM-020C1 endpoint does
not claim that resume/re-entry is complete.

Kodi Omega's official built-in reference lists `RestartApp` as implemented
only under Windows and Linux. `Quit` is an application exit, not an automatic
relaunch. JSON-RPC provides quit/restart notifications, not a supported
add-on/Python operation that guarantees a new Kodi process. Kodi's Android
source contains internal restart-exit handling, but that does not establish a
public add-on/Python restart contract; no equivalent supported primitive was
established for macOS, Fire OS, Shield, or Apple TV/tvOS.

The required BM-020C lifecycle cannot safely claim a new session without a
genuine new Kodi process. Host shell/process management, GUI automation,
`System.Exec`, or a `Quit` plus assumed external relaunch would violate the
task boundary. The disposable harness may control Kodi externally, but that
cannot substitute for the missing production mechanism.

Recommended smallest next step: supervisor approval of an explicit platform
capability model and relaunch authority. Until then, do not add a restart
coordinator, alter BM-020A/B, or run the BM-020C process-level gate.

BM-020C and BM-020 overall remain incomplete. BM-017, the remaining resume
implementation, and all device/family-room work remain deferred. The real Kodi
profile and devices remain untouched.

## BM-020B complete and synchronized on Codex

BM-020B is complete and integrated on protected `matrix`; the substantive
commit is `f3ccf2a`. The implementation stores only a versioned safe
`ReconcileRequest`, desired fingerprint, typed restart requirement, originating
Kodi session UUID, phase, and bounded diagnostics under the Kodi profile.
Writes are validated and atomic; locking uses OS-backed `fcntl.flock` and fails
closed if unavailable. Kodi's global home-window property supplies a process
session identity, and `service.py` performs one startup classification pass.

The service fast path reports no transaction without reconciliation. Same-
session `AWAITING_RESTART` remains intact and ineligible for resume. A
different Kodi process is classified `READY_FOR_RESUME` while the transaction
remains durable for BM-020C. Corruption, unsupported versions, invalid fields,
and persistence/lock failures fail closed; clear is explicit only.

Disposable BM-020B validation passed 9/9 across an external Kodi stop/relaunch;
the service ran automatically in both processes, distinguished session IDs,
and never restarted Kodi or invoked `BuildManager.reconcile()`. Focused
transaction/session/service tests passed 32/32, the full suite passed
1504/1504, and `git diff --check` passed. Codex is synchronized/idle/ready
for BM-020C; BM-020C, BM-017, and family-room distribution/source work remain
outside scope.

## BM-017D — Real Family Room structured private-resource capture integrated

BM-017D is complete and its sanitized tracking is integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. Only tracking from
worker commit `d585fd8` was integrated. The protected overlay remains outside
Git in local Build Manager storage.

The matrix tracking commit is `5a3598f`; Codex was synchronized to that tip
with a normal merge before beginning BM-023A preflight.

The authorized read-only receive targeted the Family Room Kodi app-data
container and only Red Light `databases/settings.db`. Names-only inspection
found no matching settings database WAL/SHM sidecars. Exact Red Light 2.6.8
owner/version/schema, WAL mode, and integrity checks passed. The ten declared
optional provider/auth fields were captured and verified through BM-017C;
ordinary preferences, generated state, caches, and unrelated rows were not
captured. No values or overlay contents are recorded here.

Sanitized overlay identity: `family-room-redlight-2.6.8`, fingerprint
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`,
bound to frozen software fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
Frozen Family Room software, private overlay, and captured desired state are
**COMPLETE**. Real-device frozen installation remains **NOT VALIDATED**.
BM-017B retains its historical result **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**.

The source remained read-only; no apply or device installation occurred. The
temporary raw database and local SQLite sidecars were deleted and verified
absent. The secret-blind scan reported `leak_detected=false`. Focused tests
passed **27/27** and **386/386**; no production/test code changed.

### Smallest next step

Supervisor review. Do not start real-device installation without its separate
authorization.

## BM-017C integration complete

BM-017C is complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `dce8276`, reconstructed from worker
implementation commit `8ba7bdc`; worker tracking metadata was excluded.

The structured private-resource foundation owns only explicitly declared typed
fields inside a vetted resource. Public manifests contain safe adapter,
version, schema, lifecycle, and field metadata; private values remain in the
protected overlay and are omitted from results, logs, and durable restart
metadata. The Red Light 2.6.8 adapter requires an existing exact-schema WAL
database and quiesced runtime, performs bounded row-scoped transaction writes
with per-field read-back, preserves unrelated rows, and requires explicit
restart/reload. It does not replace the mixed settings database or support
arbitrary paths, SQL, or wildcard ownership.

Integrated validation passed structured-resource **27/27**, focused
regressions **386/386**, full suite **1604/1604**, and `git diff --check`.
Tests use fake fixtures only. No real Family Room private database, credential,
Kodi profile, Apple TV, or other device was accessed or mutated.

BM-017B remains complete with result
**BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; frozen Family Room software is
**COMPLETE**, captured desired state is **INCOMPLETE**, and real-device frozen
installation is **NOT VALIDATED**. BM-017D has not started.

### Smallest next step

Supervisor direction and separate authorization are required before any
BM-017D real private-state capture/import work. Do not access the real Family
Room private database or begin another milestone from this handoff.

## BM-017B integration complete

BM-017B is complete and supervisor-approved, with result
**BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**. The reviewed sanitized evidence is
`docs/BM017B_PRIVATE_CAPTURE.md`; it records that Red Light `2.6.8` stores
required private/auth state in a mixed `databases/settings.db` resource outside
the BM-017A typed Kodi-setting boundary. No private values were captured, no
raw database was retained, no arbitrary private-file copier was added, and the
Family Room source remained read-only.

Frozen Family Room software remains **COMPLETE**; captured desired state is
**INCOMPLETE**; real-device frozen installation is **NOT VALIDATED**. Matrix
remains neutral with `active_agent: none`. BM-017C is complete and integrated
above; BM-017D remains separately authorized and not started.

## BM-017A integration complete

BM-017A is complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `321fee8`, reconstructed from worker
implementation commit `ebd4c61`. Worker tracking metadata was excluded.

The integrated foundation defines explicit public private-setting ownership,
typed version-1 overlay entries, build/overlay identity, canonical SHA-256
fingerprinting, duplicate/undeclared/type/completeness rejection, and
fail-closed missing-required behavior. Active storage is profile-local under
`addon_data/script.build.manager/private_overlays`, written atomically with
restrictive permissions where supported. It is protected local plaintext;
encryption at rest is not provided or claimed, and no custom cryptography is
used.

The existing BM-015 typed configuration backend remains the only settings
engine. Public configuration is applied first and validated private settings
second through the same typed write/read-back path. Private values are not
included in public artifacts, logs, results, `.agent/*`, or durable BM-020 /
BM-022 state. Durable state carries only overlay ID, fingerprint, and required
flag. Optional absence is a safe no-op; required absence and fingerprint drift
fail closed.

Integrated validation passed private-overlay **14/14**, BM-015/BM-020/BM-022
regressions **588/588**, full suite **1591/1591**, and `git diff --check`.
The real Family Room private profile, credentials, Kodi profile, Apple TV,
and other devices were not accessed or mutated. Required Family Room frozen
software capture remains complete, but ready-to-use configuration still
requires a separately authorized real private overlay capture/import, and
real-device frozen installation is not validated. BM-017B has not started.

### Smallest next step

Supervisor review and explicit authorization of any future BM-017B private
capture/import work. Do not access real private Family Room state or begin
another milestone from this handoff.

## BM-022V / BM-022V-R integration complete

BM-022V and BM-022V-R are complete, supervisor-approved, and integrated on
protected `matrix`. The clean matrix-side substantive commit is `31b8f9d`,
reconstructed from approved worker commit `784ea8f`; worker-only `.agent/*`
metadata was not copied. Matrix remains neutral with `active_agent: none`.

The read-only Family Room software capture is complete for required software:
37 nodes; 67 required and 3 optional edges; zero required missing artifacts;
30 exact artifact-backed nodes; 194,254,227 captured bytes; and fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
The exact Dropbox `10.3.1+matrix.1` artifact is present with SHA-256
`5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6` and
size 667,538 bytes. The cached Robotocjksc ZIP remains byte-for-byte
unchanged; its single safe alternate root is accepted by the generalized
validator and normalized during staged extraction. Optional YouTube remains
non-blockingly incomplete because the installed and cached versions differ.

Ready-to-use configuration is **INCOMPLETE / BLOCKED_BY_BM017** because
private/authenticated state was not captured. Real-device frozen installation
is **NOT YET VALIDATED**. The Family Room profile/evidence remained read-only;
no installation, update, enable/disable, repository refresh, restart,
settings/database write, or reconciliation occurred. BM-017 remains deferred
and no next milestone was started.

Validation from the integrated tree passed focused tests **331/331**, the
full suite **1577/1577**, and `git diff --check`. The smallest next step is
supervisor direction on the separate BM-017/private-state boundary; do not
install the candidate build or begin another milestone from this record.

## BM-022 integration complete

BM-022 is complete, supervisor-approved, and integrated on protected `matrix`.
The clean matrix-side substantive commit is `56ea26a`, a cherry-pick of
worker commit `27f4215`. The worker tracking commit and all worker `.agent/*`
metadata were excluded. Matrix remains neutral with `active_agent: none`.

The integrated lifecycle consumes only complete BM-021B manifests and exact
immutable artifacts, validates artifact identity and ZIP structure, installs
the required third-party graph deterministically, and excludes Kodi/system
dependencies from artifact installation. It reuses the reviewed BM-011
staged-package boundary and does not create a second unrestricted installer.
Wrong-version replacement, downgrade, broken state, missing metadata, and
orphaned target directories fail closed.

The durable frozen transaction captures build/manifest identity, phase,
original updater policy, guard ownership, restart linkage, and bounded status.
The updater guard is persisted before the first mutation, `NEVER_CHECK` is
verified before installation and reasserted before BM-020 startup/resume, and
release restores and verifies the original policy before clearing the frozen
transaction. Failures remain diagnosable in `NEEDS_ATTENTION`; there is no
silent completion or automatic software rollback. Explicit abandon is
available and does not claim rollback.

BM-022 composes with the existing Build Manager configuration and BM-020
restart/resume lifecycle. The new read-only dependency metadata fallback only
reads the known installed VFS path when Kodi cannot expose a freshly
discovered disabled add-on handle; it does not mutate Kodi state or fabricate
metadata.

Rerun evidence: focused regressions **639/639**, disposable
`validate-frozen-install` passed, full suite **1573/1573**, and
`git diff --check` passed. The proof used only `.kodi-test`; complete real
Family Room capture/install and real-device validation remain pending.

BM-020, BM-021A, BM-021B, and BM-022 are complete. BM-017 remains deferred.
No next milestone was started. The smallest next step is supervisor direction
on the remaining real Family Room/device validation boundary.

## BM-021B integration complete

BM-021B is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`. The reviewed
substantive endpoint was reconstructed as `2ee040c` (`feat(BM-021B): add
frozen artifact capture core`); worker-specific `.agent/*` files were not
copied.

The capture core provides a SHA-256 content-addressed, atomic write-once
artifact store with immutable sidecar metadata and read-back verification;
exact ZIP/package validation without execution or installed-directory
synthesis; typed installed inventory, transitive dependency closure, exact
system boundary, honest provenance, deterministic manifest/fingerprint, and
fail-closed incomplete states; plus exact store/cache/repository acquisition
ordering. The updater guard uses supported Settings JSON-RPC, captures and
restores the global policy explicitly, and must reassert/read-back
`NEVER_CHECK` before each resumed mutation because that setting does not
persist across restart.

The disposable gate proved 18/18 AF3 third-party closure entries healthy plus
the system boundary, exact installed versions and edges, and an honest
`incomplete_artifact` result when exact package-cache ZIPs were unavailable.
It did not claim a complete build, installed-directory provenance, frozen
installation, retention, pinning, scheduling, freshness enforcement, or
garbage collection. The updater proof passed read/set/read-back, restart
reassertion, no observed scheduled updater activity while guarded, explicit
restoration, and second-restart restoration. Focused validation passed
372/372 tests and the full suite passed 1557/1557; `git diff --check` is
clean. The live proof used only the disposable `.kodi-test` profile; no real
Kodi profile or Apple TV was accessed.

BM-020 and BM-021A/B are complete. BM-022 has not started, BM-017 remains
deferred, and family-room source/distribution concerns remain pending. The
smallest next step is supervisor direction on those separate concerns; no
next milestone was started.

## BM-021A integration complete

BM-021A is complete, supervisor-approved, and integrated on protected `matrix`.
The substantive audit commit is `b32369e`; no worker-specific metadata was
copied. `docs/FROZEN_BUILD_CAPTURE.md` records the exact artifact/provenance,
dependency-closure, updater-policy, immutable-store, and freshness conclusions
for future BM-021B/BM-022 work. It explicitly rejects installed-directory
zipping and undocumented per-addon auto-update assumptions.

BM-021B and BM-022 remain unstarted. BM-020 remains complete, BM-017 remains
deferred, and family-room source/distribution concerns are not independently
marked solved. Matrix remains neutral with `active_agent: none`.

## BM-020C integration complete

BM-020C is complete, supervisor-approved, and integrated on protected
`matrix`; matrix is neutral with `active_agent: none`. The matrix-side
substantive commits are `81ba44b` and `091cfe9`. Codex worker metadata was not
copied.

The guarded resume coordinator now re-reads the durable request after a new
Kodi session, previews the exact request and fingerprint before mutation,
claims `AWAITING_RESTART` atomically as `RESUMING`, runs normal
`BuildManager.reconcile()`, verifies the final fingerprint and `NONE`, and
clears the expected transaction atomically. Preview/fingerprint/reconcile
failures, claim/clear conflicts, exceptions, repeated restart requirements,
and later `RESUMING` or `NEEDS_ATTENTION` states fail closed. The service does
not restart Kodi or a host process; current supported platforms require a
manual full Kodi restart, after which resume is automatic.

Integrated validation passed focused tests **465/465**, disposable BM-020C
resume gate **8/8** with AF3 dependency closure **18/18**, full suite
**1536/1536**, and `git diff --check`. The gate proved service automatic
resume, authoritative read-back, fingerprint equality, `NONE`, no duplicate
handoff, later no transaction, and real Kodi profile immutability. AF3
generated first-run runtime state was bootstrapped only in `.kodi-test`; the
AF3 unmanaged probe is intentionally owned by BM-020A because AF3 normalizes
that entry across restart. Pristine first-ever AF3 provisioning is not claimed.

BM-020 overall is complete. BM-017 and family-room distribution/source work
remain deferred. The smallest next step is supervisor direction on those
separate concerns; no next milestone was started.

## BM-020C1 integration complete

BM-020C1 is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive commit is `bcaf2ca`. Codex worker metadata was not
copied.

The integration adds the typed capability resolver and manual restart
coordinator, with current and unknown platforms conservatively mapped to
`MANUAL_APP_RESTART_REQUIRED`. Successful `KODI_RESTART` handoff preparation
persists and read-backs `AWAITING_RESTART` with attempt count `0`, never
restarts or quits Kodi, and returns structured manual guidance. Failed runs
create no transaction, `NONE` completes without one, same-session requests do
not re-run reconciliation, and a new session with count `0` is ready for the
later resume phase. No automatic adapter or resumed reconciliation is
claimed.

Matrix validation passed focused tests **63/63**, disposable manual gate
**8/8** with AF3 closure **18/18**, full suite **1517/1517**, and
`git diff --check`. The gate used only `.kodi-test`; the real Kodi profile,
Apple TV, and all devices remained untouched.

BM-020C resume work remains incomplete: fingerprint revalidation, `RESUMING`,
resumed reconciliation, success clear, loop prevention, and failure/recovery
semantics. Do not begin that work, BM-017, or family-room distribution/source
work as part of this integration record.

## BM-020B integration complete

BM-020B is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive integration commit is `f3ccf2a`. Worker-specific
Codex metadata was not copied.

The durable foundation is profile-local and schema-versioned. It records only
the safe request, desired fingerprint, restart requirement, originating Kodi
session UUID, and transaction phase. Writes are staged in the same directory,
flushed and fsynced, atomically replaced, read back, and rejected if corrupt
or unsupported. An explicit clear removes the record safely. A profile-local
sidecar uses nonblocking `fcntl.flock`; lock ownership is released by the OS
when the process exits. The current Kodi session UUID is held in the home
window property `script.build.manager.kodi_session_id`.

`service.py` is a thin `xbmc.service` startup entrypoint. It classifies the
record and publishes the bounded result without restarting Kodi, reconciling,
resuming, or claiming a transaction. BM-020C owns actual resume/re-entry
execution.

The integrated disposable gate passed **9/9**: service fast path, session
identity, production preparation without restart, same-session protection,
external process boundary, automatic ready-for-resume classification, clear,
returned fast path, and real-profile immutability. Transaction tests passed
**32/32**, the full suite passed **1504/1504**, and `git diff --check` passed.
The first gate invocation observed only a startup-readiness race and was not
used as evidence of a code failure; the unchanged retry passed all 9 checks.
The real Kodi profile, Apple TV, and all devices remained untouched.

BM-020C and BM-017 remain unstarted. No next milestone was started. The
smallest next step is supervisor direction on BM-020C's resume/re-entry
policy; no worker handoff is implied by this matrix record.

## Prior integrated state

## BM-020A integration complete

BM-020A is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive commits are `eeafc1c`, `0ed2c35`, `821e69e`,
`0fb0bd5`, and `1ad0fdb`. Worker-specific Codex metadata was not copied.

The callable contract now available to BM-020B is
`BuildManager.reconcile(ReconcileRequest) -> ReconcileResult`. It owns the
load/inspect/resolve/preflight/plan/ordered execution/post-validation flow,
returns the safe request, deterministic desired fingerprint, ordered action
results, structured failure, validation report, and aggregated BM-019
`RestartReport`. It does not restart Kodi, persist transactions, resume after
restart, lock, or handle restart loops.

The integrated disposable `validate-build-manager` gate passed using the
self-contained AF3 fixture and production `af3-common` package: 18/18 AF3
closure entries healthy, `SET_SKIN` → `SkinActivator`, `CONFIGURE` →
`ConfigurationManager`, all 16 settings read back, `files=[]`, and
`RestartRequirement.NONE`. The second identical request retained the same
fingerprint and made no mutations. Managed `Navigation.OnBack` drift was
repaired; unmanaged `TMDbHelper.Corner.Radius` was preserved; invalid selector
failed closed before mutation. The `kodi.resource` system-dependency fix was
minimal and regression-tested.

Codex worker synchronization completed by normal merge from protected matrix;
the worker remains idle/ready for BM-020C and the external active-worker
pointer remains `build-manager -> codex`.

Focused integrated validation passed 1458/1458; full suite passed 1472/1472;
`git diff --check` passed. The family-room production source/distribution gap
remains a separate pending concern and is not claimed by BM-020A. The real
Kodi profile, Apple TV, and all devices remained untouched. BM-020B/C and
BM-017 were not started.

- Normal composition reached manifest/profile resolution, production package
  resolution, planner, `SET_SKIN` through BM-018A, `CONFIGURE` through
  ConfigurationManager, and post-validation through BM-014.
- The real `af3-common` descriptor applied and read back all 16 typed settings;
  its effective file target list was empty. First pass required no restart.
- Exact second request kept the same fingerprint and made zero mutations.
- A deliberate managed `Navigation.OnBack` drift was repaired, while the
  unmanaged `TMDbHelper.Corner.Radius` probe remained unchanged.
- Invalid device selector failed closed during resolve without state change.
- The disposable AF3 closure was healthy; `kodi.resource` is now correctly
  treated as a Kodi system dependency, with focused regression coverage.

Focused tests passed 1391/1391 and the full suite passed 1472/1472.
`git diff --check` passed. BM-020B/C and BM-017 remain unstarted. The real
Kodi profile, Apple TV, and all devices remained untouched. Family-room
distribution/source work remains separate and was not started.

## BM-023A macOS retry — 2026-09-24

**Status:** `BLOCKED_BM023A_ADAPTER_NAMESPACE_PACKAGE_PATH_TYPEERROR` after one authorized live attempt and offline diagnosis.

**What was done:** Confirmed the dedicated Kodi 21.3 app remained in portable
mode and was the only Kodi process. Installed Build Manager 0.1.0 and the
temporary BM-023A invocation adapter through Kodi's built-in ZIP installer in
the test app's portable profile. Invoked the adapter once. It returned
`ok=false`, `error_type=TypeError` without an outcome, code, transaction, or
lifecycle stage. Offline reproduction located it at the temporary adapter's
`Path(resources.__file__)` source check: `resources` is a namespace package
and `__file__` is `None`. The filtered target log has no traceback. The
updater policy read-back remained 0, equal to the pre-run value.

**What was not done:** No frozen transaction or imported overlay file appeared
in the portable profile, and none of the 32 non-system manifest add-ons had an
installed add-on directory. Red Light resource initialization, private apply,
activation release, restart/resume, and final validation have no positive
evidence. No product code change or test suite run. No normal Kodi profile or
real device was accessed. The exact test-app process was subsequently stopped
and verified exited; no second attempt occurred.

**Smallest next step:** Supervisor review of the adapter guard correction
recommendation. The adapter can validate `resources.lib.__file__` or
`resources.__path__`; any live retry requires separate supervisor direction.

**Human input:** Supervisor direction before changing the adapter or resuming
macOS BM-023A. tvOS remains unvalidated.

## BM-023B — protected matrix integration and Codex synchronization

The reviewed substantive implementation commit `1d60ed3` was cherry-picked to
protected `matrix` as `5648c678`; sanitized neutral tracking is `d867b80`. The
Codex worker branch was synchronized through this normal merge, preserving its
BM-023A/B history and Codex identity. Worker `.agent/*` files were not copied
onto matrix. The worker BM-023B usage row and neutral matrix integration row
are each preserved exactly once.

Matrix validation passed focused relevant modules **581/581**, full suite
**1643/1643**, `compileall`, schema/example JSON parsing, and
`git diff --check`. The synchronized substantive endpoint matches matrix when
`.agent/**` is excluded. No Kodi app, Family Room, device, portable profile,
or private-overlay value was accessed during integration.

BM-023A-R1 is separately authorized and architecturally unblocked; it had not
started at this synchronization checkpoint. The next action is the isolated
macOS destination preflight using only `/Applications/Kodi Build Manager Test.app`.
tvOS remains NOT VALIDATED.

## macOS BM-023A offline skin activation diagnosis — 2026-09-24

**Classification:** `BLOCKED_BM023A_SKIN_ACTIVATION_FAILURE_REASON_UNPERSISTED`.

The worker was clean on `agent/codex` before this task. Only the dedicated
portable test-app profile and repository files were inspected. No Kodi launch,
adapter invocation, retry, recovery, production edit, or test run occurred. No
normal Kodi profile, real device, or private overlay values were accessed; no
product commit was made.

The preserved adapter 0.0.2 result is `ok=true`, `outcome=needs_attention`,
`code=FROZEN_CONFIGURATION_ACTION_FAILED`. The durable transaction is still
present at phase `needs_attention`; its safe status detail is
`outcome=failed; phase=execute; failure=ACTION_FAILED; action=SET_SKIN;
addon=skin.arctic.fuse.3`. The transaction is at configuration execution,
`lifecycle_stage=none`, restart count 0, with no activation-hold IDs and
`activation_hold_released=true`. The updater guard is required: current policy
2 (`NEVER_CHECK`), original policy 0 (`AUTOMATIC`).

`skin.arctic.fuse.3` is installed, enabled, unbroken at 3.3.1. The portable
`lookandfeel.skin` value remains `skin.estuary`. Red Light 2.6.8 is installed,
enabled, and unbroken. YouTube is recorded as skipped and absent, consistent
with policy. The adapter imported the overlay, but the failed `SET_SKIN` action
preceded any `CONFIGURE` action; private application, structured-resource
initialization, private verification, activation release, and final validation
were not reached. The durable `private_overlay_required=false` was not updated
with result overlay metadata because `_handle_configuration_result` raises on
failure before its later persistence transition; do not treat it as evidence
that the overlay was not imported or required.

The planner orders `SET_SKIN` before `CONFIGURE`, and `BuildManager.reconcile`
returns on the first failed action. Therefore no public/private CONFIGURE
action failed here; the failure is specifically skin activation through
`BuildManager._dispatch_action` and `SkinActivator.activate`, wrapped by
`FrozenInstallCoordinator._handle_configuration_result` as
`FROZEN_CONFIGURATION_ACTION_FAILED`. The resulting `SkinResult` has status
`FAILED`, but neither its message nor a typed failure code is persisted. The
final portable setting shows the target skin was not persisted. The exact
inner branch (dialog timeout, JSON-RPC error, read-back mismatch, or another
skin activation failure) cannot be determined from the preserved result.

In the current portable Kodi log, two warnings at approximately 10:20:12.589
and 10:20:13.350 report a failed `Timers.xml` load while the target skin is
referenced; the installed target skin directory contains no `Timers.xml`. A
generic error follows at approximately 10:20:13.714. No safe log marker
identifies the SkinResult failure branch, and no JSON-RPC error, Python
traceback/TypeError, database error, private verification, or activation
release marker was found in the correlated interval. The XML warnings are a
correlated clue, not proven root cause.

No restart was requested because reconciliation stopped during action
execution before RestartCoordinator could handle a successful reconciliation.
The zero restart count is expected at this failure point. The no-hold state
also means the BM-022 private-verification/release stages did not apply.

**Smallest correction recommendation:** add an allowlisted static failure code
to each `SkinResult` failure path and preserve that code in frozen diagnostics;
do not persist the raw result/exception message. Review whether the missing
`Timers.xml` warning is causal before considering any skin package correction.
Do not clear the `needs_attention` transaction. This task made no correction.

- BM-017F: `COMPLETE`.
- macOS BM-023A: `BLOCKED_BM023A_SKIN_ACTIVATION_FAILURE_REASON_UNPERSISTED`.
- tvOS: `NOT VALIDATED`.

**Human input:** supervisor review of this classification and correction
recommendation before any production change or live retry.

## BM-023A offline skin failure instrumentation — 2026-09-24

**Classification:** `BLOCKED_PENDING_DIAGNOSTIC_RETRY`. This is an
observability correction only; the AF3 activation failure itself is not fixed.

Added `SkinFailureCode` and optional `SkinResult.failure_code`. Successful and
already-active results retain `None`; existing positional `SkinResult`
construction remains compatible. Failure codes are static enum values and
never incorporate Kodi text, values, paths, or exceptions. The activation
algorithm retains its previous command order, Home preparation, `SendClick(11)`
path, timeout durations, post-confirmation persisted/active read-back order,
stability check, and implicit keep/revert behavior. The code has no explicit
rollback/revert operation.

Audited failure paths and assignments:

- Invalid add-on ID: existing `SkinValidationError` is raised before backend
  access; no `SkinResult` or mutation.
- Initial active-skin read error → `INITIAL_SKIN_STATE_READ_FAILED`; already
  active remains successful with no failure code.
- Target state read error → `TARGET_SKIN_STATE_READ_FAILED`; absent and
  disabled targets → `TARGET_SKIN_NOT_AVAILABLE` and `TARGET_SKIN_DISABLED`.
- Pre-existing confirmation dialog → `PREEXISTING_CONFIRMATION_DIALOG`;
  failure reading the initial dialog state →
  `CONFIRMATION_STATE_READ_FAILED`.
- Home/preparation failure → `SKIN_CHANGE_PREPARATION_FAILED`; failure to set
  the skin → `SET_SKIN_COMMAND_FAILED`, unless a typed Kodi JSON-RPC failure
  gives `JSONRPC_FAILURE`.
- Confirmation polling expires without a state-read error →
  `CONFIRMATION_NOT_OBSERVED`; terminal active/dialog read errors are separately
  `ACTIVE_SKIN_READ_FAILED` or `CONFIRMATION_STATE_READ_FAILED`.
- Yes/click failure → `CONFIRMATION_ACTION_FAILED`; close polling expires with
  the dialog still visible → `CONFIRMATION_NOT_CLOSED`; terminal visibility
  read error → `CONFIRMATION_STATE_READ_FAILED`.
- Persisted setting read failure → `PERSISTED_SKIN_READ_FAILED`; a completed
  read-back with a different skin → `TARGET_SKIN_NOT_PERSISTED`.
- Loaded-skin read failure → `ACTIVE_SKIN_READ_FAILED`; completed read-back
  with a different skin → `TARGET_SKIN_NOT_ACTIVE`.
- Stability polling timeout → `SKIN_DID_NOT_REMAIN_STABLE`; terminal setting or
  active-skin read error is identified as `PERSISTED_SKIN_READ_FAILED` or
  `ACTIVE_SKIN_READ_FAILED`. The final fallback is
  `UNKNOWN_SAFE_FAILURE`.

Frozen `needs_attention` diagnostics retain the existing top-level
`FROZEN_CONFIGURATION_ACTION_FAILED` and add `skin_failure_code=<allowlisted
enum>` only for failed `SET_SKIN`. Existing `action=SET_SKIN` and
`addon=skin.arctic.fuse.3` identify the action/owner. `SkinResult.message` is
not copied. Regression coverage proved fake exception text, a private-looking
path, and secret text are absent from the durable transaction; existing
CONFIGURE diagnostics remain unchanged.

**Read-only AF3 package audit:** retained package metadata identifies
`skin.arctic.fuse.3` 3.3.1, SHA-256
`4d10cb10b9358a12a79519a813e82864b513370c627b85406e2840357b07729c`; ZIP
integrity passed. Neither that ZIP nor the portable installed 3.3.1 directory
contains exact `Timers.xml`, and a scan of package XML found no exact
`Timers.xml` reference in `addon.xml` or other AF3 XML. AF3 references to
`MyPVRTimers.xml` point to that distinct file, which is present. The installed
directory and retained ZIP have the same 3,700-file path set but three content
mismatches: `1080i/Includes_Home.xml`, `1080i/Includes_Labels.xml`, and
`1080i/Includes_SkinSettings.xml` (HomeSwitcher changes). Thus version matches,
but the retained ZIP is not byte-identical to the installed directory. The
warning is **correlated warning only**, not a demonstrated packaging defect or
cause of SET_SKIN failure. No source evidence established Kodi's precise
caller for the `Timers.xml` lookup.

The current portable failed transaction was not read for additional values,
modified, cleared, or recovered during this instrumentation task. No Kodi
application was launched; no adapter was invoked; no normal Kodi profile, real
device, or private overlay value was accessed. No skin behavior, AF3 package,
planner order, frozen lifecycle, transaction, or current portable policy was
changed.

Validation: skin activation tests **44/44**; skin frozen-diagnostic integration
and existing CONFIGURE diagnostics **9/9**; full suite **1810/1810**;
`compileall`, `.agent/AGENT_STATUS.json` and schema JSON parsing, and
`git diff --check` passed. Codex usage figures were unavailable; recorded as
unavailable rather than estimated. Requested Luna-6/High was not independently
observable in the runtime label.

**Implementation/test commit:**
`20bb8f09c8804c4bb1ea1405f1a1b2c7845974b9`. The sanitized tracking commit is
separate. Matrix remains
`66b0fd8a123ef778b23ba42703937b07eefc4e6f`; this work is only on
`agent/codex`.

- BM-017F: `COMPLETE`.
- macOS BM-023A: `BLOCKED_PENDING_DIAGNOSTIC_RETRY`.
- tvOS: `NOT VALIDATED`.

**Next step:** supervisor reviews this safe diagnostic change and authorizes a
separate live retry/recovery plan. Do not launch, rerun, or clear the current
transaction without that authorization.
