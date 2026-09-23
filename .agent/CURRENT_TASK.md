# Current Task

## BM-017F — Deferred Activation & Structured-Resource Lifecycle

**Status**: `IMPLEMENTED_PENDING_ALIAS_LIVE_VALIDATION` on `agent/codex`.
Latest alias correction commit: `81e8b2c`; verified import roots were first
implemented in `93be55a3e3a900de488d388c88fbf39aca885869`. The historical
`BLOCKED_RED_LIGHT_REQUESTS_ALIAS_SOURCE_MISMATCH` is corrected offline and
awaits live proof. Red Light's clean-destination lifecycle remains **NOT YET
LIVE-VALIDATED**. macOS BM-023A remains **STILL BLOCKED**; tvOS remains **NOT
VALIDATED**.

### Verified package import context

Red Light's package-owned initialization imports now use the canonical
`<verified plugin.video.redlight>/resources/lib` root derived from the exact
installed source descriptor. The add-on root is not used as the Python root.
The declared module path is checked against `addon.xml`; traversal, symlinks,
missing roots, wrong owner identity, and wrong version fail closed.

The owner context derives Python dependency roots from the transaction's
fingerprinted frozen manifest and exact installed resolution records. The
audited import chain requires `script.module.requests` (2.31.0), with its
frozen transitive module dependencies `script.module.urllib3` (2.2.3),
`script.module.certifi` (2023.5.7), `script.module.chardet` (5.1.0), and
`script.module.idna` (3.10.0). Registry versions and enabled state must match
the exact frozen records. `script.module.pil` and other Red Light dependencies
are not added to the import path because the audited initializer does not
require them.

`verified_addon_import_context` routes known packages only to those verified
roots and blocks host-package fallback. It validates ordinary module origins
and namespace `__path__` locations for `caches` and `modules`, rejects external
collisions, restores `sys.path` and preexisting modules, and removes newly
created owner modules and namespace roots on success or failure. Red Light
continues to load its schema/default declarations and marker setter from the
installed package while the owner remains held disabled; no service, provider,
authentication, or network entrypoint is called.

Module ownership is derived from canonical source paths, not module names.
Ordinary modules use `__file__` or spec origin; namespace packages use every
`__path__` entry. Each path must resolve inside exactly one verified provider
root. Requests compatibility names are limited to its audited 2.31.0 aliases
for `urllib3`, `idna`, and `chardet`. An alias must be backed by the matching
provider in the current frozen dependency closure, sit under the verified
Requests package, and be the same module object as its canonical provider
entry. Host/system packages, missing providers, ambiguous roots, and path or
symlink escapes fail closed. Context-created aliases and controlled modules are
removed on success or failure; preexisting module objects and dictionaries,
`sys.path`, and `sys.meta_path` are restored. A failed ownership check followed
by a same-process retry passes offline.

The source audit of the exact retained Requests 2.31.0 `requests/packages.py`
confirmed its structural alias rule and the three provider names. The frozen
Red Light import fixture reaches `requests.adapters.Retry` from frozen
`urllib3.util.retry` and then passes post-import ownership validation.

### Latest offline alias diagnosis and correction

After the import-root correction, the offline Red Light import reached
`requests.adapters.Retry`; the first ownership rejection was
`requests.packages.urllib3.exceptions`, whose actual source belonged to the
verified `script.module.urllib3` provider. The old prefix-only check required
every `requests.*` entry to originate in Requests. That also left newly created
Requests aliases in `sys.modules` after failure, causing a same-process retry to
fail during preflight.

Commit `81e8b2c` now validates physical provider ownership and canonical object
identity for the three audited aliases, enforces Requests 2.31.0 and verified
dependency-closure membership, and restores the temporary module state. Safe
diagnostics retain `import_failure_category`, `failing_module`, and verified
provider IDs through CONFIGURE transaction status without paths, exception
text, or private values. This remains offline implementation evidence only.

### Resolved pre-correction import diagnosis

