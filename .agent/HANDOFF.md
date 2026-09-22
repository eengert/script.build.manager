# Agent Handoff — synchronized Codex worker

## BM-017D — Real Family Room structured private-resource capture complete

BM-017D is complete on `agent/codex`. Matrix remains unchanged at `2374ee5`;
the real private overlay is stored only outside Git in protected local Build
Manager storage. No other worker branch was modified.

The explicitly authorized read-only Xcode `devicectl` receive targeted only
`AppleTV - Family Room (4)`, bundle `com.eengert.koditvosnew`, and
`Library/Caches/Kodi/userdata/addon_data/plugin.video.redlight/databases/settings.db`.
The names-only directory check found no `settings.db-wal` or `settings.db-shm`
sidecars. No unrelated cache sidecars were received.

The BM-017C adapter validated the Red Light 2.6.8 contract, exact
`settings(setting_id, setting_type, setting_default, setting_value)` text
schema, WAL mode, and SQLite integrity. All ten optional reviewed fields were
captured and verified: `mdblist.refresh`, `mdblist.token`, `mdblist.user`,
`pm.account_id`, `pm.token`, `tb.token`, `trakt.expires`, `trakt.refresh`,
`trakt.token`, and `trakt.user`. No required fields were missing. Ordinary,
generated, cache, and unrelated rows were not captured.

