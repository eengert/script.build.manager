# Agent Handoff — BM-018E

## Status

BM-018E implementation remains on `agent/codex`, but the required production
`af3-common` disposable live gate is not complete. No matrix, Claude, or
Antigravity branch was changed.

## Implemented

- Added `resources/config/packages/af3-common/package.json` with exactly 16
  supervisor-approved typed skin settings: 13 bools and 3 strings.
- Kept `files: []`; no settings.xml, generated/runtime state, paths, auth, or
  private data is packaged.
- Updated the Eric example manifest to select `af3-common` through
  `skin.config_packages` and declare all exact targets as `target: "skin"`.
- Documented the approved policy and the six intentionally unmanaged
  candidates in AF3 portability and package documentation.
- Added focused tests for exact values/types, skin ownership, no file overlay,
  excluded candidates, and example-manifest wiring.

## Validation before this continuation

- Focused package/resolver/schema tests: 61/61.
- Existing disposable AF3/Kodi BM-018D runtime gate: 17/17. It exercised the
  production backend with synthetic runtime package data; the production
  `af3-common` descriptor and all 16 targets were validated by unit tests.
- Full suite: 1453/1453.

## BM-018E production gate result

Added a harness-only `validate-af3-package` path in `tools/kodi_test.py` and a
dispatch test. It reads the installed disposable copy of
`eric-main.example.json`, resolves the `family-room` profile and winning
`skin.config_packages: ["af3-common"]`, loads the installed package root, and
checks planner `SET_SKIN -> CONFIGURE` ordering.

Live evidence from the disposable profile:

- AF3 3.2.19 and its complete transitive closure: 18/18 installed, enabled,
  and not broken.
- AF3 generated-state bootstrap reproduced the original transient fallback,
  then BM-018A activated AF3 with persisted skin and `xbmc.getSkinDir()` both
  reporting `skin.arctic.fuse.3`.
- The real package resolved to 16 bool/string skin targets and `files: []`.
- 12 targets applied/read back; 4 failed read-back with Kodi JSON-RPC
  `-32602 Invalid params.`
- A direct disposable probe returned the same error for both canonical and
  lowercase IDs for `Navigation.OnBack`, `View.UseDetailedListLabels`,
  `Widgets.DisableNoResultsItem`, and `Widgets.EnableShowMore`.
- The backend already performs the approved lowercase retry on `-32602`; this
  is not a missing normalization fallback. Kodi 21.1 does not expose these
  four AF3 IDs through `Settings.GetSkinSettingValue` in this disposable run.
- The gate stopped before claiming all-16 read-back, idempotency, drift repair,
  ownership, wrong-skin, or restart persistence. No package weakening or
  production-code workaround was attempted.

Harness tests passed 96/96 and `git diff --check` was clean after the
diagnostic change. The real Kodi profile mtime remained unchanged; no Apple
TV or other device access occurred.

## Boundaries

BM-015 ownership, BM-018D skin activation/backend/normalization and AF3
cross-setting validation remain authoritative. BM-017, BM-019, and BM-020
were not started. The existing BM-018E usage row remains exactly once; no
telemetry was fabricated or duplicated for this continuation. No production
AF3 package was integrated to `matrix`; the smallest next step is supervisor
review of the Kodi runtime/API blocker.