The latest supervisor-run disposable result completed `SOURCE_REVALIDATION`,
then failed at `LOAD_INITIALIZER_DECLARATIONS` with
`INITIALIZER_IMPORT_FAILED`; `last_completed_stage` was
`SOURCE_REVALIDATION`. The installed disposable source identifies as
`plugin.video.redlight` 2.6.8; BM-017F's validated artifact digest is
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`.

`RedLightSettingsAdapter._redlight_initializers()` inserts the installed
add-on root into `sys.path`, then first calls
`importlib.import_module("caches.base_cache")`. In the exact installed layout,
`caches/base_cache.py` is under `resources/lib/caches`, and the add-on root has
no `caches` directory. A side-effect-free isolated import probe using the same
root-only path reproduced `ModuleNotFoundError` for `caches`; source inspection
also confirmed that `resources/lib` is the package import root. The latest
persisted Kodi diagnostic contains only the stage/cause, not the exception or
frame, so the source-path reproduction identifies the first failing operation
but does not independently recover a live traceback. The same safe cause can
also be set by the pre-import namespace-collision guard; the live transaction
does not persist enough information to distinguish those branches. A static
scan found no Build Manager source imports of top-level `caches` or `modules`.

The remaining import chain, if that path is supplied, reaches
`modules.kodi_utils` (Kodi API imports), then `caches.settings_cache`, which
imports `modules.http_defaults` and `requests.adapters.Retry`. Red Light
declares `script.module.requests`, whose installed module code is under its
`lib` directory; Build Manager itself declares only `xbmc.python`, so dependency
visibility is a follow-on import-context check. Module-scope inspection found
no database, network, service/thread, migration, or Kodi-property operation
before the failed first import. The `caches` and `modules` directories have no
`__init__.py`; their namespace package objects have no `__file__`, which is why
the pre-correction collision and cleanup logic missed those package roots. The
current context checks their `__path__` locations and cleans them up. No
narrower existing defaults module was found; `resources/settings.xml` has no
setting declarations.

Historical classification for that pre-correction run:
`BLOCKED_RED_LIGHT_IMPORT_PATH_CONTEXT` (architecture verdict A). The
implementation above corrects the missing package root and adds verified,
isolated dependency resolution plus namespace collision handling. This task
did not run Kodi or the lifecycle harness; live confirmation remains pending.
No normal Kodi profile, real device, or private overlay values were accessed.
macOS BM-023A remains **STILL BLOCKED**; tvOS remains **NOT VALIDATED**.

### Historical BM-017F blocker progression

- `BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE` is resolved. The
  retained archive is SHA-256
  `64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`, size
  1,261,957 bytes.
- `BLOCKED_POST_RESTART_REGISTRY_READINESS_BYPASSED` is resolved. BM-022's own
  restart continuation now proves held-disabled registry readiness before
  configuration.
- `BLOCKED_RED_LIGHT_XBMCADDON_LOOKUP_WHILE_HELD_DISABLED` was addressed by
  deriving and revalidating the installed source from the frozen transaction.
- The most recent supervisor-run disposable attempt passed readiness and source
  validation, entered `redlight.settings` initialization, and stopped before
  private apply or activation release. Its latest preserved diagnostic names
  `LOAD_INITIALIZER_DECLARATIONS` and `INITIALIZER_IMPORT_FAILED`; the offline
  source/layout probe narrows the first operation to the missing `resources/lib`
  import root, subject to the live traceback limitation above.
- A later offline probe against the verified installed package roots established
  that the import chain reaches `requests.adapters.Retry`, then fails post-import
  ownership validation on the Requests compatibility alias backed by frozen
  `script.module.urllib3`. Commit `81e8b2c` corrects that provider mismatch and
  alias cleanup. No live rerun was performed.

### Actual initializer map

`RedLightSettingsAdapter.initialize()` in
`resources/lib/redlight_resource.py` now names the actual operations in order:

1. Validate the declared owner/resource/version.
2. Inspect any existing database and verify an already-populated resource.
3. Verify quiescence and activation hold; revalidate the frozen installed-source
   context, then revalidate the source again immediately before helper imports.
4. Import the package-owned schema/default helpers and marker setter.
5. Check the existing resource is empty. For a missing database, load the
   package schema declaration, create `addon_data`, create the database
   directory, open SQLite, set WAL mode, and execute/commit the schema.
6. Recheck the empty-state predicate, build package defaults, and insert rows.
7. Confirm rows persisted and validate the final database/WAL/schema.
8. Publish Red Light's two existing sync markers through its window-property
   helper, then return the same successful result.

Each operation uses a project enum stage. The split directory checks name the
existing recursive path creation boundaries; successful paths still create the
same directories and database content.

### Diagnostic propagation and safety

`ResourceInitializationStage` and `ResourceInitializationCause` in
`resources/lib/private_resource.py` provide allowlisted typed codes. A failure
retains the current `initialization_stage`, deepest
`last_completed_stage`, and typed safe cause while preserving the high-level
`PRIVATE_RESOURCE_INITIALIZATION_FAILED` code and safe owner/resource IDs.

The structured-resource manager carries these fields into the existing action
failure diagnostic. Import ownership errors additionally carry a validated
failure category, Python module ID, and verified provider IDs. The frozen
CONFIGURE handler persists only allowlisted
`action`, `resource_failure`, `owner`, `resource`, `cause`,
`initialization_stage`, `last_completed_stage`, and optional import ownership
tokens in the transaction status message. New optional action-result fields
are omitted for legacy errors, preserving their serialized shape. Exception
text, paths, settings rows, fake secrets, and private overlay values are never
copied into the diagnostic.

### Validation and live boundary

- Focused verified-source, import-context, Red Light resource, private overlay,
  add-on registry, Build Manager, dependency, frozen install/readiness,
  transaction, resume, CONFIGURE diagnostics, and manifest/schema suites:
  **456 passed**.
- Full repository `unittest` suite: **1,756 passed**.
- Project manifest/schema tests: **50 passed**.
- `compileall` over `resources`, `tests`, and `tools`: passed.
- All **7 tracked JSON files** parsed; `git diff --check` passed.
- No Kodi executable or BM-017F lifecycle harness command was run. No normal
  Kodi profile, real device, or real private overlay values were accessed.

Current classification is `IMPLEMENTED_PENDING_ALIAS_LIVE_VALIDATION`.
Both the historical import-path correction and the current Requests alias
correction are implemented and await live proof. Red Light clean-destination
lifecycle remains **NOT YET LIVE-VALIDATED**; macOS BM-023A remains **STILL
BLOCKED**; tvOS remains **NOT VALIDATED**. The supervisor will run the next
disposable validation from normal Terminal.

### Next manual command — supervisor only

Do not run this command from Codex:

```text
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex

