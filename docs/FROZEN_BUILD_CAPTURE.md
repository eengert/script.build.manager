# BM-021A — Frozen build capture feasibility and provenance audit

Status: complete as a read-only feasibility audit. This document records what
Kodi 21.1 and the current Build Manager implementation expose, what was
observed in the disposable `.kodi-test` profile, and the minimum safe design
boundary for BM-021B/BM-022. It does not implement frozen capture, an artifact
store, freshness enforcement, or frozen installation.

The real Kodi profile, Family Rm, Apple TV, and all other devices were not
accessed or modified. The only mutable runtime used by this audit was the
project disposable profile under `.kodi-test`.

## Decision summary

Frozen capture is feasible, but not by treating Kodi's installed add-on
directory or package cache as a durable build artifact store. A complete
capture needs a Build Manager-owned, content-addressed artifact store and a
versioned manifest that records exact versions, hashes, dependency edges,
ownership, provenance confidence, enabled state, and capture freshness.

The safe recovery policy is:

1. use a previously captured Build Manager artifact when its SHA-256 and
   `addon.xml` identity verify;
2. otherwise use an exact cached Kodi package only when the cache ZIP contains
   the requested add-on ID/version and its content is rehashed;
3. otherwise use a recorded repository package/index only when the exact
   version remains available and the downloaded ZIP is revalidated;
4. otherwise mark the capture incomplete and do not publish or install it.

Zipping an installed add-on directory is not an acceptable substitute for an
original artifact. It can be a narrowly useful diagnostic or emergency import
input, but it cannot establish original provenance, original bytes, repository
digest, or reproducibility and must be classified `UNSAFE_REJECTED` for a
future frozen-build capture.

## Evidence labels

- **Verified** — observed in the disposable profile, the checked-in Build
  Manager source/tests, or the Kodi 21.1 installation/source inspected for
  this audit.
- **Design** — a proposed BM-021B/BM-022 contract, not an implemented or
  live-proven feature.
- **Unknown / needs testing** — a question that the available public API,
  disposable evidence, or source review does not establish.
- **Rejected** — a tempting approach that fails the provenance or safety
  requirement.

## 1. Scope and audit environment

**Verified.** The worker was first synchronized to protected `matrix` by a
normal merge. The synchronization merge is `00ca66c`; the matrix endpoint was
`34fbd7b`. No substantive endpoint difference existed outside worker metadata,
and the worktree was clean before the audit began.

The disposable profile used Kodi 21.1 with the project's JSON-RPC test setup.
The existing BM-011 repository/add-on gate passed **19/19**, and the existing
BM-020A production executor gate passed with AF3 dependency closure **18/18**.
Those gates were reused as evidence; no new production capture code was added.

## 2. Installed add-on metadata

**Verified.** Public JSON-RPC `Addons.GetAddonDetails`/`Addons.GetAddons`
exposes the useful installed-state fields used by the audit:

- add-on ID, version, type, and installed path;
- enabled, installed, and broken state;
- declared dependency IDs, minimum versions, and optional flags.

