# Agent Handoff — BM-020A integrated

## BM-017C integration complete

BM-017C is complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `dce8276`, reconstructed from worker
implementation commit `8ba7bdc`; worker tracking metadata was excluded.

The structured private-resource foundation owns only explicitly declared typed
fields inside a vetted resource. Public manifests contain safe adapter,
version, schema, lifecycle, and field metadata; private values remain in the
protected overlay and are omitted from results, logs, and durable restart
metadata. The Red Light 2.6.8 adapter requires an existing exact-schema WAL
database and quiesced runtime, performs bounded row-scoped transaction writes
with per-field read-back, preserves unrelated rows, and requires explicit
restart/reload. It does not replace the mixed settings database or support
arbitrary paths, SQL, or wildcard ownership.

Integrated validation passed structured-resource **27/27**, focused
regressions **386/386**, full suite **1604/1604**, and `git diff --check`.
Tests use fake fixtures only. No real Family Room private database, credential,
Kodi profile, Apple TV, or other device was accessed or mutated.

BM-017B remains complete with result
**BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; frozen Family Room software is
**COMPLETE**, captured desired state is **INCOMPLETE**, and real-device frozen
installation is **NOT VALIDATED**. BM-017D has not started.

### Smallest next step

Supervisor direction and separate authorization are required before any
BM-017D real private-state capture/import work. Do not access the real Family
Room private database or begin another milestone from this handoff.

## BM-017B integration complete

BM-017B is complete and supervisor-approved, with result
**BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**. The reviewed sanitized evidence is
`docs/BM017B_PRIVATE_CAPTURE.md`; it records that Red Light `2.6.8` stores
required private/auth state in a mixed `databases/settings.db` resource outside
the BM-017A typed Kodi-setting boundary. No private values were captured, no
raw database was retained, no arbitrary private-file copier was added, and the
Family Room source remained read-only.

Frozen Family Room software remains **COMPLETE**; captured desired state is
**INCOMPLETE**; real-device frozen installation is **NOT VALIDATED**. Matrix
remains neutral with `active_agent: none`. BM-017C is complete and integrated
above; BM-017D remains separately authorized and not started.

## BM-017A integration complete

BM-017A is complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `321fee8`, reconstructed from worker
implementation commit `ebd4c61`. Worker tracking metadata was excluded.

The integrated foundation defines explicit public private-setting ownership,
typed version-1 overlay entries, build/overlay identity, canonical SHA-256
fingerprinting, duplicate/undeclared/type/completeness rejection, and
fail-closed missing-required behavior. Active storage is profile-local under
`addon_data/script.build.manager/private_overlays`, written atomically with
restrictive permissions where supported. It is protected local plaintext;
encryption at rest is not provided or claimed, and no custom cryptography is
used.

The existing BM-015 typed configuration backend remains the only settings
engine. Public configuration is applied first and validated private settings
second through the same typed write/read-back path. Private values are not
included in public artifacts, logs, results, `.agent/*`, or durable BM-020 /
BM-022 state. Durable state carries only overlay ID, fingerprint, and required
flag. Optional absence is a safe no-op; required absence and fingerprint drift
fail closed.

Integrated validation passed private-overlay **14/14**, BM-015/BM-020/BM-022
regressions **588/588**, full suite **1591/1591**, and `git diff --check`.
The real Family Room private profile, credentials, Kodi profile, Apple TV,
and other devices were not accessed or mutated. Required Family Room frozen
software capture remains complete, but ready-to-use configuration still
requires a separately authorized real private overlay capture/import, and
real-device frozen installation is not validated. BM-017B has not started.

### Smallest next step

Supervisor review and explicit authorization of any future BM-017B private
capture/import work. Do not access real private Family Room state or begin
another milestone from this handoff.

## BM-022V / BM-022V-R integration complete

BM-022V and BM-022V-R are complete, supervisor-approved, and integrated on
protected `matrix`. The clean matrix-side substantive commit is `31b8f9d`,
reconstructed from approved worker commit `784ea8f`; worker-only `.agent/*`
metadata was not copied. Matrix remains neutral with `active_agent: none`.

The read-only Family Room software capture is complete for required software:
37 nodes; 67 required and 3 optional edges; zero required missing artifacts;
30 exact artifact-backed nodes; 194,254,227 captured bytes; and fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
The exact Dropbox `10.3.1+matrix.1` artifact is present with SHA-256
`5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6` and
size 667,538 bytes. The cached Robotocjksc ZIP remains byte-for-byte
unchanged; its single safe alternate root is accepted by the generalized
validator and normalized during staged extraction. Optional YouTube remains
non-blockingly incomplete because the installed and cached versions differ.