python tools/kodi_test.py validate-bm017f-lifecycle \
  --retained-manifest /private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json \
  --artifact-store /private/tmp/bm022v-familyroom.ygB0t5/artifact-store
```

## BM-023A-H — Historical Exact Artifact Recovery

**Status**: Complete with result
`EXACT_YOUTUBE_7.4.4_UNOFFICIAL_2_NOT_RECOVERED`. Public exact-version metadata
was searched before considering packages. No candidate ZIP was downloaded,
imported, substituted, or repackaged.

### Public search and provenance

- The official v7.4.4 upstream release is commit `922cc0d` and publishes the
  normal `7.4.4` package plus `7.4.4+unofficial.1`; it does not publish `.2`:
  <https://github.com/anxdpanic/plugin.video.youtube/releases/tag/v7.4.4>.
- The upstream installation guide lists the normal and `.unofficial.1` ZIP
  variants and names `repository.yt.unofficial` and
  `repository.yt.testing_unofficial`:
  <https://github.com/anxdpanic/plugin.video.youtube/wiki/Installation>.
- The upstream release workflow checks out `master` for official packages and
  `nexus-unofficial` for unofficial packages, runs the repository generator,
  and mirrors generated ZIPs and XML indexes to OSMC stable/testing paths:
  <https://github.com/anxdpanic/plugin.video.youtube/blob/master/.github/workflows/release-development-repository.yml>.
  This identifies a generic packaging path, but not a `.2` source commit or
  build output.
- Current upstream `nexus-unofficial/addon.xml` declares version `7.4.4`, not
  `.2`:
  <https://raw.githubusercontent.com/anxdpanic/plugin.video.youtube/nexus-unofficial/addon.xml>.
- The checked OSMC unofficial-testing package index lists `7.4.4+beta.1` through
  `beta.4` and bare `7.4.4`, with no `.unofficial.2` asset:
  <https://ftp.fau.de/osmc/osmc/download/dev/anxdpanic/kodi/youtube/unofficial_testing/zips/plugin.video.youtube/>.
  The OSMC repository download index exposes repository ZIPs but no historical
  plugin package index:
  <https://ftp.fau.de/osmc/osmc/download/dev/anxdpanic/repositories/>.
- Exact-version and exact-filename searches across public GitHub, OSMC, and
  Panicked references produced no `.2` metadata result. The Panicked repository
  endpoints and Wayback CDX query were inaccessible through the available
  research surface. No exact `addons.xml` entry, package URL, provider checksum,
  public fork/cached package, or `.2`-specific source commit was located.

Therefore no exact artifact could be validated or imported, and no comparison
against upstream `.unofficial.1` was performed. The known retained local ZIP is
still the inexact bare `7.4.4` artifact and was not changed.

### Frozen input validation

The retained manifest and artifact store were left unchanged. The graph reports
37 nodes: 31 installed managed non-system nodes, 1 absent optional node, and 5
system/runtime nodes. The earlier 32 non-system total consisted of 31 installed
nodes plus absent optional `pysocks`; corrected semantics does not change the 37
node graph but no longer treats `pysocks` as an installed artifact requirement.
The manifest contains 30 artifact references, all 30 present in the store;
required and optional edges are 67 and 3. Exactly one installed managed node
lacks its artifact: `plugin.video.youtube` `7.4.4+unofficial.2`.

`script.module.pysocks` remains absent on the source, optional, missing,
disabled, artifactless, and excluded from installation order. YouTube remains
installed, enabled, managed desired software, reached from Umbrella through an
optional edge, and still requires its exact artifact.

The retained manifest still declares `capture_status=complete`, but production
`validate_frozen_manifest` rejects it with
`installed add-on artifact is incomplete for plugin.video.youtube
7.4.4+unofficial.2`. It is not a valid installable complete input. Its
canonical fingerprint remains
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`,
matching the previously recorded private-overlay target fingerprint. The
private overlay itself was not read or changed.

