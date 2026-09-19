# Agent Handoff — BM-016 research substantially complete

**Date**: 2026-09-19
**Agent**: Codex (Sol / Ultra requested; runtime slug unavailable)
**Status**: Pending supervisor review. BM-017 not started.

## Result

- Created `docs/RED_LIGHT_PORTABILITY.md` at commit `cbb93db`.
- Inspected Red Light `plugin.video.redlight` 2.6.2 read-only.
- Inventoried all 508 source settings plus 70 generated display rows.
- Classified source settings: 337 `PUBLIC_PORTABLE`, 71
  `PRIVATE_PORTABLE_CANDIDATE`, 47 `DEVICE_SPECIFIC`, 45
  `GENERATED_RUNTIME`, and 8 `UNKNOWN_NEEDS_TESTING`.
- Found that real settings live in mixed-content custom SQLite
  `settings.db`, not Kodi's typed settings surface. BM-015 therefore has
  zero directly deployable Red Light settings today, and whole-file deployment
  is unsafe.
- Documented file/state inventory, auth field names, do-not-copy state,
  cross-platform limits, and BM-017 evidence boundaries.

## Validation and safety

- Production code changed: no.
- Tests added: no.
- Full unit suite: 1378/1378 passing.
- Disposable Red Light mutation: not run; no safe BM-015 target exists and a
  custom SQLite writer is outside BM-016.
- Secret audit: 508 inventory rows; every private default redacted; no JWT or
  bearer marker; no real-profile absolute path in the report.
- Real Kodi profile: read-only inspection only; no Kodi process/device control.
- `matrix` and `agent/claude`: untouched.

## Scope boundary / remaining unknowns

- tvOS, Android TV/Shield, and Fire OS remain `UNTESTED_CROSS_PLATFORM`.
- Structured row application/restart behavior, selected auxiliary databases,
  and account portability remain explicitly unproven.
- No production package, private overlay, credential move, or BM-017 code was
  created.

## Smallest next step

Supervisor review of BM-016. If accepted, scope BM-017 to the documented
authentication field names and disposable reauthorization/restore evidence.
A separate reviewed task is required before any structured public Red Light
settings adapter or `redlight-common` package.

## Usage

Start: 5-hour 15% used / weekly 2% used.
End: 5-hour 90% used / weekly 14% used.
Observed delta: +75 / +12 percentage points used. These are account-level
shared-usage readings, not task-isolated billing.
