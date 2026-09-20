# Current Task

## BM-019 — restart-requirement aggregation

**Status**: Complete on `agent/codex`; not integrated to `matrix`.

Substantive commit: `703ff4c3ae4fdf5cb88445e5521e041287adef57`.

Implemented the typed `RestartRequirement` contract with `NONE` and
`KODI_RESTART`, monotonic aggregation, immutable reporting/serialization, and
result metadata for repository, add-on, dependency, skin, and configuration
operations. Only successful changed operations contribute; idempotent results
do not, failed/uncommitted results do not establish a restart requirement, and
later failures preserve an earlier successful requirement.

Added `docs/RESTART_REQUIREMENTS.md` and updated the canonical restart section.
BM-018D/BM-018E paths remain `NONE`; their typed skin persistence compatibility
behavior does not request a restart. No automatic restart or BM-020 resume
behavior was added.

Validation: focused restart/planner/config/add-on/dependency/repository/skin
tests **813/813**; full suite **1476/1476**; `git diff --check` clean. No live
restart test was invented because no current operation legitimately requires
one. Only disposable/unit validation is in scope; the real Kodi profile and
devices were not accessed.

Usage telemetry was unavailable; no values were fabricated. BM-017 and BM-020
remain deferred. The smallest next step is supervisor review of BM-019.

## Prior integrated state

## Synchronized worker state

**Status**: BM-018D and BM-018E are complete, supervisor-approved, and
integrated on `matrix`. Codex is synchronized, idle, and ready for the next
supervisor assignment. No new milestone has started.

Current matrix: `cfd335499123126027741f8e595489cc32b9e207`.

The integrated state preserves the approved 16-setting `af3-common` package
with `files: []`, explicit skin ownership, and AF3-specific mutual-exclusion
policy outside the generic backend. The generic skin backend handles
canonical/lowercase typed lookup, guarded double-`-32602` fallback, safe
`Skin.SetBool`/`Skin.SetString`/`Skin.Reset` persistence, strict effective
read-back, and bounded persisted-state verification.

BM-018D disposable validation passed 17/17. BM-018E production AF3 validation
passed 14/14 for all 16 settings, including authoritative read-back,
idempotency, drift repair, ownership failure before mutation, restart
persistence, and wrong-skin rejection. The AF3 dependency closure was 18/18
installed, enabled, and not broken. The first-run AF3 generated-runtime
bootstrap remains disposable-only; pristine first-ever AF3 provisioning is not
overstated as proven.

Focused tests passed 461/461 and the full suite passed 1463/1463. The real
Kodi profile remained read-only, with no Apple TV or other device access.
BM-017, BM-019, BM-020, and any next milestone were not started.

## Prior worker record

**Agent**: Codex
**Branch**: `agent/codex`
**Status**: Complete on worker; ready for supervisor review/integration.

Commit `28b8b90` completes the generic typed skin-setting compatibility work.
The approved `resources/config/packages/af3-common/package.json` remains
unchanged: exactly 16 reviewed bool/string targets and `files: []`, with the
six reviewed candidates still unmanaged. BM-018A's confirmation lifecycle
and the AF3-specific mutual-exclusion policy were not changed.

Root causes and resolution:

- AF3 3.2.19's first-run generated-state initialization can reload the skin
  during Kodi's keep/revert transaction and cause the original transient
  Estuary fallback. The harness bootstraps that generated runtime state only
  inside `.kodi-test`; pristine first-ever AF3 provisioning is not claimed.
- Kodi's typed `Settings.SetSkinSettingValue` path reports success but does
  not schedule the skin-settings XML save. Successful typed writes now also
  use safe `Skin.SetBool`, `Skin.SetString`, or `Skin.Reset` persistence
  commands, followed by strict read-back and bounded persisted-state polling.
- When canonical and lowercase typed lookups both return `-32602`, fallback
  eligibility is guarded by the active skin's persisted key/type entry only;
  effective reads use `Skin.HasSetting`/`Skin.String`, never XML contents.

Validation:

- `python3 tools/kodi_test.py validate-skin-config`: 17/17.
- `python3 tools/kodi_test.py validate-af3-package`: 14/14, including all 16
  production targets, idempotent reapply, drift repair, ownership failure
  before mutation, restart persistence, and wrong-skin failure before mutation.
- Focused implementation/config/planner/harness tests: 461/461.
- Full unit suite: 1463/1463.
- `git diff --check`: clean.

The AF3 dependency closure was installed, enabled, and verified not broken at
18/18 nodes in the disposable profile. The real Kodi profile remained
read-only; no Apple TV or other device was accessed. BM-017, BM-019, BM-020,
and any next milestone were not started. The smallest next step is supervisor
review and normal worker-to-matrix integration; no handoff has occurred.