Focused frozen tests passed **25/25**. Matrix BM-023A-R validation passed
frozen capture/manifest/install **25/25**, dependency regressions **147/147**,
full suite **1607/1607**, and `git diff --check`. No production code changed.
Family Room and devices were not accessed; Kodi was not launched; the portable
test profile and private overlay were not touched.

**Smallest next step**: supervisor chooses whether to pursue another archival
source, accept an altered build, explicitly remove YouTube from managed desired
state, or arrange a separately authorized recapture. Keep BM-023A's historical
result `BLOCKED_MISSING_FROZEN_ARTIFACTS`; do not resume installation here.

## BM-023A-R — Frozen input completeness reconciliation

**Status**: Complete with result
`MANIFEST_SEMANTICS_CORRECTED_BUT_ARTIFACT_GAP_REMAINS`. The worker began on
`agent/codex` at `093757bc3ebacbf4c554aea50b5810498d90f7d5`; protected
`origin/matrix` was at the supplied starting SHA
`5a3598f565ad5b0c0164215eeefdf39b54a1d682`. The implementation is committed
as `a8d4b71`, integrated on matrix as `ff5c000`, and recorded by neutral matrix
tracking commit `a51a84d`. Codex is synchronized by a normal merge that
preserves worker history. Claude and Antigravity branches were not changed.

### Completeness semantics

- Every installed non-system node in the frozen desired software graph needs
  an exact artifact, including a node reached only through optional edges.
- An optional dependency absent at capture remains `capture_status: missing`,
  disabled, and artifactless; it does not block completeness and is excluded
  from installation order. System nodes remain artifactless declarations.
- Capture and `validate_frozen_manifest` now enforce the same rule. The parser
  accepts the capture-native empty version/type representation for missing
  nodes and the retained `not-installed` marker; neither becomes package
  identity.
- Schema v1 has no implicit unmanaged/excluded state for an installed node.

### Retained evidence and classifications

The existing candidate at
`/private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json` has 37
nodes and 32 non-system nodes. `script.module.pysocks` is a missing optional
node, disabled and without an artifact. Its only parent is
`plugin.video.youtube`, through an optional edge. The graph contains it because
capture traverses declared optional imports and records dependencies absent
from installed inventory. It needs no artifact and is no longer scheduled.
Before this correction, validation rejected it under the blanket
non-system-artifact rule; the old order builder also included every
non-system node, but no schedule was returned because validation failed first.

