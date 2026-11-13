# BM-UI-NATIVE-SKIN-STAGE — PASS (2026-11-10)

- Done: one supported stage of independently reviewed `20a75f7b8506d46847590a3a1d59b4959cfb254e`, agent/codex, unchanged HEAD. Correct disposable Test.app/zero-process admission passed; previous installed candidate 50c5f5ffe51058f1dc561e94f7567d8818971b42 and adapter verified against its manifest first. Existing approved machine-local configuration hash unchanged and validated normally.
- Stage exit 0, durable_commit=true, stage_area_removed=true; both replaced product trees backed up/verified. Separate supported read-only verify exit 0, installed_equals_candidate/manifest=true and Git checked/ok; no missing/modified/unexpected/unreadable entries or Git mismatches. Product 0.1.0 / 85 files; adapter 0.0.16 / 5 files, tree SHA256 `09afc6b56fa85418a89d1ec959ec287b330ab7e391af89cdb9265676bd43c1cb`. Final target state not_running, zero target processes.
- Manifest: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/native-skin-styling-stage-20261110T161236Z/stage-20261110T161312Z-20a75f7b8506/stage_manifest.json`, SHA256 `474695b6085b732af521afc0d655c158f4e2948b24964a36d26d5684a122e313`. Report `.qualification-evidence/native-skin-styling-stage-20261110T161236Z/REPORT.md`; source/tree identities and verification retained in final-integrity.json and helper receipts.
- Preservation: product-only swap left portable userdata, existing builds, active-skin selection and AF3 settings in place; AF3 not modified/reinstalled. User supplied separate AF3 3.3.12 compatibility inspection. No A15/extended qualification or independent userdata-content comparison was run.
- Not done: no source/new product commit, Test.app launch/quit/restart/native UI/Create, saved-build operation, skin change, normal Kodi/profile/device access, DECISIONS update, Agent Handoff, merge, push or release. No native visual or design/beta acceptance claim.
- Next/human input: Eric launches with Dock shortcut and visually evaluates AF3. No staging/verification blocker remains. Stop agent work after this bounded installation.
- Cleanup: helper build/stage scratch removed normally; one duplicate stdout copy removed after equality check. New receipts/manifest/report and verified replaced-product backups retained. All old evidence and incoming dirty .agent histories preserved; tracking additive/uncommitted. Usage/model variant/effort unavailable.

# BM-UI-NATIVE-SKIN-STYLING — offline candidate ready for independent review (2026-11-10)

- Done: one 12-file local commit `20a75f7b8506d46847590a3a1d59b4959cfb254e`, base `50c5f5ffe51058f1dc561e94f7567d8818971b42`, agent/codex. AF3 native dialog/background/focus/checkbox/button/scrollbar includes; explicit native Estuary variant; self-contained neutral other-skin fallback with four small owned PNG assets. Visual private/add-on checkbox state retains existing selection semantics. Create buttons Apply / Cancel / Help; other requested orders/routes retained. Backend/NativeDialogs/workflow unchanged; no new GUI framework.
- Source authority: AF3 v3.3.12 tag commit 660a05c35546718e90a88be7798bb0a92632abce, 18 direct includes and icon/checkbox assets checked; Estuary Kodi 21.3, four direct includes checked. Pinned metadata/source hashes in tests/fixtures/native_skin_contracts.json; approach/limits in docs/NATIVE_DIALOG_STYLING.md. Current upstream AF3 3.4.20 initially inspected, then exact retained 3.3.12 target verified. No installed-skin version probe.
- Validation: final 388 focused UI/Create/routing/busy-state tests PASS, zero failures/errors/skips, 12.444s. AST/XML/native-contract hash/fallback asset/exact scope/diff checks PASS. Strict Kodi 21.3 scrollbar restriction retained; no Python 120/121 wrappers. Full historical suite not run per task. Author and committer Eric Engert <eengert@gmail.com>, checked effective and raw fields.
- Not done: no Test.app stage/launch/restart/observe, skin/profile/saved-build modification, normal Kodi/profile/device access, backend/lifecycle change, Agent Handoff, merge, push or release. Offline tests do not prove rendered native appearance or universal skin inheritance. Item 8/design/beta acceptance not claimed.
- Report: `.qualification-evidence/native-skin-styling-20261110T154600Z/REPORT.md`; final focused log, static validation and exact commit/file summaries retained there.
- Next/human input: independent source review of 50c5f5f..20a75f7, then separately authorized staging and Eric's AF3-first visual test (theme/corners/focus/checkboxes/action icons/long content/navigation), Estuary and an additional fallback skin. Stop after this implementation; no staging authority in this task.
- Cleanup: 37 task-owned downloaded sources/tree/generator/test scratch files and their temporary directory removed after final evidence retention. No screenshots/recordings created. All incoming .agent history and old evidence preserved; local tracking remains additive/uncommitted. Model variant/effort/usage unavailable; no estimates.

# BM-UI-AF3-MAIN-FIX — corrected, validated and staged (2026-11-10)

- Confirmed root cause: stopped portable Kodi log has three onInit failures at getControl(120). Kodi 21.3 exposes no Python scrollbar wrapper; the exception occurred after the title and before list/action population. Strict offline stub reproduced the exact error before edits.
- Done: four-file presentation-only correction in `50c5f5ffe51058f1dc561e94f7567d8818971b42`, parent `804dd56f3ebc810754d492debe2582d4a3747284`, agent/codex. Move scrollbar visibility and action horizontal navigation to conditional XML in AF3/Default; no layout/color/backend redesign. Tighten control stub and add four regressions. Eric author/committer checked before commit and raw afterward.
- Validation: 382 focused UI/Create/busy-state tests PASS, zero failures/errors/skips; Python AST/XML/scope/diff and unchanged-other-XML-properties checks PASS. No full-suite repeat, per task.
- Staging PASS: exactly one supported stage using unchanged approved config; old 804dd56f installation verified/stopped first. Durable commit=true, stage_area_removed=true, verified backups retained. Separate read-only verification matches candidate/manifest/Git. Final Test.app not_running, zero target processes. Product 0.1.0 (80 files), adapter 0.0.16 (5 files). Manifest `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/af3-main-menu-correction-20261110T150414Z/stage-20261110T150909Z-50c5f5ffe510/stage_manifest.json`, SHA256 `1b3893114b7e8c1c86412d071b00d2aad7643f2c6a2cd1e9ed6c6f2043cf253e`.
- Report: `.qualification-evidence/af3-main-menu-correction-20261110T150414Z/REPORT.md`. Not done: no launch, unattended UI test/Create execution, saved-build or skin operation, A15, normal Kodi/profile/device access, Agent Handoff, push or release. No native visual PASS for corrected candidate. Product-only stage left userdata/builds/skin settings in place; no independent userdata-content qualification.
- Next/human input: Eric opens through Dock and manually rechecks six AF3 menu labels, one Close, focus/selection/Back; then Create/Add-ons/Review scrolling and Estuary compatibility. Stop after this correction.
- Cleanup: normal helper build/stage scratch removed; one duplicate stdout file removed after equality check. Sanitized diagnosis, reproduction/focused logs, installation evidence and backups intentionally retained. No raw Kodi log/screenshots retained; all incoming .agent history preserved outside source commit. Usage/model variant/effort unavailable.

# BM-UI-CREATE-STAGE — PASS (2026-11-10)

- Done: exactly one supported stage of independently reviewed `804dd56f3ebc810754d492debe2582d4a3747284` into stopped disposable Test.app, reusing the prior approved config unchanged. Previous installed candidate `a5a4a23b026ee5004f7f62ccf6387a7689d6c4c2` verified first. Stage exit 0, durable_commit=true, stage_area_removed=true; both replaced trees backed up. Separate Git-bound verification exit 0, installed_equals_candidate/manifest=true, final not_running/count=0. Product 0.1.0 / 80 files; adapter 0.0.16 / 5 files. No new Git commit; HEAD unchanged.
- Manifest: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/ui-redesign-staging-20261110T145310Z/stage-20261110T145451Z-804dd56f3ebc/stage_manifest.json`; SHA256 `dd9eccc13c35a79ac5c9e969abecd1c1c4fccc52358e805895847e2937b6fe2b`. Product tree `c8f50686bc1ffe6e27d19ea42f773675c74f46b23dfce0de2529a221f3c90a42`; adapter tree `0b57a5684284843fb2be8dd8aad556c0d02b750dce1c95e9f3208aa6a69872e7`. Report: `.qualification-evidence/ui-redesign-staging-20261110T145310Z/REPORT.md`.
- Preservation scope: stage swapped only product/adapter add-on trees; userdata, saved builds and skin settings were not replaced/reset or operated on. No A15 or independent userdata content comparison. No preservation-qualification claim.
- Not done: no launch, UI exercise, active-skin inspection/change, saved-build operation, MCP modification, source/DECISIONS change, normal Kodi/profile/device access, Agent Handoff, push, merge or release. Visual evaluation only; no design adoption or beta acceptance.
- Next: Eric launches through his existing Dock shortcut and evaluates AF3 first. No remaining installation/verification blocker established. Human input: manual visual feedback; no further agent operation authorized by this task.
- Cleanup: helper build/stage scratch removed through normal successful cleanup. New manifest/results/report and verified replaced-product backups intentionally retained in the one fresh evidence directory. All earlier evidence and incoming dirty .agent histories preserved. Usage readings/model variant/effort unavailable.

# BM-UI-CREATE-REDESIGN — offline candidate ready for independent review (2026-11-10)

- Done: four requested UI changes; 13 source/resource/test files in local commit `804dd56f3ebc810754d492debe2582d4a3747284` on `agent/codex`, parent `54e5f15d46dd83b0e397dcab422a22be6dddf716`. Author and committer both Eric Engert <eengert@gmail.com>, raw fields verified. Native WindowXMLDialog presenter, AF3/Estuary resources, localized actions; existing confirmation/execute and backend semantics retained.
- Validation: final focused/related 378 PASS, zero failures/errors/skips (33 new tests). Initial complete guarded discovery: 4626 tests, 2 failures/5 errors/6 skips, NOT full PASS. Its stale Create busy-state fixture was migrated and passes in the final related suite. Remaining helper/provenance/process/compiler results retained. Three helper/provenance isolation checks: 2 PASS, historical adapter AST check FAIL. No full rerun for the tiny test-harness migration. AST/XML/localization/scope/diff checks PASS. Report: `.qualification-evidence/create-workflow-ui-redesign-20261110/REPORT.md`; exact broad/isolation traces: sibling REGRESSION-RESULT.txt.
- Not done: no Test.app staging/launch/observe/mutation, normal Kodi/profile/device or saved-build access, backend/protected qualification changes, push, merge, release or Agent Handoff operation. No native visual PASS. Broad issues outside this task remain unresolved; no clean baseline full run was reproduced.
- Next: independent source review of `54e5f15..804dd56`, accounting for the recorded broad limitations; then separately authorized Test.app staging and AF3-first/Estuary visual verification. Human input: relay review; authorize staging only in a subsequent task.
- Cleanup: three owned scratch logs removed; compact local report/result extract intentionally retained as offline evidence. All incoming .agent history preserved, outside the product commit. Usage readings/model variant/effort unavailable; no quota estimates.

# Item 8 D-028 trusted manifest and builtin admission — PARTIAL; offline implementation ready for review

- Local commit 84f524a1a298bda520e241ff1e0ba99c244ac76f; exact review range a4b55cbf2f15420d9528d9300f9d06d8915b967c..84f524a1a298bda520e241ff1e0ba99c244ac76f. Twelve source/test files; authored AF3 22 nodes/45 edges, 17 exact original archives, four systems and one PIL platform requirement. Fingerprint 0399a872129059607efed0281c83a9e1f87699648ada55f9fa876a8b8324f545. Production round-trip and both strict validators PASS; raw core XML limitation retained.
- Shared fail-closed builtin collection/ABI/closure/freshness/repository-minimum checks, static system-edge validation and retry-before-artifact-write admission implemented. No diagnostic/adapter/UI/policy change. GUI/resource/core native usability remains UNVERIFIED.
- Validation: focused 473 PASS; corrected isolation/related 159 PASS; complete guarded offline suite 3924 PASS in 363.839s, no skips, exit 0, zero guarded live-target IO attempts. Twelve isolated mutations detected; AST/JSON/diff/source checks PASS.
- Safety deviation: initial broad suite's old fixture probed/read installed Test.app PIL XML. No native launch/staging/mutation. See SAFETY-NOTE.md and REPORT.md in .qualification-evidence/item8-d028-trusted-admission-20261020. Whole-task zero-Test.app-access cannot be claimed. Old native-input dependency was replaced with retained XML for final validation. Temporary runner multiprocessing recursion was corrected and the final suite is valid.
- Next: independent Claude review of complete range/evidence before any native staging. No native D-028 PASS; Item 8 and beta OPEN. Human input: relay independent review; no further construction input needed.
- Cleanup: 20 owned scratch/cache entries removed; compact qualification/incident evidence and incoming tracking snapshots retained. All incoming history follows unchanged.

# Item 8 D-028 trusted manifest/admission — BLOCKED at required design input

- Branch/HEAD verified: agent/codex, a4b55cbf2f15420d9528d9300f9d06d8915b967c. No source/test changes or commit.
- Required latest "ITEM 8 D-028 TRUSTED INPUT DESIGN: VIABLE" report not found in retained worktree evidence; requested exact path/contents. No claim construction is inherently impossible or archives missing.
- New unchanged-source bypass reproduction: managed -> GUI >=999 and system-only GUI -> core both accepted with zero builtin checks; no mutation APIs. Existing focused tests 114 PASS (2.664s, exit 0); five AST/three JSON checks and diff check PASS. Full suite not rerun; accepted unchanged 3893-test candidate preserved.
- Evidence: .qualification-evidence/item8-d028-trusted-admission-input-gate-20261020/REPORT.md. No native/Test.app/external operation. D-028 native proof, Item 8 and beta remain OPEN.
- Next: provide named retained viable-design report and resume bounded offline implementation. No native staging before independent Claude review.
- Cleanup: no task scratch/caches/screenshots retained; compact blocker evidence and incoming tracking snapshots intentionally retained. All incoming history follows unchanged.

# Item 8 D-028 verifier unblock — BLOCKED (2026-10-20T11:32:25.195626+00:00)

- HEAD remains a4b55cbf2f15420d9528d9300f9d06d8915b967c, agent/codex. No product/test changes or commit; no implementation review range. Test.app NOT touched, including no observe/probe; last-known stopped state is prior evidence only.
- Explicit missing-input STOP: retained 22-node/45-edge closure reports are not production frozen manifests and lack software_fingerprint. Four builtin-style nodes have no ordinary extension declarations; unchanged platform capture/type contract rejects them. No graph/type/fingerprint/capture result fabricated and no D-028 policy redesign.
- Existing driver lacks platform_check; naive new mode would enter source-repair bootstrap. No incomplete diagnostic mode added.
- 114 focused platform/adapter status/UI tests PASS; AST of eight source files, input probes, prior 143-file seal and diff checks PASS. Full suite not repeated for unchanged source.
- Shutdown: active synchronous Dialog.select is consistent with prior default.py five-second termination, not a proven root cause. Existing cancellation returns; no stack/native control comparison exists. Report specifies one future menu-open/fully-dismiss/quit/preservation control run, with script-return evidence explicitly conditional on supported observation.
- Report: .qualification-evidence/item8-d028-unblock-offline-20261020/REPORT.md. Next: Supervisor resolves trusted frozen-input/builtin representation blocker before invocation-only implementation; no AF3/native progression authorized by this result. Item 8/beta OPEN.
- Cleanup: test profiles self-cleaned; no task cache/worktree/native output. Compact report/probes/test log and exact incoming .agent tracking snapshots retained; historical seals unchanged. Usage unavailable, GPT-6 variant/effort unavailable.

---

# Item 8 native staging / D-028 — PARTIAL (2026-10-20T11:19:29.841168+00:00)

- HEAD/install: a4b55cbf2f15420d9528d9300f9d06d8915b967c, agent/codex; no source edits/commits. Established helper staged 76+5 Git-bound product/driver files, durable commit and final verify PASS. Original 61a5f28 package/driver copies retained and verified.
- Native: MCP portable launch/menu/public two-entry chooser/cancel PASS. Quit reached stopped, independently confirmed. No Python exception marker; CPythonInvoker terminated default.py after it did not stop within five seconds while main menu remained open. Unresolved, no relaunch.
- D-028: all five requirements BLOCKED on node-specific native registered identity/enabled/usable/unbroken/closure proof; no exposed read-only inventory/verifier invocation in MCP or exact driver. Static minima/metadata/no-shadow checks pass, not native admission. Foreground PID not independently exposed/proven; arbitrary network/profile state UNKNOWN.
- Preservation: profile 16777220/442000438, public library/selection/applied files, add-on state, Estuary/updater, transaction/hold census unchanged. Test.app STOPPED. No AF3/dependency installation/configuration qualified. Environment NOT admitted to next installation.
- Evidence/report: .qualification-evidence/item8-native-d028-20261020/REPORT.md; 143 sealed files; SHA256SUMS digest a149f73f53360a76b2e18bb2d7b8131d25b6a21fd56d4c7aa49763d21c1f559c. Two exact-window MCP PNGs, original rollback trees, before/after and diagnostics retained. Accepted offline 3893 PASS reused without rerun.
- Not done: temporary adapter/injection, runtime platform mutation, private Create/Red Light, normal Kodi/devices, keychain/NSUserDefaults, Agent Handoff/ai-supervisor, push/merge/release. Item 8/beta remain OPEN.
- Next/human input: Supervisor assesses the exact missing read-only native observation mechanism and shutdown diagnostic; new bounded task required before installation. No routine reapproval requested.
- Cleanup: three duplicate /private/tmp outputs removed; image buffers cleared; no task caches/worktrees. Historical evidence and original rollback bytes retained. Usage start/end/delta unavailable; observed model family GPT-6, exact variant/effort unavailable.

---

# ITEM 8 STAGE 2B1A B3 CORRECTION: COMPLETE (offline; re-review pending)

- Commit `5fb47fcf7dc9f0a98a55dc65747bb223a948fa17`, direct parent `7062f3f917c46b18f886ace77f87a3e5b1dea2e1`, agent/codex in authorized worktree. Exactly resources/lib/status.py and tests/test_status.py; 246 insertions/20 deletions. No amend/history rewrite. Admission: item 8 truthful verified-protection evidence during status assembly failure.
- Before source changes: one independent synthetic regression test exercised R1 final replace, R2 combine + one-shot _unverifiable_operation failure, R2prime combine + one-shot _failed_status failure, R3 invalid area objects. Each route tested HELD alone, HELD+frozen hold, UNVERIFIABLE+frozen hold: all 12 probes failed on parent with protection_active=False. After correction all 12 PASS.
- Per-call _StatusEvidence carries only verified hold Boolean and typed/sanitized operation reasons. Create hold recorded immediately after successful observation; frozen hold recorded immediately after accepted transaction read, before code/session assembly. Context passed locally through _check/_operation/_frozen_operation, never retained on service; guard inspect_operation also owns a fresh local context. No owner or transaction rereads for fallback reconstruction.
- Area/levels assembly now inside protected result boundary. Ordinary fallback retains assembled OperationStatus; if that/helper assembly fails, independent emergency construction uses context directly (no replace dependency), reports Needs Attention/Create UNVERIFIABLE/protection_unknown while retaining known active holds and reasons. Up to two emergency construction attempts, no recursive fallback. Persistent core constructor failure is outside valid-BuildStatus guarantee and yields sanitized RuntimeError("Build Status result construction unavailable"); test confirms four total constructor calls (main, ordinary fallback, two emergency attempts).
- Validation: 605 focused status/model/UI/adapter and plan/library/publication/install/guard-consumer tests: 604 PASS, only known baseline plan-view import-policy failure. Related B3+B2+B1/assessor/lifecycle/readiness/restart/transaction 199 PASS. Includes seven new B3 methods, all 12 original probes, 63-case prior normal matrix, fresh sequential checks after failure, simultaneous checks on same service, late frozen code failure, guard entry, pending Create + one-shot constructor and bounded persistent-constructor tests. Full known-red suite not rerun. Diff/staged checks PASS.
- Privacy/creation-free evidence: sanitized result/log tests, one observer call per original fault route, three observer/frozen calls for three sequential checks, unchanged filesystem snapshots/read-only open flags/no mkdir/CaptureStore lock/save/owner mutation in R3, existing guards and B2 error-path tests pass. No actual profiles/devices or private data.
- Consumer assessment: ui/status_view only displays both flags. plan.py includes protection_active in plan identity; operation Needs Attention adds blocker and any inspection gap makes plan INCOMPLETE. install_workflow.run refuses all non-NONE operation kinds. No consumer inspected treats active=False alone as permission when unknown=True. Faulted operation guard now retains local evidence/Needs Attention. No consumer product files changed; no supervisor stop conflict found.
- B1/B2 and normal observed states/precedence retained. No P5/D2, observer/assessor contract, lifecycle authority, frozen persistence, startup/recovery UI or deferred N1-N6 changes. No live Kodi/Test.app/normal profiles/devices, Agent Handoff, push/merge/release/history rewrite.
- Next/human input: STOP for independent Claude re-review of exact parent-to-correction delta. No further implementation/live work authorized.
- Cleanup: two task-owned focused logs removed; synthetic profiles self-cleaned; bytecode disabled. Existing qualification/review evidence and four dirty .agent histories preserved; new tracking unstaged. Usage/model exact tier/effort unavailable, no estimates.

