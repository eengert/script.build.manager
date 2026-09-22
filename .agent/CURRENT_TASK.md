# Current Task

## BM-017C — Structured Private Resource Foundation

**Status**: Active on `agent/codex` after normal synchronization with current
protected `matrix` tip `6bd927c`. BM-017B is complete and supervisor-approved
with result **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**.

BM-017C is limited to non-private Red Light `2.6.8` source/frozen-artifact
audit, a generic structured-private-resource foundation, a narrowly scoped
Red Light schema/adapter, fake SQLite fixtures, disposable validation, and
sanitized documentation. It must not retrieve the real Family Room
`databases/settings.db`, capture private values, create the real overlay,
write to Family Room, install to a real device, or begin retention, pinning,
scheduling, or freshness work.

## BM-017B — Private overlay capture blocker integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

BM-017B result: **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**. Red Light `2.6.8`
requires private/auth state in a mixed `databases/settings.db` resource outside
the BM-017A typed Kodi-setting boundary. The sanitized read-only evidence is
recorded in `docs/BM017B_PRIVATE_CAPTURE.md`; no private values were captured,
no raw database was retained, no arbitrary private-file copier was added, and
the Family Room source remained read-only. Frozen Family Room software remains
**COMPLETE**, captured desired state remains **INCOMPLETE**, and real-device
frozen installation remains **NOT VALIDATED**.

BM-017C has not started. The next authorized step is the separate structured
private-resource foundation on `agent/codex`; it must use non-private Red Light
source/frozen artifacts and fake fixtures only, without retrieving the real
Family Room `settings.db`.

## BM-017A — Private/auth overlay foundation integrated

**Status**: Blocked by unsupported private state on `agent/codex`; current
`origin/matrix` was merged normally before work began. BM-017A is complete and
integrated. The required Family Room software capture remains **COMPLETE**;
private overlay capture is **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**;
captured desired state is **INCOMPLETE**; real-device frozen installation
remains **NOT VALIDATED**.

Scope is limited to relevant add-on schemas/source ownership review, approved
read-only Family Room file listing/receive, secret-blind extraction of only
declared private settings, protected local overlay creation, structural
validation, and sanitized evidence. No source-profile writes, Kodi settings
changes, add-on state changes, restarts, repository operations, database
writes, Backup Pro operations, reconciliation, installation, or broad profile
scraping are authorized.

No raw private values may appear in terminal output, logs, errors, reports,
Git, `.agent/*`, documentation, public manifests, or durable transactions.
Temporary raw evidence must stay outside the repository with restrictive
permissions and must be deleted after validated extraction. Opaque private
state that cannot be represented by BM-017A typed settings is an architectural
blocker, not a reason to add arbitrary file copying.

The non-secret inventory and narrow read-only inspection completed. Red Light
owns a mixed opaque `databases/settings.db` settings layer; secret-blind
comparison found non-default provider/account fields, but Red Light's Kodi
settings schema does not expose them through BM-015's typed backend. MyAccounts
source exposes provider-auth setting operations, but its addon_data directory
was empty; no duplicate owner was inferred. No private declarations or overlay
were created, no raw values were emitted, and all temporary evidence was
deleted. A future dedicated structured private-resource design is required
before capture/import can proceed.

## BM-017A — Private/auth overlay foundation complete

**Status**: Complete on `agent/codex`; synchronization to the current matrix
tip was performed by normal merge as `a1ceab1`. No matrix, Claude, or
Antigravity branch was modified.

BM-017A adds the secure application foundation without accessing real Family
Room private state. Public manifests now declare explicit private targets,
typed values, required/optional ownership, sensitivity class, and an overlay
identity. The separate version-1 overlay is canonicalized and fingerprinted;
private values remain outside public manifests, packages, artifacts, logs,
`.agent/*`, and durable BM-020/BM-022 records. The initial storage backend is
restrictive profile-local plaintext JSON with atomic writes, `0700` directory
and `0600` file permissions where supported; no encryption-at-rest claim or
custom cryptography is made.

Private application reuses the existing BM-015 typed backend rather than
creating a parallel settings engine. Public configuration is applied first,
then validated private settings through the same typed read/write/read-back
path. Undeclared, duplicate, wrong-type, missing-required, mismatched-build,
malformed, and fingerprint-drift cases fail closed before private mutation.
Results and restart/frozen-install transactions carry only safe overlay
identity/fingerprint/required metadata. Optional absence is a safe no-op;
required absence is `PRIVATE_OVERLAY_REQUIRED`.

Validation: new private-overlay tests **14/14**; BM-015/BM-020/BM-022
regression group **588/588**; full suite **1591/1591**; and
`git diff --check` passed. The disposable fixtures used temporary profile
storage and a fake typed backend. No real Family Room private files,
credentials, Kodi profile, Apple TV, or other device were accessed or
mutated. BM-017A provides software ready-to-use support pending a future
explicit capture/import workflow; real private capture and device frozen
installation remain unvalidated. No next milestone was started.