`plugin.video.youtube` is installed at `7.4.4+unofficial.2`, desired enabled,
and reached from `plugin.video.umbrella` through an optional edge. It is part
of the managed frozen software state because there is no explicit exclusion
state. The candidate declares no configuration packages; the protected
captured private overlay targets Red Light only. No captured public/private
configuration dependency on YouTube was found. Excluding it would change the
captured enabled software state and remove the add-on from the destination;
specific runtime feature effects were not device-tested. Provenance is
`repository_evidence`; `installed_origin` is only the placeholder `recorded`,
so an exact provider ID is unavailable.

Search stayed within retained local capture evidence and the named protected
Build Manager storage location. The capture directory's `artifact-store`,
`packages`, and `repository-candidates` were checked, along with matching
filenames in the retained `source` and `evidence` directories. No exact
YouTube `7.4.4+unofficial.2` artifact exists in the store or candidates. The
only YouTube ZIP is `packages/plugin.video.youtube.zip`: production ZIP
validation confirms ID `plugin.video.youtube`, embedded version `7.4.4`, SHA-256
`d744e5ba2d2b50924a9fa5624f4d209c2be95b97ef1ad1682cafbed160fb428f`, size
1,093,649 bytes. Validation rejects it for `7.4.4+unofficial.2`. It was not
imported, normalized, or substituted. No public-network lookup or Family Room
recapture was performed.

Production changes are in `resources/lib/frozen.py` and
`resources/lib/frozen_install.py`; regression tests and sanitized contracts
were updated in `tests/test_frozen.py`, `tests/test_frozen_install.py`,
`docs/FROZEN_BUILD_CAPTURE.md`, and `docs/FROZEN_BUILD_INSTALL.md`.

Focused frozen capture/install tests passed **25/25**. The full suite passed
**1607/1607**. `git diff --check` passed. No Kodi instance was launched, the
portable test profile was not modified, and Family Room was not accessed.

**Checkpoint next step**: BM-023A-H is recorded above as
`EXACT_YOUTUBE_7.4.4_UNOFFICIAL_2_NOT_RECOVERED`. The production validator still
rejects the retained input; do not resume frozen installation.

## BM-023A — Isolated macOS frozen-install validation preflight blocked (historical)

BM-023A remains historically complete as a validation task with result
`BLOCKED_MISSING_FROZEN_ARTIFACTS`; BM-023A-R corrects its interpretation of
optional installed versus absent nodes without changing that historical
result.

### BM-023A preflight evidence (historical)

**Status**: Complete as a validation task with result
`BLOCKED_MISSING_FROZEN_ARTIFACTS`. BM-017D tracking was integrated on
protected `matrix` at `5a3598f`, and Codex was synchronized by normal merge
at `bcd0fe5`. Kodi was not launched and the authorized disposable profile was
not mutated.

Read-only validation of the exact candidate manifest at
`/private/tmp/bm022v-familyroom.ygB0t5/candidate-FrozenManifest-v1.json` and
its paired artifact store found software fingerprint
`8ce7d2daf131f6c1bbcdf152c02c15745f9c52eac34480ee43e9f7af093e035`, 37 graph
nodes, and `capture_status=complete`; however, two of 32 non-system nodes are
not installable: `plugin.video.youtube` `7.4.4+unofficial.2` and
`script.module.pysocks` `not-installed`. Only 30 artifacts are present.
`validate_frozen_manifest` therefore fails closed with an incomplete-required-
artifact error. This exact artifact set does not satisfy BM-023A's frozen
install gate. Do not recapture from Family Room or substitute newer packages.

The protected `family-room-redlight-2.6.8` overlay was read via
`PrivateOverlayStore`; typed overlay/resource validation passed, all ten
declared field identifiers were present, and its target fingerprint matches
the frozen software fingerprint. Private values were not displayed. The
existing bundled portable profile contains prior Kodi data, but no cleanup,
wipe, launch, install, reconciliation, or other test-profile mutation was
performed. No ordinary Kodi process enumeration was needed after the frozen
artifact gate failed.

No BM-023A live gate or tests were run. Smallest next step: recover the exact
approved missing frozen artifacts/evidence from existing retained capture
outputs, then rerun read-only manifest validation. If those exact artifacts
are unavailable, stop for supervisor direction. No Family Room recapture,
newer-package substitution, Apple TV access, or next milestone is authorized.

## BM-017D — Real Family Room structured private-resource capture complete

