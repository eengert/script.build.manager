# BM-UI-003B — Create Capture Engine: PASS offline; STOP

## Identity and admission
- Worktree: /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex
- Branch: agent/codex; clean exact start e1e5c936ff2eed57bc5b64b77a53be2015c0dd2c.
- Product commit: f08b3fda497da74ba3a6a4afaff672ee9b9ba05d. Separate endpoint tracking commit follows.
- Advances beta exit item 8 / missing G1 capture foundation. Live Agent Handoff confirmed Codex active before edits.
- Accepted Build Library f660332d4701bbf8493037f956ea62d8a539e023 and G2/G3 contracts unchanged.

## Completed
- Immutable CreateBuildRequest, explicit PublicCaptureSpecification/PublicSettingTarget, read-only CapturePreview, typed COMPLETE/INCOMPLETE/FAILED CreateBuildResult and immutable PreparedPublicBundle.
- Existing capture_frozen_build handles roots/dependencies/acquisition. Active skin comes through injected existing KodiStateInspector.inspect contract and joins managed/frozen roots. Root enabled states retained; dependencies not promoted to top-level roots.
- Only declared typed settings/files read through ConfigurationBackend. Deterministic per-capture package descriptors/exact assets pass existing ConfigPackage ownership validation.
- Existing-schema manifest uses build info, captured roots/skin, config/private declarations, platform profile and extending device profile. Exact default remains; no fabricated repositories/fallback/Skip policies.
- Canonical public frozen graph removes diagnostic maps/error text but retains typed capture/provenance/artifact/optional-absence truth. Its fingerprint binds separate in-memory private overlay; build/package/device identity checks pass.
- Existing PrivateSettingDeclaration and StructuredPrivateResourceManager.capture (real RedLightSettingsAdapter in isolated SQLite fixture) reused. Required failures discard all prepared output. Optional actual absence preserved; backend errors remain incomplete. No private persistence.
- Public envelope is validated against accepted library format and transport limits. registration_inputs() stages ONLY public material in a fresh owned temporary context for later BuildLibrary.register(*inputs); capture never calls it, registers or selects.
- Safe result/repr omit payloads/paths/raw exceptions; artifact gaps contain validated IDs and typed statuses. Incomplete capture exposes no partial bundle/overlay.

## Files
- resources/lib/create_capture.py
- tests/test_create_capture.py
- docs/CREATE_CAPTURE.md
- Endpoint bookkeeping: .agent/HANDOFF.md, CURRENT_TASK.md, AGENT_STATUS.json, USAGE_HISTORY.md.

## Validation
- 46 new offline capture tests PASS.
- Final focused: 656 tests PASS (2.551 s).
  python3 -m unittest tests.test_create_capture tests.test_frozen tests.test_config tests.test_private_overlay tests.test_private_resource tests.test_build_library tests.test_manifest_loader tests.test_manifest_resolver tests.test_artifacts -q
- One final full suite: 2785 tests PASS (131.332 s).
  python3 -m unittest discover -s tests -q
  Permitted execution used for existing disposable loopback/process fixtures. No source/test/document edits afterward.
- Candidate hashes of all three product/test/document files remain unchanged after full suite. git diff --cached --check PASS.
- Logs: /private/tmp/bm-ui-003b-focused.log; /private/tmp/bm-ui-003b-full.log.
- Disposable library registration validates prepared output, leaves selection unset and proves private sentinel absent from library envelope.
- Private sentinel absent from public result/repr/serialization, generated manifest/frozen/package, and logging calls. Real structured capture leaves disposable DB bytes unchanged.
- Mutation tripwires cover settings/files, public/private apply, resource apply/initialize, install, enable, skin, updater policy, restart transaction/coordinator, frozen install/retry/resume, overlay save and automatic registration. Exact artifacts are acquired only through established frozen engine.
- Automated/offline evidence only. No independent review or live-runtime qualification claimed.

## Limits / not done
- Explicit public specification must be curated by trusted product code: existing library checks reject known private channels, but cannot classify secrets disguised as arbitrary declared public text/files.
- Red Light requires existing quiesced/held/disabled/initialized resource state. Capture reports incomplete when unavailable; no state preparation or mutation. Existing pre-0.2.0 SQLite URI '#' hardening finding unchanged.
- Diagnostic cleanup intentionally creates canonical public software identity; private binding uses its recomputed fingerprint. Missing exact artifacts are incomplete, never substituted. Incomplete results have no registration inputs; library contract unchanged.
- Existing library ID/version conflicts, I/O errors and private persistence/selection atomicity belong to the later confirmed UI commit flow.
- No native dialogs, real registration/selection, Install/Repair Apply, G6, version/icon/repository changes, new network logic, push/publication/matrix integration, Test.app launch, normal Kodi/profile/device access or mutation.

## Smallest next step / human input
Independent review of this candidate, then native Create Build dialogs + confirmed registration/selection (private overlay saved separately).
No implementation human input remains. Eric/ChatGPT supplies the bounded review/next-task prompt. STOP.
