# Handoff — Update / Repair Build supported workflow

- State: STOPPED offline candidate. Product commit 866080e (local; not pushed; not merged). It is not ready for independent review as the complete supported workflow until a product decision is made on repository-current packages for applied builds.
- Start: clean agent/claude at 6b5f43c97c4531425b451a2c5d2447fe2411ea91. Accepted product ancestor 62a3f9062df8b41c1a64df6012b476b7f8626482; the 6b5f43c..HEAD delta was four .agent files only. Active agent in .agent/AGENT_STATUS.json was claude. The live Agent Handoff controller was not run, because this task prohibits Agent Handoff operations.
- Done (866080e):
  - REPAIR now invokes a real workflow, injected in default.py like Install. Constructing it builds no mutating owner.
  - No verified applied association: the page says so and points to Install Build. Nothing is planned or started, and saved selection is never used.
  - Overview shows the applied build and offers Check for Changes, Choose Different Revision..., Help, and Back.
  - Check for Changes uses BuildPlanService.preview on the exact desired target. NO_CHANGES shows Current / Healthy and offers no Apply.
  - Apply Changes is offered only for a reviewed CHANGES_READY plan. It requires explicit confirmation and validate() CURRENT immediately before LibraryInstallTarget.from_plan_target() and FrozenInstallCoordinator.install_target(interactive=False). A stale or unverifiable review applies nothing and requires a new review.
  - Decisions are limited to what the plan offers, and Cancel does no work. An ignored answer cannot spin or bypass review. Preparation is retrieval only and requires a fresh review.
  - DIFFERENT_VERSION_INSTALLED and INSTALLED_ADDON_BROKEN are visible blockers with no Apply. G6 is not implemented or worked around.
  - Choose Different Revision lists only the same build_id that supports the applied profile. It changes only the session target. It writes nothing and previews nothing until Check for Changes runs. Completion uses the existing publication path.
  - Install's decision and preparation loop is now settle_library_plan(), shared with Update / Repair. Install's call sequences are unchanged, and its tests pass.
  - Corrected 32122, 32302 and 32303 copy and added 32900-32916. No stale "unavailable" Update / Repair copy remains in the product path.
- Stop: two repository-current limits. A product decision is needed.
  1. Applied builds cannot use repository-current packages for Update / Repair. RepositoryPreparationService.prepare refuses any target that carries an install_resolution. Associated targets always carry one, so preparation returns TARGET_INVALID and the user sees the safe "could not be prepared" message. The task forbids broadening repository resolution without authority, so this was not changed.
  2. A recorded repository-current record on an applied build cannot be bound to execution. The installer asks for a fresh choice for every non-exact add-on, and recorded records are not bound into execution. Apply is therefore refused before mutation, and the review shows note 32914. Checks still run. Recorded accepted skips are carried as SKIP and do work.
  Decision options for ChatGPT and Eric: (a) accept the refusal for beta and document it as a limit; or (b) authorize an engine-owned binding for recorded repository records and applied-target preparation, which needs its own review.
- Files: default.py; resources/lib/install_workflow.py; resources/lib/update_repair_workflow.py (new); resources/lib/ui/repair_view.py (new); resources/lib/ui/native_dialogs.py; resources/language/resource.language.en_gb/strings.po; tests/test_update_repair_workflow.py (new, 29 tests); tests/test_install_workflow.py (one assertion moved to the corrected fallback copy); docs/UPDATE_REPAIR_WORKFLOW.md (new); docs/TESTING.md (one row).
- Validation: focused suite (new file plus Install, Foundation, Plan UI, Status UI, Create, Plan, Status) passes except the two pre-existing import-policy failures. Full suite on the candidate: 3132 run; 3126 pass; the same two failures and four errors as the git-backed starting HEAD (3103 run). Compile, git diff --check, non-ASCII scan, string-ID definition check, and UI import policy checks pass for the changed modules.
- Live-proven: none. Everything is unit-tested with injected fakes. No Test.app, normal Kodi, profile, device, MCP, or push activity.
- Not updated: .agent/AGENT_STATUS.json, which is controller-owned under D-026 and not edited by hand. BUILD_MANAGER_PROJECT_PLAN.md and AGENTS.md are unchanged.
- Out of scope, noticed (not fixed):
  - resources/lib/ui/plan_view.py imports typing, which fails two pre-existing ImportPolicy tests (test_no_engine_imports, test_the_presentation_modules_import_no_engine). Both fail identically at the starting HEAD.
  - tests/test_bm_test_app_keychain.py: 4 errors (TypeError in tools/bm_test_app.py resolve_commit with the fixture commit). Also pre-existing at the starting HEAD.
  - Five tests skip in the git-archive copy of HEAD but run in the worktree; this is environmental.
- Next: product decision on the two repository-current limits. Then independent review of 866080e. The runtime Test.app step needs a separate, explicit authorization.
- Usage: see the last row of .agent/USAGE_HISTORY.md.