Representative disposable results included `repository.xbmc.org`,
`script.build.manager`, `skin.estuary`, `script.module.pil`, and
`metadata.themoviedb.org.python`. The query did not expose the add-on's
repository origin, original package URL, package digest, installation method,
or a per-add-on automatic-update flag. Kodi documents the public fields in
[the JSON-RPC add-on API](https://kodi.wiki/view/JSON-RPC_API/v13.11).

**Verified.** The installed add-on directory contains `addon.xml`, which is
the authoritative local declaration of the installed ID, version, type,
dependencies, and extension points. It is necessary for a capture, but it is
not by itself provenance evidence. Kodi's dependency declaration format is
documented in [Addon.xml](https://kodi.wiki/view/Addon.xml).

**Design.** A future capture must record both the public/runtime observation
and the local declaration, then reject an entry if the ID or version disagrees
with the artifact's `addon.xml`. A runtime-only record is insufficient for
reconstruction.

## 3. Provenance and origin

**Verified.** Kodi's Addons database has internal tables for installed state,
repository content, repository links, package cache entries, and update rules.
The observed `installed` schema includes an `origin` field. Repository-backed
installs can carry a repository add-on ID; manually staged/direct installs in
the Build Manager disposable gates had an empty origin. The Kodi source also
updates origin information when a repository add-on is discovered and joins
repository content when resolving installable metadata. See Kodi's
[AddonDatabase.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/AddonDatabase.cpp)
and [AddonInstaller.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/AddonInstaller.cpp).

**Verified.** Origin is therefore useful evidence of the last known Kodi
installation source, not a universal proof of original artifact provenance:

- a repository origin can identify the repository add-on ID;
- an empty origin is compatible with a manual ZIP or Build Manager's direct
  staged installation;
- the same add-on can be available from multiple repositories;
- a repository can later disappear, change its index, or stop retaining old
  versions;
- the public JSON-RPC API does not expose this internal origin field.

The real profile must not be read by opening its private database for this
purpose. Production capture should use supported runtime metadata where
available and mark provenance as `unknown` when it cannot be established.

**Design.** Store provenance as nullable, confidence-labelled data, never as a
guessed URL:

```json
"provenance": {
  "repository_id": "repository.example",
  "repository_url": "https://example.invalid/repository.example",
  "method": "kodi_origin|manifest|cache|unknown",
  "confidence": "observed|derived|unknown"
}
```

The example values are schema shape only. An empty or unknown field is valid;
inventing a repository from an add-on ID is not.

## 4. Kodi package cache and exact-version recovery

**Verified.** Kodi's home profile uses `special://home/addons/packages/` for
downloaded add-on packages. In the macOS disposable profile this mapped under
`.kodi-test/home/Library/Application Support/Kodi/addons/packages/`. The
cache contained Kodi-generated ZIPs with a single top-level add-on directory.
Each inspected ZIP was parsed, its add-on ID/version was read from
`addon.xml`, and its byte content was SHA-256 hashed.

The Addons database `package` table maps an add-on ID to a cache filename and a
recorded repository digest. That digest is a Kodi repository/package digest,
not a guarantee that it is SHA-256. Repository metadata controls the hash type
and may use an HTTP header or a sidecar checksum. Kodi's repository resolution
code is described in
[Repository.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/Repository.cpp).

**Verified.** The cache was not a complete installed-artifact inventory:

- it contained several official metadata and peripheral packages;
- it did not contain every third-party add-on installed for AF3;
- some cached package versions differed from the currently installed version;
- Kodi prunes the cache according to its configured package-cache size and
  retains only a bounded number of packages per add-on.

Kodi's installer and cache behavior is implemented in
[AddonInstaller.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/AddonInstaller.cpp),
and the `special://home/addons` layout is documented by Kodi's
[special protocol](https://kodi.wiki/view/Special_protocol).

**Design.** A cache ZIP is usable only after all of these checks pass:

1. the filename/database association is only a hint;
2. the ZIP has safe paths and exactly the expected top-level add-on;
3. `addon.xml` has the requested ID and exact requested version;
4. the ZIP is rehashed with SHA-256;
5. any recorded repository digest is checked using its declared algorithm;
6. the entry records that recovery came from a bounded Kodi cache.

An exact cache hit is therefore a valid recovery source, but only for the
versions still present. Cache absence is not evidence that a version never
existed.

**Unknown / needs testing.** Kodi does not provide a supported public API that
guarantees historical repository versions remain available. Repository
indexes and package URLs are controlled by each repository. A future capture
must not claim exact recovery from a repository unless the requested version,
package bytes, and digest are available at capture time.

## 5. Repository metadata, mirrors, and redirects

**Verified.** The disposable BM-011 repository used Kodi 21's current
repository schema:

```xml
<dir>
  <info compressed="false">.../addons.xml</info>
  <checksum>.../addons.xml.md5</checksum>
  <datadir zip="true">...</datadir>
</dir>
```

With `zip="true"`, the project resolver constructs the conventional package
path `{datadir}/{addon_id}/{version}/{addon_id}-{version}.zip`. The repository
add-on itself is a normal add-on containing an
`xbmc.addon.repository` extension; it is not an external trust anchor.

**Verified.** Kodi resolves repository metadata and package locations through
the repository's configured directory and checksum rules. A redirect can be
part of acquisition, but a redirect URL is not a stable artifact identity.

**Design.** The manifest should record the original repository identity and
the immutable artifact SHA-256. It may record the observed package URL and
redirect chain as diagnostic acquisition metadata, but neither URL is the
identity used for later equality. Mirrors are equivalent only when the
revalidated bytes produce the same SHA-256 and `addon.xml` identity.

## 6. Installed-directory ZIP fallback

**Rejected.** A ZIP made by archiving `addons/<addon-id>/` after installation
does not prove that it is the original package. It may contain generated
files, Python bytecode, platform-specific files, post-install modifications,
or files that were never present in the repository artifact. It also loses the
original repository checksum, package filename semantics, redirect history,
and installation provenance. Dependencies are not made complete merely by
zipping one installed directory.

Kodi's native ZIP installer expects a valid ZIP with one top-level folder and
reads its descriptive `addon.xml`; the implementation is visible in the
[native InstallFromZip path](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/AddonInstaller.cpp).
That importability condition is much weaker than reproducible artifact
provenance.

**Design.** BM-021B may use an installed-directory ZIP only as an explicitly
labelled diagnostic import path, never as a complete frozen capture and never
as a substitute when the exact package is unavailable. The capture result must
be `incomplete` if no trusted artifact source remains.

## 7. Dependency closure

**Verified.** The AF3 3.2.19 disposable closure walk found **21 nodes**:

- **18 third-party nodes** installed in the disposable profile;
- **3 Kodi/system nodes** (`xbmc.gui`, `xbmc.python`, and the exact
  `kodi.resource` system exception).

The closure includes direct AF3 requirements, TMDb Helper's requirements, and
transitive modules such as requests' certificate/encoding/URL dependencies,
six, PIL, QR code support, and helper libraries. The BM-020A disposable gate
reported every required non-system node installed, enabled, and not broken;
its AF3 dependency-health check passed **18/18**.

The checked-in Build Manager rule treats only IDs beginning with `xbmc.` and
the exact ID `kodi.resource` as system dependencies. This is an explicit
boundary, not a license to treat arbitrary `resource.*` add-ons as built in.

**Design.** A frozen manifest must represent dependency edges, not just a flat
list:

```json
"dependencies": [
  {
    "addon_id": "script.module.requests",
    "min_version": "2.9.1",
    "optional": false,
    "system": false,
    "frozen": true,
    "via": ["plugin.video.themoviedb.helper"]
  }
]
```

Required third-party nodes need exact artifacts. Optional nodes are recorded
with `optional: true` and do not block a complete capture when absent, unless a
future add-on-specific policy promotes them to required. System nodes get
their required minimum version and Kodi compatibility constraint but no frozen
artifact. Cycles must be detected and reported rather than silently flattened.

## 8. Repository add-ons and repository enablement

**Verified.** The BM-011 disposable test installed a repository add-on and two
normal add-ons. Kodi reported the repository as installed and enabled and
recorded repository-origin metadata for the repository-backed path. The
project's installer separately validates package paths, IDs, versions, and
atomic staging; it does not rely on Kodi's dependency resolver for the normal
add-on closure.

**Design.** Repository add-ons are ordinary frozen entries. Their exact ZIP,
`addon.xml`, version, SHA-256, and repository configuration must be captured
like any other required third-party artifact. A future offline installer can
install the captured repository ZIP directly and install the rest from the
captured artifact store; it must not depend on a live repository to rediscover
the build.

Keep repository add-ons disabled while an offline exact-artifact transaction is
being assembled when the supported installation path permits that state.
Restore the declared enabled state only after all artifacts and dependency
checks pass. Enabling a repository can trigger repository indexing and update
activity, so repository enablement is a final-state operation, not a harmless
bootstrap detail.

**Unknown / needs testing.** The current Build Manager has no end-to-end
live-proof that a complete future frozen install can remain repository-disabled
through every native Kodi package lifecycle while using only captured ZIPs.
The offline artifact transaction and final repository enablement need a
dedicated BM-021B disposable gate.

## 9. Global and per-add-on update control

**Verified.** Kodi 21.1 exposes the global `general.addonupdates` setting as
three values in the installed settings definition:

| Value | Meaning |
|---:|---|
| `0` | install updates automatically |
| `1` | notify, but do not install |
| `2` | never check for updates |

The disposable profile reported the default value `0`. The related
`addons.updatemode` setting controls whether unknown repositories are allowed
(`0` official only, `1` any repository) and is not a per-add-on freeze switch.

**Verified.** Kodi's repository updater registers for changes to the global
auto-update setting, avoids scheduling when the mode is `AUTO_UPDATES_NEVER`,
and only calls the automatic update installer when the mode is
`AUTO_UPDATES_ON`. See the updater's
[schedule and automatic-install logic](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/RepositoryUpdater.cpp).
This establishes a viable global guard in principle.

**Verified.** No supported public per-add-on automatic-update boolean was
exposed by JSON-RPC or the installed settings definition. Kodi's internal
`update_rules` table contains pinning rules such as old-version and ZIP-install
pins. These rules are installation/update bookkeeping, not a general durable
per-add-on policy API; Kodi's handling is visible in
[AddonInstaller.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/AddonInstaller.cpp).

**Design.** A frozen transaction should:

1. read and save the current global updater mode;
2. set `general.addonupdates` to `2` before any exact artifact mutation;
3. keep the guard through dependency installation, repository handling, and
   any required BM-020 restart/resume lifecycle;
4. verify the guard after restart before resuming;
5. restore the saved mode only after success and final-state verification;
6. leave the guard in place and report `needs_attention` on failure.

The manifest records the global policy actually observed. It must not invent a
per-add-on boolean when Kodi does not provide one. A future schema may reserve
an explicit `scope: addon` form for a platform that proves such a capability,
but the current Kodi implementation must use `scope: global` or
`unsupported`.

**Unknown / needs testing.** The audit read the setting and inspected Kodi's
updater source. It did not claim a production live proof that a setting change
made through JSON-RPC remains effective across every restart/update race. That
must be a focused BM-021B disposable test, including a setting read-back,
restart, repository refresh attempt, and restoration of the original value.

**Rejected.** A per-add-on fallback that installs while the global updater is
left active is unsafe. There is no supported per-add-on lock exposed to the
Build Manager, and a repository scan or scheduled update can race an exact
version installation. Internal pin rows are not a sufficient replacement for
an acquisition-wide guard.

## 10. Proposed content-addressed artifact store

**Design.** BM-021B should introduce an immutable store owned by Build
Manager, for example:

```text
artifact-store/
  sha256/
    <64-lowercase-hex>.zip
```

Import is write-once and atomic: stream to a temporary file in the same store,
hash while writing, flush and close, validate ZIP identity, atomically rename
to the digest path, and refuse replacement if the digest path already exists
with different bytes. Store only validated add-on ZIPs, not arbitrary profile
files. Garbage collection is outside BM-021A and must not silently remove an
artifact referenced by a published manifest.

Each artifact record should include SHA-256, byte size, ZIP filename as
observed, top-level add-on ID/version, capture time, acquisition source, and
the repository checksum algorithm/value when available. The SHA-256 is the
identity; filenames and URLs are metadata.

## 11. Proposed frozen-build manifest

**Design.** The first manifest schema should be versioned and explicit. The
following is a shape proposal, not a checked-in runtime format:

```json
{
  "schema_version": 1,
  "capture": {
    "id": "opaque-build-id",
    "created_at": "RFC-3339 timestamp",
    "status": "complete|incomplete",
    "kodi_version": "21.1",
    "platform": "macos",
    "freshness": {
      "captured_at": "RFC-3339 timestamp",
      "repository_indexes_at": "RFC-3339 timestamp or unknown",
      "stale_after": "policy-defined or unknown"
    }
  },
  "update_policy": {
    "scope": "global",
    "mode": "automatic|notify|never|unknown",
    "source": "kodi-setting|unknown"
  },
  "addons": [
    {
      "addon_id": "example.addon",
      "version": "1.2.3",
      "type": "xbmc.python.module",
      "enabled": true,
      "artifact": {
        "sha256": "64 lowercase hex",
        "size": 12345,
        "filename": "example.addon-1.2.3.zip"
      },
      "provenance": {
        "repository_id": "nullable",
        "repository_url": "nullable",
        "method": "repository|cache|build-store|unknown",
        "confidence": "observed|derived|unknown"
      },
      "dependencies": [
        {
          "addon_id": "script.module.example",
          "min_version": "1.0.0",
          "optional": false,
          "system": false,
          "frozen": true
        }
      ]
    }
  ]
}
```

Required fields for a complete non-system entry are exact ID, version,
`addon.xml` type, enabled state, artifact SHA-256/size, dependency edges, and
provenance classification. System dependencies have no artifact but retain
minimum-version and compatibility constraints. Secrets, private settings,
runtime caches, generated files, and whole profile databases do not belong in
this manifest.

## 12. Freshness and failure semantics

**Design.** Freshness is metadata, not a reason to silently change artifact
identity. The manifest should record capture time, repository-index observation
time where available, and a policy-defined stale threshold. A stale manifest
can be warned about or rejected by policy; it must not be refreshed by
silently selecting a newer add-on.

Capture is `incomplete` and non-publishable if any required third-party node
has no exact verified artifact, if the artifact ID/version disagrees, if the
hash cannot be computed, if required provenance has become ambiguous under the
chosen policy, or if the dependency closure is incomplete. The operation must
fail before publishing a manifest that looks complete.

## 13. Representative findings

| Case | Evidence | Result |
|---|---|---|
| AF3 3.2.19 | Disposable BM-020A gate, closure walk | 21 nodes; 18 third-party healthy; 3 system boundary nodes; gate **18/18** |
| Installed metadata | Kodi JSON-RPC representative queries | ID/version/type/path/state/declarations available; origin and per-addon update policy absent |
| Repository add-on | BM-011 disposable gate | Repository and normal add-ons installed; repository metadata path exercised; gate **19/19** |
| Package cache | Disposable cache and Addons DB inspection | Bounded, partial, version-variable; useful only after exact identity and rehash |
| Installed-directory ZIP | Kodi native ZIP behavior plus provenance analysis | Importability is possible in narrow cases; reproducible provenance is not; reject as capture fallback |
| Global update control | Kodi 21.1 settings definition and updater source | Three-state global policy exists; exact restart/race proof deferred to BM-021B |

## 14. BM-021B scope recommendation

BM-021B should be limited to the smallest disposable proof of the capture
contract:

- content-addressed import and rehash of a repository ZIP;
- versioned manifest serialization and fail-closed incomplete states;
- complete direct/transitive dependency closure with exact system boundary;
- repository add-on capture and offline artifact ordering;
- global updater guard read-back, restart persistence, and safe restoration;
- exact cache recovery and deliberate cache-miss failure;
- provenance confidence and stale/fresh metadata;
- no real-profile access and no device work.

It should not yet implement a general frozen-build installer or migrate
existing profile configuration.

## 15. BM-022 scope recommendation

BM-022 can consume a completed BM-021B manifest/store contract to implement
the production frozen-build installation/reconciliation path. It must preserve
the same global update guard across the entire transaction, use only verified
content-addressed artifacts, validate closure before mutation, and leave a
recoverable `needs_attention` state on failure. BM-022 is not started by this
audit.

## 16. Explicit non-goals and deferrals

- No full frozen capture implementation was added.
- No artifact store was created.
- No frozen-build installer or update guard was added to production code.
- No real Kodi profile or Apple TV was accessed.
- BM-020 remains complete.
- BM-017 remains deferred.
- BM-021B and BM-022 were not started.

## 17. Sources and checked-in evidence

Primary Kodi references used for the audit:

- [Kodi JSON-RPC add-on methods and fields](https://kodi.wiki/view/JSON-RPC_API/v13.11)
- [Kodi Addon.xml dependency and extension declarations](https://kodi.wiki/view/Addon.xml)
- [Kodi special:// path documentation](https://kodi.wiki/view/Special_protocol)
- [Kodi AddonInstaller.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/AddonInstaller.cpp)
- [Kodi AddonDatabase.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/AddonDatabase.cpp)
- [Kodi Repository.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/Repository.cpp)
- [Kodi RepositoryUpdater.cpp](https://github.com/xbmc/xbmc/blob/master/xbmc/addons/RepositoryUpdater.cpp)

Project evidence used without exposing private values:

- `tools/kodi_test.py` BM-011 repository and disposable-profile gates;
- `resources/lib/addons.py` repository index/package resolution and ZIP
  validation;
- `resources/lib/repository.py` repository bootstrap validation;
- `resources/lib/dependencies.py` exact system-dependency boundary;
- BM-020A disposable AF3 closure and executor gate output.