The smallest next step is supervisor review and authorization of any future
private-state capture/import work. Do not infer that authorization from this
foundation task.

## BM-022V-R — Family Room exact-artifact blocker resolution complete

**Status**: Complete on `agent/codex`; BM-022V remains complete. No BM-017 or
other milestone was started, and the Family Room remained strictly read-only.
The approved BM-022V-R substantive endpoint was integrated on protected
`matrix` as `31b8f9d`; this worker retains its own metadata and is now
starting BM-017A.

The BM-022V checkpoint was published first as `f5a4415` to
`origin/agent/codex`. Kodi Omega source confirms that native ZIP installation
requires one safe top-level folder and a valid `addon.xml`, but does not
require that folder name to equal the add-on ID. Kodi loads the descriptor from
the sole folder and stages its contents under the requested add-on ID
directory. Build Manager's previous root-equality check was therefore too
strict for this generalized safe case.

The smallest production correction now accepts exactly one safe top-level root,
uses the `addon.xml` ID and exact version as authority, and normalizes that
root's contents into the final requested add-on directory during staged
extraction. Multiple roots, traversal, symlinks, missing or malformed
`addon.xml`, ID mismatch, and version mismatch remain fail-closed. No package
bytes are rewritten. There is no add-on-specific exception.

The exact official Kodi Omega `script.module.dropbox` `10.3.1+matrix.1`
package was recovered from the recorded Kodi mirror URL, validated, and
immutably imported. SHA-256 is
`5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6`, size
667,538 bytes. The unchanged cached Robotocjksc ZIP also validates as the
exact `resource.font.robotocjksc` `0.0.3` artifact despite its safe alternate
root `resource.font.robotcjksc`; a temporary extraction proof placed its
original bytes under the final add-on ID directory.

The rerun candidate FrozenManifest v1 is **COMPLETE** for required software:
37 nodes, 67 required edges, 3 optional edges, zero required missing
artifacts, 30 exact artifact-backed nodes, 194,254,227 captured artifact
bytes, and fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
The optional YouTube node remains incomplete because installed
`7.4.4+unofficial.2` is not the cached `7.4.4`; it does not block required
capture completion. Ready-to-use configuration remains **BLOCKED_BY_BM017 /
INCOMPLETE** because private/authenticated state was not captured.

Focused artifact/repository/add-on/frozen tests passed **331/331**. The full
Build Manager suite passed **1577/1577**. `git diff --check` passed. Codex
usage start/end/delta are unavailable; no telemetry was fabricated.

## BM-022V — Real Family Room frozen-capture validation complete (initial checkpoint)

**Status**: Complete on `agent/codex`; this was a read-only evidence and
validation task. No production code, source-profile, package-cache, database,
settings, or device mutation occurred, and no next milestone was started.

The authorized Family Room evidence scope was respected. `Addons33.db` was
received into disposable temporary storage and parsed through a read-only
SQLite connection for installed identity, enabled state, disabled reason, and
recorded origin. The requested `guisettings.xml` was not present at the
authorized path or elsewhere in the Kodi app-data Library when checked by a
filename-only filtered listing; it was not retrieved or substituted. The raw
database copy was deleted immediately after parsing, and no raw private
evidence was committed or retained in project tracking.

The observed candidate graph contains 37 nodes and 70 dependency edges (67
required, 3 optional): 30 captured third-party nodes, two unresolved optional
metadata nodes, and five runtime/system nodes. The diagnostic FrozenManifest v1
fingerprint was `sha256:8807efedc3814b3c460761b8dc44466ae4e6d6f5dbe099f1a3cfb0a1a192660b`.
The temporary ArtifactStore contains 28 exact validated artifacts, 28 unique
SHA-256 identities, and 141,987,267 unique bytes; it is disposable evidence,
not a repository artifact.

Frozen Family Room software capture is **INCOMPLETE**. The two blocking
required artifacts are the exact installed `script.module.dropbox`
`10.3.1+matrix.1` artifact and the exact installed
`resource.font.robotocjksc` `0.0.3` artifact. The cached Robotocjksc ZIP has
the malformed top-level directory `resource.font.robotcjksc` and was not
renamed or repackaged. The optional YouTube artifact is also incomplete, while
the unresolved optional metadata findings are `script.module.inputstreamhelper`
and `script.module.pysocks`.

