# Agent Handoff — BM-020A integrated

## BM-021A integration complete

BM-021A is complete, supervisor-approved, and integrated on protected `matrix`.
The substantive audit commit is `b32369e`; no worker-specific metadata was
copied. `docs/FROZEN_BUILD_CAPTURE.md` records the exact artifact/provenance,
dependency-closure, updater-policy, immutable-store, and freshness conclusions
for future BM-021B/BM-022 work. It explicitly rejects installed-directory
zipping and undocumented per-addon auto-update assumptions.

BM-021B and BM-022 remain unstarted. BM-020 remains complete, BM-017 remains
deferred, and family-room source/distribution concerns are not independently
marked solved. Matrix remains neutral with `active_agent: none`.

## BM-020C integration complete

BM-020C is complete, supervisor-approved, and integrated on protected
`matrix`; matrix is neutral with `active_agent: none`. The matrix-side
substantive commits are `81ba44b` and `091cfe9`. Codex worker metadata was not
copied.

The guarded resume coordinator now re-reads the durable request after a new
Kodi session, previews the exact request and fingerprint before mutation,
claims `AWAITING_RESTART` atomically as `RESUMING`, runs normal
`BuildManager.reconcile()`, verifies the final fingerprint and `NONE`, and
clears the expected transaction atomically. Preview/fingerprint/reconcile
failures, claim/clear conflicts, exceptions, repeated restart requirements,
and later `RESUMING` or `NEEDS_ATTENTION` states fail closed. The service does
not restart Kodi or a host process; current supported platforms require a
manual full Kodi restart, after which resume is automatic.

Integrated validation passed focused tests **465/465**, disposable BM-020C
resume gate **8/8** with AF3 dependency closure **18/18**, full suite
**1536/1536**, and `git diff --check`. The gate proved service automatic
resume, authoritative read-back, fingerprint equality, `NONE`, no duplicate
handoff, later no transaction, and real Kodi profile immutability. AF3
generated first-run runtime state was bootstrapped only in `.kodi-test`; the
AF3 unmanaged probe is intentionally owned by BM-020A because AF3 normalizes
that entry across restart. Pristine first-ever AF3 provisioning is not claimed.

BM-020 overall is complete. BM-017 and family-room distribution/source work
remain deferred. The smallest next step is supervisor direction on those
separate concerns; no next milestone was started.

## BM-020C1 integration complete

BM-020C1 is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive commit is `bcaf2ca`. Codex worker metadata was not
copied.

The integration adds the typed capability resolver and manual restart
coordinator, with current and unknown platforms conservatively mapped to
`MANUAL_APP_RESTART_REQUIRED`. Successful `KODI_RESTART` handoff preparation
persists and read-backs `AWAITING_RESTART` with attempt count `0`, never
restarts or quits Kodi, and returns structured manual guidance. Failed runs
create no transaction, `NONE` completes without one, same-session requests do
not re-run reconciliation, and a new session with count `0` is ready for the
later resume phase. No automatic adapter or resumed reconciliation is
claimed.

Matrix validation passed focused tests **63/63**, disposable manual gate
**8/8** with AF3 closure **18/18**, full suite **1517/1517**, and
`git diff --check`. The gate used only `.kodi-test`; the real Kodi profile,
Apple TV, and all devices remained untouched.

BM-020C resume work remains incomplete: fingerprint revalidation, `RESUMING`,
resumed reconciliation, success clear, loop prevention, and failure/recovery
semantics. Do not begin that work, BM-017, or family-room distribution/source
work as part of this integration record.

## BM-020B integration complete

BM-020B is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The clean
matrix-side substantive integration commit is `f3ccf2a`. Worker-specific
Codex metadata was not copied.

The durable foundation is profile-local and schema-versioned. It records only
the safe request, desired fingerprint, restart requirement, originating Kodi
session UUID, and transaction phase. Writes are staged in the same directory,
flushed and fsynced, atomically replaced, read back, and rejected if corrupt
or unsupported. An explicit clear removes the record safely. A profile-local
sidecar uses nonblocking `fcntl.flock`; lock ownership is released by the OS
when the process exits. The current Kodi session UUID is held in the home
window property `script.build.manager.kodi_session_id`.

`service.py` is a thin `xbmc.service` startup entrypoint. It classifies the
record and publishes the bounded result without restarting Kodi, reconciling,
resuming, or claiming a transaction. BM-020C owns actual resume/re-entry
execution.

The integrated disposable gate passed **9/9**: service fast path, session
identity, production preparation without restart, same-session protection,
external process boundary, automatic ready-for-resume classification, clear,
returned fast path, and real-profile immutability. Transaction tests passed
**32/32**, the full suite passed **1504/1504**, and `git diff --check` passed.
The first gate invocation observed only a startup-readiness race and was not
used as evidence of a code failure; the unchanged retry passed all 9 checks.
The real Kodi profile, Apple TV, and all devices remained untouched.

BM-020C and BM-017 remain unstarted. No next milestone was started. The
smallest next step is supervisor direction on BM-020C's resume/re-entry
policy; no worker handoff is implied by this matrix record.

## Prior integrated state

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

