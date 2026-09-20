# Agent Handoff — BM-020A Codex worker

## Status

BM-020A disposable production-executor validation is complete on `agent/codex`
and ready for supervisor integration. The external Agent Handoff pointer was
not changed. Matrix remains
`e2458d4f977e09769b01d8e8a82635497b913546`.

Implementation and validation are committed as `1ec6cc2`. The gate uses a
self-contained disposable AF3 fixture and the real checked-in
`resources/config/packages/af3-common/package.json`; it does not patch the
family-room example or fabricate repository/package content.

Disposable evidence from a fresh isolated profile:

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