The database showed all observed captured add-ons enabled except
`service.skinsettings.backup`, which was disabled with disabled reason `1`.
`Addons33.db` has no explicit broken-state table or column, so broken status is
not claimed from this evidence. The `general.addonupdates` source value is
**UNAVAILABLE** because the authorized settings file was absent. Ready-to-use
configuration is **INCOMPLETE / BLOCKED_BY_BM017**: private/authenticated
configuration was not captured, and no one-click Family Room readiness claim
is made. BM-017, retention, pinning, scheduling, freshness UI, and real frozen
installation remain deferred.

Relevant BM-021B artifact/frozen/frozen-install tests passed **30/30** and
`git diff --check` passed. Codex usage start/end/delta are unavailable; no
telemetry was fabricated. The worker remains clean and matrix remains
`f1c23eb`.
## BM-022 — Frozen Build Installation and Transaction Lifecycle integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; this Codex worker is synchronized, idle, and ready for the next
approved milestone. The reviewed substantive integration commit is `56ea26a`, reconstructed from worker
commit `27f4215`. Worker `.agent/*` metadata was excluded.

BM-022 installs only complete BM-021B manifests backed by immutable exact
artifacts. It validates SHA-256, size, ZIP identity, exact add-on ID/version,
dependency edges, system boundaries, and deterministic topological order. It
reuses the reviewed BM-011 staged-package boundary with atomic staging,
`UpdateLocalAddons`, exact-version verification, and fail-closed
replacement/downgrade behavior.

The durable frozen-install transaction captures the original global updater
policy before mutation, owns `NEVER_CHECK` through installation,
configuration, restart/resume, and final validation, reasserts and verifies
the guard before BM-020 startup mutation, restores the original policy only
after successful final validation, and preserves diagnosable
`NEEDS_ATTENTION` state on failure. Existing Build Manager configuration and
BM-020 restart/resume remain the owners of those operations. Explicit abandon
restores policy and clears the transaction without claiming software rollback.

Integrated validation was rerun: focused BM-022/BM-021B/BM-020/dependency/
repository regressions **639/639**; disposable `validate-frozen-install`
passed; full suite **1573/1573**; and `git diff --check` passed. The live
proof used only `.kodi-test` and did not claim complete real Family Room
capture/install or real-device validation.

BM-020, BM-021A, BM-021B, and BM-022 are complete. BM-017 remains deferred;
no next milestone was started.

## BM-021B — Frozen artifact capture core integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

The reviewed BM-021B substantive commit was reconstructed from the approved
worker endpoint as `2ee040c` (`feat(BM-021B): add frozen artifact capture
core`). It adds the SHA-256 content-addressed, atomic write-once artifact
store; exact ZIP validation and read-back; typed installed inventory with
direct/transitive dependency edges and the `xbmc.gui`, `xbmc.python`, and
`kodi.resource` system boundary; honest provenance and incomplete-capture
manifest states; exact cache/repository acquisition ordering; and the
supported Settings JSON-RPC updater guard. It does not add frozen installation,
retention, pinning, scheduling, freshness enforcement, or garbage collection.

The disposable proof recorded the AF3 3.2.19 closure as 18 healthy
third-party add-ons plus the system boundary, exact versions and dependency
edges, and an honest `incomplete_artifact` result after the reset had no exact
package-cache ZIPs. No installed directory was zipped, no false `COMPLETE`
claim was made, and no real Kodi profile or Apple TV was accessed. The updater
proof verified read/set/read-back, restart reassertion because `NEVER_CHECK`
does not persist across restart, no observed scheduled updater activity while
guarded, explicit restoration, and restoration after a second restart. A
resumed transaction must reassert and verify the guard before every mutation.

BM-020, BM-021A, and BM-021B are complete. BM-022 has not started; BM-017
remains deferred; family-room source/distribution concerns remain pending.
No next milestone was started.

## BM-021A — Frozen Build Capture audit integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`.

Substantive commit: `b32369e` (`docs(BM-021A): record frozen build capture
audit`). The audit establishes exact reproducible artifact requirements,
verified artifact acquisition priority, bounded/non-authoritative Kodi cache
semantics, rejection of installed-directory zipping, frozen third-party
dependency closure, repository artifact/provenance handling, Kodi's global
three-state updater policy, the absence of a solved per-addon auto-update API,
and a SHA-256 content-addressed immutable artifact-store model. Freshness
checks warn without substituting newer package versions. Updater inhibition
restart/race behavior remains for BM-021B.

BM-021B and BM-022 have not started. BM-020 remains complete and BM-017
remains deferred. Family-room source/distribution concerns are being absorbed
by BM-021/BM-022 and are not independently marked solved.

## BM-020C — guarded post-restart resume integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`.

Substantive integration commits: `81ba44b` (`feat(BM-020C): add guarded
post-restart resume`) and `091cfe9` (`docs(BM-020C): document service readiness
boundary`). Codex worker metadata was excluded.