---

# ITEM 8 STAGE 2B1A B2 CORRECTION: COMPLETE (offline; re-review pending)

- Commit `7062f3f917c46b18f886ace77f87a3e5b1dea2e1`, direct parent `1ec2f27697886b0c44be20c2dfadca365d431526`; agent/codex, authorized worktree. Exactly resources/lib/status.py and tests/test_status.py changed; 211 insertions/23 deletions. No amend/history rewrite. Item 8 admission: preserve truthful Create/protection status on inspection error paths.
- Before source edits: five negative B2 tests on reviewed source produced nine failure reports. Missing/held/unverifiable Create plus frozen session failures became INCOMPLETE; operation/result fallbacks erased Create state and holds. After correction all tests pass.
- Frozen inspection is isolated in _operation; unexpected failure becomes UNAVAILABLE/TRANSACTION_UNREADABLE, with unknown frozen protection, while observed Create and successfully read restart/publication reasons survive. _frozen_operation catches session classification failure after reading a validated hold and retains that hold. Persistence/authority unchanged.
- _check operation fallback now explicit Create UNVERIFIABLE/protection_unknown=True/Needs Attention. Result-construction/combine failure passes the already observed operation to _failed_status; that fallback marks Create UNVERIFIABLE and protection_unknown, preserves verified protection_active and stable prior operation reasons, and uses a fresh safe UTC fallback timestamp. check-level failure without retained evidence also reports unknown/Needs Attention. Model invariants unchanged; no false absence/healthy claim.
- Validation: original B2 reproduction five tests/nine failure reports; final B2+B1 ten tests PASS (includes 63 successful-operation combinations and creation-free failure-path checks). Broader focused status/model/UI/adapter/plan/library/publication/install/guards: 598 tests, 597 PASS, only known baseline plan-view import-policy failure. Related regression/assessor/lifecycle/readiness/restart/transaction run 192 PASS. Final ten-test rerun after adding Create-only outer-fallback hold assertion PASS. Diff/staged diff checks PASS. Known-red full suite deliberately not rerun.
- Evidence: missing observer still unknown; real no-record remains no-record when inspections succeed; pending/held Create survive local failures; independently verified frozen hold survives session failure; malformed/unreadable frozen snapshots preserve Create; unexpected frozen failure retains restart/publication reasons. Total fallback preserves Create-only active hold as verified evidence beside explicit uncertainty. Serialized/log output has no paths/secrets/exception payloads. Error-path open flags/snapshots/mkdir/CaptureStore lock/save/TransactionStore lock and owner mutation tripwires pass. Synthetic temporary profiles only.
- No Create adapter, model, UI/localization, assessor, lifecycle/P5/D2, frozen persistence, restart authority, runtime composition or D1/D3 change. No normal Kodi/Test.app/profiles/devices, Agent Handoff, push/merge/release/deployment. N1-N6 remain deferred unchanged.
- Next/human input: STOP for independent Claude re-review of exact parent-to-correction delta. No further work authorized.
- Cleanup: two task-owned focused logs removed; synthetic fixtures self-cleaned; bytecode disabled. Existing qualification/review evidence and four dirty .agent histories preserved; new bookkeeping remains separately unstaged. Usage/model exact tier/effort unavailable, no estimates.

---

# ITEM 8 STAGE 2B1A B1 CORRECTION: COMPLETE (offline; re-review pending)

- New focused commit `1ec2f27697886b0c44be20c2dfadca365d431526` on `agent/codex`; reviewed parent `6b29666b81155e80d0a0bb9244ad6c8e1830852e`. Exact candidate-to-correction delta: resources/lib/status.py (one-line initialization change) and tests/test_status.py (truthful shared fixture plus three regression tests); 78 insertions, one deletion. Reviewed candidate not amended.
- Before code correction, three new tests produced six failure reports on reviewed source: healthy missing-observer status CURRENT, restart/frozen missing-observer status RESTART_REQUIRED, and missing observer NO_RECORD_OBSERVED. After correction all three PASS, including four restart/frozen/held overlap cases and absent/raised/invalid/real-empty observer distinctions.
- Missing observer now UNVERIFIABLE -> Needs Attention, protection_unknown=True, no verified recovery eligibility. Independently verified frozen holds remain protection_active=True; overlapping restart reasons retained. Explicit real observer returning NO_RECORD_OBSERVED preserves established behavior. UI presents unverifiable Create progress, unknown protection and unchecked readiness; safe serialized output has no paths/secrets. File snapshot/open-flag/mkdir and owner mutation tripwires pass.
- Shared Harness now observes its synthetic temporary profile through accepted creation-free observe_create_state. PlanHarness and downstream status/UI/plan/library/publication/install tests inherit that truthful reader. No global missing-observer fallback, and intentional None regressions retained. No other test fixture files needed changes.
- Validation: 591 focused status/model/UI/adapter, plan/UI, library/publication/install and guard-consumer tests: 590 PASS, one known baseline plan-view import-policy failure. Separate 194 regression/adapter/assessor/lifecycle/readiness/restart/transaction tests PASS; explicit corrected three-test regression rerun PASS. Diff/staged diff checks PASS. Known-red full suite intentionally not repeated under task instruction.
- Scope preserved: accepted adapter, production wiring, five observed states, composition, typed model/privacy and localization unchanged. No P5/D2/lifecycle/recovery/restart/owner/Create runtime/D1/D3 edits or live operations.
- Deferred independent-review notes, unchanged: N1 other_codes deduplication; N2 generic interrupted-work header; N3 pending-finalization wording; N4-N6 uncertainty/test coverage notes. Review's prior 525 overlap-combination PASS is accepted review evidence, not a newly reproduced exhaustive claim.
- Next/human input: STOP for independent Claude re-review of `1ec2f27697886b0c44be20c2dfadca365d431526` relative to reviewed candidate. No further implementation or live action authorized.
- Cleanup: two task-owned test logs removed; synthetic profiles self-cleaned; bytecode disabled. Existing qualification evidence and four dirty .agent histories preserved with this new bookkeeping separately unstaged. Usage/model exact tier/effort unavailable; no usage estimates.

---

# ITEM 8 STAGE 2B1A: COMPLETE (offline; independent review pending)

- Commit: `6b29666b81155e80d0a0bb9244ad6c8e1830852e`; exact baseline `6e20ace702d536315cd7a470297cd5e10a2eb07f`; branch `agent/codex`, authorized worktree. Eight committed files: resources/lib/create_status.py, status.py, status_model.py, ui/status_view.py, resources/language/resource.language.en_gb/strings.po, tests/test_create_status.py, test_status.py, test_status_ui.py. Extra adapter/presentation files are narrowly necessary for safe capability separation and visible localized status.
- Observer: lazy production callable uses TransactionStore.directory (canonical profile/addon_data/script.build.manager) and accepted CaptureStore construction/read twice; no coordinator, locks, setters or recovery. Typed sanitized enum only; disagreement/errors -> UNVERIFIABLE. Two reads detect observed disagreement, not every race; trusted accepted path/store assumptions remain.
- HELD and TERMINAL_PENDING -> Needs Attention plus verified protection_active; TERMINAL_RELEASED adds no Create hold; NO_RECORD_OBSERVED retains prior healthy/no-record behavior, without a history claim. UNVERIFIABLE -> Needs Attention and protection_unknown. Verified frozen/Create holds OR together; unknown remains explicit even beside a verified hold. Existing publication/restart/frozen primary reasons retained according to Needs Attention > Restart Required > unavailable; other_codes retain additional stable reasons, and unreadable-state gaps are retained. Existing overall precedence unchanged.
- Creation-free/privacy: synthetic before/after filesystem snapshots, read-only open flags, no mkdir/save/lock calls, actual service+reader missing-directory regression, adapter AST capability guard, serialized/result privacy checks, fresh-read tests and plain-language UI tests. No UUID, fingerprint, request metadata, raw profile path or exception payload leaves adapter. Existing status import guard and stdlib-only presentation contract pass.
- Validation: final status/adapter/model/UI/assessor/lifecycle 293/293 PASS. Broader 12-module run 553 tests: 552 PASS, one unchanged plan-view import-policy failure independently reproduced on exact baseline. Additional activation/registry/restart/import guards 127/127 PASS. Full candidate run 3590 tests with 10 failure/6 error reports; nine unchanged synthetic process/PID/socket tests PASS with permitted execution, and exact baseline archive reproduces remaining two import-policy failures plus four synthetic keychain fixture error reports. Full suite is not green. Full run preceded one additional test-only service regression and a comment clarification; final 293 run covers both. Diff and staged diff checks PASS.
- Deferred: owner/version/enablement observations, trusted competing_operation provider, positive recovery advice, assessor integration, startup/resume and Native Create recovery UI. Owner/competition/recovery eligibility remain unassessed, never False/all-clear. P5/D2 and assessor source unchanged. No real Kodi/Test.app/profile/device, mutation or runtime qualification performed; item 8 remains open.
- Next/human input: STOP for independent Claude review of exact commit. Any further implementation/live action needs a separately bounded task.
- Cleanup: temporary baseline archives and synthetic fixtures self-cleaned; three task-owned test logs removed; bytecode disabled. No new scratch artifacts remain. Existing qualification evidence and four dirty .agent histories retained; this handoff/status/usage update remains separately unstaged.

---

# ITEM 8 STAGE 2B1 STATUS: BLOCKED

- Verified agent/codex and exact baseline 6e20ace702d536315cd7a470297cd5e10a2eb07f. Product source unchanged; no commit.
- Admission: item 8 truthful Build Status Create recovery presentation. Stopped at mandatory trusted runtime-observation dependency before implementation.
- Exact blocker: assess_capture_recovery requires operations.competing_operation(); docs/CREATE_CAPTURE_LIFECYCLE.md requires positive absence of in-flight Install/restart/activation beyond transaction files. No production implementation exists in resources/lib; runtime_create_workflow has no lifecycle operation composition. File snapshots or constant False cannot satisfy this contract.
- No observer, status mapping, protection integration, production wiring or new tests implemented. Existing assessor exposes advisory reason only, so protection must separately retain verified held/released/unknown information in a future observer.
- Validation: read-only source/contract inspection and git diff --check PASS. No test run or new regression evidence; source unchanged. No live operations, owner setters, lifecycle locks, capture/recovery/restart, real profiles or devices accessed.
- Smallest next step: independently assess this blocker and define/authorize a trusted creation-free, lock-free in-flight-operation observer (or explicitly authorize partial fail-closed production status without this evidence). Do not infer missing files mean no operation.
- Cleanup: no temporary artifacts created. Existing qualification evidence and dirty bookkeeping preserved; only appended handoff/status/usage records remain unstaged.

---

# ITEM 8 D2 OPTION A: COMPLETE (offline; independent review pending)

- Commit: `6e20ace702d536315cd7a470297cd5e10a2eb07f`; exact start `98509f8a52a936e0cf5434d6cf07dcd2d7a299ba`; branch `agent/codex`. Only resources/lib/capture_lifecycle.py, tests/test_capture_lifecycle.py and docs/CREATE_CAPTURE_LIFECYCLE.md committed.
- Automatic D2 mutation implementation and private authorization helpers removed. Compatibility prepare_d2_confirmation/recover_d2 always raise before locks, writes or owner setters; D2Confirmation remains inert and strict. Receipt decoder/binding, normal Create restoration, assessor and P5 implementation unchanged.
- Original=False/current=True refuses without setters or release. Operator manually restores False; hold remains until explicit exact-request/owner recovery completes P5. Zero setter calls asserted across manual/receipt recovery, pending/crash retries and retired APIs. RESTORING COMPLETE/FAILED/CANCELLED preserved. Legacy receipt absence and valid historical receipts decode and finalize without erasing evidence; malformed/partial evidence, wrong owner/version/request, competition and rollback refuse.
- Before source change, old valid snapshot after external True -> False -> True failed the policy regression by completing automatic recovery. Old APIs also failed pre-lock refusal regression. Final nine Option A tests PASS; all pre-D2 lifecycle tests preserved unchanged.
- Final focused: 259 lifecycle/assessor/transaction/frozen-install/restart tests + 276 BuildManager/readiness/Create/Install/private tests = 535 PASS. Full run: 3568 tests, 10 failure / 6 error reports (before two additional test-only checks; all final tests validated focused). Eight unchanged PID-scoped disposable process/socket tests PASS with permitted execution. Exact starting-HEAD disposable archive reproduced remaining 2 import-policy failures and 4 synthetic keychain fixture errors. Full suite is not green. Diff and staged diff checks PASS.
- Limits: offline synthetic evidence only; trusted filesystem/cooperating writers, receipt integrity versus authenticity, owner-version versus package provenance, external races and accepted P5 release-barrier exception remain. No live Kodi/Test.app/profile/device/private data, D1/D3, UI/status/startup composition, capture/restart replay, Agent Handoff, merge/push/release or history rewrite. Item 8 remains OPEN.
- Next/human input: STOP for independent Claude review of exact commit. No further implementation or live action authorized.
- Cleanup: synthetic profiles/locks/stages self-cleaned; baseline archive self-cleaned; task-owned full-suite scratch log removed; bytecode disabled. All qualification evidence and existing ambiguous-age caches preserved. Four existing dirty .agent histories retained with these new bookkeeping additions separately unstaged.

---

# ITEM 8 P5 DURABLE TERMINAL RELEASE: COMPLETE (offline; awaiting independent review)

