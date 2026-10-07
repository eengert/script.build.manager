# Durable Build Library -> frozen install bridge

## Task / outcome
- Backend implementation only; removes the demonstrated Install blocker to beta exit item 8.
- Starting branch agent/codex, HEAD 72970ba9c07aa6d2d60c4bdc626c41a32d1a3b86, clean.
- Agent Handoff live status confirmed current agent codex; both endpoints clean at admission.
- Product/test/docs candidate: 32d915e0ea4f97748b505ca131d0f16df08832f0.

## Reproduction / design
- Disposable registered source and owned package load succeeded; envelope-as-path frozen loader rejected with FrozenInstallValidationError and configuration loader with ManifestValidationError.
- LibraryInstallTarget binds the exact library root, registered content-addressed entry ID and device profile. Derive from the same PlanTarget; Plan review now hashes exact registered source identity.
- install_target uses existing frozen installation semantics with explicit approved ResolutionChoice mappings and profile policies. Target defaults to noninteractive; missing approvals do not implicitly prompt.
- Revalidate via Build Library before plan evaluation, again after decisions before transaction creation, and on durable resume/retry. No mutable selection lookups, payload persistence or temporary extraction.
- BuildManager loads the public manifest/frozen graph/packages from the same library snapshot. Its existing configuration owners execute it; standalone/global loaders are bypassed in library mode.
- Frozen schema 4 persists validated library_target (null for standalone); reads supported schemas 1-3. BM-020 schema 2 carries library selectors; standalone schema 1 remains emitted/read. Empty legacy paths in library mode prevent ambiguous interpretation.
- Quiescence retry/resume, held registry readiness, configuration-awaiting-restart and final resume retain exact source, fingerprinted policies/resolutions and holds.

## Changed product files
resources/lib/build_library.py; resources/lib/build_manager.py; resources/lib/frozen_install.py; resources/lib/plan.py; resources/lib/transaction.py; tests/test_library_install.py; docs/LIBRARY_INSTALL_TARGET.md.

## Validation
- 14 new bridge tests pass: owned-only package material, exact entry/profile, review binding, missing/corrupt/unregistered/changed sources, initial execution, default composition isolation, fresh-owner BM-020/frozen restart, held quiescence/configuration restart/readiness, approved Skip/policy continuity, legacy schemas and source validation.
- Focused: python3 -m unittest tests.test_library_install tests.test_build_library tests.test_plan tests.test_frozen_install tests.test_resume tests.test_restart_coordinator tests.test_transaction tests.test_build_manager tests.test_config tests.test_frozen_registry_readiness -q: 561 PASS (9.519s).
- Final full candidate: python3 -m unittest discover -s tests -t . -q: 2960 PASS (146.801s), with permitted disposable process/loopback fixtures. Product source unchanged afterward.
- Initial full run found standalone injected-factory regressions (corrected), sandbox process/socket restrictions, and unqualified discovery double-importing a helper fixture. Final package-qualified run resolves these without weakening tests.
- In-memory parse validation for five product modules and new test module; git diff --check PASS.
- Public configuration executes real BuildManager/ConfigurationManager owners in disposable state. Representative held tests inject the private-owner outcome and metadata; real library load, transaction, restart, registry-readiness and final activation paths run. No live qualification claim.

## Not done / next step
No frontend changes, Test.app launch/access, normal Kodi/profile access, household devices, runtime qualification, external private stores, packaging, publication, push or matrix integration. Accepted Create implementation unchanged.
Smallest next step: independent read-only review of this exact backend candidate. Frontend review freshness/confirmation and future Install wiring remain separate tasks after acceptance. No implementation blocker remains; older product versions cannot read new library transaction schemas. No user input needed to complete this task.

## Usage
GPT-6 session identity; exact tier and effort unavailable. Start/end/delta unavailable per AGENTS.md. No subagents.