BM-020C completes the guarded post-restart resume path. Startup accepts only a
new-session `READY_FOR_RESUME` transaction, re-reads and previews the original
request, verifies the desired fingerprint, atomically claims `AWAITING` as
`RESUMING`, runs the normal `BuildManager.reconcile()` path, verifies the final
fingerprint and `RestartRequirement.NONE`, then atomically clears the expected
transaction. Preview, fingerprint, reconciliation, claim/clear conflicts,
exceptions, repeated `KODI_RESTART`, and later `RESUMING` or
`NEEDS_ATTENTION` states fail closed with bounded diagnostics. The service
remains thin: it does not restart Kodi or a host process, and current supported
platforms still require a manual full Kodi restart before automatic resume.

Integrated validation passed focused BM-020C/BM-020B/BM-020C1/BM-020A/BM-019
tests **465/465**, the disposable BM-020C gate **8/8** with AF3 dependency
closure **18/18**, the full suite **1536/1536**, and `git diff --check`.
The gate proved a new session, service-driven automatic resume, authoritative
read-back, final fingerprint equality, `NONE`, no second handoff, later no
transaction, and real Kodi profile immutability. AF3 generated first-run state
was bootstrapped only inside `.kodi-test`; the selected AF3 unmanaged probe is
owned by the BM-020A gate because AF3 normalizes that entry across restart.

BM-020 overall is complete. BM-017 and family-room distribution/source work
remain deferred. No next milestone was started.

## BM-020C1 — typed restart capability model and manual-restart handoff integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; the matrix remains neutral with `active_agent: none`.

Substantive integration commit: `bcaf2ca` (`feat(BM-020C1): add manual restart
capability handoff`). Worker-specific Codex metadata was excluded.

BM-020C1 establishes a typed restart capability seam and conservative platform
policy. macOS, Android/Shield, Fire OS, Apple TV/tvOS, and unknown platforms
resolve to `MANUAL_APP_RESTART_REQUIRED`. A successful typed `KODI_RESTART`
result persists and verifies `AWAITING_RESTART` with
`restart_attempt_count = 0`, returns structured manual guidance, and does not
restart or quit Kodi. Failed reconciliation creates no transaction; `NONE`
completes without one; same-session calls reuse the handoff without a second
reconciliation; and a new session with count `0` is `READY_FOR_RESUME`.
Explicit automatic capability selection fails closed because no approved
production adapter exists.

Integrated validation passed: focused BM-020C1/BM-020B/BM-020A/BM-019 tests
**63/63**; disposable manual handoff gate **8/8**, including AF3 dependency
closure **18/18**; full suite **1517/1517**; and `git diff --check` clean.
The disposable gate used only `.kodi-test`, proved the harness-controlled
process boundary, and confirmed the real Kodi profile remained unchanged.

BM-020 overall remains incomplete. Remaining work is read-only fingerprint
revalidation, `RESUMING` claim, normal BuildManager resumed reconciliation,
success clearing, repeated-restart loop prevention, and resume-failure/
recovery semantics. BM-017 and family-room distribution/source work remain
deferred. No next milestone was started.

## BM-020B — durable restart transaction and startup re-entry foundation integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`. `active_agent` is `none`; matrix remains neutral.

Substantive integration commit: `f3ccf2a` (`feat(BM-020B): add durable restart
transaction foundation`). Worker-only `.agent/*` metadata was not copied.

BM-020B adds a profile-local schema-v1 restart transaction record containing
only the safe request, desired fingerprint, restart requirement, originating
Kodi session UUID, and explicit transaction phase. It uses atomic staged
writes with flush/fsync/replace, read-after-write validation, fail-closed
corrupt or unsupported records, explicit clear, and a nonblocking POSIX
`fcntl.flock` sidecar lock with automatic release. The session UUID is stored
in the Kodi home-window property
`script.build.manager.kodi_session_id`.

The thin `xbmc.service` entrypoint classifies startup only: no transaction,
same-session awaiting restart, ready for resume, needs attention, invalid
transaction, or inspection failure. It does not restart Kodi, reconcile, or
resume work; BM-020C owns those actions.

Validation from this integrated tree: BM-020B transaction tests **32/32**;
the disposable process-boundary gate **9/9**; full suite **1504/1504**; and
`git diff --check` clean. The disposable gate proved service startup on
normal launch, same-session protection, durable state across an external Kodi
restart, ready-for-resume classification, explicit clear, and the returned
no-transaction path. The first gate attempt exposed only a timing race
between JSON-RPC readiness and automatic service execution; the unchanged
retry passed. The real Kodi profile remained read-only and no device or
Apple TV was accessed.

BM-020C and BM-017 remain deferred. Cross-device lock behavior is an
architecture selection for supported POSIX-like Kodi targets, not a live
claim beyond the disposable macOS validation. No next milestone was started.

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