Overlay ID: `family-room-redlight-2.6.8`. Protected storage:
`/Users/eengert/Library/Application Support/Build Manager/addon_data/script.build.manager/private_overlays/family-room-redlight-2.6.8.json`.
Overlay fingerprint:
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`.
Frozen software fingerprint:
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.

The source remained read-only: no apply operation, Red Light/Kodi setting
write, database mutation, restart/stop, add-on operation, repository refresh,
Build Manager reconciliation, Backup Pro operation, or device installation
was performed. The temporary raw database and locally generated sidecars were
deleted and verified absent. The secret-blind worktree scan reported
`leak_detected=false`.

Validation passed focused tests **27/27** and **386/386**; no production/test
code changed, so the full suite was not rerun. `git diff --check` must pass
before the tracking commit.

Frozen software is **COMPLETE**, the private overlay is **COMPLETE**, captured
desired state is **COMPLETE**, and real-device frozen installation remains
**NOT VALIDATED**.

### Smallest next step

Supervisor review of the sanitized BM-017D capture result. Do not apply the
overlay to Family Room or any destination device, and do not start another
milestone.

## BM-017C — structured private-resource foundation integrated and synchronized

Codex is synchronized with protected `matrix` through `2374ee5` by a normal
merge; matrix remains neutral, the worker identity remains `codex`, and no
other worker branch was modified. BM-017C is complete and supervisor-approved
on matrix. Its clean matrix-side substantive commit is `dce8276`, reconstructed
from worker implementation commit `8ba7bdc`; worker tracking metadata was
excluded from that substantive integration.

BM-017C provides a generic structured-private-resource protocol, exact Red
Light schema/version declarations, a quiesced row-scoped WAL adapter,
protected-overlay coexistence, restart-safe metadata, fake SQLite fixtures, and
sanitized documentation. It did not retrieve the real Family Room `settings.db`,
capture private values, create the real overlay, write to Family Room, install
on a real device, or start BM-017D/retention/scheduling.

Validation on the integrated matrix tree: structured-resource **27/27**,
focused regression group **386/386**, full suite **1604/1604**, and
`git diff --check` passed.

### Smallest next step

Stop after synchronization. Any real Red Light private capture is a separate
BM-017D authorization and must not be inferred from this foundation.

## BM-017B — Private overlay capture blocked by opaque Red Light state

BM-017B performed the authorized narrow read-only Family Room inventory using
paired-device `devicectl` against the Kodi app-data container. Device listing,
names-only relevant-directory inspection, and specifically justified metadata
and source receives succeeded. No source-profile write, Kodi control, add-on
state change, restart, repository operation, database write, Backup Pro
operation, reconciliation, installation, or unrelated profile scrape occurred.

The installed Red Light `2.6.8` source exposes a custom settings layer and its
`databases/settings.db` table is the owner of the observed private provider
state. Secret-blind schema/presence/default comparison found non-default
private-state fields in the `mdblist`, `pm`, `tb`, and `trakt` categories,
including refresh/token/account/user/expiry field IDs. Red Light's Kodi
`settings.xml` exposes only informational/action entries, so these values
cannot be represented by BM-017A's typed Kodi-setting backend. The database
also mixes ordinary preferences and generated/runtime state; copying or
replacing the whole file is explicitly unsafe.

MyAccounts `2.1.2` source exposes provider-auth setting operations for several
providers, but its Family Room addon_data directory was empty and no separate
user-state file was identified. POV and Umbrella source also contain provider
integrations, but no duplicate owner was inferred from the file evidence.

Result: frozen software capture remains **COMPLETE** with software fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
Private overlay capture is **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; no typed
declarations, required/optional overlay entries, overlay file, or overlay
fingerprint were created. Captured desired state is **INCOMPLETE** and
real-device frozen installation remains **NOT VALIDATED**.

The final targeted secret-blind leak scan returned `leak_detected=false` for
repository files. All raw received database/source/metadata evidence was
deleted from the disposable directory and its absence was verified. No real
private value appears in tracking, documentation, logs, results, or Git.

### Smallest next step

Design and review a dedicated structured private-resource boundary for Red
Light's mixed settings database, including field-level ownership and safe
lifecycle/application semantics. Do not add an arbitrary file copier, capture
real private state again, or begin destination installation without that
review.

## BM-017A — Private/auth overlay foundation complete

BM-017A is complete on `agent/codex`. The worker first synchronized current
`origin/matrix` by normal merge (`a1ceab1`); the protected matrix and other
worker branches were not modified.

The implementation adds explicit public `config.private_settings`
declarations and a version-1 local private overlay with typed values,
required/optional ownership, sensitivity classification, build/overlay
identity, canonical JSON fingerprinting, and duplicate/undeclared/type/
completeness validation. Storage is profile-local, atomically written, and
permission-restricted (`0700` directory / `0600` file where supported). It is
intentionally restrictive plaintext: there is no encryption-at-rest claim,
custom cryptography, cloud sync, or secret-bearing public artifact.

The existing BM-015 `ConfigurationManager` remains the sole typed settings
backend. Build Manager applies public settings first and validated private
settings second, with typed authoritative read-back. Private values are not
returned in results, errors, logs, manifests, packages, `.agent/*`, or
BM-020/BM-022 durable transactions. Only overlay ID, fingerprint, and
required flag cross restart/frozen-install boundaries. Required absence and
identity drift fail closed; optional absence is a safe no-op.

Tests passed: private-overlay **14/14**, combined BM-015/BM-020/BM-022
regressions **588/588**, full suite **1591/1591**, and `git diff --check`.
Disposable fixtures used temporary storage only. No real Family Room private
files, credentials, Kodi profile, Apple TV, or other device were accessed.
The software foundation is ready for a separately authorized capture/import
workflow; real private capture and real-device frozen installation were not
performed. BM-017A is complete, BM-017 remains scoped to future authorized
capture/application work, and no next milestone was started.

### Smallest next step

Supervisor review the BM-017A foundation and explicitly authorize any future
private-state capture/import task. Do not access the real Family Room profile
or begin another milestone from this handoff.

## BM-022V-R — Family Room exact-artifact blocker resolution complete

BM-022V-R is complete on `agent/codex`. The BM-022V checkpoint was published
first as `f5a4415` to `origin/agent/codex`. No BM-017 or other milestone was
started, and the Family Room remained read-only.

### Resolution

Kodi Omega source supports a package with one safe top-level folder whose
`addon.xml` declares the requested add-on ID, even when the folder name differs
from that ID. Kodi stages the extracted contents under the requested ID. The
previous Build Manager root-equality check was unnecessarily strict.

The generalized correction is limited to `resources/lib/artifacts.py` and the
shared staged extraction helper in `resources/lib/repository.py`. It accepts
one safe root and keeps exact `addon.xml` ID/version authority while preserving
rejection of multiple roots, traversal, symlinks, missing/malformed XML, ID
mismatch, and version mismatch. No package bytes are rewritten, and there is
no add-on-specific exception.

The exact official Kodi Omega Dropbox package was recovered and imported:

- ID/version: `script.module.dropbox` `10.3.1+matrix.1`
- SHA-256: `5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6`
- Size: 667,538 bytes
- Source: recorded official Kodi Omega mirror URL

The exact cached Robotocjksc ZIP now validates unchanged as
`resource.font.robotocjksc` `0.0.3`; its alternate safe root is normalized only
during staged extraction. A temporary proof confirmed the final target has
the original `addon.xml` and payload bytes.

### Final capture state

- Required frozen software capture: **COMPLETE**.
- Candidate manifest: 37 nodes; 67 required edges; 3 optional edges; zero
  required missing artifacts.
- Exact artifact-backed nodes: 30; captured artifact bytes: 194,254,227.
- Candidate fingerprint:
  `sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
- Optional YouTube remains incomplete because installed
  `7.4.4+unofficial.2` differs from cached `7.4.4`; it does not block required
  capture completion.
- Ready-to-use configuration: **BLOCKED_BY_BM017 / INCOMPLETE**. Private/auth
  state was not captured.

Focused tests passed **331/331**; full suite passed **1577/1577**; and
`git diff --check` passed. No Family Room installation, update, enable/disable,
repository refresh, restart, settings write, database write, or reconciliation
was performed. Codex usage values remain unavailable.

### Smallest next step

Supervisor review the BM-022V-R correction and, separately, authorize any
future BM-017 private-state work. Do not install the candidate build or begin
another milestone from this handoff.

## BM-022V — Real Family Room frozen-capture validation complete (initial checkpoint)

BM-022V is complete on `agent/codex` as read-only evidence validation. No
production code or documentation was added; no source Kodi profile, database,
settings, package cache, or device state was mutated; and no next milestone
was started.

The authorized `Addons33.db` was received into temporary evidence storage and
parsed with a read-only SQLite connection. The requested `guisettings.xml`
could not be received because no file with that name exists at the authorized
path or elsewhere in the Kodi app-data Library; no alternate file was used.
The raw database was deleted after parsing. The candidate FrozenManifest v1
was generated only in disposable temporary storage with fingerprint
`sha256:8807efedc3814b3c460761b8dc44466ae4e6d6f5dbe099f1a3cfb0a1a192660b`.

Evidence summary:

- Graph: 37 observed nodes; 70 edges; 67 required and 3 optional.
- ArtifactStore: 28 exact validated artifacts, 28 unique identities,
  141,987,267 unique bytes, disposable only.
- Software capture: **INCOMPLETE**, blocked by two required exact artifacts:
  `script.module.dropbox` `10.3.1+matrix.1` and
  `resource.font.robotocjksc` `0.0.3`.
- The Robotocjksc cached ZIP is malformed (`resource.font.robotcjksc` top-level
  directory) and was not repaired, renamed, or repackaged.
- Optional YouTube artifact evidence is incomplete; optional metadata remains
  unresolved for `script.module.inputstreamhelper` and
  `script.module.pysocks`.
- The database showed captured add-ons enabled except
  `service.skinsettings.backup` (disabled reason `1`). No explicit broken
  state is represented in the inspected database schema, so none is claimed.
- `general.addonupdates` is **UNAVAILABLE** because the authorized settings
  file was absent.
- Ready-to-use configuration is **INCOMPLETE / BLOCKED_BY_BM017** because
  private/authenticated configuration was not captured.

Validation: relevant BM-021B artifact/frozen/frozen-install tests **30/30**;
`git diff --check` passed. Codex usage values are unavailable under the
project's documented rules. BM-017, retention, pinning, scheduling, freshness
UI, and real frozen installation were not started.

### Smallest next step

Supervisor review the BM-022V evidence report and separately authorize any
future exact-artifact recovery or BM-017 private-state work. Do not install the
candidate build or begin another milestone from this handoff.

## BM-022 — Frozen Build Installation and Transaction Lifecycle complete

BM-022 is complete on `agent/codex` in substantive commit `27f4215`. It is
not integrated to `matrix`; protected matrix remains `7ab49f1`. No worker
branch other than `agent/codex` was touched, and no next milestone was
started.

### What was done

- Added strict schema-v1 frozen-manifest loading and validation, including
  complete-capture status, exact artifact-store SHA-256/size/ZIP identity,
  system-dependency boundaries, edge validation, and deterministic
  topological installation order.
- Added a durable profile-local frozen transaction with atomic writes and
  locking; phases cover preparation, exact software installation,
  configuration, restart handoff, resume, validation, completion, and
  `needs_attention` recovery.
- Extended the existing updater guard so the original global policy is
  durably captured before mutation, `NEVER_CHECK` can be reasserted after a
  process restart, and the original policy can be restored from durable state.
- Reused the reviewed BM-011 staged-package boundary: validated ZIP content
  is atomically staged, registered with `UpdateLocalAddons`, and verified at
  the exact requested version; wrong-version replacement/downgrade is rejected.
- Added BM-020 startup precondition/resume integration and a read-only VFS
  fallback for installed dependency metadata when Kodi cannot open a freshly
  discovered disabled add-on handle.
- Added the BM-022 design document, a real ZIP/ArtifactStore disposable
  fixture, focused tests, and the `validate-frozen-install` command.

### Live and test evidence

The disposable BM-022 gate passed completely in `.kodi-test`: exact artifact
hash selection; repository → dependency → ordinary add-on ordering; durable
BM-020 handoff; restart-time updater reassertion before BM-020 startup;
existing Build Manager configuration; exact final state; original updater
policy restoration; clearing of BM-022 and BM-020 transactions; and real Kodi
profile immutability. The proof uses generated disposable runtime state only;
pristine first-ever provisioning of arbitrary add-ons is not claimed.

Focused regressions passed **639/639**. The full suite passed **1573/1573**.
`git diff --check` passed. Codex usage start/end/delta are `unavailable` per
the project rule; no telemetry was fabricated.

### What was not done

BM-022 has not been integrated to protected `matrix`. BM-017 remains deferred.
No retention, pinning, scheduling, freshness enforcement, garbage collection,
Apple TV action, real-profile mutation, or next milestone was started.

### Smallest next step

Supervisor review the BM-022 substantive commit and, if approved, perform the
normal clean integration onto protected `matrix` without copying worker
metadata wholesale.

## BM-021B capture core complete

BM-021B is complete and integrated on protected `matrix`; this worker is
synchronized, idle, and ready for BM-022. BM-021A is complete and its findings remain in
`docs/FROZEN_BUILD_CAPTURE.md`.

Implementation commit: `89525bd`. The implementation is limited to exact artifact capture, dependency-aware
inventory, manifest v1, deterministic incomplete results, and the independent
global updater guard. It does not install frozen builds or implement retention,
pinning, scheduling, freshness UI, garbage collection, BM-017, or device work.

Verified: Kodi 21.1 public add-on metadata exposes identity, version, type,
path, enabled/installed/broken state, and declared dependency edges, but not
provenance or per-addon update policy. The disposable profile's internal
database showed origin, package-cache, repository, and update-rule evidence;
the cache was bounded and did not contain every installed third-party package,
and some cached versions differed from installed versions. AF3 3.2.19's
closure was 21 nodes (18 third-party, 3 Kodi/system), with BM-020A dependency
health **18/18**. BM-011 repository/add-on validation passed **19/19**.

Decision: exact version recovery is feasible only from a verified immutable
artifact, an exact cache hit, or a still-available repository package. A ZIP
made from an installed directory is rejected as a reproducible artifact
fallback. The BM-021B manifest carries SHA-256 identity, exact ID/version,
dependency edges, enabled state, provenance confidence, and capture status;
system dependencies are constraints rather than frozen artifacts. Kodi's
global updater setting was proven through the supported Settings API; the
`NEVER_CHECK` value did not persist across restart, but deterministic guard
reassertion succeeded before capture mutation and no scheduled updater activity
appeared while guarded.

The representative disposable capture correctly returned `incomplete_artifact`
because no exact package-cache ZIP was available after reset; no installed
directory was zipped and no COMPLETE result was claimed. Evidence: BM-021B
focused tests **21/21**; combined focused tests **370/370**; full suite
**1557/1557**; updater-guard disposable proof passed. `NEVER_CHECK` did not
persist across restart, but deterministic reassertion succeeded before capture
mutation and original-policy restoration survived restart. BM-022 and BM-017
have not started. The real Kodi profile, Apple TV, devices, and other workers
remain untouched.

## BM-020C — post-restart resume orchestration complete

BM-020C is complete, supervisor-approved, and integrated on protected `matrix`.
The worker is synchronized to the integrated state; its substantive matrix
commits are `81ba44b` and `091cfe9`.

The implementation adds the read-only `BuildManager.preview()` seam,
`resources/lib/resume.py`, expected-state transaction transitions and bounded
status diagnostics, automatic `service.py` delegation for `READY_FOR_RESUME`,
focused resume tests, and the disposable `validate-build-manager-resume` gate.

The coordinator re-reads the persisted record, verifies a new session,
previews the desired state before mutation, requires an exact fingerprint
match, atomically claims `RESUMING`, and runs the normal BuildManager
reconciliation from the beginning. It clears only an unchanged `RESUMING`
record after success + matching final fingerprint + `NONE`. Failures,
fingerprint drift, repeated restart requirements, claim conflicts, and clear
conflicts fail closed into preserved `NEEDS_ATTENTION` state. Existing
`RESUMING` and `NEEDS_ATTENTION` records are not retried automatically.

Evidence: focused tests **465/465**, disposable BM-020C gate **8/8** with AF3
closure **18/18**, full suite **1536/1536**, and `git diff --check` clean. The
live gate proved automatic service-driven resume after a harness-only Kodi
restart, normal reconciliation with matching fingerprint and
`RestartRequirement.NONE`, automatic transaction clear, all 16 managed AF3
settings, no second handoff, and later `NO_TRANSACTION`. The unmanaged AF3
probe is covered by the BM-020A gate because this runtime normalizes that
schema entry across process restart. The real Kodi profile, Apple TV, and all
devices remained untouched.

BM-020C and BM-020 overall are complete. Current supported platforms still
require a manual full-Kodi restart; Build Manager does not automatically
relaunch Kodi. BM-017 and family-room distribution/source work remain
deferred. The next step is the BM-021A audit documented above.

## BM-020C1 — typed capability model and manual restart handoff complete

BM-020C1 is complete and integrated on protected `matrix`; its substantive
implementation commit is `bcaf2ca` (worker implementation `a6bf902`). The implementation adds
`resources/lib/restart_coordinator.py`, focused coverage in
`tests/test_restart_coordinator.py`, the disposable
`validate-build-manager-manual-restart` gate, and the BM-020B/C1 transaction
documentation.

The capability resolver maps macOS, Android/Shield, Fire OS, Apple TV/tvOS,
and unknown platforms to `MANUAL_APP_RESTART_REQUIRED`. A successful typed
`KODI_RESTART` result creates and read-backs `AWAITING_RESTART` with attempt
count `0`, returns `MANUAL_RESTART_REQUIRED`, and leaves Kodi running. Failed
reconciliation and `NONE` are fail-closed/no-transaction paths. A matching
same-session call reuses the durable record without a second reconciliation;
a changed session is `READY_FOR_RESUME` with count `0`, while BM-020C resume is
not implemented. Automatic capability selection fails closed because no
approved automatic adapter exists.

Evidence: focused BM-020C1/BM-020B/BM-020A/BM-019 tests **63/63**,
disposable manual gate **8/8**, full suite **1517/1517**, and
`git diff --check` clean. The gate used the real BM-020A fixture and
fingerprint, with only the restart requirement synthesized to exercise this
contract. It used only `.kodi-test`; the real Kodi profile, Apple TV, and all
devices remained untouched. The gate also proved AF3's disposable dependency
closure, same-process manual behavior, new-session classification, no resume,
and explicit clear.

Remaining BM-020C work is pre-resume fingerprint validation, `RESUMING`,
resumed reconciliation, success clear, restart-loop prevention, and recovery
after resume failure. Do not begin that work, BM-017, or device work as part
of this handoff. The smallest next step is supervisor direction on the later
resume contract.

## BM-020C audit stop — production restart primitive not established

BM-020C was started on Codex and stopped at its mandatory read-only restart
mechanism audit before the later BM-020C1 capability/manual-handoff work.
That audit remains historical context; the integrated BM-020C1 endpoint does
not claim that resume/re-entry is complete.

Kodi Omega's official built-in reference lists `RestartApp` as implemented
only under Windows and Linux. `Quit` is an application exit, not an automatic
relaunch. JSON-RPC provides quit/restart notifications, not a supported
add-on/Python operation that guarantees a new Kodi process. Kodi's Android
source contains internal restart-exit handling, but that does not establish a
public add-on/Python restart contract; no equivalent supported primitive was
established for macOS, Fire OS, Shield, or Apple TV/tvOS.

The required BM-020C lifecycle cannot safely claim a new session without a
genuine new Kodi process. Host shell/process management, GUI automation,
`System.Exec`, or a `Quit` plus assumed external relaunch would violate the
task boundary. The disposable harness may control Kodi externally, but that
cannot substitute for the missing production mechanism.

Recommended smallest next step: supervisor approval of an explicit platform
capability model and relaunch authority. Until then, do not add a restart
coordinator, alter BM-020A/B, or run the BM-020C process-level gate.

BM-020C and BM-020 overall remain incomplete. BM-017, the remaining resume
implementation, and all device/family-room work remain deferred. The real Kodi
profile and devices remain untouched.

## BM-020B complete and synchronized on Codex

BM-020B is complete and integrated on protected `matrix`; the substantive
commit is `f3ccf2a`. The implementation stores only a versioned safe
`ReconcileRequest`, desired fingerprint, typed restart requirement, originating
Kodi session UUID, phase, and bounded diagnostics under the Kodi profile.
Writes are validated and atomic; locking uses OS-backed `fcntl.flock` and fails
closed if unavailable. Kodi's global home-window property supplies a process
session identity, and `service.py` performs one startup classification pass.

The service fast path reports no transaction without reconciliation. Same-
session `AWAITING_RESTART` remains intact and ineligible for resume. A
different Kodi process is classified `READY_FOR_RESUME` while the transaction
remains durable for BM-020C. Corruption, unsupported versions, invalid fields,
and persistence/lock failures fail closed; clear is explicit only.

Disposable BM-020B validation passed 9/9 across an external Kodi stop/relaunch;
the service ran automatically in both processes, distinguished session IDs,
and never restarted Kodi or invoked `BuildManager.reconcile()`. Focused
transaction/session/service tests passed 32/32, the full suite passed
1504/1504, and `git diff --check` passed. Codex is synchronized/idle/ready
for BM-020C; BM-020C, BM-017, and family-room distribution/source work remain
outside scope.

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

Codex worker synchronization completed by normal merge from protected matrix;
the worker remains idle/ready for BM-020C and the external active-worker
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
