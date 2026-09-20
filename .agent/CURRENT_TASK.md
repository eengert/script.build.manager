# Current Task

## BM-020A production reconciliation executor

**Status**: BM-020A production executor validation is complete on `agent/codex`
and ready for supervisor integration. No matrix integration was performed.

The gate uses the self-contained disposable AF3 fixture
`bm020a-executor.example.json`, while the actual checked-in `af3-common`
descriptor remains the production package under test. No synthetic package
content or repository action is used.

Current matrix: `e2458d4f977e09769b01d8e8a82635497b913546`.

Validation commit: `1ec6cc2` adds the disposable executor fixture and gate
evidence, plus the narrow Kodi built-in `kodi.resource` dependency
classification correction exposed by the real AF3 closure.

Gate evidence:

- Actual production path: manifest/profile resolution → skin selection →
  package resolution → planner → `SET_SKIN` → `CONFIGURE` → typed backend.
- Real production `resources/config/packages/af3-common/package.json` loaded;
  all 16 settings read back exactly and `files: []` was proven.
- First pass succeeded with `RestartRequirement.NONE`; identical second pass
  retained the same fingerprint and changed nothing.
- Deliberate `Navigation.OnBack` drift was repaired; unmanaged
  `TMDbHelper.Corner.Radius` remained unchanged through configuration passes.
- Invalid profile selector failed in resolve with disposable state unchanged.
- Focused tests: 1391/1391. Full suite: 1472/1472. `git diff --check` passed.

BM-019, BM-018D, and BM-018E remain complete and integrated. BM-020B/C and
BM-017 have not started. The real Kodi profile, Apple TV, and all devices
remained untouched. The family-room distribution/source gap remains separate
and was not assigned to BM-020A.
