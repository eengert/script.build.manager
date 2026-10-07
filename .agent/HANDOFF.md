# Handoff — Install Build frontend

- State: COMPLETE OFFLINE; STOP after implementation report. No independent review or runtime qualification begun.
- Starting state: clean agent/codex at d4b14ce0cad61f56b4ad47519c8bc61158a6c34a. Read-only Agent Handoff status confirmed current agent Codex; no switch.
- Beta admission: advances exit item 8 by making native Install usable through the reviewed backend chain; beta qualification is not claimed.
- Product commit: c5d2a441e7694dbeccdc7bb605f3307302b24969.
- Product files: default.py; resources/lib/install_workflow.py; resources/lib/build_library.py; resources/lib/ui/native_dialogs.py; resources/lib/ui/plan_view.py; resources/language/resource.language.en_gb/strings.po; tests/test_install_workflow.py; docs/INSTALL_WORKFLOW.md.
- Architecture: workflow retains exact target/review/prepared identity; NativeDialogs presents selection/decisions/full review/confirmation/results; default.py composes lazily. Execution/preparation owners are deferred until needed.
- Selection: read-only arbitrary-entry plan_target validates declared profile and never reads or writes saved selection. Friendly name/version/profiles only.
- Plan: only offered choices; Cancel exits, Skip remains bound; Repository Current preparation followed by fresh preview with actual version and fallback meaning. All review rows/exceptions shown.
- Apply: explicit confirmation with Back default; validate exact target/review. Stale/unverifiable requires fresh review and another approval. CURRENT derives exact LibraryInstallTarget then install_target with prepared_resolution unchanged, explicit ResolutionChoice mapping, interactive=False, and no policy/path override or post-Apply fetch.
- Results: localized stable outcomes only; complete/with exceptions distinct from restart/active/attention/cancel/failure. Pending operation observation prevents competing install. Existing frozen/BM-020/startup owners retain lifecycle responsibility.
- Validation: 24 new focused methods PASS; 689 focused/related tests PASS; final full package-aware discovery 3024 PASS in 140.433s; git diff --check PASS. Initial sandbox full run had only process-listing/loopback denials in existing disposable harness fixtures; unchanged source rerun with permitted fixture access passed.
- Behavioral evidence: real disposable native selection -> Plan decisions -> repository preparation -> fresh resolved-version review -> validation -> frozen exact saved-package execution; prepared identity unchanged and resolver/refetch forbidden after Apply. Create/Status/Settings/Help regressions green; Update / Repair stays unavailable.
- Not done: Test.app/runtime/remote-focus/restart-UI qualification, normal Kodi/profile/device access, Update / Repair, G5/G6, imports/exports, new lifecycle owner, package/release/publication, push, matrix integration, independent review, ai-supervisor or CUA.
- Smallest next step: separately assigned independent review of this product commit; runtime qualification requires its own bounded task. None begun.
- Human input: none required to complete this implementation. Separate assignment required for further work.
- Usage/model/effort: unavailable; no inferred telemetry.