Focused integrated validation passed 1458/1458; full suite passed 1472/1472;
`git diff --check` passed. The family-room production source/distribution gap
remains a separate pending concern and is not claimed by BM-020A. The real
Kodi profile, Apple TV, and all devices remained untouched. BM-020B/C and
BM-017 were not started.

## Prior integrated state

## BM-019 integration complete

BM-019 is complete and integrated on protected `matrix`; the matrix state is
neutral with `active_agent: none`. The substantive integration commit is
`202f41d` (`feat(BM-019): integrate restart requirement aggregation`).

The typed contract exposes `NONE` and `KODI_RESTART`. Operation results declare
requirements locally, and central aggregation retains only the strongest
successful changed requirement. Idempotent/no-change operations do not create
restart requirements. Failed/uncommitted operations do not establish one, and
a later failure cannot erase an earlier successful requirement. The planner
does not infer restart requirements from action kinds.

`docs/RESTART_REQUIREMENTS.md` documents the contract and the BM-019/BM-020
boundary. BM-018D/BM-018E paths remain `NONE`; no current production operation
legitimately requires restart, so no synthetic live restart scenario was run.
BM-020 restart execution, transaction persistence, and resume/re-entry remain
unstarted.

Validation from the integrated tree: focused tests **813/813**, full suite
**1476/1476**, and `git diff --check` clean. The real Kodi profile and all
devices remained untouched.

## Prior integrated state

## Current matrix state — BM-018D compatibility extension + BM-018E

**Status**: Complete, supervisor-approved, and integrated on `matrix`.
`active_agent = none`; no worker identity or Agent Handoff pointer was copied
into the matrix state.

Integrated substantive commit: `1c024e9` —
`feat(BM-018E): integrate AF3 compatibility and package`.

- The approved `af3-common` package contains exactly 16 reviewed bool/string
  targets and `files: []`.
- Generic Kodi skin-setting compatibility handles canonical-to-lowercase
  access, guarded fallback after double `-32602`, safe Skin.* persistence,
  strict typed/effective read-back, and bounded persistence verification.
- XML remains eligibility/persistence evidence only; it is not the effective
  runtime backend.
- AF3 mutual-exclusion validation remains in the AF3-specific policy layer;
  BM-018A confirmation behavior is unchanged.
- BM-018D disposable validation passed 17/17; BM-018E production validation
  passed 14/14; the AF3 dependency closure was 18/18 healthy; focused tests
  passed 461/461; and the full suite passed 1463/1463.
- The JSON-RPC setter persistence quirk is handled generically. AF3's
  first-run generated-state bootstrap is disposable-only, so pristine
  first-ever AF3 provisioning remains intentionally unclaimed.
- The real Kodi profile remained read-only. No Apple TV or other device was
  accessed. BM-017, BM-019, BM-020, and no next milestone were started.

The existing WF-002 handoff record follows as historical integration context.

**Status**: WF-002 is complete and supervisor-approved. The helper and tests
are integrated on matrix; `active_agent = none` and matrix awaits the next
assignment.

## What was done

- Implemented `tools/antigravity-usage` helper around `/usr/local/bin/codexbar`:
  - Queries `provider = antigravity`, `source = auto`, JSON format, no-color.
  - Parses and preserves named rate windows from `usage.extraRateWindows`
    (e.g., "Gemini weekly" and "Claude/GPT weekly") without collapsing them.
  - Preserves account email, source, login method, and reset descriptions.
  - Calculates remaining percent strictly as `100.0 - usedPercent`.
  - Fails closed with normalized, sanitized unavailable result on error or missing data.
  - Supports `--human` summary output and JSON output.
- Created `tests/test_antigravity_usage.py` covering:
  - Multi-window parsing and distinct Gemini vs. Claude/GPT pool separation.
  - Remaining percentage calculation.
  - Fallback to primary/secondary windows if extraRateWindows is absent.
  - Error handling: malformed JSON, command exit code, missing binary, timeout,
    missing provider record, missing usage section, sanitized error output.
  - All 11/11 tests pass.
- Updated `AGENTS.md` with Antigravity-Specific Notes documenting the authoritative
  command, helper usage, distinct pool preservation, and usage conventions.
- Updated `.agent/USAGE_HISTORY.md` with task convention note and WF-002 row.
- Updated `.agent/AGENT_STATUS.json` and `.agent/CURRENT_TASK.md`.

## Validation

- Focused tests: `python3 -m unittest tests/test_antigravity_usage.py` — 11/11 passing.
- Live read-only smoke test: attempted; current CodexBar invocation timed out.
  The helper returned a sanitized unavailable result and exposed no raw stderr
  or private account data.
- `git diff --check`: passed cleanly.
- Real Kodi profile untouched; no Apple TV access; no BM milestone work started.

## Prior BM-018D boundary

- BM-018D remains complete: 17/17 disposable AF3 live checks and 1438/1438
  full tests were previously recorded.
- No production `af3-common` package was created.
- BM-018E, BM-017, BM-019, and BM-020 were not started.
- Real Kodi profile remained read-only; no Apple TV access occurred.

## WF-002 usage record

The Antigravity worker's measured WF-002 usage row is preserved exactly once
in `.agent/USAGE_HISTORY.md`; no Codex usage figures were fabricated.

Next task awaits supervisor assignment.
