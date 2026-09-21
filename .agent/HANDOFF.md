# Agent Handoff — BM-020A integrated Codex worker

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
the worker remains idle/ready for BM-020B and the external active-worker
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
