# Current Task

## BM-020A — production reconciliation executor integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`. `active_agent` is `none`; matrix remains neutral.

Substantive integration commits: `eeafc1c`, `0ed2c35`, `821e69e`, `0fb0bd5`,
and `1ad0fdb`.

BM-020A establishes the callable `BuildManager.reconcile()` contract: typed
serializable request/result models; load → inspect → resolve → preflight → plan
→ execute → validate orchestration; planner-authoritative owner dispatch;
deterministic desired-state fingerprints; ordered fail-closed execution; and
BM-019 `RestartReport` aggregation. No restart execution, transaction
persistence, resume, locking, or restart-loop behavior was added.

The disposable `validate-build-manager` gate passed from this integrated tree.
It used the self-contained `bm020a-executor.example.json` / `bm020a-disposable`
fixture and the checked-in production `af3-common` package. The real AF3
dependency closure was healthy at 18/18; the first pass exercised `SET_SKIN`
through `SkinActivator` and `CONFIGURE` through `ConfigurationManager`, read
back all 16 typed settings with `files=[]`, and reported
`RestartRequirement.NONE`. The identical second pass retained fingerprint
`sha256:05f278188815d3900760d7b3d4d82c31e6e50324128a3e45031cca9ee8606d86`
and made no mutations. Managed `Navigation.OnBack` drift was repaired while
unmanaged `TMDbHelper.Corner.Radius` remained unchanged. An invalid device
selector failed in resolve with disposable state unchanged.

The narrow `kodi.resource` system-dependency classification correction is
included and covered by focused tests. The real family-room distribution and
source coverage gap remains separate: BM-020A does not claim fresh-installable
coverage for POV, Red Light, Umbrella, MyAccounts, AF3, or the production
repository bootstrap/source binding.

Focused integrated validation passed 1458/1458; the full suite passed
1472/1472; and `git diff --check` passed. The real Kodi profile, Apple TV, and
all devices remained untouched. BM-020B/C and BM-017 remain unstarted.

## BM-020A1 — action-ownership prerequisites integrated

BM-020A1 remains complete and is included in the BM-020A integration history.

## BM-019 — restart-requirement aggregation integrated

**Status**: Complete, supervisor-approved, and integrated on `matrix`.
`active_agent` is `none`; matrix remains neutral.

Substantive integration commit: `202f41d`.

Established the typed `RestartRequirement` contract with the current levels
`NONE` and `KODI_RESTART`. Individual operation results declare their local
requirement, while orchestration aggregates successful changed results
centrally and monotonically. The planner remains non-mutating and does not
infer restart requirements from action kinds. Idempotent/no-change operations
report `NONE`; failed/uncommitted operations do not establish a requirement;
later failures preserve earlier successful requirements.

The contract and JSON-safe `RestartReport` are documented in
`docs/RESTART_REQUIREMENTS.md`. BM-018D/BM-018E paths remain `NONE`; their
typed AF3 persistence compatibility behavior does not spuriously request a
restart. BM-020 owns actual restart execution, transaction persistence, and
resume/re-entry and has not started.

Focused BM-019/planner/config/add-on/dependency/repository/skin tests passed
813/813. Full suite passed 1476/1476. `git diff --check` passed. No current
production operation legitimately requires restart, so no synthetic live
restart scenario was added. Real Kodi profile and devices remained untouched.

## Prior integrated state

## BM-018D compatibility extension + BM-018E — integrated

**Status**: Complete, supervisor-approved, and integrated on `matrix`.
`active_agent` is `none`; matrix remains neutral and awaits the next
assignment.

Substantive integration commit: `1c024e9`.

The integrated work preserves the approved 16-setting `af3-common` package
with `files: []`, explicit skin ownership, and the AF3-specific mutual-
exclusion policy outside the generic backend. The generic skin backend now
handles canonical/lowercase typed lookup, double-`-32602` fallback, safe
`Skin.SetBool`/`Skin.SetString`/`Skin.Reset` persistence, strict effective
read-back, and bounded persisted-state verification. XML is used only for
fallback key/type eligibility and persistence verification, never as the
effective state backend.

BM-018D disposable validation passed 17/17. BM-018E's production AF3 gate
passed 14/14 for all 16 settings, including authoritative read-back,
idempotency, drift repair, ownership failure before mutation, restart
persistence, and wrong-skin rejection. AF3's complete disposable dependency
closure was 18/18 installed, enabled, and not broken. The first-run AF3
generated-runtime bootstrap remains disposable-only; pristine first-ever AF3
provisioning is not overstated as proven.

Focused tests passed 461/461; the full suite passed 1463/1463; and
`git diff --check` passed. The real Kodi profile remained read-only, with no
Apple TV or other device access. BM-017, BM-019, BM-020, and any next
milestone were not started. BM-019/BM-020 retain ownership of future
restart aggregation/resume work.

Next task awaits supervisor assignment.

## Prior integrated task

### WF-002 — Antigravity usage reporting via CodexBar integrated

**Status**: Complete, supervisor-approved, and integrated on `matrix`;
`matrix` remains neutral and awaits the next assignment.

Integrated workflow commit: `fcc7caa` (cherry-picked with provenance).

WF-002 adds the read-only `tools/antigravity-usage` helper, focused tests, and
the Antigravity CodexBar usage guidance in `AGENTS.md`. The helper preserves
distinct named Gemini and Claude/GPT pools, account/source/login metadata when
available, and sanitized bounded failure results.

Focused tests: 11/11 passing. The live helper smoke test was attempted
read-only; the current CodexBar invocation timed out and the helper returned
the sanitized unavailable result without exposing stderr or private data.

Integrated substantive commits:

- `28a6fd4` — `feat(BM-018D): add typed skin configuration support`
- `5a3cc9a` — `fix(BM-018D): resolve AF3 disposable live gate`

BM-018D generic typed skin-setting support is complete. The disposable AF3
live gate passed 17/17 and the full suite passed 1438/1438. The disposable
environment must install, enable, and verify the complete AF3 dependency
closure, with no dependency broken. AF3's first-run generated-state
initialization caused the original transient fallback; the harness performs
that generated-runtime bootstrap only inside `.kodi-test`, then validates the
actual BM-018A Estuary -> AF3 confirmation/activation path. Completely
pristine first-ever AF3 provisioning is not overstated as proven.

AF3 key normalization and non-boolean string-setter return handling are
implemented in the skin backend/runtime adaptation. AF3-specific mutual
exclusion policy remains isolated from the generic backend.

- Focused BM-018D tests: 765/765 passing.
- Full suite: 1438/1438 passing.
- `git diff --check`: passing.
- Real Kodi profile remained read-only; no Apple TV access occurred.
- At that earlier WF-002 checkpoint, no production `af3-common` package had
  yet been created.
- At that checkpoint BM-018E, BM-017, BM-019, and BM-020 were not started.

Next task awaits supervisor assignment.
