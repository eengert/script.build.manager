# BM-UI-003C — PASS offline; STOP for independent review

## Identity and outcome
- Branch: agent/codex; clean start d905190ec69d2f896ab675b74e71136b21c261c1.
- Product commit: db8ffe803a3e5350407f70f7618fc4c494dc3d17.
- Advances beta exit item 8: native Create route and confirmed capture/save/select.
- Agent Handoff read-only status confirmed Codex active at the expected clean start.

## Done
- Added trusted Create workflow/catalog and native opt-out session/preview/confirmation/results.
- All eligible roots/current skin selected; private capture On. AF3 production schema and vetted Red Light declaration reused. Human name/version/profile inputs only.
- COMPLETE-only registration; deterministic private identity, exact-content/no-overwrite store commit, bounded matching rollback, recovery of post-publication registration errors, saved-but-not-selected warning.
- Added expected-active-skin guard; inventory now requests human names. Updated Help and unique English IDs 32700-32739 (gaps intentional).
- Files: default.py; create_workflow.py; native_dialogs.py; create_capture.py; frozen.py; private_overlay.py; build_library.py; strings.po; test_create_workflow.py; test_ui_foundation.py; docs/CREATE_WORKFLOW.md.

## Validation
- 68 new workflow tests; 652 relevant UI/capture/library/private/config/frozen tests PASS.
- One full run: 2865 tests PASS in 131.219 seconds; permitted offline subprocess/loopback fixtures only.
- All 11 product/test/documentation files SHA-256 unchanged after full-suite start; git diff --check PASS.
- Sentinel privacy, native cancellation/confirmation, actual capture/library/private commits, conflict/rollback/publication ambiguity, runtime lazy-store composition and zero managed-state mutation covered offline.
- Status/Settings/Help/Install/Repair regression coverage retained. No live UI/end-to-end claim.

## Not done / limits
- No push, matrix integration, publication, version/icon change, Test.app launch/staging, normal Kodi/profile access, devices, Install/Repair or G6 work.
- Separate stores are not a transaction: crash can leave private orphan/staging content. Unreadable/unsafe rollback state is retained, with saving-unconfirmed result. No broad cleanup.
- Fresh capture timestamps can make same-version attempts conflict; choose a new version.
- Trusted config scope is AF3 public schema and supported Red Light private resource; unknown software gets no inferred configuration.

## Exact next step
Independent BM-UI-003C review of the product commit/delta. After independent acceptance, a separate bounded task stages the exact reviewed commit into /Applications/Kodi Build Manager Test.app and qualifies it in mandatory portable -p mode. Eric/ChatGPT must dispatch that next task; do not start it here.
