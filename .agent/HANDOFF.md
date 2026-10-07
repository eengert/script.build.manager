# Install Build frontend — STOP at missing capability

## Reconciliation and outcome
- Task: bounded offline Install Build frontend; beta exit item 8.
- Start: agent/codex, 4edc54ab1b19b033e93f6f2596291eaa9bdb6339, clean. Live Agent Handoff: Codex current, both endpoints clean.
- No product/test/localization changes. Accepted bridge architecture remains intact.

## Demonstrated blocker
Permitted DecisionChoice.INSTALL_CURRENT produces PlanState.RESOLUTION_REQUIRED, an unknown resolved version, and no ReviewIdentity. BuildPlanService.preview issues review identity only for CHANGES_READY; validate requires that state for CURRENT. tests/test_plan.py test_19 and test_21 explicitly prove this contract; the read-only repository tripwire test proves no package resolution occurs in preview.
FrozenInstallCoordinator resolves repository-current packages inside installation, after transaction preparation and possible prerequisite installation. Its install_target API accepts choices, not a prepared resolution bound to a reviewed plan. Calling it to prepare a review would bypass the required validate-before-mutation boundary. Fetching alone cannot turn the exact library PlanTarget into a reviewed fallback plan without a supported backend resolution binding.

## Validation
python3 -m unittest tests.test_plan: 102 tests PASS (6.201s). No full suite: stopped before source changes; existing tests prove the blocker. No new tests or product commit.

## Smallest next step / required input
Separately authorize a narrow backend pre-Apply repository-resolution contract that yields a backend-owned resolved plan/review identity and revalidates that same resolution during install_target. Then resume this bounded frontend task. Do not synthesize prior install outcomes or widen backend work within this task.

## Boundaries
Create/Status and Update/Repair behavior unchanged. No Test.app, normal Kodi/profile, household device, runtime qualification, CUA, independent review, push, merge, release, or publication. Usage unavailable; exact model tier/effort unavailable in session metadata.