- Product commit: `716e96235dd2737012e34d00a231849b31b52e58`; exact start `e4848c38bcf4a52e1f4015d85af28a18c5016c84`; branch `agent/codex`, authorized worktree.
- Exactly five committed files: resources/lib/capture_lifecycle.py, resources/lib/capture_recovery_assessor.py, tests/test_capture_lifecycle.py, tests/test_capture_recovery_assessor.py, docs/CREATE_CAPTURE_LIFECYCLE.md. Frozen-install/restart persistence contracts unchanged.
- Original defect reproduced before source edits: independent store/hold reader observed empty hold after terminal replacement with failing directory sync; regression failed on expected HEAD.
- Contract: strict Boolean commit_pending, missing legacy field=False; True only for matching terminal phase/outcome. Pending terminal holds across shared activation/admission paths. Under existing three locks: pending publication + successful directory barrier/readback, then same outcome released publication + final barrier. No setter between publications. Final release barrier failure reports sanitized lifecycle error while release can already be visible, as explicitly approved; no rollback.
- Explicit pending recovery verifies request/operation, audited owner/version, original enablement and competing-state checks; freshly republishes pending and barriers it before fresh release. No setter, capture or restart replay; original outcome/identity preserved. Released terminal recovery remains a record-write-free no-op. Drift refuses with hold intact. Assessor reason TERMINAL_FINALIZATION_PENDING -> advisory REVIEW_EXPLICIT_RECOVERY, with prior precedence intact; new reason awaits independent review.
- Validation: final 13-module related run 526/526 PASS. Includes lifecycle/assessor, activation guards, restart/coordinator, transaction, frozen-install/readiness, Create capture/workflow, BuildManager, private resource/overlay and Install workflow. 36 injected failure cases (3 outcomes x 2 original states x 6 boundaries); all ordinary outcomes publish pending then release. Eight real synthetic writer os._exit boundaries before/after both replacements and barriers; fresh recovery without setters. Separate-process readers verified held pending at first barrier and released terminal at second. Strict malformed/legacy, pending-retry barrier failure, drift between publications, creation-free guards and setter failure covered. git diff --check and staged diff check PASS.
- Full candidate run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`: 3561 tests, 10 failure reports / 6 error reports. All accounted for outside P5: sandbox ps restrictions (8 failure reports / 2 errors) passed unchanged in permitted PID-scoped disposable process/socket rerun (8 tests); exact expected-HEAD disposable export reproduced 2 pre-existing import-policy failures and 4 keychain synthetic fixture-initialization errors (discovery module alias leaves helper FIXTURE.good=None). No real keychain access. Full suite is not green; no unrelated fixes made.
- Limits/not done: deterministic synthetic/process-exit evidence only, not power-loss or storage/fsync qualification. No D1/D2/D3, UI/startup/background recovery, Install/Apply authority, registration, Test.app/Kodi/real profiles/private Red Light data/devices, Agent Handoff, integration/push/release/history rewrite. Item 8 remains OPEN; nothing live-proven.
- Next step/human input: STOP for independent Claude review of this exact commit, including the new diagnostic reason. No further product work without the bounded next task.
- Cleanup: TemporaryDirectory tests removed synthetic profiles/records/locks/staged files and crashed-writer scratch. Expected-HEAD export removed automatically. No task scratch logs/screenshots or code copies retained; bytecode disabled. Existing/uncertain-age ignored caches and qualification evidence retained. All four prior dirty .agent histories preserved; new bookkeeping remains separately unstaged.

---

# ITEM 8 STAGE 2A RECORD-MOVE CORRECTION: COMPLETE (offline)

- Product commit: `1f3621aab513aedc0b7ada884747bb1201709f1c`; start `a4575d8e3d355f33d3bf78aa334573d0a3bd6874`; branch `agent/codex`, authorized worktree. Exactly resources/lib/capture_lifecycle.py, tests/test_capture_lifecycle.py and docs/CREATE_CAPTURE_LIFECYCLE.md committed.
- Before source edits: both valid restart/frozen records moved out and restored during descriptor-relative reads admitted begin() to awaiting_restart and disabled the owner once. Recovery and activation/locked _checked regressions also failed on the original source (4 tests, 7 assertion failures).
- Shared competing-record helper now compares pinned-directory st_mtime_ns/st_ctime_ns immediately before/after both reads and refuses any detected change regardless of returned values. Original typed parsing, read limits and descriptor-relative no-follow reads remain. Transition fd sampled once locally; invalid/closed/non-directory descriptors fail closed. Existing lock order/lifetime untouched; single-threaded composition explicitly documented.
- macOS Darwin, temporary synthetic profiles, no sleeps: 50 restart and 50 frozen moves all detected. Restart mtime/ctime delta range 569043..1108112 ns; frozen 570802..968440 ns. After: both begin paths refuse with zero setters and retained competing records. Recovery refuses with hold unchanged/no additional setter; activation and locked _checked fail closed. Capture admission refuses before callback.
- Final affected 11-module focused suite: 467/467 PASS, including tests.test_capture_lifecycle 81/81 and existing directory swaps, unsafe records, symlinked ancestors, stable absence/presence, lock compatibility, fd cleanup, expiry recovery, reconstruction and privacy behavior. git diff --check PASS. No full suite.
- Docs: stable absence admits, detected entry changes during the bounded observation block; trusted-filesystem timestamp dependency, single-threaded composition and exact pre/post/process/session limitations stated. No cross-session tamper detection claim. Prior privacy inventory, canonical-root and recovery descriptions intact.
- Deferred/limits: D1-D3, cross-session state-tampering recovery, final-directory symlink policy and Stage 2B/native UI/startup unchanged. Evidence verifies the temporary filesystem on this Mac; no universal timestamp guarantee or detection before/after the observation window. Item 8 remains OPEN; nothing live-proven. No Test.app, normal Kodi, real profile/private values/devices, Agent Handoff, push/integration/release/history rewrite/evidence deletion.
- Next/human input: STOP for independent correction-delta re-review; verdict and bounded next task required before further product work.
- Cleanup: test and numeric-probe TemporaryDirectory fixtures removed synthetic profiles, moved records, locks and decoys. No scratch logs, screenshots, code copies or bytecode caches retained. Existing qualification evidence and four prior dirty .agent histories preserved; this bookkeeping remains separately unstaged.

---

# ITEM 8 STAGE 2A PINNED-READ CORRECTION: COMPLETE (offline)

- Product commit: `a4575d8e3d355f33d3bf78aa334573d0a3bd6874`; start `07152d32de656a16c2e9116ba6d43a42c461dd2c`; branch `agent/codex`, authorized Codex worktree. Only resources/lib/capture_lifecycle.py, tests/test_capture_lifecycle.py and docs/CREATE_CAPTURE_LIFECYCLE.md committed.
- BLOCK-1 reproduced before source edits: a valid restart record hidden by a transient canonical-directory decoy allowed begin() to reach awaiting_restart, disable the owner once, and leave restart state pending. After correction, restart and frozen swaps refuse begin() with zero setter calls; canonical records remain intact.
- All three sites (activation holds, _exclusive and _checked) read competing records through CaptureStore.competing_records_present(). Locked reads use the existing transition descriptor; observers pin their canonical directory without creating state. Existing bounded no-follow primitive, filenames, limits and original RestartTransaction/FrozenInstallTransaction.from_dict validators retained. Shared stores unchanged; no added lock acquisition/callback or lock-order change. Transition descriptor reference clears in finally before locks/descriptors close.
- Synthetic regressions cover swaps at all sites, locked descriptor identity/lifetime, invalid/unreadable/unsupported records, creation-free observation and both lock exclusion directions. Existing symlink-ancestor, expiry/recovery, restoration, metadata reconstruction and privacy tests pass. Recovery test now uses real synthetic competing records rather than mocks of the superseded pathname API.
- Validation: tests.test_capture_lifecycle 74/74 PASS in final focused run; 11-module focused run 460/460 PASS (lifecycle, transaction, frozen-install/readiness, restart/coordinator, Create capture/workflow, private resource/overlay and BuildManager activation/Install coverage); git diff --check PASS. No full-suite rerun. Initial regression fixture errors were corrected before final validation.
- BLOCK-2 docs now cover pinned competing reads, instance-only identity detection, trusted filesystem/new-instance discovery limits, persisted audited owner/version versus installed-owner verification, final-directory symlink refusal/admission impact, and private declarations not scoped to roots. Corrected metadata privacy inventory and COMPLETE-versus-registration distinction retained.
- Deferred: D1-D3 policies, cross-session tampering recovery, final-directory symlink policy decision and Stage 2B runtime/UI/startup. Item 8 remains OPEN; nothing live-proven. No Test.app, normal Kodi, real profiles/devices, Agent Handoff, integration, push, release or history rewrite.
- Next: STOP for independent correction-delta re-review. Human input: independent verdict and a bounded next task before further work.
- Cleanup: TemporaryDirectory fixtures removed synthetic profiles, records, locks, decoys and SQLite material. No task scratch logs, screenshots or bytecode caches retained. Existing qualification evidence and all prior dirty .agent history retained; task bookkeeping separately unstaged.

---

# ITEM 8 STAGE 2A B1/B2 CORRECTION: COMPLETE (offline)

- Product commit: `07152d32de656a16c2e9116ba6d43a42c461dd2c`; start `998e16f9f6f1190bba655a0c173fd4d41112c632`; branch `agent/codex`, authorized Codex worktree.
- Exactly resources/lib/capture_lifecycle.py, tests/test_capture_lifecycle.py, docs/CREATE_CAPTURE_LIFECYCLE.md committed. B1: trusted profile ancestors canonicalize consistently with restart state; final state directory/files remain no-follow. Existing canonical components bind device/inode identity; reads, OS locks and atomic capture persistence use directory descriptors. Alias/root/lock drift fails closed; swaps cannot redirect writes or authorize owner enablement. Frozen/restart locks retain their exact shared filenames/flock semantics. No-record guards/admission work under symlinked profiles; held Create still blocks activation/Install/reconciliation.
- B2: document every persisted request metadata category, including free-text build_name/description, labels/profile IDs, public destinations, private setting declaration identities, trusted resource IDs and private overlay ID. Captured values/results/credentials and overlay contents are excluded; free text can contain secrets. Reconstruction remains creation-free and lock-free; recovery-purpose reconstruction after expiry grants no transition authority. COMPLETE is not registration.
- Before source correction: 2/2 new B1 tests errored on the requested HEAD (no-record guard and coordinator reconstruction). After: both pass; symlinked begin persists hold and disables exactly once, competing admissions remain blocked. Final 13-module focused run: 890/890 PASS, including 67 lifecycle tests and existing expiry/recovery/privacy coverage. git diff --check PASS. No full-suite rerun for this scoped delta. Earlier exploratory test invocations had test-harness field/module-name errors, corrected before the final run.
- Existing Stage 1 recovery semantics and Stage 2A metadata/hold atomicity retained. No D1-D3/N1-N6 work, Stage 2B composition, Test.app/Kodi/profile/device access, Agent Handoff, integration, push, release, or history rewrite. Nothing live-proven; item 8 remains open.
- Next: STOP for independent B1/B2 correction-delta re-review. Human input: review verdict/new bounded prompt before any further product work.
- Cleanup: disposable profiles, state, locks, staged collision/swap fixtures and SQLite resources removed by TemporaryDirectory fixtures. No task scratch logs/screenshots or bytecode caches retained. Existing qualification evidence and the four pre-existing dirty .agent histories remain; this bookkeeping stays separately unstaged.

---

# ITEM 8 STAGE 1 B1/B2 CORRECTION: COMPLETE (offline)

Product commit: `7e221ff6c677d1478fc5b9cb2a5650a7b8f5b342`; starting candidate `b908b687f306566403f2cf6b1da88a90e1243d3e`.
Worktree/branch: script.build.manager-codex / agent/codex.

- Changed only resources/lib/capture_lifecycle.py, tests/test_capture_lifecycle.py, docs/CREATE_CAPTURE_LIFECYCLE.md.
- Explicit recovery permits ordinary expiry and verified original-enabled no-op restoration. Preparation/retry and capture remain expiry-bound; rollback, exact request/operation, owner/version, competing-operation and durable-hold checks remain enforced. Recovery grants no restart/capture authority. Capture rejects unexpected enablement, including the post-callback/pre-restoration race; original-disabled unexpected enablement remains blocked.
- Before source correction: 45 lifecycle tests ran; 42 passed, 3 errors reproduced B1 expired awaiting/recovery, B1 expired interrupted restoring, B2 already-restored recovery. After: 45/45 PASS. Established 13-module Stage 1 focused set: 662/662 PASS. git diff --check PASS. No full-suite rerun required for this delta.
- No private results/values are persisted or exposed in sanitized errors. No runtime/UI/startup composition, Test.app, normal Kodi, real profiles/devices, Agent Handoff, push, matrix integration or release. D-028, quiet-WAL and Install/Apply/activation product sources unchanged.
- D1-D4 policy concerns remain unresolved and outside this correction; their detailed reviewer text was not supplied in this task or found in repository guidance. No policy resolution inferred. N1-N7 and H1-H7 remain outside scope; Stage 2 implications require separate review/authorization.

Cleanup: disposable synthetic profiles/databases/locks were removed by test fixtures. No task scratch files, screenshots or caches created; existing qualification evidence retained. Four pre-existing dirty .agent histories preserved, with this bookkeeping separately unstaged and excluded from product commit.

Next: STOP for independent correction-delta re-review. No Stage 2 work authorized. Human input: independent review verdict before further work.

# ITEM 8 CREATE CAPTURE STAGE 1: COMPLETE (offline)

Product commit: `b908b687f306566403f2cf6b1da88a90e1243d3e`
Branch/worktree: `agent/codex` — `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`
Starting HEAD: `d07a95736524ecb74e90017dcf652fa4573a9268`

## Done

- Added a Create-only durable coordinator/record with exact full-request digest, audited Red Light owner/version, original enablement, operation/session IDs, expiry, explicit restart waiting and owned restoration. Phases: preparing, awaiting_restart, capturing, restoring, complete, cancelled, failed.
- Shared activation readers enforce Create holds; Install admission, frozen/restart record creation, restart reconciliation and direct Apply reject active capture. Existing OS transaction locks and atomic persistence are reused. No Install/Apply capability is issued to Create.
- Interruption before/after every phase save and disable/enable effects retains safe authority. Exact same-session preparation retry is idempotent; recovery never replays a capture, preserves original enablement and retains the hold on ambiguity. Different session plus mandatory explicit complete-restart proof is required; a new UUID alone is insufficient.
- Ten committed files: resources/lib/capture_lifecycle.py, activation.py, build_manager.py, frozen_install.py, restart_coordinator.py, transaction.py; tests/test_capture_lifecycle.py, test_create_workflow.py, test_frozen_registry_readiness.py; docs/CREATE_CAPTURE_LIFECYCLE.md. Native Create/workflow product source, D-028 authority/PIL, quiet-WAL reader, and publication/identity source were not changed.
- Final focused 13-module run: 657/657 PASS (40 new lifecycle tests plus existing Create/private/activation/Install/transaction/restart coverage). Real adapter read used only a disposable existing WAL database; initialize/Apply were forbidden and database/sidecar bytes were unchanged. Preview/back and declined confirmation created no new files or lifecycle preparation.
- Final committed-source full suite: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -q`: 3488 run, 3486 passed, 2 failures, 0 errors. Both failures independently reproduce at original HEAD: tests.test_plan.ImportPolicy.test_the_presentation_modules_import_no_engine; tests.test_ui_foundation.NativeFoundationTests.test_no_engine_imports. Six changed product modules parse; git diff --check PASS.
- The first exploratory discovery run hit sandbox fake-process listing restrictions, helper-module double-loading from omitted top-level discovery, and a registry test double without a root. Proper discovery with offline host execution and a disposable root restored all affected coverage; the final candidate has no additional failure.

## Not done / remaining limits

No native Create, service-startup or real runtime activation; runtime private capture still fails closed. Operations and complete-restart proof remain mandatory injected synthetic capabilities, with no permissive runtime defaults. The runtime competing-operation provider, complete-process boundary verifier, narrow held-owner restoration capability, confirmed UI request reconstruction, original desired enablement in captured output, registration outcomes, and stale/corrupt recovery policy remain future Stage 2 work. No force release or blind recovery exists. COMPLETE describes lifecycle completion, not build registration or beta acceptance.

No Test.app operation/staging, real profile/private-overlay access, household device, Agent Handoff, matrix integration, push, release, history rewrite or ai-supervisor work occurred. Item 8 remains OPEN and nothing was live-proven.

## Next / required input

STOP for ChatGPT review of this offline product commit. Stage 2 requires a separate bounded prompt after that review. No human input is required to close Stage 1. The four pre-existing dirty .agent files and their history are preserved; task bookkeeping remains separately unstaged to avoid committing unrelated prior changes.

## Cleanup

Removed the three task-owned scratch suite logs. Disposable test profiles and the exact-HEAD baseline code copy self-cleaned. No screenshots or new qualification evidence remain; tests used PYTHONDONTWRITEBYTECODE and parse checks wrote no bytecode. Existing qualification evidence, artifacts and prior tracking history remain intentionally preserved.

---

# Item 8 Fixture E readiness preflight — BLOCKED (read-only)