Ready-to-use configuration is **INCOMPLETE / BLOCKED_BY_BM017** because
private/authenticated state was not captured. Real-device frozen installation
is **NOT YET VALIDATED**. The Family Room profile/evidence remained read-only;
no installation, update, enable/disable, repository refresh, restart,
settings/database write, or reconciliation occurred. BM-017 remains deferred
and no next milestone was started.

Validation from the integrated tree passed focused tests **331/331**, the
full suite **1577/1577**, and `git diff --check`. The smallest next step is
supervisor direction on the separate BM-017/private-state boundary; do not
install the candidate build or begin another milestone from this record.

## BM-022 integration complete

BM-022 is complete, supervisor-approved, and integrated on protected `matrix`.
The clean matrix-side substantive commit is `56ea26a`, a cherry-pick of
worker commit `27f4215`. The worker tracking commit and all worker `.agent/*`
metadata were excluded. Matrix remains neutral with `active_agent: none`.

The integrated lifecycle consumes only complete BM-021B manifests and exact
immutable artifacts, validates artifact identity and ZIP structure, installs
the required third-party graph deterministically, and excludes Kodi/system
dependencies from artifact installation. It reuses the reviewed BM-011
staged-package boundary and does not create a second unrestricted installer.
Wrong-version replacement, downgrade, broken state, missing metadata, and
orphaned target directories fail closed.

The durable frozen transaction captures build/manifest identity, phase,
original updater policy, guard ownership, restart linkage, and bounded status.
The updater guard is persisted before the first mutation, `NEVER_CHECK` is
verified before installation and reasserted before BM-020 startup/resume, and
release restores and verifies the original policy before clearing the frozen
transaction. Failures remain diagnosable in `NEEDS_ATTENTION`; there is no
silent completion or automatic software rollback. Explicit abandon is
available and does not claim rollback.

BM-022 composes with the existing Build Manager configuration and BM-020
restart/resume lifecycle. The new read-only dependency metadata fallback only
reads the known installed VFS path when Kodi cannot expose a freshly
discovered disabled add-on handle; it does not mutate Kodi state or fabricate
metadata.

Rerun evidence: focused regressions **639/639**, disposable
`validate-frozen-install` passed, full suite **1573/1573**, and
`git diff --check` passed. The proof used only `.kodi-test`; complete real
Family Room capture/install and real-device validation remain pending.

BM-020, BM-021A, BM-021B, and BM-022 are complete. BM-017 remains deferred.
No next milestone was started. The smallest next step is supervisor direction
on the remaining real Family Room/device validation boundary.

## BM-021B integration complete

BM-021B is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`. The reviewed
substantive endpoint was reconstructed as `2ee040c` (`feat(BM-021B): add
frozen artifact capture core`); worker-specific `.agent/*` files were not
copied.

The capture core provides a SHA-256 content-addressed, atomic write-once
artifact store with immutable sidecar metadata and read-back verification;
exact ZIP/package validation without execution or installed-directory
synthesis; typed installed inventory, transitive dependency closure, exact
system boundary, honest provenance, deterministic manifest/fingerprint, and
fail-closed incomplete states; plus exact store/cache/repository acquisition
ordering. The updater guard uses supported Settings JSON-RPC, captures and
restores the global policy explicitly, and must reassert/read-back
`NEVER_CHECK` before each resumed mutation because that setting does not
persist across restart.

The disposable gate proved 18/18 AF3 third-party closure entries healthy plus
the system boundary, exact installed versions and edges, and an honest
`incomplete_artifact` result when exact package-cache ZIPs were unavailable.
It did not claim a complete build, installed-directory provenance, frozen
installation, retention, pinning, scheduling, freshness enforcement, or
garbage collection. The updater proof passed read/set/read-back, restart
reassertion, no observed scheduled updater activity while guarded, explicit
restoration, and second-restart restoration. Focused validation passed
372/372 tests and the full suite passed 1557/1557; `git diff --check` is
clean. The live proof used only the disposable `.kodi-test` profile; no real
Kodi profile or Apple TV was accessed.

BM-020 and BM-021A/B are complete. BM-022 has not started, BM-017 remains
deferred, and family-room source/distribution concerns remain pending. The
smallest next step is supervisor direction on those separate concerns; no
next milestone was started.

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
