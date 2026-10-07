# Current Test.app Helper Correction — PASS offline; STOP

## Identity and outcome
- Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex; branch agent/codex.
- Clean starting HEAD: 3e41647bb9de04eb43c6f10bbc82ac6136c13aa0.
- Starting helper blobs verified: bm_test_app.py 1cd9bc488b4eb89ed8cd0bd6ac18b6b2ad1e784d; bm_test_app_keychain.py 03ce202ecdda57f5b2dc6d577613d1a65d45fa5d.
- Correction commit: f6892d02bcb107619d2bff389026ffc3a6b89847.
- Removes six demonstrated helper safety blockers to beta exit item 8. This is implementer evidence, not independent approval or live qualification.

## Before / after adversarial evidence
All probes used disposable fake bundles/RPC and synthetic credentials; source was unchanged until all baseline failures were reproduced. The same standalone six-probe harness was rerun separately from the regression suite against the correction.

| Blocker | Baseline | Corrected probe |
| --- | --- | --- |
| Short credential | 3-character credential in unknown key escaped stdout and output file; exit 0 | credential_unsupported, exit 1; no stdout/file leak; no authenticated retry |
| Redirected rollback | Failed fourth rename replaced Resources with symlink; three rollback renames followed it | rollback_ancestor_unsafe; zero redirected renames; stage/old/evidence retained |
| Durability | Successful _apply_stage: 75 file fsyncs, zero directory fsyncs, old deleted | 75 file fsyncs, 42 directory fsyncs before cleanup; durable commit permits old deletion |
| Same PID | Foreign executable at same numeric PID received second RPC | foreign_kodi_process_present; only first request sent |
| Final source drift | Fresh adapter success + modified service.py: exit 0, ok true, manifest equality false | exit 1, ok false, adapter_ok true, modified_files evidence retained |
| Post-swap interrupt | Verification KeyboardInterrupt left new trees live, old retained, no rollback | originals restored, interrupt propagated; evidence backups retained |

## Correction
- tools/bm_test_app.py: shared >=8-character policy; fixed safe credential error; per-request full identify + original PID + listener check, including authenticated retry; final runtime validity and independent adapter/command outcomes.
- StageJournal pins st_dev/st_ino for every ancestor through addons and stage/new/old/failed. Shallowest-first checks before rollback inspection and each rename reject real-directory and symlink substitutions. Rollback stops on first failure; unsafe/failed rollback performs no cleanup.
- Strict directory fsync publishes backup directories bottom-up and run/evidence parents, new staging hierarchy, and both parents after every swap/rollback rename. Post-swap verification, backup recheck, moved-old validation and final fsync stay inside one guarded commit boundary. Original exceptions/interrupts propagate after successful rollback; rollback failure is a safe fixed error. Old deletion follows durable commit only.
- Backup mismatch after mutation attempts rollback and retains stage evidence even when originals are restored. Cleanup now refuses symlinked old without inspecting it and rechecks pinned identities.
- tests/test_bm_test_app.py and tests/test_bm_test_app_keychain.py: 28 added test methods, with parameterized cases for all requested credential lengths, directory identities, exception classes, RPC identities and command outcomes. Replaced intentional drift-success/runtime-invalid-success expectations; direct RPC Keychain fixture now provides a real fake portable identity.
- docs/BM_TEST_APP_HELPER.md: credential policy, full per-request identity, run exit semantics, strict durability, explicit commit/rollback boundary and independent review gate.

## Validation
- New focused regressions: 28 PASS in 8.560s.
- Required full helper-focused suite: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm_test_app tests.test_bm_test_app_keychain — 437 PASS in 87.914s, supported Codex escalated context.
- Initial restricted full run had expected ps/socket restrictions plus missing fake runtime identity in older direct-RPC Keychain fixture; fixture corrected without bypassing safety. Final permitted suite has no failures.
- Cross-findings: post-rename fsync failure -> guarded durable rollback; fsync failure + ancestor substitution -> zero further renames; completed-swap interrupt + unsafe ancestor -> preserved old/evidence; 401 -> credential policy -> refreshed runtime/listener -> retry. Every rollback rename syncs both parents. CLI interrupt after completed swap restores originals and exits 130.
- Standalone corrected A-F probes all close the baseline failure (counts above). Tests prove fsync ordering/failure semantics, not hardware power-loss survival.
- In-memory Python parse and git diff --check PASS. No product/shared runtime source changed; no product full-suite rerun required by this task. Keychain wrapper source and tools/bm023a_adapter_support.py unchanged.

## Limits / not done
- No live Test.app staging, verify, launch, run, quit, snapshot or portable_data access/mutation; no normal Kodi/profile access; no real Keychain retrieval; no household device access; no push/release/publication/matrix integration/history rewrite.
- --no-git-binding remains available. The future qualification prompt must prohibit it. Existing process census, exact target, provenance, freshness, loopback, schema and other accepted safety properties remain in place.
- Identity checks use stable device/inode comparisons immediately before operations; no claim of eliminating concurrent check-to-use races. Ambiguous recovery is intentionally retained.
- After durable commit, conservative cleanup/reporting failures cannot require rollback of already discarded old state.
- Observed model: GPT-6 session identity; exact tier and effort unavailable. CLI telemetry unavailable; only a desktop end reading was captured: 45% five-hour / 43% weekly remaining, start/delta unknown. Account-wide concurrency is not excluded.

## Next step / human input
Independent correction-delta review of 3e41647bb9de04eb43c6f10bbc82ac6136c13aa0..f6892d02bcb107619d2bff389026ffc3a6b89847, limited to the six blockers and their interactions. Eric/ChatGPT supplies the bounded independent review task. Only after that PASS, restart BM-UI-003C Test.app qualification. Helper is not cleared for live use. STOP here.