Worktree: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex`
Branch: `agent/codex`
Expected HEAD: `d07a95736524ecb74e90017dcf652fa4573a9268`
Accepted product: `6147562f08d86f141772ee0156408b1cd02bb85d`

## Done

- Git identity reconciled; accepted product is an ancestor and product source is unchanged. Existing dirty `.agent` content was retained below this section.
- Claude preflight JSON evidence checksums passed 8/8; D-028 runtime evidence checksums passed 142/142.
- Current production `capture_frozen_build` re-evaluation over retained inventory, current trusted add-on XML, and the existing read-only ArtifactStore produced a complete 9-node public closure. Seven exact managed artifacts match the retained graph. `script.module.pil` 5.1.0 is `platform_provided`, has the required `xbmc.python >= 3.0.0` edge, and has no ZIP artifact. No fallback or ArtifactStore write occurred. Its current trusted XML digest matches the retained D-028 runtime record.
- Test.app observe-only MCP reported stopped. Production `RedLightSettingsAdapter._has_settings_rows()` passed against the current portable profile database: it is populated, quiet WAL with no sidecars, and database/sidecar metadata plus directory listing remained unchanged. No private values were emitted.
- Focused `QuietWalReadCompatibilityTests`: 10/10 PASS. Full suite not rerun.

## Not done

The full preflight is not READY: `private-compatibility-gate.json` in the retained Claude evidence is `NOT_RUN`, and this task did not run Create Build's private capture/validation or register E. No Test.app launch/navigation/staging, Install, Apply, restart, private-overlay access/mutation, product edit, commit, push, integration/release, or normal Kodi/device access occurred. The retained D-028 live runtime evidence is historical; no fresh Kodi JSON-RPC verification is claimed.

## Next

A separately scoped portable Test.app Create Build preview for fixture E through the private compatibility gate, stopping before confirmation/registration. If the gate passes, use a separate bounded task for registration and restart/resume qualification. Human input required: a new prompt granting those exact Test.app actions.

## Cleanup

Removed 14 task-created `.pyc` files. Test and production temporary directories self-cleaned. No evidence files were created; database/sidecars, ArtifactStore and existing qualification evidence remain intentionally retained.

---

# WF-testapp-mcp-install — complete (offline)

Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex
Branch: agent/codex
Documentation commit: 72233d1c22f69027914179c2ba5e817b3a982679
Source repository commit: 2861935330963019f2a1d290665fb472507fd215

## Done

- Installed the read-only `dist/bundle` runtime at `/Users/eengert/.codex/mcp/build_manager_testapp`; the 4,219-entry tree matches the source bundle and its native helper digest matches `native/helper.sha256`. Both installation directories are mode 0700.
- Registered `build_manager_testapp` in `/Users/eengert/.codex/config.toml` with `/usr/local/opt/node@24/bin/node` and the installed `src/server.js`. `codex mcp list` recognizes it as enabled, and all pre-existing listed servers remain present.
- The installed server passed offline MCP initialization and tool listing with exactly `test_app_observe`, `test_app_navigate`, `test_app_launch`, and `test_app_quit`. An invalid navigation enum was refused before any runtime operation.
- Updated `AGENTS.md` to make these MCP tools the default Codex Test.app interaction mechanism and corrected the admission count to eight items. Only `AGENTS.md` was committed.

## Not done

No Test.app operation was called: no observe, launch, navigate, or quit. No normal Kodi/profile/device, Claude installation, MCP source, or Build Manager product code was touched. No Screen Recording permission check was made.

## Next

Start a new Codex session to load the registered tools; existing sessions do not refresh tool discovery. A full app restart was not performed. For any live use, follow a separately scoped task. Screen Recording permission may be required for Codex or the MCP host when a tool captures a window; the runtime reports `screen_recording_permission_required` if unavailable. Item 8 qualification remains open.

## Cleanup

No temporary files were created. The private runtime installation, Codex configuration entry, and prior qualification evidence are intentionally retained.

---

# D-028 accepted-correction runtime admission — PASS

Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex
Branch: agent/codex
Starting HEAD: fd46770690d1fccfbd8268b9259f06166e65dc43
Accepted product candidate: 6147562f08d86f141772ee0156408b1cd02bb85d
Candidate Git tree: b4c3850681ae213ea1b83c09c8158b2fc6df5d49

## Done

- Reconciled a clean starting checkout and confirmed the accepted candidate is an ancestor of HEAD.
- Confirmed Test.app was stopped, transaction states were absent, and the pre-stage profile census matched the preserved D-028 final snapshot.
- Used bm_test_app.py dry-run and transactional stage for the exact candidate. The prior adapter configuration fingerprint matched. The previous staged product and driver trees were preserved and verified against the previous manifest.
- Completed Git-bound candidate verification after staging and after the runtime probe.
- Launched only Kodi Build Manager Test.app in portable mode. Verified PID 54316 and the foreground procedure.
- Reused the saved read-only probe. Production verify_platform_requirements admitted script.module.pil 5.1.0 with the required xbmc.python >=3.0.0 edge. Live inventory/system metadata reported 3.0.0. The verifier returned {"script.module.pil":"5.1.0"}. The isolated capture made no artifact and the store had zero ZIPs.
- Gracefully quit Kodi. The helper's HTTP transport failed closed; the saved raw JSON-RPC script verified port 9090 belonged only to PID 54316 and its allowlisted Application.Quit returned OK. The final helper identity reports Test.app stopped.
- Compared final and pre-stage snapshots: installed add-ons, settings, adapter result, build library, private-data projection, and transaction state match. No build was applied and both transaction states remain absent.

## Not done

No full suite was rerun. No fixture E, Install/Repair, Apply, restart/resume qualification, normal Kodi/profile, household device, Agent Handoff, matrix integration, repository publication, push, or release action occurred. The broader beta qualification remains open. No product source changed.

## Evidence and cleanup

Full sanitized evidence and checksums: .qualification-evidence/d028-runtime-6147562-20261010T123358Z/

Removed the temporary adapter input and the 30 Python bytecode files created by the probe; verified the cache directory is gone. Probe scratch cleaned itself and no matching scratch remained. No screenshots were made. Prior staged-tree backups and reproducible probe scripts remain as qualification evidence.

## Next

Stop after this scenario. No further Test.app workflow is authorized by this task. A separate bounded qualification task is needed for any next scenario; no human input is needed to close this one.

---

# D-028 runtime admission evidence reconciliation — PASS (existing exact run)

## Done

- Reconciled the re-request against the preserved exact-candidate runtime run at `.qualification-evidence/d028-runtime-6147562-20261010T123358Z/`; all 142 entries in `SHA256SUMS.txt` verify.
- Confirmed Test.app is currently stopped with the supported read-only observe operation.
- The preserved run started from the requested clean HEAD `fd46770690d1fccfbd8268b9259f06166e65dc43`, staged exact product candidate `6147562f08d86f141772ee0156408b1cd02bb85d`, and passed production `verify_platform_requirements` for live `script.module.pil` 5.1.0 requiring `xbmc.python >= 3.0.0`.

## Not done

No second stage, launch, runtime probe, or profile snapshot was performed. The exact requested scenario is already complete in preserved evidence; this checkout has since advanced to `d07a95736524ecb74e90017dcf652fa4573a9268` and has four pre-existing `.agent` modifications, so it no longer satisfies the requested clean starting state. The accepted product candidate remains an ancestor; the only committed path difference from it is `AGENTS.md`. No new runtime or profile state was changed.

## Evidence and cleanup

The existing report, runtime identity/API/XML evidence, state comparisons, and cleanup record remain in `.qualification-evidence/d028-runtime-6147562-20261010T123358Z/`. No temporary material was created or removed in this reconciliation. The prior staged-tree backups remain intentionally retained.

## Next

Stop after the one accepted runtime scenario. Item 8 and broader beta qualification remain open. No human input is needed for this evidence reconciliation; a separate task and matching clean baseline are required for any independent rerun.


## Item 8 Create capture Stage 2A — COMPLETE offline

- Product commit: ca83f20a00b9ae1ff91bd9ca239ac4745a8c5181; capture_lifecycle.py and test_capture_lifecycle.py only.
- Confirmed typed request declarations persist in the same atomic transaction as the hold; catalog resource IDs reconstruct trusted declarations. Exact operation/fingerprint/owner/version validation; bounded no-follow reads and typed validation. Request/hold durable before disable; interrupted publication never permits disable.
- Read-only reconstruction calls no lifecycle capability, takes no locks, and writes nothing. Separate Python-process reconstruction proven. COMPLETE records no registration or recoverable capture result. Metadata shares transaction ownership: no independent orphan cleanup; retained active/legacy/corrupt evidence is not deleted.
- Validation: 51 lifecycle tests and 434 combined capture/Create workflow/frozen install/dependency tests PASS; git diff --check PASS. Initial related-suite failures exposed fixed macOS alias handling, corrected and rerun. No full suite required.
- D1-D3 remain unresolved with existing fail-closed gates unchanged; detailed prior concern text is not present in the supplied task/current guidance. No live Kodi/Test.app/profile/device, UI/startup, Install/Apply, restart, push, integration or release.
- Next: independent offline Stage 2A review; STOP before Stage 2B. No human input required to close this implementation.
- Cleanup: removed only eight task-generated Python bytecode files; test temporary profiles and staged-write scratch self-cleaned. Pre-existing caches, qualification evidence, and dirty .agent history intentionally retained. Bookkeeping remains unstaged separately from product commit.


## Item 8 Stage 2A expiry correction — COMPLETE offline

- Product commit 998e16f9f6f1190bba655a0c173fd4d41112c632: resources/lib/capture_lifecycle.py and tests/test_capture_lifecycle.py only.
- Before at ca83f20: synthetic begin disabled/held owner; clock advanced beyond expiry; fresh reconstruction BLOCKED while recovery with original in-memory request CANCELLED, restored enablement and released hold.
- Added explicitly named store/coordinator reconstruct_request_for_recovery APIs. Only recovery reconstruction relaxes expiry; clock rollback and non-finite time remain refused. Reconstruction is read-only; actual recover still validates owner/version, competing transactions and restoration authority under existing locks. Normal reconstruction/preparation/retry/capture remain expiry-bound.
- Tests: 56 lifecycle PASS; 383 related Create capture/workflow, frozen install and dependencies PASS; final combined 439 PASS; git diff --check PASS. Separate-process expired reconstruction and fresh-coordinator cancellation; interrupted RESTORING, disabled owner, unsafe records, identity, rollback and competing authority covered. COMPLETE leaves synthetic Build Library empty and stores no private result. No full suite.
- D1-D3, Stage 2B, UI/startup, D-028, quiet-WAL, Install/Apply unchanged. No Test.app/Kodi/profile/device/Agent Handoff/integration/push/release.
- Cleanup: synthetic profiles and child-process fixtures self-cleaned; bytecode disabled. No scratch artifacts retained or prior evidence removed. Four pre-existing dirty .agent records preserved with separate unstaged bookkeeping.
- Next: STOP for independent review of this correction. No human input required to close implementation.


## Item 8 D2 confirmed recovery — BLOCKED (offline)

- Exact worktree/branch and expected HEAD e4848c38bcf4a52e1f4015d85af28a18c5016c84 verified. Four pre-existing dirty .agent files preserved. No product commit; all task-owned candidate edits to capture_lifecycle.py and test_capture_lifecycle.py removed by restoring their exact HEAD bytes. docs unchanged.
- Attempted a dedicated confirmation API binding the full validated record/request snapshot, exact UUID/owner/version, original False, observed True, target False and cancellation. Under existing capture -> frozen -> restart locks it published operation-bound D2 consent/restoration intent before setter. Candidate checks covered decline, stale evidence, six crash boundaries, retry without redundant setter, invalid intent, identity/competition/path drift and strict legacy compatibility. This is discarded experimental evidence, not delivered product behavior or acceptance.
- STOP blocker: CaptureStore.save() replaces the transaction with terminal CANCELLED before directory fsync. If _sync_directory raises after replacement, recovery reports CAPTURE_LIFECYCLE_BLOCKED, but a fresh read sees held=False; capture_activation_holds() is empty and require_no_capture() admits. Thus terminal durability is not established before protection becomes observably released. D2 specifically requires a persistence error to retain protection. The current one-record phase/hold contract cannot distinguish an unsynced published terminal record from a committed terminal record. Blind rollback would contradict accepted retain-published-evidence semantics and would not remove the release window. A separate durability/release protocol would need explicit design/review rather than silently changing accepted lifecycle guarantees.
- Candidate focused suite: 127 run, 126 passed, 1 failure: D2 terminal directory-sync failure must retain protection. Standalone failing regression: asserted store.read().held after injected terminal sync failure; observed False.
- Independently reproduced on unchanged expected HEAD using synthetic originally-disabled begin(), then ordinary recover() with _sync_directory patched to raise only when store.read().phase is CANCELLED: recovery_error=CAPTURE_LIFECYCLE_BLOCKED; phase=cancelled; held=False; enabled=False; activation_holds=0; require_no_capture=admits; setter_calls=0; locks_released=True. This establishes a pre-existing persistence limitation, not a new D2 defect. No sensitive exception payload was emitted.
- Final unchanged-source validation: 118/118 lifecycle + recovery assessor + update guard tests PASS; git diff --check PASS. No broader suite; no source change remains. Baseline acceptance tests do not cover the stricter D2 terminal-fsync condition.
- Not done: D2 implementation, product commit, native UI/startup/runtime, frozen-install/restart-store contract changes, live Kodi/Test.app/profiles/Red Light user data/devices, Agent Handoff, push/merge/release/history rewrite. Item 8 remains open.
- Smallest next step: independent Claude review of the terminal-publication/fsync blocker and a reviewed durable hold-release design before resuming D2. Human input: a separately bounded task authorizing any necessary persistence-contract correction; no automatic continuation.
- Usage: reliable Codex app account-wide start 5h 90% / weekly 98% remaining; end 5h 88% / weekly 98%; rounded delta 2 / 0 percentage points, not attributable solely to this task. Session identifies GPT-6; exact model tier and effort unavailable.
- Cleanup: discarded all task-owned product/test edits; TemporaryDirectory profiles self-cleaned; bytecode disabled. No scratch files/screenshots or new qualification evidence remain. Existing qualification evidence, pre-existing caches and four dirty bookkeeping histories remain; only appended task records are retained.


## Item 8 D2 confirmed recovery — COMPLETE offline; review pending

- Baseline 716e96235dd2737012e34d00a231849b31b52e58; agent/codex in the authorized Codex worktree. Local product commit 2d446946aa23550e62d78014cf126d8350f6d8a8; exactly resources/lib/capture_lifecycle.py, tests/test_capture_lifecycle.py, docs/CREATE_CAPTURE_LIFECYCLE.md. Four pre-existing dirty bookkeeping files/history preserved separately unstaged.
- Dedicated prepare_d2_confirmation/recover_d2 APIs bind explicit True consent to the whole validated durable record/request, operation UUID, audited owner/version, original False, observed True, target False and CANCELLED. Decline/missing consent is creation-free. Full evidence is revalidated under capture -> frozen -> restart locks. Durable RESTORING/cancelled receipt (consent UUID, full source-record digest, operation/action binding digest) must finish publication/barriers/readback before one setter attempt. Strict three-field validation; all-absent legacy D2 fields remain readable. No original-state edits.
- Before confirmation: originally-disabled nonterminal record plus unexpectedly enabled owner remains held; ordinary recover refuses. After explicit confirmation: durable consent -> exactly audited owner disabled once -> state/owner verification -> P5 CANCELLED pending/held first barrier -> released second publication/barrier. Only CANCELLED is permitted. No source changes to ordinary recover/_restore or P5; pending-terminal finalization still has no setter authority.
- Interruption/replay: intent write, flush, file fsync, replace and directory barrier failures never call setter; fresh confirmation/republication/barrier required for an enabled retry. Nine crash boundaries cover before/after intent, before/after setter, after verification and before/after both P5 publications. Both P5 stages have write/flush/file-sync/replace/directory-barrier failures covered. Already-disabled recovery verifies/finalizes without redundant setter. If enabled after an uncertain attempt, persisted intent cannot distinguish no original effect from newer external re-enable: generic recover and stale confirmation refuse; a renewed reviewed snapshot/explicit agreement authorizes one new attempt. No action-completion evidence is synthesized.
- Validation: 378/378 focused tests PASS (109 lifecycle including 17 D2, 21 assessor, 17 update guard, 38 transaction, 71 frozen install, 15 restart coordinator, 100 Create workflow, 7 frozen registry/readiness). D2 17/17 additionally rerun after adding flush-failure cases. git diff --check and staged diff check PASS. No full suite; no candidate regression. An exploratory fixture-name error was corrected before final green validation.
- Guards/limits: exact Booleans, changed owner/version, stale source/request/UUID, malformed/legacy-unverifiable records, terminal/pending-terminal and originally-enabled records refuse; competing durable/active operations, root/lock drift and descriptor closure covered. D2 pending-terminal Install/restart/activation guards remain protected; assessor classifications unchanged. P5 approved post-commit release/barrier-error exception preserved. Binding checksums do not authenticate arbitrary disk edits; version strings do not prove package bytes or eliminate all external observation-to-setter races. Trusted injected operations and trusted durable evidence remain prerequisites. D1/D3 authority deferred.
- No live Kodi/Test.app/real profiles/private Red Light data/devices, UI/startup/background recovery, Install/Apply/registration, frozen/restart-store contract edits, Agent Handoff, push/merge/release/history rewrite. Offline evidence only; Item 8 remains open.
- Next: STOP for independent Claude review of this focused commit. No human decision needed to close implementation; further work requires its own bounded task.
- Cleanup: TemporaryDirectory profiles and staged-write scratch self-cleaned; bytecode disabled; no task scratch files/screenshots or new qualification evidence remain. Existing qualification evidence, prior caches and all four dirty bookkeeping histories intentionally remain. Shared Git metadata permission was used only to stage/commit the three authorized files.


## Item 8 unattended staged bundle — COMPLETE; independent acceptance pending

Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex; branch agent/codex.
Accepted P5 baseline: 716e96235dd2737012e34d00a231849b31b52e58.
D2 implementation: 2d446946aa23550e62d78014cf126d8350f6d8a8 (already COMPLETE before bundle).
D2 correction candidate: 98509f8a52a936e0cf5434d6cf07dcd2d7a299ba. STOP for ChatGPT assessment and independent Claude review; this is implementation-lane self-validation only.

### Stage 2 — adversarial evidence and focused correction

- Demonstrated missing confirmation namespace binding: copied the exact valid transaction/request into another synthetic profile; the original confirmation disabled the second profile's owner and cancelled it. A new coordinator over a replacement directory at the same canonical pathname also accepted the original confirmation with the copied record. Two focused regression tests failed before the correction (no expected refusal).
- Separate correction commit 98509f8a52a936e0cf5434d6cf07dcd2d7a299ba: confirmation now carries an opaque SHA-256 binding to the canonical capture-state root and its locked/pinned device+inode identity. It is checked before intent publication, after successful publication/barrier, and immediately before setter. The source digest binds the reviewed transaction together with that root binding. Paths and raw filesystem identity are not persisted or printed in confirmation repr/diagnostics. Two root-domain regressions now refuse without lifecycle writes/setter; trusted aliases of the same canonical directory remain supported, and malformed/mismatched binding tests fail closed.
- Exactly three product files changed/committed: resources/lib/capture_lifecycle.py, tests/test_capture_lifecycle.py, docs/CREATE_CAPTURE_LIFECYCLE.md. Correction adds 98 lines/removes 8; no amend/history rewrite. Existing P5, record schema fields, generic recover/_restore, frozen-install/restart-store contracts and assessor implementation remain unchanged. Previously persisted D2 receipts remain readable; only new explicit confirmations require the root binding.
- Final targeted suite: 382/382 PASS (113 lifecycle, including 21 D2; 21 assessor; 17 update guard; 38 transaction; 71 frozen install; 15 restart coordinator; 100 Create workflow; 7 frozen registry/readiness). Four additional synthetic nonterminal-phase checks passed for PREPARING, AWAITING_RESTART, CAPTURING, and RESTORING/failed, each cancelling without capture/restart replay and with one audited-owner disable. git diff --check and staged diff check PASS. No full-suite rerun or candidate regression.
- Existing D2 matrices remain green: intent write/flush/file sync/replace/directory barrier errors perform no premature setter; enabled uncertain retries require fresh explicit consent and fresh publication/barrier; disabled retries skip setter; both P5 publication/barrier paths and approved post-commit error exception; exact Boolean state, stale request/operation/record, owner drift, competing records/operations, pending-terminal guards, expiry/fresh-coordinator reconstruction, lock ordering and descriptor cleanup. No independent review was dispatched or declared complete.

### Stage 3 — D1 source/design preparation only

- Exact checks: CaptureTransaction.__post_init__ admits only audited Red Light owner/version; CaptureLifecycleCoordinator._checked checks current owner version, exact request/UUID, clock, competing operations/records and root; _disable/_eligible/_restore/_terminal_checked/_release_terminal preserve the phase/hold/state protections. D2 also checks the confirmation's root domain. assess_capture_recovery prioritizes OWNER_IDENTITY_UNVERIFIED ahead of enablement actions. No owner/version field is rewritten to match drift.
- Available source capabilities: KodiInventoryBackend.read_installed_metadata reads addon.xml only below established trusted roots and proves HOME/APPLICATION origin; ArtifactStore.validate_addon_artifact/read_bytes/find establishes exact retained ZIP identity/size/ID/version. VerifiedInstalledAddonSource ties a canonical source path to a frozen resolution identity and revalidates metadata/import roots; its documentation explicitly says the archive digest is NOT an installed-directory hash. PrivateResourceOwnerContext adds held/disabled and frozen-record relationships, not current byte equality.
- Missing authority: no Create-operation-bound installed-tree attestation, immutable installation generation, or trustworthy external enablement/action epoch is provided by the capture operations interface. Repository origin, matching addon.xml/version, saved archive digest, or copied frozen identity cannot establish current package bytes or prove no later replacement. No existing D1 changed-owner setter authority exists.
- Proposed READ-ONLY interface (not implemented): inspect_recovery_owner(record, trusted_inventory, retained_artifact) -> OwnerRecoveryEvidence with expected/observed ID+version, root-bound metadata evidence, separately verified archive identity, installed-tree equality/action-generation status or UNKNOWN, and sanitized reason codes. assess_owner_recovery(evidence) -> retain-hold/operator-review/same-owner-recheck advice, never a setter capability.
- Transition rules: changed/missing/unknown owner -> retain existing hold and evidence; no automatic mutation and no terminal reactivation. Any manual package remediation needs a separate explicit policy/task and fresh trusted evidence; only return to ordinary/D2 recovery when original audited identity and current state are freshly verified. Do not replace original owner/version to normalize drift.
- Implementable follow-up: synthetic read-only evidence collector/classifier and exact refusal tests. Policy/evidence blockers: any changed-version mutation, installed-tree attestation semantics (including mutable/generated package files), replacement/action epoch fencing, and operator remediation authority need separate design/authorization and independent review.
- Required future tests: same-version altered installed files, wrong/unavailable archive, shadowed/untrusted roots, version/owner drift at every boundary, stale generation, unavailable evidence, secret-safe diagnostics, and zero setters/hold release on any unproven owner. Source investigation only; no actual package/profile/device inspected.

### Stage 3 — D3 source/design preparation only

- The capture transaction is the sole durable authority for original_enabled, full request, operation/session UUIDs, timestamps, phase/outcome and hold/commitment. request_metadata, request_fingerprint and D2 digests share that file; they are not independent recovery witnesses. CaptureStore CAS and directory/device/inode checks protect a live instance but do not authenticate cross-session arbitrary file replacement. The documented missing-record/new-instance limitation remains deferred, not silently repaired here.
- Candidate independent stores do not contain the necessary Create history: ArtifactStore proves retained software archives; BuildLibrary contains registered bundles and Install applied-publication state; frozen/restart records describe competing other operations and cannot be adopted as Create evidence. Current enabled state, current version, process-session property, private database contents, application logs or agent notes cannot establish the lost original state or explicit consent. Temporary save files are not independently authenticated authority and must not be promoted on filename/hash guesses.
- Irreversible uncertainty: if original enablement, exact request, operation/root identity, source ownership or durable consent/commitment is lost and no independent trusted witness exists, recovery cannot choose a restoration target or reconstruct authority. Current state does not distinguish legitimate histories requiring different outcomes. Preserve evidence and fail-closed guards; do not read private data to guess intent or design force-release/administrative retirement.
- Proposed READ-ONLY interfaces (not implemented): inspect_capture_evidence(root, independently_trusted_sources) -> CaptureEvidenceAssessment (custody/root/operation binding, complete typed candidate or missing-field/conflict reasons); validate_reconstruction_proposal(assessment) -> recovery-review advice with no mutation authority. Independent witness must predate corruption, retain all authority-critical fields, be operation+profile-bound, and have independently trustworthy custody/ordering. A checksum inside the corrupt file or unauthenticated copy is insufficient.
- Transition rules: no adequate witness/conflicting witnesses -> retained unresolved evidence and no setter/release/replay. Complete trustworthy witness -> proposed reconstruction for a separately authorized and independently reviewed persistence transition, followed by ordinary locked owner/request/state checks; witness alone never starts capture or overrides P5. No reconstruction or administrative retirement was implemented.
- Implementable follow-up: read-only witness inventory/validator with synthetic evidence. Blockers: no such complete independent witness currently exists in the Create contract; custody/authenticity, phase/commitment ordering and safe reconstruction publication must be designed and reviewed separately without weakening existing stores.
- Required tests: lost original True versus False, partial/conflicting/stale witnesses, different UUID/profile/owner, copied records, hash-only/self-authenticating evidence, unsupported schema, corrupted commitment, terminal non-reactivation, competing authority, and no mutation/release when evidence remains unknown.

### Stage 4 — native/startup integration inventory (read-only)

| Purpose | Exact current source entrypoint | Future bounded integration |
|---|---|---|
| Native routing | default.py:main -> NativeDialogs.run -> NativeDialogs.create (resources/lib/ui/native_dialogs.py) | Keep lazy route/provider composition; show recovery review before permitting unrelated Create work. Never auto-confirm or replay stale dialog state. |
| Create confirmation/capture/registration | NativeDialogs.create yesno -> CreateBuildWorkflow.execute; runtime_create_workflow in resources/lib/create_workflow.py | Current execute calls capture engine then registration directly. A later explicit lifecycle composition must persist confirmed request/hold, await manual restart, prove restart, read capture once and preserve original desired enablement in exported output. Lifecycle COMPLETE does not prove registration. |
| Advisory recovery/confirmation | assess_capture_recovery; reconstruct_request_for_recovery; prepare_d2_confirmation/recover_d2/recover | Add a read-only presenter first; show original/current/target state and cancellation clearly. D1/D3 remain blocked advice. D2 agreement uses the exact fresh root-bound snapshot; decline writes nothing; stale state requires a new dialog. Pending terminal offers verification/finalization only, no new setter. |
| Build Status / Needs Attention | default.py:status_provider -> check_build_status; StatusOwners and BuildStatusService._operation (resources/lib/status.py); NativeDialogs.check_status/status and StatusViewModel | Status currently reads restart/frozen/publication snapshots but has no capture observer. Add an injected read-only Create observer and typed sanitized operation presentation, including pending-terminal protection and truthful unverified/invalid states, while keeping UI free of mutation adapters. |
| Startup/manual restart/resume | service.py:main -> run_startup (resources/lib/startup.py), then run_frozen_install_startup; resources/lib/session.py process-window session identity | Future preflight observes Create before unrelated automatic resume paths and reports Needs Attention. Never hand Create records to RestartTransaction/ResumeCoordinator or recover/capture automatically. Existing session UUID is necessary but not independent complete-process restart proof. |
| Resource and activation authority | RedLightSettingsAdapter._capture_snapshot requires lifecycle validation; runtime_create_workflow currently constructs default active adapter; activation/frozen/restart admission guards already enforce capture holds | A separately reviewed runtime capability must target only the audited held owner, positively exclude active operations, validate exact state/identity, supply complete restart proof and bind private read verification. Do not loosen shared activation, initialize/write private data, or provide permissive default verification. |

- Existing coverage to preserve: test_capture_lifecycle, test_capture_recovery_assessor, test_create_workflow (100 native/engine/library tests), test_ui_foundation, test_status/test_status_ui, test_transaction startup/service tests, test_restart_coordinator, and test_frozen_registry_readiness. Current tests explicitly preserve absent lifecycle/startup composition; future authorized integration must replace those assertions with meaningful gates rather than quietly bypass them.
- Missing coverage for future work: capture-aware status with no selected/applied build; remote Back/decline/refresh/stale/root-bound recovery dialogs; P5 pending versus released result presentation; D1/D3 disabled actions; same-session/new-session without restart proof; capture record never dispatched to Install/Apply; real narrow runtime restoration and active-operation observation; expired request reconstruction; original desired enablement export; crash before registration without false saved-build success. No UI/startup source changed or executed.
- Smallest safe sequence: (1) independently review the complete D2 range from accepted P5 through 98509f8a52a936e0cf5434d6cf07dcd2d7a299ba; (2) separately authorize and review a read-only Create recovery presenter/status/startup admission adapter, with D1/D3 blocking states and no automatic recovery; (3) separately authorize synthetic native explicit cancellation/finalization integration backed by the narrow trusted runtime capability contract; (4) independently establish complete-process restart proof before full confirmed Create/restart/capture/registration composition; (5) only then request exact-candidate portable Test.app qualification with named actions. No stage in this bundle authorizes those implementations or live work.

### End state / cleanup / next review

- Product tree clean at 98509f8a52a936e0cf5434d6cf07dcd2d7a299ba; only the four pre-existing .agent files are dirty with additive preserved history. No D1/D3/UI/startup implementation, live Kodi/Test.app/real profiles/Red Light values/devices, Agent Handoff/ai-supervisor, push/merge/release/history rewrite occurred.
- No unresolved D2 integration blocker was found after the correction. Remaining limitations: trusted injected operations/profile evidence; no general package-byte provenance or external-action epoch proof; persisted intent never permits enabled-state setter replay; P5 approved post-commit release/barrier exception. D1/D3 evidence/policy gaps remain future blockers, not new mutation authority.
- Cleanup: task TemporaryDirectory profiles, retained fake roots and CAS scratch self-cleaned; bytecode disabled; no scratch source copies, logs, screenshots or recordings retained. Four dirty bookkeeping histories and all prior qualification/review evidence remain. The retained regression tests and this handoff carry reproducible failure evidence without private values.
- Precise next independent Claude review: accepted baseline 716e96235dd2737012e34d00a231849b31b52e58 -> implementation 2d446946aa23550e62d78014cf126d8350f6d8a8 -> correction 98509f8a52a936e0cf5434d6cf07dcd2d7a299ba; exactly the three D2 files. Reproduce consent/replay/durability/P5/guard matrices plus cross-profile/replaced-root refusals and canonical-alias success. D1/D3/Stage 2B notes are preparation only. Stop for ChatGPT assessment; independent PASS has not been obtained.


## Item 8 consolidated qualification — 2026-10-17

- Starting HEAD bd69ff5af77a4315429b15de0d2580d575cdaa43; additive local correction 8c569d607d3a7ef3714d3bb43534691502d72138, exactly strings.po and test_ui_foundation.py. No integration/publication.
- Runtime remained Git-bound reviewed 2b5cb2d52934ada4537175233a3c89b71aeba88f in disposable portable Test.app; one MCP launch/quit, final stopped. New correction NOT staged/live-qualified.
- Native bounded PASS: Status zero-settings disclosure + Check Again; Settings Cancel; alternate native-created build/profile Install no-op, original applied build retained. Native Help FAIL: interruption assurance too broad and ambiguous problem-page route. Corrected offline; independent Claude review pending.
- Public witness PRESERVED for 59 installed add-on identity/enabled records, updater and active skin. Stopped library selection/registry, portable add-ons and frozen/restart census unchanged. Arbitrary settings/resources/database preservation remains UNKNOWN.
- Focused 187/187 PASS; broader 219/220 with reproduced starting-HEAD import-policy failure. Full-suite outcome in qualification completion.json.
- Evidence: .qualification-evidence/item8-consolidated-20261017/REPORT.md and companion JSON/log/checksum records. Item 8 OPEN; D-029/D-030 unchanged. AF3 absent from disposable inventory; structured private live coverage unavailable under public-only/no-Red-Light scope.
- Next: independent exact-delta review, then a cohesive trusted-AF3 public configuration/skin capture/apply/reconciliation package with final-candidate UI and preservation evidence. Supervisor must explicitly resolve remaining private-resource coverage; no private action authorized here.
- Cleanup: no scratch copies/worktrees or local screenshots; witness temporary database removed internally; prior evidence/caches and pre-existing dirty tracking records preserved. New tracking updates additive and unstaged.

- Final validation addendum: full repository-root host suite 3,801 tests / 3,799 PASS / exactly two starting-HEAD import-policy failures / zero errors, 328.685s. Final profile inode [16777220, 442000438], stopped after all tests. completion.json records final 8c569d607d3a7ef3714d3bb43534691502d72138; no new product changes.


## Item 8 offline readiness — 2026-10-17

- READY FOR INDEPENDENT REVIEW; Item 8 OPEN. Start 8c569d607d3a7ef3714d3bb43534691502d72138; final c1adfe551e8e12b4cdca98a1fbd80c7c39c3e072.
- Local commits: 2b7759b AF3 source denial/normal-profile probe removal; 91cb672 truthful zero-scope Status; dd685f3 exact import policies/negative controls; 0659367 fake-credential fixture isolation; c1adfe5 prerequisite/evidence-plan documentation. Accepted Help unchanged.
- Validation: focused 128/128, 539/539, 39/39 and 32/32; full 3820/3820 PASS, zero errors/failures. AST/compile and diff checks PASS. Source unchanged after full run except documentation.
- Offline only: no Test.app, normal Kodi/profile/devices, real credentials, AF3/Red Light payload acquisition/installation/activation, private transfer, Agent Handoff, push/integration/publication or recovery changes.
- Public metadata options P=3.3.12 and H=3.2.19 are attributable, not selected. 15/16 keys have source references; EnableIconText unconfirmed. Full dependency admission, archive SHA-256, actual compatibility and durable native image retention remain open. Private-resource native scope remains required under unchanged D-029/D-030.
- Evidence: .qualification-evidence/item8-offline-readiness-20261017/REPORT.md and completion.json; docs/ITEM8_OFFLINE_READINESS.md and docs/ITEM8_NATIVE_EVIDENCE_PLAN.md contain exact approval needs and next native checklist.
- Next/human input: independent review, explicit source/version/archive/dependency approval and approved image retention before any separately authorized native package. No native mutation authorized here.
- Cleanup: no scratch copies/worktrees/raw databases/local screenshots retained; compact evidence remains; all previous dirty tracking contents preserved. New tracking updates are additive and unstaged. Usage/model variant/effort unavailable; no invented usage readings.


## Item 8 correction C1 — 2026-10-18

- Result: READY FOR RE-REVIEW; Item 8 remains OPEN.
- Start: c1adfe551e8e12b4cdca98a1fbd80c7c39c3e072; final: 64741b3d9a7ee515daacb1dd7cd36252858448f8.
- Local commits: bb42354 (harness claims), 55ed7c1 (Status completeness), 64741b3 (documentation).
- B1/B2 and six B3 docstrings corrected; equivalent unsupported output claims removed. Harness non-string AST unchanged.
- Status requires exact unique expected setting/file observations, nonempty identity and PASS before Current/Not Applicable. Existing drift/unreadable/FAIL and integrated validator checks preserved.
- Tests: focused 503/503; adversarial selection 22/22; full offline 3824/3824 PASS (376.667s). In-memory guard removal caused six direct and one UI failure; independent B1/B2/B3 wording reversions each detected.
- Documentation: P/H distinction, H closure unresolved, dependency minima versus compatibility, exact D-029 constraints, separate legacy launch/bm023a issues, Git-excluded worktree-local retention. EnableIconText and native image-retention gates preserved.
- Evidence: `.qualification-evidence/item8-c1-20261018/`; checksummed, Git-excluded, local only. Prior 20 evidence checksums verified.
- Not done: no Test.app/profile/staging, normal Kodi/profile, devices, credentials, Red Light, AF3 acquisition/install, structured-private change, Agent Handoff, integration, push or publication.
- Next: independent review of exactly `c1adfe551e8e12b4cdca98a1fbd80c7c39c3e072..64741b3d9a7ee515daacb1dd7cd36252858448f8`; no staging authority. Supervisor review required before further work.
- Cleanup: in-memory mutations/compilation only; synthetic test fixtures cleaned by their test contexts. Prior evidence preserved; minimal C1 logs/manifests remain local.


## Item 8 C1 final acceptance conditions — 2026-10-18

- Result: C1 correction conditions SATISFIED; Item 8 remains OPEN.
- Starting HEAD: 64741b3d9a7ee515daacb1dd7cd36252858448f8. Final HEAD / sole correction commit: 61a5f28d227b5790d1de0406f338d6bdcedcd79a.
- Documentation now records that the October 18 review found the listed safeguards technically sound but returned NOT PASS for the overall package; it no longer describes them as formally accepted.
- Added three isolated Status regressions: complete observation plus WARNING check; same-count unrelated setting observation; and all declared settings plus a duplicate. The duplicate case is also exercised through the integrated validator path.
- Scratch-only removal of each individual production guard caused its corresponding regression to fail. No production Status or validator code changed.
- Focused Status/UI/validator run: 346/346 PASS. Full offline suite: sandboxed run 3827 tests with 8 failures/2 errors from denied scoped ps process reads; unchanged permitted rerun 3827/3827 PASS in 320.680 seconds. `git diff --check` passed.
- Only the requested documentation and test files are in the correction commit. No Test.app, Kodi/profile, device, AF3, Red Light, credential, publication, integration, or push operation occurred.
- Cleanup: mutation scratch copies auto-removed; test-owned temporary fixtures cleaned. Existing qualification evidence and prior `.agent` history preserved.
- Next: ChatGPT Supervisor reviews this single local correction commit; no runtime or integration action is authorized by this task.


## Item 8 final public qualification — 20261018T141623Z
PARTIAL: exact candidate 61a5f28 confirmed; native A/B/C BLOCKED before stage/launch by process_listing_failed and unestablished native capture. MCP reports stopped. AF3 P root-only acquisition proposal prepared; no download. Evidence: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-final-public-20261018T141623Z/REPORT.md
Next: Supervisor approval of bounded offline P inspection; resolve identity/capture before native work. Item 8 OPEN. Cleanup: compact evidence and synthetic PNG retained, no scratch.


## Item 8 native unblock + AF3 admission — 2026-10-18T14:31:01.568284+00:00

- PARTIAL; Item 8 OPEN. Exact HEAD 61a5f28d227b5790d1de0406f338d6bdcedcd79a, agent/codex; no product changes/commits.
- Sandboxed identity process_listing_failed reproduced; unchanged narrowly permitted host identify PASS, exact Test.app stopped/zero processes. Host installed verification PASS against existing 2b5cb2d manifest; no final-candidate staging. Public stopped census retained; no frozen/restart transaction file.
- Automatic approval review rejected existing prelaunch Swift/CoreGraphics probe (GUI-policy conflict and shell PID). No workaround. MCP observe stopped; native PNG retention unestablished. A/B/C BLOCKED before stage/launch. Explicit operator override question pending.
- Exact AF3 P root-only approval requested in conversation; pending, zero downloads. No new packaged 16-key/dependency audit; EnableIconText and closure unresolved.
- Evidence: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-native-unblock-20261018T142932Z/REPORT.md. Prior 3827/3827 offline suite preserved; current diff check PASS.
- Next: resolve explicit operator capture/root decisions; root offline audit independently; approved capture before one final-candidate native A/B/C package. No dependencies/private/AF3 staging authorized.
- Cleanup: no scratch/caches/downloads/images; compact local evidence retained, all prior evidence and dirty tracking history preserved.


## Item 8 approved continuation — 2026-10-18T16:47:33.444025+00:00
- PARTIAL; Item 8 OPEN. Eric approved AF3 root P and existing exact-PID/window-only path. Host identity unblocked; final 61a5f28 staged and Git/manifest verified. One MCP portable launch/quit, final stopped; no native navigation/Apply.
- Exact-PID Swift helper PASS. Second automatic approval review rejected /usr/sbin/screencapture despite broad window-only approval; exact command approval now pending. No workaround/native PNG. A/B/C remain BLOCKED.
- Root P acquired only approved immutable URL: 58,482,102 bytes, blob cb697255ab4d70e1f959b0e34ee4047863660635, SHA-256 baa7f38da51379f4a65f9aee421e27b369ce799103d58fdef9087920b9041492. ZIP 3750 entries/68,835,168 bytes, CRC/path/type/limits PASS, no extraction/execution. 15 keys static reader/writer references; EnableIconText full-key/fragment absent across all members. Separate catalog/version decision required. Seven direct dependencies extracted; full recursive packaged closure unresolved; zero dependencies downloaded.
- Final profile inode unchanged, zero capture holds/transaction; scoped Addons33/updater/skin witness PRESERVED. Public library/selection, portable add-ons and transaction census unchanged; other preservation UNKNOWN.
- Report: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-native-unblock-20261018T142932Z/REPORT-CONSOLIDATED.md. Prior 3827/3827 suite reused; no source change.
- Next: exact command approval, one native A/B/C package; separately reviewed key decision/full dependency admission before AF3 provisioning.
- Cleanup: synthetic PNG/capture scratch script removed; approved archive/audit and stage rollback evidence retained; all prior sealed evidence and tracking histories preserved.


## Item 8 native A/B/C after exact capture approval — 2026-10-18T17:14:10.400637+00:00
- PARTIAL; Item 8 OPEN. Exact 61a5f28 unchanged and installed Git/manifest verification PASS, 73+5 files. Capture admission PASS after Eric explicitly approved the screencapture command: 10 exclusive exact-window PNGs plus timestamps/hashes, existing identity/Swift helpers before every capture.
- A PARTIAL: Restarts wording and Build Status -> Overall route readable/return PASS; Safety page1 readable but supported Down (and distinct Right/Down hypothesis) did not reach page2; interruption wording NOT visually verified. No product fix/tool workaround.
- B PASS: legitimate retained BM-ITEM8-INSTALL-20261015 1.0.0 / current-device-8794224972c6; zero settings/files independently resolved; Not part of this build, detail, Check Again and applicable Overall health native-proven.
- C scoped PASS: Settings Cancel/return, applied=selected association confirmed read-only; MCP graceful quit; stopped exact profile inode; no capture hold/transaction; registry/selection/add-on/transaction census unchanged; Addons33/updater/skin witness PRESERVED, uncovered UNKNOWN. No mutation repeats.
- AF3 prior approved root audit retained: exact blob/bytes/SHA256, 3750 safe CRC-checked entries, 15 static supported keys, EnableIconText absent as literal/fragment. Full dependency closure incomplete; zero dependencies/install/activation/catalog change.
- Final consolidated report: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-native-unblock-20261018T142932Z/REPORT-FINAL.md. Existing 3827/3827 offline evidence reused; no source changes/commits.
- Next substantial package: bounded Help paging diagnosis/correction review and full Safety visual qualification plus AF3 catalog/version/full exact dependency approval readiness before later provisioning. Private-resource/preservation/publication gaps remain.
- Cleanup: capture scratch script/transient dirs removed; selected PNG/log/verification/root audit and stage rollback evidence retained; all earlier sealed evidence and dirty histories preserved.


## Item 8 Help and AF3 admission — 2026-10-18
- PARTIAL; Item 8/beta OPEN. Start 61a5f28d227b5790d1de0406f338d6bdcedcd79a; local source commit caad545923232af00fe2d6e2bd218336953ae425 (10 scoped files), independent review required before staging.
- Safety native PASS on unchanged installed 61a5f28: supported Up/Down reached page 2/2 twice; corrected Overall/manual-help guidance readable. Two exact-window MCP PNGs retained with timestamps/SHA-256. No Help product correction. Stopped, installed Git/manifest identity verified; scoped public preservation PASS, uncovered UNKNOWN.
- Eric explicitly approved exact-version 15-key af3-3.3.12 scope and D01-D16 quarantine inspection, then standing task authority. New package/example/capture selection and version guards preserve legacy policy/data and reject incompatible targets. No new product staged or dependency installed/enabled/executed.
- Regression before: 3.3.12 capture returned unsupported key. Final: 10 regressions PASS; 614 affected tests PASS; 3837 full tests PASS (324.602s); five in-memory guard mutations detected; AST/JSON/diff checks PASS.
- Acquired exactly 16 pinned archives: 15 static/supported-reader PASS; D04 original font ZIP rejected for differently spelled root. Internal ID/version/hash correct; actual supported dependency reader KeyError reproduced. Historical maintainer blob identical; no corrected trusted artifact found. Graph: 22 nodes/45 edges, no missing IDs/cycles. D-028 runtime usability and four managed suffix comparisons remain unproven.
- Evidence: .qualification-evidence/item8-help-af3-20261018/REPORT.md, trusted-closure.json, approved/source/hash manifests. All 183 prior sealed evidence files unchanged. Four original dirty tracking histories copied exactly before updates; not committed.
- Next: independent review caad545; resolve font layout through a trusted correctly packaged artifact or separately reviewed product correction. Then one reviewed AF3 native Create/non-restart apply/15-setting/Status/no-op package with D-028 checks. No further operator policy/acquisition approval is pending for completed scope. D-029/D-030 unchanged.
- Cleanup: three empty/duplicate metadata scratch files and image-transfer buffers removed. Sixteen original archives (one explicitly rejected), two PNGs, compact evidence and tracking preservation copies intentionally retained. No task bytecode caches/worktrees created.


# ITEM 8 AF3 CORRECTION — LOW-QUOTA CHECKPOINT (2026-10-18T20:09:16.646741+00:00)

STATUS: PARTIAL — operator instructed immediate stop; do not continue without resume authorization.
Repository: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex
Branch: agent/codex. HEAD: 1b55a8d16309390c456b97f1eebc4f5142695a1c. Start: caad545923232af00fe2d6e2bd218336953ae425.
Local additive commits: 63968f44830cafd22628867df6a1fa6e94363d95 (reconciliation); b79aaf961e483306b896b975aa58596e5b226e66 (ZIP); 98aab72e0ad56f4d39afac41d56abdfaac0068d6 (dependency admission); 1b55a8d16309390c456b97f1eebc4f5142695a1c (Create shape/final admission and follow-up regressions).

Completed implementation: B1/B2/B3 planned package identity, pre-mutation policy and actual CONFIGURE version safeguards; all namespaces; restart barrier; shared bounded ZIP root validation and atomic exclusive publication; restricted fail-closed +matrix admission and conjunction; Create shape preflight separated from strict complete-library admission. Conditional upgrade test does not introduce replacement support.
Verified: final affected 1064 tests PASS (40.822s); 9/9 in-memory safety mutants detected; closure from original retained archives 22 nodes/45 edges, no missing IDs/cycles, all static minima PASS; D04 original SHA preserved and metadata readers PASS. AST/compile/JSON/diff checks PASS before stop. Earlier sealed 3837 PASS and 87 evidence checksums preserved.
Incomplete: final full suite was interrupted on operator instruction (exit 130, KeyboardInterrupt); no final full-suite PASS. Initial full run: 3862 tests, eight failures/three errors — ten process-listing-related outcomes in sandbox and one Create placeholder-preflight regression. Create regression was corrected and affected suites passed; process tests and full-suite aggregate remain unconfirmed in the interrupted permitted rerun. Final expected discovery count 3865, not a completed-run result.
Uncommitted: only four pre-existing dirty .agent files, now receiving this append-preserving checkpoint. No uncommitted product source or untracked visible Git files. Ignored evidence retained under .qualification-evidence/item8-af3-correction-20261018; tracking-before/ contains exact incoming tracking copies. REPORT.md is an unfinished draft, not readiness approval. Final evidence seal and cleanup remain incomplete.
Safety: no Test.app operation/staging/profile mutation, normal Kodi access, devices, download, third-party package execution, push/integration/release/Agent Handoff. D028 runtime usability/unbroken proof and native qualification remain pending. Test command stopped with Ctrl-C/exit 130; no further implementation/testing initiated.
Cleanup: none during urgent wrap-up; preserve all evidence and scratch. Four temporary index-construction source copies remain in /private/tmp/bm-af3-index-n3jtch54 (index-scratch.json records path). Eight task-era Python caches were identified in resources/lib/__pycache__; cleanup deferred. Diagnostic iteration logs and source-inspection.patch retained. Do not broadly clean or remove ambiguous state.
Exact resume: obtain explicit resume authorization; read this checkpoint and current Git state; inspect full-suite-final.log as interrupted evidence; continue only required full offline validation with supported process-listing permissions, address any genuine final failures, and retain the original failed/interrupted logs. Recheck current source before testing if anything changed. Finish report, evidence checksums, minimal owned scratch/cache cleanup and tracking updates. Independent re-review of caad545..1b55a8d16309390c456b97f1eebc4f5142695a1c is required before any future Test.app staging. Item 8/beta OPEN. No further product decision requested.


# ITEM 8 AF3 VALIDATION CLOSEOUT — 2026-10-19T11:12:15.663733+00:00

Verdict: READY FOR INDEPENDENT RE-REVIEW. HEAD 1b55a8d16309390c456b97f1eebc4f5142695a1c, agent/codex. Exact review range caad545923232af00fe2d6e2bd218336953ae425..1b55a8d16309390c456b97f1eebc4f5142695a1c; four existing correction commits, no new source changes or commits during continuation.
Final complete offline suite: 3865 PASS, exit 0, unittest 337.339s / wall 339.351s. Log: .qualification-evidence/item8-af3-correction-20261018/resume-20261019/full-suite.log; exact SHA/command/timing in full-suite-result.json. Retained affected 1064 PASS; 9/9 safety mutants detected; graph 22 nodes/45 edges, no missing IDs/cycles, static minima PASS. Earlier full-suite failure and interruption logs retained. Process-listing restriction resolved by supported permission path; Create correction already in 1b55a8d passes. No remaining offline test failure.
Checks: candidate unchanged from checkpoint; 21-path delta; AST/compilation/JSON/diff/source-patch checks PASS; 87 earlier sealed evidence files verified; 31 incoming correction files verified before REPORT finalization, exact prior REPORT snapshot preserved. D028 strict comparator and policies unchanged. Report: .qualification-evidence/item8-af3-correction-20261018/REPORT.md; master and resume SHA256SUMS manifests verified at closeout.
Cleanup: removed 4 Git-verified temporary index copies plus empty task directory, and 8 positively identified task-era bytecode caches. Unique evidence, historical logs, prior tracking contents and pre-existing/ambiguous caches retained. Incoming/outgoing tracking snapshots retained. Only four .agent files dirty; no dirty product source.
Not done: Test.app/native work, current D028 runtime proof, integration/push/publication/Agent Handoff. No normal Kodi/profile/device/credential/Red Light operations. Item 8/beta OPEN. D030 live restart-producing demonstrations remain deferred; safeguards unchanged.
Next: independent Claude review of the exact complete range before any Test.app staging. Supervisor selects any subsequent native qualification package after review. No further operator decision needed for this offline closeout.


# ITEM 8 AF3 F-1 FINAL IDENTITY CORRECTION — 2026-10-19T14:19:39.643870+00:00

- READY FOR RE-REVIEW; Item 8/beta OPEN. Start 1b55a8d16309390c456b97f1eebc4f5142695a1c; single local commit d09a38dead10b5fcb46115a55508f75d24fc2b71, agent/codex. Exact re-review range 1b55a8d16309390c456b97f1eebc4f5142695a1c..d09a38dead10b5fcb46115a55508f75d24fc2b71.
- Production: only AF3 policy recognizes ASCII case variants for admission and refuses noncanonical IDs in version/loader policy. Existing pre-mutation/actual CONFIGURE gates now apply; no aliasing, stored-data rewrite or global identity change. Three regression files cover RG-1..RG-7.
- Before correction: identity suite 49 assertion failures; installed and absent cases wrote configuration, absent also installed. Final: 44 focused PASS; 1304 affected PASS; 3879 full offline PASS (327.928s), exit 0. 16/16 in-memory mutants detected, including single-root seeds 0..7. AST/compile 148 Python + JSON 9 PASS; diff checks PASS. Prior 50+18 sealed checksums preserved.
- First full run's sole failure was relative-interpreter self-process parsing; unchanged fixture relative FAIL / absolute PASS; final full uses absolute executable. Failed/probe logs retained. Installed-state re-entry is offline evidence only, with no fabricated/live restart claim.
- Scope preserved: accepted earlier package, D028/D029/D030, no new upgrade support. No Test.app or normal Kodi/profile/device/private-data operation, downloads/installations, Agent Handoff, push/merge/release/publication or ai-supervisor.
- Report/evidence: .qualification-evidence/item8-af3-f1-20261019/REPORT.md. All four incoming dirty .agent files preserved byte-for-byte in tracking-before/; these updates stay unstaged.
- Next: STOP for independent re-review of the exact correction range. No further operator input needed for completed offline scope; no runtime/integration authorization. No remaining newly demonstrated safety blocker.
- Cleanup: redundant intermediate log removed; fixtures self-cleaned, no task-era bytecode/external scratch. Prior sealed evidence, original tracking snapshots and compact new sealed evidence intentionally retained.


# ITEM 8 AF3 RB-1/RB-2 CORRECTION — 2026-10-19T16:30:32.970991+00:00

- READY FOR INDEPENDENT RE-REVIEW; Item 8/beta OPEN. Start d09a38dead10b5fcb46115a55508f75d24fc2b71; local additive commit 9bc7ad180f86f8b04da99dabe28601bbc6c7f7a8; exact review range d09a38dead10b5fcb46115a55508f75d24fc2b71..9bc7ad180f86f8b04da99dabe28601bbc6c7f7a8. Eight scoped source/test files only.
- Baseline synthetic RB-1 succeeded with one install/one write; RB-2 private-only 3.3.12 succeeded with one private write. AF3 ASCII malformed identities now rejected without rewriting. Private 3.3.12 declarations/entries rejected at planned-final preflight, actual CONFIGURE and direct private APIs; missing/uncertain/conflicting AF3 version evidence fails closed.
- Zero mutation boundary assertions include public/private mixed and prepared-entry-only paths, optional/missing/no overlay reference. Canonical 15-key public, verified legacy private and unrelated structured/private flows preserved. Direct legacy AF3 private APIs require exact target_versions evidence.
- Final 62 focused PASS; 1007 affected PASS; complete offline 3891 PASS, 328.154s, exit 0 with supported process-listing permissions. 10/10 isolated guard mutations detected (including ZIP encryption/root XML; no ZIP implementation change). Mixed real-writer policy-removal control writes both settings despite final failure. AST/compile 136 + JSON9 + diff PASS; 28 prior sealed files verified.
- Evidence: .qualification-evidence/item8-af3-rb-20261019/REPORT.md and SHA256SUMS. Incoming four dirty tracking files preserved byte-for-byte; updates remain unstaged.
- No live/staging/profile/device/private-value/download/dependency installation/Agent Handoff/integration/push/release actions. D028/D029/D030 unchanged. No remaining demonstrated offline blocker.
- Next: independent review of exact correction range before any staging. No additional human policy decision needed for completed scope.
- Cleanup: superseded intermediate focused log removed; disposable fixtures self-cleaned; no task scratch trees/bytecode caches created. Qualification evidence, reproducible probes and incoming/outgoing tracking copies intentionally retained.


# ITEM 8 RG-2 TEST CLOSURE — 2026-10-19T18:29:22.056705+00:00

- READY FOR FINAL INDEPENDENT RE-REVIEW; Item 8/beta OPEN. Start 9bc7ad180f86f8b04da99dabe28601bbc6c7f7a8; single tests-only local commit a4b55cbf2f15420d9528d9300f9d06d8915b967c; exact range 9bc7ad180f86f8b04da99dabe28601bbc6c7f7a8..a4b55cbf2f15420d9528d9300f9d06d8915b967c.
- Only tests/test_af3_private_policy.py committed: desired AddonEntry LF/uppercase PREFLIGHT zero-action regression; real plan preview AF3 3.3.12 private UNAVAILABLE/gap regression; complete synthetic direct-private overlay metadata and no-delegation assertion.
- Focused 14 PASS; related 494 PASS; final-commit full offline 3893 PASS, 331.994s, exit 0. Sequential M13/M15/M06/M07/M08 detected with 2/1/3/1/2 assertion failures, zero errors; original in-memory methods restored after each.
- 141 non-test/non-tracking paths unchanged; AST149/JSON9/diff PASS; 104 prior evidence checksums verified. Evidence/report: .qualification-evidence/item8-rg2-20261019/REPORT.md. Incoming four dirty histories preserved in tracking-before; updates unstaged.
- No product source, Test.app, normal Kodi/profile/device/private-data, download/dependency, Agent Handoff, push/merge/release/history-rewrite or ai-supervisor operation. No newly exposed reachable product defect.
- Next: independent final tests-only re-review; no additional operator input needed for completed scope. Item 8/beta acceptance remains Supervisor/reviewer work.
- Cleanup: no external scratch/source copies or task caches created; test fixtures self-cleaned. Sealed qualification evidence and tracking snapshots intentionally retained; pre-existing ambiguous state preserved.


## Item 8 D-028 F-1 correction — BLOCKED (2026-10-20)

- Start/final HEAD: 84f524a1a298bda520e241ff1e0ba99c244ac76f, agent/codex. No commit; partial source retained uncommitted.
- Partial F-1: exact ZIP/manifest edge equality, immutable edge binding into builtin admission, unavailable-binding refusal and held-retry source validation. New regressions and mutation controls authored. F-7 now asserts complete replacement requirement tuple; F-9 removes import-time live PIL lookup/skip and authenticates retained XML.
- STOP: faithful legacy fallback reproduction completes on baseline only after transaction/updater/repository mutations precede replacement acquisition. Candidate refuses before mutations. Preserving this path and enforcing pre-mutation trustworthy edges needs a broader preparation/order design; unresolved previews also need separation from execution admission. No guard weakened.
- Validation: 18 bounded checks PASS, zero errors/failures/skips (16 historical fixture, F-7 assertion-based mutation, legacy ordering proof). Earlier focused 40: 3 failure reports/1 error; related 346: 67 failure reports/19 errors; zero skips. Final focused interrupted at STOP, exit 130; full suite not run. AST/JSON/diff checks PASS. All 24 previous sealed evidence files unchanged.
- Report: .qualification-evidence/item8-d028-f1-correction-20261020/REPORT.md. Source hashes, failed/interrupted logs and original dirty-history snapshots retained. Historical initial live PIL access preserved; second unguarded/recursive-wrapper runs cannot be established probe-free from retained logs.
- Not done: complete correction, full acceptance/mutations/V3 replay, commit, independent review, native/runtime or integration work. This task made no Kodi/Test.app/profile/device access or package acquisition/execution.
- Next/human input: Supervisor supplies a bounded preparation/order decision and follow-on scope. Do not stage or accept this partial candidate. Item 8/macOS beta OPEN.
- Cleanup: task-owned runners stopped; sandbox/test temporaries self-cleaned; no task-created caches found. Failure/stop evidence and original histories intentionally retained.


## 2026-10-20 USER QUOTA CHECKPOINT — D-028 preparation correction

PARTIAL / explicitly paused by Eric. HEAD 84f524a1a298bda520e241ff1e0ba99c244ac76f. No commit. All source and prior histories retained. Shared preparation/standalone review/apply and recovery corrections implemented, final validation incomplete. Latest related run: 169 tests, one optional-incoming-minimum fixture failure. Full and final affected runs interrupted; no runner remains. Exact state/results/resume steps: `.qualification-evidence/item8-d028-preparation-20261020/CHECKPOINT.md`. Resume only on explicit authorization; no native access/staging.


## 2026-10-20 D-028 PREPARATION RESUME — BLOCKED; NO COMMIT

- HEAD remains `84f524a1a298bda520e241ff1e0ba99c244ac76f`, branch `agent/codex`; all partial F-1/F-7/F-9/preparation work and original histories preserved.
- Resumed delta: faithful optional-incoming-minimum synthetic ZIP in tests/test_d028_corrections.py; original assertion unchanged. This fixture and legacy round trip PASS.
- Affected/related: 567 PASS, zero failures/errors/skips; F-1 V1/V2/V3, F-7, F-9 and seven assertion-only mutation controls PASS.
- ONE full guarded verbose run: 3957 tests, 14 failure reports, 6 errors, zero skips, exit 1. Process EPERM: 8 failures/2 errors. Other unresolved failures: 2 builtin plan-shape errors, 2 capture archive/edge mismatches, 6 registry-readiness admission/fixture failures. No failure suppressed; guard unchanged.
- Commit gate unmet. Product remains uncommitted. Next: bounded reconciliation of those fixture/API contracts and a compatible guarded process-test environment, then validation before commit and independent Claude review. No native staging authorized. Item 8/macOS beta OPEN.
- Exact report/results/patch/hash list: `.qualification-evidence/item8-d028-preparation-resume-20261020/REPORT.md`. Prior seals 12/12 and 29/29 PASS; product AST/JSON/source identity/diff checks PASS. Six obsolete task authoring scripts removed individually; source/evidence preserved; suite runners completed.


## 2026-10-20 D-028 FINAL REGRESSION CORRECTION — BLOCKED; NO COMMIT

- HEAD 84f524a1a298bda520e241ff1e0ba99c244ac76f, agent/codex. All incoming 18 product hashes preserved; only three test files changed in this task (builtin authority, frozen capture, registry readiness). Real plan/transaction/package/configuration evidence replaces incomplete fixtures; no production or guard change.
- Original 10 failures PASS; final three groups 94 PASS; existing affected set 567 PASS; all seven mutations detected, zero skips. Full suite not repeated: safe process arrangement prerequisite unmet. Original setuid ps EPERM remains; unprivileged identical-byte copy exits signal 9 and original assertions fail (8 inner tests, 9 reports/1 error). No commit gate reconciliation.
- Patch SHA-256 9610e93b17735129a2980ef0c8826f9010c3f1e8aea1d13dc09071400de62a02; review base HEAD plus uncommitted candidate.patch. Report: .qualification-evidence/item8-d028-regression-correction-20261020/REPORT.md. Prior seals 12/29/14 entries unchanged; 19 Python AST, JSON, diff hygiene PASS.
- Next/human input: stop for ChatGPT Supervisor assessment of process execution gate; no autonomous continuation, staging or integration. Item 8/macOS beta OPEN. No live Kodi/Test.app/profile/device access.
- Cleanup: temporary authoring script and fixture-managed disposable trees/processes removed; source, histories, snapshots and sealed evidence retained.


## 2026-10-20 D-028 SCOPED VALIDATION — READY FOR INDEPENDENT REVIEW

- Starting HEAD 84f524a1a298bda520e241ff1e0ba99c244ac76f; final 8fe3b183f399f33b99c6db7c086893bfbc552448, agent/codex. One additive local product commit, 22 paths; .agent histories excluded. Incoming candidate preserved plus exact scoped offline runner support and five harness tests.
- Guarded broad regression: PASS for 3957 executed tests, six explicitly excluded environmental tests UNVERIFIED. Discovery 3963; zero failures/errors/skips. All seven mutations detected; prior 94/567 evidence preserved and included. Historical full 3957 FAIL remains honest evidence.
- Supervisor exception applies only to local commit gate. Exact six identities, full execution, pre-execution harness refusal/correction, source hashes and seals: .qualification-evidence/item8-d028-scoped-validation-20261020/REPORT.md. Kernel protections and process detection/tests unchanged.
- Claude review range: 84f524a1a298bda520e241ff1e0ba99c244ac76f..8fe3b183f399f33b99c6db7c086893bfbc552448. Stop for independent review. Item 8/macOS beta OPEN; no native operation/integration or other-chat message.
- Cleanup: fixtures cleaned disposable state and runners completed; source/histories/snapshots and all sealed evidence retained.


## 2026-10-21 ITEM 8 D-028 B-1 — READY FOR INDEPENDENT RE-REVIEW

- Rejected predecessor 8fe3b183f399f33b99c6db7c086893bfbc552448; final local correction bbf2b4417dcc24584a7617276e0e101e5756b7a6, agent/codex. Exact range 8fe3b183f399f33b99c6db7c086893bfbc552448..bbf2b4417dcc24584a7617276e0e101e5756b7a6. Three committed paths only: frozen.py, frozen_install.py, test_d028_b1.py; .agent histories excluded.
- Reproduced real synthetic prepare READY / preview CHANGES_READY / Apply complete bypass before correction. Shared strict parser now refuses namespace/ambiguity before mutation; valid ordinary/zero-dependency configured Apply works. Retained review and resume evidence fail closed.
- 14 new and 675 affected tests PASS. Guarded broad regression: PASS for 3971 executed tests, six explicitly excluded environmental tests UNVERIFIED. Discovery 3977; zero failures/errors/skips. Seven previous and two B-1 mutation controls assertion-detected. No full-suite PASS or native acceptance claim.
- All 20 retained seals / 812 entries verified; runner, process detection/tests unchanged; AST/JSON/hash/diff PASS. Exact logs, patch/identities and matrix: .qualification-evidence/item8-d028-b1-correction-20261021/REPORT.md. Intermediate fixture issues retained, not counted as success.
- Stop for independent Claude re-review / ChatGPT Supervisor assessment. Item 8/macOS beta OPEN. No native operation, protected access, download/package execution, Agent Handoff, ai-supervisor, push/merge/integration.
- Cleanup: runners completed; fixtures dispose temporary state; source/histories/snapshots and sealed evidence retained. No task-created scratch scripts/worktrees/caches.


## 2026-10-21 D-028 OPTIONAL BOOLEAN — READY FOR INDEPENDENT REVIEW

- Baseline bbf2b4417dcc24584a7617276e0e101e5756b7a6; final local correction 88129fc5e7c06b0762d8c198d5b5d0a52f5a30ba, agent/codex. Exact review range bbf2b4417dcc24584a7617276e0e101e5756b7a6..88129fc5e7c06b0762d8c198d5b5d0a52f5a30ba. Only frozen.py and test_d028_b1.py committed (71 insertions/two deletions); original dirty .agent histories preserved separately.
- Before-fix tRuE/TrUE synthetic prepare/review/Apply completed; after-fix both refuse before transaction/updater/install/configuration mutation. true/True/TRUE stay optional; false/False/FALSE and absence mandatory. No normalization or additional encodings.
- 75 focused / 680 guarded affected PASS, zero failures/errors/skips. Seven prior, two namespace B-1 and one boolean mutation controls detected. No full/broad rerun; six unchanged process tests remain UNVERIFIED.
- AST/JSON/diff/source identity PASS; all 21 prior seals / 839 entries unchanged. Report: .qualification-evidence/item8-d028-optional-boolean-20261021/REPORT.md.
- Stop for independent Claude review; no overall D-028 acceptance. Item 8/macOS beta OPEN. No native/protected/device/download/package execution, Agent Handoff or integration operation.
- Cleanup: runners completed; fixture-managed disposable state; histories, before/after logs and sealed evidence retained. No extra scratch scripts/worktrees/caches authored.


## 2026-10-21 D-028 native platform_check feasibility — DIAGNOSTIC COMPLETE; SAFE REFUSAL

- HEAD unchanged 88129fc5e7c06b0762d8c198d5b5d0a52f5a30ba, agent/codex; product clean; no code/test edits or commits. Accepted offline architecture/security not reopened.
- One fixed Test.app MCP observe: stopped. Fixed Info.plist reports 21.3. / 20251031-a3a448d26b. No runtime query, launch, restart, profile inspection, code staging, add-on execution or application write.
- Source a3a448d26b supports partial registered/enabled/version queries, not a complete externally exposed origin/ABI/closure/usability proof. UNKNOWN providers are filtered from Addons RPC. Python remains the existing reference, not executed here. All four target rows UNVERIFIED today.
- Stock core XML has requires/c-pluff; Kodi imports loop ignores non-import children while current strict BM parser refuses them. Source-conditional compatibility blocker; actual bundle descriptors not read. No filtering/synthesis/parser change authorized.
- Existing adapter has no platform_check mode and writes results / executes an addon, so was not used. Partial host-only read JSONRPC design documented, with no admission grant. Complete verifier implementation not justified until separately reviewed native authority/transport/core compatibility decisions.
- Report: .qualification-evidence/item8-d028-native-feasibility-20261021/REPORT.md. Stop for Supervisor assessment; no native qualification PASS; Item 8/macOS beta OPEN.
- Cleanup: no scratch code/caches/download tree; diagnostic evidence and original history snapshots retained.


## D-028 pinned passive builtin implementation — 2026-10-21

READY FOR INDEPENDENT REVIEW. One local commit 5698044790d3c9e1701d0964d37a00695a9724a2; exact range 88129fc5e7c06b0762d8c198d5b5d0a52f5a30ba..5698044790d3c9e1701d0964d37a00695a9724a2. Eight scoped production/test files; tracked source clean. Approved passive compatibility for core/gui/resource only on pinned macOS Kodi 21.3; Python execution proof retained. Native build/bundle identity, exact SHA pins, narrow core c-pluff grant, builtin numeric ordering and minversion refusal implemented.

Validation: 57 focused / 715 affected PASS; one guarded broad 4017 discovered, 4011 executed, six exact environmental tests UNVERIFIED; zero failures/errors/skips. Previous 10 + new 5 mutations detected. 161 AST / 9 tracked JSON / diff checks; 23 prior seals / 868 entries intact. Failed iteration logs retained (cleanup/source-inspection setup), superseded by stable final runs.

No Test.app/device/native Kodi operations, integration or push. Offline proof only; no functional passive API usability or native qualification claimed. All original .agent histories preserved, snapshots retained, tracking/evidence excluded from commit. Report: .qualification-evidence/item8-d028-pinned-passive-20261021/REPORT.md. Cleanup: synthetic temporary roots/canaries removed automatically; auditable evidence retained.

Next: stop for independent Claude review; separate authorization required for native qualification. Item 8/macOS beta remain OPEN. Model GPT-6 (exact variant unavailable); effort/usage unavailable.


## D-028 versionless mandatory builtin correction — 2026-10-21

READY FOR FOCUSED RE-REVIEW. Starting 5698044790d3c9e1701d0964d37a00695a9724a2; one additive local commit 50294792379e804ada26300d0b2e7740ee4be701; exact correction range 5698044790d3c9e1701d0964d37a00695a9724a2..50294792379e804ada26300d0b2e7740ee4be701. Two-line shared parser guard and eight appended regression tests only (122 insertions / zero deletions). Existing passive tests byte-preserved; 230 other product files unchanged.

Before: versionless mandatory GUI accepted by both parsers; synthetic configured Apply completed (one frozen transaction, two updater changes, three installs, two configuration mutations). After: mandatory missing/empty/blank versions refuse across four builtin IDs; configured negative path has zero mutation. Optional/unrelated managed versionless behavior and valid-version configured Apply preserved.

Validation: 65 focused / 723 affected PASS; one broad 4025 discovered / 4019 executed / six exact environmental tests UNVERIFIED / zero failures/errors/skips. All 15 old + one new mutation controls detected. 161 AST / 9 JSON / diff and source identity checks; 24 historical seals / 898 entries intact. Initial new-test wrapper mismatch retained in evidence and corrected only in new test.

Report: .qualification-evidence/item8-d028-versionless-20261021/REPORT.md. Original .agent histories snapshotted/preserved, tracking/evidence excluded from commit. No protected Kodi/device/native operation, integration or push. Cleanup: synthetic roots/canaries removed automatically; auditable evidence retained.

Next: STOP for focused independent Claude re-review; no native qualification or overall acceptance claimed. Item 8/macOS beta remain OPEN. Model GPT-6 (exact variant unavailable); effort/usage unavailable.


## 2026-10-21 — D-028 read-only native platform_check transport

READY FOR INDEPENDENT REVIEW. Start 50294792379e804ada26300d0b2e7740ee4be701; sole local product commit 8d1d0f05a7335fa153f79f49535fe2a9101d8e0e; review 50294792379e804ada26300d0b2e7740ee4be701..8d1d0f05a7335fa153f79f49535fe2a9101d8e0e. Eight adapter/helper/test files, +957/-39; production frozen.py/frozen_install.py and 225 other tracked product files unchanged. Adapter 0.0.16 adds exactly platform_check, Git/source/public-manifest binding, reviewed fixed-provider and complete read-only closure verification, strict sanitized not_qualified result, existing-parent result-only write.

Validation: 139 final transport/adapter tests PASS; 1380 affected PASS before the explicitly recorded final three-file request-routing/graph-bound delta; all 16 prior + 4 new mutation controls detected. Zero final failures/errors/skips. Six exact environmental /bin/ps methods remain UNVERIFIED. Historical 4019 broad retained, not rerun. 162 AST / template / 9 JSON / diff and exact committed identity PASS; 25 prior seals / 919 entries intact. Initial expanded failed iteration retained honestly.

Report: .qualification-evidence/item8-d028-platform-check-20261021/REPORT.md. Tracking/evidence excluded from commit; initial four dirty histories preserved in tracking-before. No Test.app/normal Kodi/profile/device access, native staging/execution/configuration, credentials/private inputs, Agent Handoff, ai-supervisor, push or integration. Cleanup: temporary synthetic fixtures/canaries released; sealed audit evidence retained.

Next: STOP for independent Claude security review. Native compatibility remains UNVERIFIED; Item 8/macOS beta OPEN. Any later native operation requires its own bounded authorization. Model GPT-6 (exact variant unavailable); effort/usage unavailable.


## 2026-10-21 — D-028 platform_check B1/B2 correction

READY FOR FOCUSED RE-REVIEW. Start/rejected transport 8d1d0f05a7335fa153f79f49535fe2a9101d8e0e; sole additive correction b4c6bf34bc912815f3d0f1e63456c01c0f1d7268; review 8d1d0f05a7335fa153f79f49535fe2a9101d8e0e..b4c6bf34bc912815f3d0f1e63456c01c0f1d7268. Exactly four product/test paths: adapter entrypoint, new test_d028_platform_check_b1_b2.py, and targeted existing transport/adapter test expectations. +855/-463 includes mechanical outer-try indentation. B1 uses pre-import diagnostic-only source loading/hash checks and preload/source-less refusal; B2 rejects every malformed platform prefix before imports/writers. Adapter 0.0.16, strict not_qualified result, production verifier and legacy behavior preserved. No H1-H7 work.

Both original blockers reproduced first on Python 3.10.9 in guarded disposable fixtures. Fresh final validation: 155 focused / 1397 affected PASS, zero failures/errors/skips; all prior 20 + 2 new mutation controls detected with meaningful assertions. No historical counts reused; six exact environmental /bin/ps methods remain UNVERIFIED; no broad rerun. 163 AST / template / 9 JSON / diff / tested-committed identity PASS; 230 other tracked product files unchanged; 26 prior seals / 946 entries intact.

Report: .qualification-evidence/item8-d028-platform-b1-b2-20261021/REPORT.md. Original four dirty histories snapshotted/preserved; tracking/evidence excluded from commit. No Kodi/Test.app/profile/device access, native operation, actual acquisition/execution, credentials/private overlay inspection, Agent Handoff operation, ai-supervisor or push/integration. Cleanup: owned synthetic/cache/Git roots and canaries removed automatically; auditable evidence retained; no arbitrary caches deleted.

Next: STOP for focused independent Claude re-review. No remaining scoped offline blocker observed; native D-028 remains unqualified; Item 8/macOS beta OPEN. No new runtime authority. Model GPT-6 (exact variant unavailable); effort/usage unavailable.


## 2026-10-22 — D-028 platform_check R1 correction

READY FOR FOCUSED RE-REVIEW. Start b4c6bf34bc912815f3d0f1e63456c01c0f1d7268; sole additive correction ce488ac743c65bbe3ce1e97f0e7f45549fcf5b42; review b4c6bf34bc912815f3d0f1e63456c01c0f1d7268..ce488ac743c65bbe3ce1e97f0e7f45549fcf5b42. Exactly three committed files: host witness, diagnostic import isolation, dedicated R1 tests (+377/-0). Accepted D-028/B1/B2 and all legacy ASTs preserved. Both original R1 paths reproduced first. Fresh final 165 focused / 1407 affected tests PASS, zero failures/errors/skips; all prior 22 plus 2 new meaningful mutation controls detected. Six exact environmental /bin/ps tests remain UNVERIFIED; no broad rerun. Tested/staged/committed source identical; 38 historical seals / 1701 entries intact. One bootstrap-test launcher failure retained honestly and corrected.

Report: .qualification-evidence/item8-d028-platform-r1-20261022/REPORT.md. Original four dirty histories snapshotted and retained; tracking/evidence excluded from commit. No Test.app/Kodi/profile/device/native operation, real acquisition/execution, credential/private overlay access, Agent Handoff, ai-supervisor, push or integration. Cleanup: owned synthetic/cache/Git/mutation roots and canaries removed automatically; minimum sealed review evidence retained.

Next: STOP for focused independent Claude re-review. No scoped offline blocker observed; native D-028 remains unqualified; Item 8/macOS beta OPEN. No human input needed for completed work; a new bounded task is required for further work. Model GPT-6 (exact variant unavailable); effort/usage unavailable.


## 2026-10-22 — D-028 R1 conventional test completion

READY FOR REVIEW. Start ce488ac743c65bbe3ce1e97f0e7f45549fcf5b42; sole additive commit a185e4d346229c1797dfd75e79a7ba3ee016dd53; review ce488ac743c65bbe3ce1e97f0e7f45549fcf5b42..a185e4d346229c1797dfd75e79a7ba3ee016dd53. Three committed files (+488/-4): two product-root corrections preserved byte for byte from the interrupted candidate, plus 18 conventional regression methods/helpers. Exact uncommitted reproduction additions preserved as INERT checksummed evidence before restructuring; committed historical test prefix unchanged. No security reproduction, executable module substitution, source replacement or mutation-control execution after the conventional-only instruction.

Validation: initial 18 new / final 41 explicitly selected ordinary tests PASS, zero failures/errors/skips. Path/cleanup/spec/hash-boundary checks, mocked filesystem identities, bounded no-follow inventory, host witness difference refusal and positive not_qualified results pass. Legacy AST/path/signature/callback and historical 0.0.15 metadata checks pass. 164 AST / template / eight non-agent JSON / diff / exact tested-staged-committed identity PASS. All 39 prior seals / 1724 entries and interrupted evidence intact. Six environmental process tests UNVERIFIED. Full generated entrypoint, broad/affected suites, all 24 prior controls and two product-root mutation controls were NOT executed; security-specific proof remains UNVERIFIED. Earlier reproduction logs are historical only, not this commit's validation.

Report: .qualification-evidence/item8-d028-r1-conventional-20261022/REPORT.md. Original four dirty histories preserved in tracking-before; status history nested intact. Tracking/evidence outside commit. No Test.app/Kodi/profile/device/native operation, credentials/private-overlay access, installation/configuration/restart, Agent Handoff, ai-supervisor or push/integration. Cleanup: ordinary owned fixtures and canaries released; inert/historical and conventional review evidence intentionally retained; no active task process.

Next: STOP and return to Supervisor for independent focused review. No concrete conventional blocker observed; no R1/security/native qualification PASS claimed. Item 8/macOS beta OPEN. No input needed to complete this bounded task; further work requires a new instruction. Model GPT-6 (exact variant unavailable), effort/usage unavailable.


# D-028 public artifact store — PREPARED (2026-10-22)

- HEAD a185e4d346229c1797dfd75e79a7ba3ee016dd53, agent/codex; no product/test/runner changes or commit.
- Prepared ignored .qualification-evidence/item8-d028-public-artifact-store-20261022: exact 17 ZIP/17 production metadata records, 176,256,381 original ZIP bytes; original/transport byte identity and strict 22-node/45-edge graph validation PASS. D04 bytes/rejected-root history unchanged; installability not established.
- 40 historical seals / 1,747 entries preserved. Source identity, final integrity and new seal retained. Initial evidence-script PIL naming assertion corrected before archive import; failed log retained. No test suites or mutations rerun; six process tests remain UNVERIFIED.
- No Test.app/protected/native/network access or operation. R1 security/native compatibility remain UNVERIFIED; Item 8/beta OPEN.
- Next: Supervisor assessment, then separately authorized native setup/preflight; no further autonomous action. Native accessibility remains unverified.
- Cleanup: 17 redundant new progress JSON files removed after consolidated inventory comparison; store, minimal audit utilities/logs, snapshots and sealed evidence retained. Incoming histories preserved.


# D-028 native Test.app staging — BLOCKED (2026-10-22)

- Candidate a185e4d346229c1797dfd75e79a7ba3ee016dd53/tree 278f3e7fa49586e2db4e8d055232bf6990c64418 verified; exact 76-file/1,922,211-byte product and adapter 0.0.16 source identities match. No source/test change or commit.
- MCP stopped and supported secret-blind public snapshot PASS: fixed portable Test.app 21.3 build 20251031-a3a448d26b stopped; no incomplete stage area; frozen/restart records absent, zero-byte locks, result absent. Estuary/AUTOMATIC; Build Manager enabled, existing adapter 0.0.15 disabled. Existing installed tree fingerprints retained.
- STOP: supported stage config mandates CONFIGURATION_PATH, OVERLAY_SOURCE, DEVICE_PROFILE_ID and EXPECTED_OVERLAY_ID in addition to approved manifest/store. No approved complete public config supplied; no arbitrary or private values substituted. No config fingerprint, dry-run, stage, backups, native launch, RPC or diagnostic.
- Evidence .qualification-evidence/item8-d028-native-stage-20261022/REPORT.md; prior store seal and 51 entries preserved; 235 non-agent tracked source identities unchanged. No tests/mutations rerun; six process tests remain UNVERIFIED.
- Next: Supervisor-approved complete public diagnostic-only config (or explicit inert values for unused fields), then fresh baseline and bounded staging task. R1 security/native compatibility UNVERIFIED; Item 8/beta OPEN.
- Cleanup: no scratch/cache/generated adapter; minimal baseline/identity/seal evidence and incoming tracking snapshots retained. No Test.app mutation or cleanup.


# D-028 native stage R2 — BLOCKED before config/dry-run/stage (2026-10-22)

- HEAD a185e4d346229c1797dfd75e79a7ba3ee016dd53, agent/codex/tree 278f3e7fa49586e2db4e8d055232bf6990c64418; source unchanged. Approved sentinel decision accepted, no config-authority gap.
- Fresh supported snapshot PASS: Test.app stopped, no frozen/restart transaction records, zero-byte locks, result absent; Build Manager enabled, driver 0.0.15 disabled, Estuary/AUTOMATIC. Store and previous stage evidence seals verified.
- Additional task-created public_witness.py failed: FrozenInstallStore.inspect() attempts lock open a+ despite constructor create=False; sandbox denied EPERM. This observation method was unsuitable for read-only baseline. No successful lock open/native write; no retry/escalation/alternate route. Dependent config step stopped before writing due missing witness output.
- No config/fingerprint, dry-run, stage, backup, launch, RPC or diagnostic. Hold/root-identity comparison incomplete. Source/check failure disclosed in .qualification-evidence/item8-d028-native-stage-r2-20261022/REPORT.md and failure.json.
- Next: Supervisor decision; use verified creation-free/lock-write-free observation or explicitly bounded lock authority in a later task. No automatic continuation. R1 security/native compatibility UNVERIFIED; Item 8/beta OPEN.
- Cleanup: no scratch/cache/generated adapter; minimal failed witness, public baseline, failure report and incoming history snapshots retained.


# D-028 native stage R3 — READY FOR CONTROLLED LAUNCH (2026-10-22)

- HEAD a185e4d346229c1797dfd75e79a7ba3ee016dd53; no product/test/helper change or Git commit. Audited lock-free frozen/restart/Create readers; no records or holds; acknowledged publication validated by creation-free production pending_publication=None. Repeated public identity/write-descriptor/process observations stable.
- Approved diagnostic-only sentinel config mode0600, fingerprint sha256:aab5bbcb59e2b8bbd55da5227679c82b6de615aa6de6e0d7b48ecded3f3ea8f6; sentinel paths absent. Dry-run PASS; exactly one supported stage PASS; stage area removed; old exact trees backed up and independently verified.
- Git-bound verify PASS: BM0.1.0 76 files/1,922,211 bytes tree d60435486232420bcc11aee95c6d043e61520f70e9b5cee6c22641273e3e39c4; driver0.0.16 five files/370,802 bytes tree 7fa55b5c4bb133dce7cfef4d482c12e6c998f18bf5dc3b4b82fe56995aba1ffc. Stage manifest hash16cf4fb6fd076249ab9b7c8a11dc7a4e9fa2b776c78ecc294aa1ba0b0b6ef0fb.
- Test.app remains stopped; BM enabled, driver disabled. Public snapshots differ only driver version; public record identities unchanged; no transaction/hold/result created. Source bindings verified from literal config without execution.
- Evidence .qualification-evidence/item8-d028-native-stage-r3-20261022/REPORT.md includes intermediate task-local audit assumption/timing corrections; no product failure or staging retry. Store/R1/R2/history preserved.
- Next: Supervisor review then separately authorized portable launch/driver enablement/diagnostic. No launch/RPC/platform_check/enablement in this task. R1 security/native compatibility remain UNVERIFIED; Item8/beta OPEN. No tests/mutations rerun.
- Cleanup: exact task scratch removed after byte-copy comparison; supported helper removed .bm-stage; exact backups (including old caches), config, manifests and sealed evidence retained.


# D-028 controlled native platform_check — BLOCKED at HTTP transport preflight (2026-10-22)

- HEAD a185e4d346229c1797dfd75e79a7ba3ee016dd53; R3 seal/manifest and Git-bound installed identity verified. Pre-launch public/lock-free baseline exactly matched accepted R3. No restaging/source/helper changes or Git commit.
- Exactly one MCP portable launch; verified PID64595, -p, exact Test.app executable/build metadata. Passive listeners only loopback9090; sole owner64595 confirmed twice, startup reached Estuary home. No compatible public HTTP endpoint established for unchanged RpcClient's HTTP /jsonrpc transport. No port scan/alternate transport/settings change.
- Zero RpcClient requests/auth attempts/enablement calls/platform_check invocations. Runtime version/add-on visibility and native provider proof remain UNVERIFIED. Adapter never enabled; no restoration needed.
- Exactly one MCP graceful quit confirmed stopped. Post snapshot identical; no records/holds/pending publication/result created. Driver0.0.16 remains disabled; BM enabled. Only observed change30 ordinary BM startup .pyc files/onecache directory; Git-bound source verification PASS.
- Evidence .qualification-evidence/item8-d028-native-platform-check-20261022/REPORT.md; prior sealed evidence and backups preserved. Next Supervisor-approved compatible HTTP endpoint/auth setup before separately authorized new native attempt. R1 security, native D-028, Item8/beta not accepted.
- Cleanup: no task scratch/process; minimal evidence retained; ordinary runtime caches retained without unauthorized cleanup.


# D-028 guarded TCP host transport — READY FOR INDEPENDENT REVIEW (2026-10-22)

- One local commit8813bfc22281e662b1c688dcba60737fe0933d1b; review a185e4d346229c1797dfd75e79a7ba3ee016dd53..8813bfc22281e662b1c688dcba60737fe0933d1b. Only tools/bm_test_app.py/tests/test_bm_test_app.py committed. Staged product remains a185, source0.1.0/adapter0.0.16 unchanged.
- Added explicit PID-bound IPv4TCP127.0.0.1:9090 for platform_check and narrow Git-bound preflight/checked driver-state controls. Guard before connect/send and after receive; bounded incremental JSON/UTF8/notifications, ID matching/duplicate refusal, no retry. No TCP quit or install/retry/recover/status access. HTTP unchanged.
- Focused20 PASS; final stable affected449 PASS, zero failures/errors/skips; existing kernel guard/self-checks PASS. AST/diff/source identity PASS; old manifest loads with later helper while all76 candidate product entries/source blobs remain exact. Real-network/process classes/full suite/mutations not run; historical six methods UNVERIFIED, exclusion unchanged.
- Evidence .qualification-evidence/item8-d028-tcp-transport-20261022/REPORT.md and seals;45 prior seals/1,993 entries preserved. No Test.app access, real socket/network, native staging/diagnostic, credentials/overlays or device/profile operations. Last known runtime state is historical only.
- Next independent review of exact host-only range before separately authorized native TCP task. No native TCP/platform_check/R1 security PASS; Item8/beta OPEN.
- Cleanup: fixture/runner scratch cleaned by existing harness; minimum logs/patch/identities/snapshots retained; no task-owned process.


# D-028 TCP B1 correction — READY FOR RE-REVIEW (2026-10-22)

- Local additive commit3e72f03f70418ea920080bf6b5d33ca1b0bb98f1; correction range8813bfc22281e662b1c688dcba60737fe0933d1b..3e72f03f70418ea920080bf6b5d33ca1b0bb98f1. Only helper/tests committed. Product/stage remains a185e4d346229c1797dfd75e79a7ba3ee016dd53.
- run_platform_control compares exact21/3/revision against existing adapter PLATFORM_BUILD immediately after structural validation. Mismatch sanitized platform_build_mismatch; success-only build_verified=true. Tag remains structural, not stable-pinned.
- Focused25 PASS; affected454 PASS, zero failures/errors/skips. Original449 identities preserved plus five B1 tests.40 negative command cases prove zero SetAddonEnabled/ExecuteAddon. Exact-build enable and disable pass with fake sockets. Existing kernel guard/exclusions unchanged.
- AST audit:161 other helper functions/classes and all existing test-module class methods unchanged; __main__ unmoved. HTTP/TCP accepted behavior preserved. AST/JSON/diff/source checks PASS;46 prior seals/2,006 entries preserved. Evidence .qualification-evidence/item8-d028-tcp-b1-correction-20261022/REPORT.md.
- Nonblocking notes unchanged: post-send state may be ambiguous; require fresh read-only observation before separately authorized correction; no blind retry/rollback. Local TCP is not cryptographic authentication.
- No native/Test.app/real network operations, no restaging/adapter regeneration, no mutations/security experiments. Restricted tests remain UNVERIFIED; R1/native/Item8/beta not accepted. Next independent B1 re-review; stop for Supervisor.
- Cleanup: existing fixture/runner scratch removed; minimal sealed review evidence/tracking snapshots retained; no task-owned process.


# D-028 TCP run-path guard — READY FOR RE-REVIEW (2026-10-22)

- One additive local commitb9277f7cf18242f29d2c71000ba7e74a96d63c22; range3e72f03f70418ea920080bf6b5d33ca1b0bb98f1..b9277f7cf18242f29d2c71000ba7e74a96d63c22. Only helper/tests committed. Product/stage remains a185e4d346229c1797dfd75e79a7ba3ee016dd53.
- Extracted accepted B1 validator unchanged into _require_platform_build; TCP platform_check now independently queries/validates exact21/3/PLATFORM_BUILD after Ping before views/ExecuteAddon. Existing controls reuse identical validator. No HTTP build gate, new methods, overrides or allowlist changes.
- Focused30 PASS; affected459 PASS, zero failures/errors/skips; every prior454 identity retained plus five methods.18 invalid execution cases zero ExecuteAddon; complete exact-build synthetic path exercises Git/source/witness/freshness/postverify with qualification not_qualified. B1 cases and explicit HTTP legacy/diagnostic preservation PASS.
- AST/JSON/diff/tested-source checks PASS; R3 manifest/source bindings untouched;47 prior seals/2,020 entries preserved. Evidence .qualification-evidence/item8-d028-tcp-run-guard-20261022/REPORT.md.
- No native/Test.app/network/staging/enablement operations; no restricted process/network tests, security experiments or mutation controls. N1-N6 unchanged. R1/native/Item8/beta not accepted; next independent review then Supervisor decision.
- Cleanup: existing fixture/runner scratch removed; minimal sealed review evidence and incoming histories retained; no active task process.


# D-028 controlled native TCP preflight — BLOCKED (2026-10-22)

- Host HEAD b9277f7cf18242f29d2c71000ba7e74a96d63c22; staged candidate a185e4d346229c1797dfd75e79a7ba3ee016dd53. No source changes/commit.
- Initial verify, snapshot and audited lock-free baseline each failed process_listing_failed; baseline traceback identifies unavailable kernel executable identity. Underlying cause/PID unestablished; no retry/fallback. Fresh target/process/state authority UNVERIFIED.
- Zero launch/preflight/RPC/enablement/diagnostic/quit. No task-owned runtime process. 48 historical seals/2,033 entries preserved; host source/diff hygiene PASS.
- Report .qualification-evidence/item8-d028-native-tcp-preflight-20261022/REPORT.md. Stop Supervisor; smallest next step is a separately authorized bounded identity-gate diagnosis. No native/provider/R1/Item8/beta acceptance.
- Cleanup: no scratch or native cleanup; minimum failure evidence and incoming histories retained.


# D-028 process identity diagnosis — INCONCLUSIVE (2026-10-22)

- HEAD b9277f7cf18242f29d2c71000ba7e74a96d63c22, agent/codex; product/helper/tests unchanged; no commit.
- One authorized same-setting passive census: ps exit0, 1,034 listed, 1,020 inspected, one ESRCH vanished; first unavailable identity PID98544, immediate errno2 ENOENT. Mechanism reproduced; actual cause and target relevance UNKNOWN. No lookup retries or alternate probes.
- Preserve ESRCH-only exemption and all foreign/portable/auxiliary guards. No correction/exemption justified; optional future sanitized diagnostics only after separate authority/tests.
- Zero Test.app launch/quit/RPC/network/staging/diagnostic or signals; no suites/mutations. 49 historical seals/2,044 entries preserved.
- Evidence .qualification-evidence/item8-d028-process-census-diagnosis-20261022/REPORT.md. Stop Supervisor; further bounded causal investigation requires separate authorization. No native/D028/R1/Item8/beta acceptance.
- Cleanup: no scratch/background processes; sanitized witness/code/results and incoming tracking histories retained.


# D-028 native TCP preflight R2 — BLOCKED (2026-10-23)

- Host b9277f7cf18242f29d2c71000ba7e74a96d63c22, agent/codex; staged authority a185e4d346229c1797dfd75e79a7ba3ee016dd53. Product/helper/tests unchanged; no commit.
- First supported Git-bound verify exited1 process_listing_failed. Entire native attempt stopped; no snapshot, additional census witness or PID query. Current PID/errno/state not established; historical ENOENT not substituted.
- Zero launches/preflights/RPC/quits/enablement/diagnostics. Current native/portable baseline UNVERIFIED. 50 prior seals/2,054 entries and 235 non-agent source hashes preserved; diff hygiene/index PASS.
- Evidence .qualification-evidence/item8-d028-native-tcp-preflight-r2-20261022/REPORT.md (user-specified root suffix). Second preflight refusal requires separate Supervisor decision on security-preserving identity design; no further retry authorized. Item8/beta OPEN.
- Cleanup: no scratch/background processes/native cleanup; minimal failure evidence and incoming tracking histories retained.


## WF-testapp-text-entry — offline validated, registration blocked (2026-11-09)

- Reconciled agent/codex at 70a804388019336ee3657cae7c8fd941553ea09b. Preserved incoming tracking history, product code, sealed A15 evidence.
- Added tools/testapp_text_entry: pinned unapplied MCP patch, runner, focused tests and findings. Kodi 21.3 source supports replacement with done:false. 28 focused + 43 existing controller/transport tests PASS; native behavior UNVERIFIED.
- External MCP source/runtime unchanged. Current four-tool interface cannot send text. No Test.app call, A15 retry, Create confirmation, installation, configuration, restart, push or Agent Handoff operation. Last-known Test.app stopped from supplied context; not refreshed.
- Next: separately authorize MCP project patch/review/package/install and connection refresh, then bounded native smoke/cancel/quit. A15 remains unqualified; automated typing not yet live-proven.
- Cleanup: disposable validation copies removed automatically; generation script removed; minimal candidate artifacts retained.


## WF-testapp-text-entry-install — installed; client refresh blocked (2026-11-09)

- MCP master commit bef6bdf0d47cdce2a894c6f0d0467d47b29d0d70; exact 10-file change in evidence REPORT.md. Reviewed three-module patch unchanged; P1–P5 integrated. Full 155/155 and focused 28/28 PASS; supported package/build PASS.
- Installed five changed files at existing Codex MCP path; config/dependencies/native helper unchanged. Fresh stdio installed probe lists/calls all five with invalid arguments, no live runtime access. Active chat still has four tools.
- Supported refresh unavailable: no reconnect tool/CLI command; computer use refuses Codex app access. Stop before smoke. Zero Test.app operations; native Name/Version/replacement and final process state UNVERIFIED. Create never confirmed; A15 not run.
- Next: operator/client-supported MCP reconnect, discover fifth tool, then only the already-authorized one bounded smoke/cancel/quit. No new integration permission needed.
- Evidence: .qualification-evidence/mcp-text-entry-install-20261109/REPORT.md; SHA256SUMS seal b14f919f782deb4fc35a1a7eb408f14e5bf279c2afd62111908994925c944f95.
- Cleanup: temporary scripts/loose logs removed after evidence retention; existing uncertain dist caches/evidence and final package retained. Incoming .agent histories preserved.


## Status and Help redesign — ready for independent review (2026-11-10)

- One scoped commit `2a8519dc0d68642cea2068b8c5fd08748691089b`, base `20a75f7b8506d46847590a3a1d59b4959cfb254e`, agent/codex; 11 files in evidence REPORT.md.
- Status: read-only text and inline diagnostics, only Check Again in action column, one read per refresh, cancel/Back/native close does not recheck. Applied/selected, privacy, Needs Attention and unavailable semantics retained; engine/calculations untouched.
- Help: ordinary Main-style topic rows, all ten sections/native viewers and return focus preserved; current Create/review/Status/Close instructions. Existing AF3/Estuary/fallback styling reused; native header close added for Status only where needed.
- Offline 536 PASS + final Help 46 PASS, zero failures/errors/skips; AST/XML/JSON/diff and pinned AF3 close contract PASS. No native visual proof, Test.app access/stage, saved-build changes, A15, backend changes or Agent Handoff/push.
- Next: independent review of exact candidate; no human input needed for that review. Native visual checks require reviewed staging in a later authorized task. Item 8 remains OPEN.
- Evidence: `.qualification-evidence/status-help-redesign-20261110T163426Z/REPORT.md`; final logs/identity/static checks sealed. Cleanup: task scratch and superseded failed iteration logs removed; existing evidence and incoming histories preserved.


## Status and Help UI staging — PASS (2026-11-10)

- Installed exact `2a8519dc0d68642cea2068b8c5fd08748691089b` using one supported durable stage and unchanged approved config. Previous candidate verified as 20a75f7b8506d46847590a3a1d59b4959cfb254e. Eric explicitly waived independent source review for this UI-only candidate.
- Independent supported Git-bound verify PASS: 85 product + 5 adapter files; zero missing/modified/unexpected files. Adapter 0.0.16, tree `0678d6d8651314927c80142a6e5f282fab8aa294890ba541d56f22b05fe71a17`. Manifest `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/status-help-ui-stage-20261110T170041Z/stage-20261110T170124Z-2a8519dc0d68/stage_manifest.json`, SHA256 `5a3775a35439d837ffa8477937fad26398bf8dcc3a4b94583aef5948dbb0966e`.
- Final Test.app not_running, count 0. Userdata/builds/AF3 settings not replaced/reset under product-only staging contract. No content-comparison qualification; no launch/UI/Create/A15/source edit/new commit or Agent Handoff/push.
- Next: Eric launches via Dock for AF3-first manual visual review; no staging blocker. Native visual acceptance remains pending.
- Evidence `.qualification-evidence/status-help-ui-stage-20261110T170041Z/REPORT.md`; replaced product/adapter backups retained. Cleanup: helper removed build workspace and stage area; minimum operational evidence/backups and incoming histories preserved.


## Pending UI refinements — ready for independent review (2026-11-11)

- Commit `4e8715bb8d0c6dcc0af05b3d52f3941b53d30848`, parent `b57e3003592d8b3b000cfcead7b7bc45fe205cd6`, agent/codex; 10 files listed in evidence REPORT.md. Status Check Again/Back; direct actionable Install review Apply Build/Back/Help; prominent conditional overwrite warning above final confirmation details; read-only full Repair entry details and requested four actions; text-only AF3 action buttons.
- Existing native yes/no approval, safe No/Back default, fresh validation, coordinator, revision choice and transaction/restart behavior retained. Engines/models/timestamp fallback and production diagnostics byte-identical. Native owned-dialog icons remain a documented API limitation; actual checkbox and header X controls retained.
- Focused 168 PASS; broader 573 PASS; final Repair 33 PASS. XML/AST/JSON/diff and pinned AF3 text-only contracts PASS. Narrowly fixed pre-existing test allowlist mismatch for existing diagnostic call/emit; evidence retained. No native visual PASS inferred.
- No Test.app staging/access/launch/UI/RPC, live install/repair, userdata/build/device changes, Agent Handoff/merge/push/release. Item 8 remains OPEN. Next: independent review, then separate approved staging/manual AF3 visual evaluation; no input required for source review.
- Evidence `.qualification-evidence/pending-ui-refinements-20261111T170330Z/REPORT.md`; cleanup removed downloaded XML and superseded iteration logs, retained final sealed checks and minimal old guard-failure proof. Incoming histories preserved outside scoped commit.


## Reviewed timestamp + UI staging — PASS (2026-11-11)

- Installed `4e8715bb8d0c6dcc0af05b3d52f3941b53d30848` using one supported durable exact-Git stage. Chain 83cec151 -> b57e300 -> 4e8715b reconciled; previous product/adapter verified before replacement. Supplied independent reviews/readiness PASS accepted.
- New manifest `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/timestamp-ui-refinements-stage-20261111T181738Z/stage-20261111T181818Z-4e8715bb8d0c/stage_manifest.json`, SHA256 `f14f44842dcb633683a152f1b81f5d2137b7d5b209323faa901427b2b980b79a`. Separate Git-bound verify PASS: 86 product + 5 adapter files, zero missing/modified/unexpected files. Adapter 0.0.16, tree `6e03b02bece67f83a0500ab197699ccec58d95d33eef4a2503618cbbc64c5ac7`. Final Test.app not_running/count 0.
- Approved local config unchanged; verified old-tree backups retained. Userdata, builds, association, Keymap Editor state, AF3 and TMDb Helper configuration untouched under the product-only mutation contract; no native flag query/full-profile comparison or preservation qualification.
- No source edits/commits, launch/UI/RPC, live workflow, normal Kodi/device access, Agent Handoff/merge/push/release. Existing histories/evidence preserved. Next: Eric manually launches via Dock and visually reviews; no staging blocker. Item 8 remains OPEN.
- Evidence `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/timestamp-ui-refinements-stage-20261111T181738Z/REPORT.md`. Cleanup: helper temporary build/stage area removed; final sealed evidence/backups retained; no additional scratch.


## Final UI polish — ready for independent review (2026-11-11)

- Commit `1196f84587fd4ac188ce33a07adf5eef5ce90d0e`, parent `4e8715bb8d0c6dcc0af05b3d52f3941b53d30848`, agent/codex; nine files in evidence report. Centered single-render AF3 actions through native Button_Control; exact Repair labels Check Changes / Choose Revision / Help / Back; Back-only Install NO_CHANGES; separate tall owned Install confirmation with centered icon-free Apply Build/Back and initial Back focus.
- Existing warning/body preserved. Review apply and final confirm are distinct results; input release settles before new modal, terminal callbacks fenced, X/Back/Escape cancel. Fresh validation/coordinator safeguards, all engines/models/transactions, timestamp fix and production diagnostics unchanged.
- Focused 117 PASS; broader 579 PASS, zero failures/errors/skips. XML/AST/JSON/diff, native hashes and geometry PASS. AF3 frame1280x880/textbox800x618 vs prior native frame1280x600; conservative normal-content estimate fits, native rendering pending. Estuary/Default resources unchanged and compatible.
- No Test.app access/stage/launch/UI/RPC or interaction with Eric's running session, no live install/repair/profile/build/device changes, Agent Handoff/merge/push/release. Item 8 OPEN. Next: independent review then separately authorized stopped-state staging/manual AF3 visual review; no input required for source review.
- Evidence `.qualification-evidence/final-ui-polish-20261111T183207Z/REPORT.md`. Cleanup: downloaded source scratch and early redundant logs removed; final sealed evidence and incoming .agent histories preserved outside commit.


## Final UI polish staging — BLOCKED (2026-11-11)

- Exact candidate `1196f84587fd4ac188ce33a07adf5eef5ce90d0e`, parent `4e8715bb8d0c6dcc0af05b3d52f3941b53d30848`, agent/codex reconciled. Source/index unchanged; approved config unchanged; existing dirty histories preserved.
- First supported identify: correct portable disposable target, running_portable, main count 1 and XBMCHelper count 1. Stop rule applied immediately. No stage, verify, new manifest, process termination, GUI/RPC or workflow operation. Candidate not installed by this task.
- Current installed product/adapter not reverified. Last verified prior candidate 4e8715b / adapter0.0.16 remains historical only. Userdata/builds/association/Keymap/AF3/TMDb configuration and evidence untouched.
- Next: Eric fully closes Test.app and requests a new bounded stage; supported stopped-state admission must pass. No automatic retry. Item 8 remains OPEN.
- Evidence `.qualification-evidence/final-ui-polish-stage-20261111T185903Z/REPORT.md`. Cleanup: no scratch/build/stage area created; minimal blocked-attempt evidence and incoming histories retained.


## Final UI polish staging retry — PASS (2026-11-11)

- Installed exact `1196f84587fd4ac188ce33a07adf5eef5ce90d0e` via one durable supported stage after fresh stopped-state admission; prior 4e8715bb product/adapter Git-bound verified. Eric waived independent source review for manual visual staging; previous blocked attempt retained.
- Separate Git-bound verification PASS: 86 product + 5 adapter files, zero mismatches. Adapter 0.0.16, tree `5c72503fdbb86cf45457a5a7350674194050b7091c596eeab2ae70d9b77e099c`. Manifest `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/final-ui-polish-stage-retry-20261111T190159Z/stage-20261111T190230Z-1196f84587fd/stage_manifest.json`, SHA256 `daf744612e4d230afacbc7b5bec5ed79faa75e6653cc88d0ea5dd8e7a15b3211`. Final Test.app not_running/count0.
- Approved config unchanged; userdata/builds/association/Keymap/AF3/TMDb configuration untouched under product-only mutation contract, no full-profile comparison. Verified old-tree backups retained. No launch/UI/RPC/workflow/source edit/commit, Agent Handoff/merge/push.
- Next: Eric manually launches from Dock for AF3 visual review; no staging blocker, native acceptance pending. Evidence `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/final-ui-polish-stage-retry-20261111T190159Z/REPORT.md`. Cleanup: helper temporary workspace/stage area removed; final evidence/backups, blocked evidence and incoming histories retained.


## Update / Repair navigation — ready for independent review (2026-11-11)

- Commit `acd6f463e524917b34d2dca2b0fb3194ab2ea8a0`, parent `1196f84587fd4ac188ce33a07adf5eef5ce90d0e`, agent/codex; four files in evidence report. Repair proposed changes now directly beside Apply Changes/Back/Help; initial Back focus; cached Help round trips. Read-only results have only Back and complete text/notes/timestamp. Main order Check Changes/Choose Revision/Back/Help; all owned Help panes tested for Help-last order.
- Separate existing final Repair confirmation/body/cancellation and second affirmative gate unchanged; shared input/queued-event safeguards retained. Engines, revision/association logic, fresh validation/stale-plan rules, timestamp/diagnostics and all skin resources unchanged. Install confirmation regression PASS.
- Focused90 PASS; broader584 PASS, zero failures/errors/skips; XML/AST/JSON/diff and protected-source checks PASS. No native visual acceptance. No Test.app access/staging/launch/GUI/RPC/workflow or current-session change, no profile/build/device changes, Agent Handoff/merge/push/release. Item8 OPEN.
- Next: independent review then separately authorized staging/manual AF3 navigation/visual checks. Evidence `.qualification-evidence/repair-navigation-20261111T192925Z/REPORT.md`. Cleanup: early focused logs removed; final sealed evidence and incoming .agent histories retained outside commit.


## Repair navigation staging — PASS (2026-11-11)

- Installed exact `acd6f463e524917b34d2dca2b0fb3194ab2ea8a0` via one supported durable stage after stopped admission. Previous1196f845 product/adapter Git-bound verified. Approved config unchanged; no source edits/new commits.
- Independent Git-bound verify PASS: 86 product + 5 adapter files, zero mismatches. Adapter 0.0.16, tree `19d83d024c98bb6bf91d962e0616380d8dee96bdb1b9180fc9ec89dda10c245e`. Manifest `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/repair-navigation-stage-20261111T194146Z/stage-20261111T194220Z-acd6f463e524/stage_manifest.json`, SHA256 `5a131806797cc2ecaab81f2884e86e5769ef8b0b8395323dcc1c9270f16dbee8`. Final Test.app not_running/count0.
- Userdata/builds/applied association/device profile/Keymap Editor enabled state/AF3/TMDb configuration untouched under two-add-on mutation contract; no live state query/full-profile comparison. Verified backups/evidence retained. No launch/UI/RPC/workflow or device/normal-Kodi access, Agent Handoff/merge/push/release.
- Next: Eric manually launches for AF3 visual testing; no staging blocker. Evidence `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/repair-navigation-stage-20261111T194146Z/REPORT.md`. Cleanup: helper temporary workspace/stage area removed; minimal sealed evidence, verified backups and incoming histories preserved.


## Shared button standards — ready for independent review (2026-11-11)

- Commit `0ba37912451abac09141a054c99bdc0b391e0888`, parent `acd6f463e524917b34d2dca2b0fb3194ab2ea8a0`, agent/codex; 11 files in report. Mandatory AGENTS/styling contract; runtime action-order/confirmation-focus checks; Create/Repair now share Install's parameterized final presenter; original bodies/labels preserved. Explicit Estuary/Default single-line flags, no new renderer.
- All confirmations require a distinct final confirm with Back focused; cancellation/failure/queued-event/input-release safeguards retained. Create/Repair changed only final presentation calls; Install, shared callbacks, engines/models/timestamp/diagnostics/localization/AF3 resource unchanged.
- Focused304 PASS; broader591 PASS; final policy48 PASS; XML/AST/JSON/diff and protected-source checks PASS. Audit corrected legacy fallback Help order; native data choosers and dormant fallback presentation reported without broader conversion. No native visual acceptance.
- No Test.app access/stage/launch/UI/RPC/workflow/current-session change, device/normal-Kodi/profile/build mutation, Agent Handoff/merge/push/release. Item8 OPEN. Next: independent review then separately authorized staging/manual AF3/Estuary/Default confirmation checks.
- Evidence `.qualification-evidence/shared-button-standards-20261111T201127Z/REPORT.md`. Cleanup: early redundant logs removed; final sealed evidence and incoming .agent histories preserved outside commit.


## Shared button standards staging — PASS (2026-11-11)

- Installed exact `0ba37912451abac09141a054c99bdc0b391e0888` after stopped admission; previous acd6f463 product/adapter Git-bound verified. One durable supported stage, only two product trees; approved config unchanged; no source edit/commit.
- Independent Git-bound verify PASS: 86 product/5 adapter files, zero mismatches. Adapter 0.0.16, tree `f5095bf53e9f6a003e88fc13bd5f7b8ab839451504acba28f6585fbdb3d0aa5c`. Manifest `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/shared-button-standards-stage-20261111T204614Z/stage-20261111T204649Z-0ba37912451a/stage_manifest.json`, SHA256 `1d90652aced3f914021e4c53a5ab468f2244d80adb741beee11ae42522d5bfcd`. Final Test.app not_running/count0.
- Portable userdata/builds/association/device profile/enabled Keymap Editor/AF3/TMDb settings untouched under product-only mutation contract; no full-profile comparison or live state query. Verified backups/evidence and incoming histories retained. No launch/GUI/RPC/workflow, normal Kodi/device access, Agent Handoff/merge/push/release.
- Next: Eric manually launches for visual testing; no staging blocker, no native qualification claim. Evidence `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/shared-button-standards-stage-20261111T204614Z/REPORT.md`. Cleanup: helper build workspace/stage area removed; minimal sealed evidence and verified backups retained.


## Header Close removal — offline PASS (2026-11-11)

- Commit `afb774b5025bf2391cb052af33439d8094a12237`, parent `0ba37912451abac09141a054c99bdc0b391e0888`: presenter flag/property/205 route removed; AF3/Default header controls removed; pinned Estuary background composed without its implicit Close controls. Main Close and navigation/confirmation safety retained; permanent guidance updated.
- Focused178 / broader592 PASS (overlapping), Python192/XML8/JSON/diff checks PASS. Engines/NativeDialogs unchanged. No Test.app access/session interaction, staging, device/normal-profile access, Agent Handoff, push/merge/release.
- Evidence `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/header-close-removal-20261111T211025Z/REPORT.md`. Next: separately authorized staging and Eric's AF3/Estuary/Default visual check; no native visual acceptance claimed.
- Cleanup: public source download, transient marker and two task compiler caches removed; minimal evidence and all incoming histories retained outside product commit.


## Header Close removal staging — PASS (2026-11-11)

- Installed exact `afb774b5025bf2391cb052af33439d8094a12237` using one durable supported stage after stopped admission; previous `0ba3791` product/adapter Git-bound verified. Approved local config SHA/fingerprint unchanged; no source edits/commits.
- Independent verify: product86/adapter5, zero mismatches. Adapter 0.0.16, tree `c2d5524cceb38509e93444d9aa4d6a32cefd573fcc25bf286c5bb8b7643aa3b3`. Manifest `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/header-close-removal-stage-20261111T211820Z/stage-20261111T211855Z-afb774b5025b/stage_manifest.json`, SHA256 `f31c1c10cf49e90e4d8dd9f4eaf09e3accce6e56c08dd9aa3627639c86d5e745`. Final not_running/count0.
- Portable userdata/builds/association/device/settings/current Estuary preserved under product-only staging contract; no full-profile comparison or native workflow/launch/GUI/RPC. Backups and incoming histories retained. No Agent Handoff, merge/push/release.
- Next: Eric manually launches for visual evaluation. Report `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/header-close-removal-stage-20261111T211820Z/REPORT.md`. Cleanup: helper build workspace/stage area removed; verified backups and sealed evidence remain.
