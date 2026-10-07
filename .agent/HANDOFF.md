# Install Build frontend — stopped at product capability boundary

## Task and baseline
- Requested first bounded Install Build frontend slice; no authoritative BM-UI-004 ID assigned.
- Advances macOS Beta exit item 8; expected outcome was an executable native Install path.
- Reconciled branch agent/codex, HEAD 74ebefbe28ed3befa8bc9e7ca0c34d88cf0b944b, clean.
- Live Agent Handoff: current agent codex; both endpoints clean.

## Result / exact blocker
No product source changed. Stop condition: existing APIs do not bridge the reviewed library-owned target into durable frozen installation/configuration/resume.

BuildLibrary.selected_plan_target supplies LibrarySource plus compatibility path fields pointing to one bundled envelope (schema_version, manifest, frozen, packages). BuildPlanService consumes LibrarySource.load(), including its owned configuration loader. FrozenInstallCoordinator.install instead reloads configuration_manifest_path with load_manifest_file; its default resume loader parses manifest_path as a standalone FrozenBuildManifest. Neither accepts the library envelope. Configuration ReconcileRequest is path-based and its default configuration loader uses the global package root, not the library-owned package snapshot. Passing the envelope path cannot preserve the reviewed content into execution/resume. UI-side extraction or custom replacement of configuration/resume orchestration would bypass the requested product-owner boundary.

## Evidence
Disposable tests.test_build_library.LibraryTests fixture: register/select/load library source and owned configuration PASS; FrozenInstallCoordinator._configuration_profile rejects selected compatibility path with ManifestValidationError; _default_manifest_loader rejects it with FrozenInstallValidationError. Only exception class names printed.
python3 -m unittest tests.test_build_library tests.test_plan -q: 155 tests PASS (7.763s).
No new behavior/tests; no final product candidate; full suite and additional subsystems not run.

## Smallest next step
Separately authorize a product-owned, durable library install-target bridge: revalidate exact library entry/profile, carry its manifest/frozen/config packages into existing installation/configuration and restart/resume owners, and preserve approved review choices. Require offline round-trip and changed-input rejection tests before frontend wiring. No UI-side freshness approximation or transport implementation.

## Preserved boundaries
Create unchanged; Install remains unavailable; Update / Repair remains unavailable. No Test.app, normal Kodi, real profile, household device, runtime qualification, restart, independent review, push, release, or publication. Only .agent task bookkeeping changed.

## Usage
GPT-6 session identity; exact tier and effort unavailable. Start/end/delta unavailable per repository Codex guidance.