**Status**: Complete and recorded for protected `matrix`; matrix remains
neutral with `active_agent: none`. The captured overlay remains outside Git
in protected local Build Manager storage.

Matrix tracking integration commit: `5a3598f`. Codex was synchronized to that
tip by normal merge before BM-023A preflight began.

Using the explicitly authorized read-only Xcode `devicectl` connection to
`AppleTV - Family Room (4)` and bundle `com.eengert.koditvosnew`, the only
received resource was
`Library/Caches/Kodi/userdata/addon_data/plugin.video.redlight/databases/settings.db`.
The names-only directory check found no `settings.db-wal` or `settings.db-shm`
sidecars, so the authorized main-database snapshot was sufficient. Unrelated
cache database sidecars were not retrieved.

The BM-017C Red Light adapter validated owner/path contract
`plugin.video.redlight`, version contract `2.6.8`, resource
`redlight.settings`, schema `redlight-settings-v1`, exact four-column text
schema, WAL mode, and SQLite integrity. The ten reviewed field-level
allowlist entries were all optional private/auth candidates and were captured
and verified: `mdblist.refresh`, `mdblist.token`, `mdblist.user`,
`pm.account_id`, `pm.token`, `tb.token`, `trakt.expires`, `trakt.refresh`,
`trakt.token`, and `trakt.user`. No required fields were declared or missing;
all 10 optional fields were present. Derived/generated, ordinary preference,
cache, and unrelated rows remained intentionally unmanaged.

The protected overlay is `family-room-redlight-2.6.8` at
`/Users/eengert/Library/Application Support/Build Manager/addon_data/script.build.manager/private_overlays/family-room-redlight-2.6.8.json`,
with fingerprint
`sha256:a82915f7ae6017b497f4c8c16070420b0ab375b180a23a8cac5f9c119d85c295`.
It is protected plaintext with `0600` file permissions; encryption at rest is
not claimed. The overlay is bound to frozen software fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.

No structured-resource apply path was called. No Red Light/Kodi setting,
database, add-on state, repository, device, or source profile was modified.
The raw database snapshot and locally generated SQLite sidecars were deleted
and verified absent. The secret-blind worktree scan reported
`leak_detected=false`.

Focused validation passed structured-resource/private-overlay tests **27/27**
and the focused BM-017A/BM-017C/manifest/build-manager/BM-020/BM-022 group
**386/386**. No production or test code changed, so the full suite was not
rerun. The worker and matrix integration diff checks passed.

Frozen Family Room software is **COMPLETE**; Family Room private overlay is
**COMPLETE**; captured desired state is **COMPLETE**; real-device frozen
installation remains **NOT VALIDATED**. No next milestone was started.

## BM-017C — Structured private resource foundation integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

The reviewed substantive matrix commit is `dce8276`, reconstructed from worker
implementation commit `8ba7bdc`; worker tracking and all worker `.agent/*`
metadata were excluded. BM-017C provides generic structured private-resource
declarations, typed protected-overlay values, explicit field ownership,
secret-safe results, and manifest/schema/resolver/build-manager integration.
The Red Light 2.6.8 adapter is exact-version and exact-schema, requires an
existing WAL database and quiesced runtime, updates only declared string rows
inside a bounded `BEGIN IMMEDIATE` transaction, verifies each row before
commit, preserves unrelated rows, and reports an explicit restart/reload
requirement. It never replaces the mixed database, creates missing state, or
accepts arbitrary SQL, paths, or wildcard fields.

Validation rerun on the integrated tree passed structured-resource tests
**27/27**, the focused BM-017A/BM-017C/manifest/build-manager/BM-020/BM-022
regression group **386/386**, the full suite **1604/1604**, and
`git diff --check`. Tests use fake Red Light SQLite fixtures only; no real
Family Room private database, credentials, Kodi profile, Apple TV, or other
device was accessed or mutated. BM-017B remains complete with historical
result **BLOCKED_BY_UNSUPPORTED_PRIVATE_STATE**; frozen Family Room software
is **COMPLETE**, captured desired state is **INCOMPLETE**, and real-device
frozen installation is **NOT VALIDATED**. BM-017D has not started.

No next milestone was started. The smallest next step is supervisor direction
and separate authorization for BM-017D's real private-state capture work.

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

BM-017C is complete and integrated above. BM-017D is complete; its sanitized
capture state is recorded at the top of this file. BM-023A is now in preflight.

## BM-017A — Private/auth overlay foundation integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`.

The reviewed substantive matrix commit is `321fee8`, reconstructed by
cherry-picking worker implementation commit `ebd4c61`. The worker tracking
commit and all worker `.agent/*` metadata were excluded. BM-020, BM-021A/B,
BM-022, and BM-022V/BM-022V-R remain complete. Required Family Room frozen
software capture is **COMPLETE**; ready-to-use configuration remains
**PENDING REAL PRIVATE OVERLAY CAPTURE / IMPORT**; real-device frozen
installation remains **NOT VALIDATED**.

BM-017A provides explicit public private-setting declarations with target
namespace, setting ID, type, required/optional status, sensitivity class, and
deterministic ownership. Version-1 overlays contain typed entries, build and
overlay identity, duplicate/undeclared/type/completeness checks, and a
canonical SHA-256 fingerprint. Active storage is
`special://profile/addon_data/script.build.manager/private_overlays/`, with
atomic writes and restrictive `0700`/`0600` permissions where supported.
The current backend is protected local plaintext: encryption at rest is not
claimed and no custom cryptography is used.

BM-015 remains the sole typed settings backend. Public configuration is
applied first, then validated private values through the same typed
write/read-back/verification path. Private values stay outside public
manifests, packages, frozen artifacts, logs, `.agent/*`, and BM-020/BM-022
durable state; those transactions persist only overlay ID, fingerprint, and
required flag. Missing required overlays and fingerprint drift fail closed;
optional absence is a safe no-op.

Integrated validation passed private-overlay tests **14/14**, the
BM-015/BM-020/BM-022 regression group **588/588**, the full suite
**1591/1591**, and `git diff --check`. No implementation or test accessed
real Family Room private data, credentials, a real Kodi profile, Apple TV,
or another device. BM-017B real private capture/import has not started.

No next milestone was started. The smallest next step is supervisor direction
and explicit authorization for any future private-state capture/import work.

## BM-022V / BM-022V-R — Frozen Family Room software capture integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The clean
matrix-side substantive commit is `31b8f9d`, reconstructed from the approved
worker endpoint `784ea8f`; worker `.agent/*` metadata was excluded.

BM-022V read-only validation and BM-022V-R exact-artifact recovery establish
that Frozen Family Room software capture is **COMPLETE** for required
software: 37 graph nodes, 67 required edges, 3 optional edges, zero required
missing artifacts, 30 exact artifact-backed nodes, 194,254,227 captured
artifact bytes, and candidate fingerprint
`sha256:8ce7d2daf131f6c1bbcdf152c02c15745f9bc52eac34480ee43e9f7af093e035`.
The optional YouTube artifact remains incomplete (`7.4.4+unofficial.2`
installed versus cached `7.4.4`) but is non-blocking. The exact Dropbox
`script.module.dropbox` `10.3.1+matrix.1` artifact is captured with SHA-256
`5a954c48be820fa3e5fee2bf29cdf3befd46b4b02c92de1a8f7f8231032424e6` and
size 667,538 bytes. The unchanged Robotocjksc ZIP is accepted through the
generalized one-safe-root validator and normalized only during staged
extraction; package bytes were not rewritten.

BM-023A-R later established that optional incoming edges do not waive the
artifact requirement for this installed, enabled node. The non-blocking
classification above is preserved as historical BM-022V/R tracking and is
superseded by the current completeness invariant.

Ready-to-use configuration remains **INCOMPLETE / BLOCKED_BY_BM017** because
private/authenticated state was not captured. Real-device frozen installation
is **NOT YET VALIDATED**. Family Room evidence and software capture remained
read-only: no install/update, enable/disable, repository refresh, restart,
settings/database write, or reconciliation occurred. BM-017 remains deferred
and no next milestone was started.

Integrated validation passed focused artifact/repository/add-on/frozen tests
**331/331**, the full Build Manager suite **1577/1577**, and
`git diff --check`.

## BM-022 — Frozen Build Installation and Transaction Lifecycle integrated

**Status**: Complete, supervisor-approved, and integrated on protected
`matrix`; matrix remains neutral with `active_agent: none`. The reviewed
substantive integration commit is `56ea26a`, reconstructed from worker
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
