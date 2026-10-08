# Canonical Build Library (BM-UI-003A)

This foundation advances macOS Beta Qualification item 8: native Create,
Install, Repair and Status need the same owned build definition and durable
selection. It adds no capture UI, Apply, repository acquisition or repair.

## Persistence audit and ownership

| Existing primitive | Library use |
| --- | --- |
| `manifest.validate_manifest` / `resolver.resolve_manifest` | Validate the existing public manifest format and every advertised device profile. |
| `FrozenBuildManifest.from_dict` / `fingerprint` | Validate and retain the exact prepared frozen manifest; bind its build ID with the accepted `check_frozen_identity`. |
| `ConfigPackageLoader` / `default_packages_root` | Reuse descriptor, value, overlay, AF3 and manifest-ownership preflight. The embedded root remains the existing default for legacy targets; library targets use their own verified package bytes. |
| `ArtifactStore` | Exact ZIPs remain under the existing BM `frozen-artifacts/artifacts/<sha256>.zip` store. Registration validates reference structure, never acquires, duplicates, opens or imports ZIPs. |
| `PrivateOverlayStore` | Private payloads remain under the existing profile-owned `private_overlays/<safe-id>.json` store. Registration never opens that store. Existing safe overlay IDs/declarations may remain in the public manifest. |
| `FrozenInstallResolutionManifest` / `FrozenInstallStore` | Completed outcomes remain installed-state evidence in `install_resolutions/<fingerprint>.json`. Applied association stores only entry/profile identity; targets carry `install_resolution=None` unless a caller supplies separately validated resolution evidence. |
| `default_frozen_install_root` | Same BM profile parent. Library production translation deliberately has no host `/tmp` fallback: absent Kodi translation means no selection. |
| Transaction persistence | Reuse the established staged write, file fsync, atomic replace, directory fsync and nonblocking OS lock pattern. Library/selection share a separate library lock; no install/restart transaction is created. |
| `readonly_io.read_regular_file` | Reuse bounded nonblocking regular-file reads. Its optional `dir_fd` allows anchored reads after every directory component is opened with `O_DIRECTORY | O_NOFOLLOW`. |
| `StatusTarget` / `PlanTarget` | One optional typed `LibrarySource` reloads the verified public/frozen/package snapshot; existing target fields and accepted resolution/policy/review identity semantics remain. |

The active Kodi abstraction alone supplies the production root:

```text
special://profile/addon_data/script.build.manager/
  build-library/
    registry.json
    selection.json
    library.lock
    builds/
      <64 lowercase hexadecimal SHA-256>.json
```

The immutable envelope contains the existing public manifest, the exact frozen
manifest and existing package descriptors with their referenced source assets
encoded as base64. It introduces no alternative semantic manifest or artifact
store. A single envelope gives readers one coherent bounded snapshot without
copying arbitrary source directories or repeatedly opening package paths after
validation. No public entry or selection model contains a filesystem path.
The future Build Transfer Folder is independent and unused here.

## Registration and identity

`BuildLibrary.register(manifest_path, frozen_path, packages_root)` accepts an
already prepared public bundle. Explicit filesystem roots are supported for
isolated callers/tests; production callers obtain the library through
`default_build_library()` and its active special-profile translation.

Registration reads bounded regular sources without following any ancestor or
leaf symlink. It rejects traversal, duplicate JSON fields/non-finite constants,
invalid public or frozen manifests, mixed build IDs, invalid/duplicate nodes,
malformed artifact digests/sizes/filenames, invalid profile inheritance and
missing or unsafe required packages/assets. Every advertised device profile
passes the real resolver and package preflight. The required package set is the
union of all those resolved profiles and the frozen manifest's package IDs.
Only those descriptors and explicitly referenced assets are copied.

The entry key is SHA-256 of canonical JSON for the entire envelope. It binds
public declaration, frozen content, every package descriptor and every owned
asset. JSON whitespace and object-key ordering do not change it. Display names
are labels, not identities. Exact re-registration is idempotent after reloading
and validating the stored copy. A different envelope with the same build ID and
version raises `LibraryConflict`; nothing is silently overwritten. An existing
indexed corrupt/missing entry also fails closed on duplicate registration.

`registered_bundle(bundle)` resolves exact-public authority without writing. It
returns None only when the entire root is genuinely absent, or a readable valid
registry lacks the exact canonical envelope key. Once indexed, the builds
directory and exact envelope must be readable, valid and consistent with their
hash and registry metadata. Missing or unavailable indexed content raises a
safe LibraryError instead of authorizing private rollback. A present root with
no readable registry is ambiguous and also fails closed.


`LibraryEntry` is frozen and carries entry ID, build ID/version, display name,
sorted device profiles and `usable`. Usable means the public definition is
validated and fully owned; it does not promise that exact ZIPs are available or
that a device is installed/current. Accepted G2/G3 checks retain that authority.
Listing omits corrupt entries and orders usable entries by case-folded display
name, build ID, version and entry ID. Malformed registry state raises a stable
`LibraryError`. Entry metadata must exactly agree with the loaded content.

## Privacy contract

Inputs must already be public configuration under the existing package
contract. There is no private payload parameter, capture, recursive import,
private-store read or resolution-record import. Unknown overlay payload fields
are rejected by the existing manifest validator. Nonempty overlay path hints or
descriptions are rejected rather than copied. Registration rejects values for
any private setting declared in any manifest layer, all Red Light settings,
credential-like setting keys, Red Light file destinations and credential-like
file destinations, including packages shadowed by later packages.

Frozen diagnostics are not a public-data channel: source metadata permits only
`kodi_version` matching the typed source version; node errors and arbitrary
provenance-detail maps are rejected. Prepared bundles must omit those diagnostic
maps rather than silently changing a supplied frozen graph. Ordinary public
labels, setting values and asset bytes retain the existing caller obligation to
contain public data; this is not a general detector for secrets disguised as
arbitrary public text. The later capture workflow must enforce that same
public/private classification before registration.

Errors expose stable library codes, never source values, paths or underlying
exception text. Tests use private and Red Light sentinels and prove unrelated
private files are not copied, declared private values are rejected before
publication, and persisted library/registry/selection, safe result models and
logs omit the sentinels and internal paths.

## Atomic publication and recovery

Writers hold one nonblocking `flock` on a regular no-follow lock file. The
macOS beta implementation uses existing POSIX directory-descriptor/locking
facilities; unsupported runtimes fail closed. Source files/descriptors/assets
are bounded at 4 MiB each, envelopes at 32 MiB, registry/selection at 1 MiB,
package count at 256 and aggregate imported package bytes at 16 MiB.

An envelope is validated completely, staged and atomically published before the
registry indexes it. Only registry-indexed, digest-matching content is usable.
An interrupted staged file or an unindexed complete envelope cannot be selected.
A retry may publish the identical validated envelope and then its registry row.
Unexpected leftover stage/unindexed files are ignored and retained; this task
adds no destructive cleanup. Invalid indexed content requires a later explicit
repair/removal operation, rather than automatic recovery that changes identity.

Reads create no directory or lock. All traversal/writes retain no-follow
ancestor descriptors, so a symlink replacement cannot redirect them into its
target. Replacements may cause the current lexical library to become
unavailable; they never authorize following the replacement. File, directory,
FIFO, symlink, size and registry/content disagreement failures are covered.

## Selection and production targets

`select(entry_id, device_profile_id)` validates the current owned entry/profile
and atomically writes only schema version, immutable entry ID and profile ID.
`current_selection()` reloads both records/content without mutation; missing,
corrupt, removed, changed or unavailable content/profile returns `None`.
`clear_selection()` atomically clears the selection. A sole entry is never
automatically selected. Registry and selection share the writer lock.

`selected_status_target()` and `selected_plan_target()` bridge the selection
to accepted target contracts. `plan.default_plan_target()` retains this selection
bridge. Production `status.default_status_target()` uses only the verified applied
association; absence or invalidity preserves truthful unavailable build comparison. Every service call
revalidates the typed source, so a target obtained before corruption cannot
silently fall back to another build or global package content.

Both services use one loaded manifest/frozen/package snapshot. The production
package parser accepts an optional byte reader; the library's in-memory loader
uses this to retain the existing configuration validation without external path
lookup. Existing path-based callers retain their previous loaders. Effective
package content still participates in G3 build/review fingerprints; frozen,
resolution, policy binding and stale review validation remain intact.

## Verified applied association

`applied.json` lives beside `selection.json` under the profile-owned Build Library
(`special://profile/addon_data/script.build.manager/build-library`). Its exact
schema is `{"schema_version":2,"entry_id":"<immutable library entry ID>",
"device_profile_id":"<declared profile ID>",
"resolution_fingerprint":"<64 lowercase hex>"}`. The fingerprint names the
immutable completed `FrozenInstallResolutionManifest`, not a path or a review.
Schema-1 records fail closed; no resolution is inferred or migrated.

`current_applied_association()` revalidates the registered envelope/profile and
loads the exact referenced resolution from the profile-local frozen store's
`install_resolutions/<fingerprint>.json`. Existing `bind_resolutions()` validates
build, frozen graph, install plan, effective policy, record semantics and resulting
software. Missing, corrupt, changed or unbindable evidence returns `None`; no
selection, sole-entry, directory scan or latest-record fallback is used.
Associated Status and Plan attach that same manifest as `install_resolution`,
retaining accepted Skip and Repository Current semantics. Reads remain bounded,
creation-free and use no-follow traversal for association and resolution evidence.

## Durable completion publication

The existing frozen completion owner persists the exact completed resolution and
restores the updater, then atomically claims `COMPLETE -> PUBLICATION_PENDING`
under the FrozenInstallStore lock with the exact transaction UUID and expected
COMPLETE phase. This durable frozen phase is the publication ownership fence.
A concurrent abandon either clears COMPLETE first (the fence fails and no journal
can be created), or loses to the fence and cannot clear/cancel it.

`_create_applied_publication()` requires this exact fenced transaction. The store
positively confirms/re-fsyncs the fence under its lock before library creation;
lock-free checks inside the library writer lock reject obsolete observations but
are not the mechanism protecting ownership. Generic clear, clear_expected and
transition_expected reject PUBLICATION_PENDING; create cannot replace an active
record, and held retry predicates exclude it. Abandon refuses before touching
policy. Attention helpers cannot transition the fence away. No frozen and library
writer locks are held together, and no new global lock is introduced.

The bounded `applied-publication.json` journal remains schema 2 with exactly:
`schema_version`, `transaction_id` (UUID), `candidate` (schema-2 association),
`previous` (verified schema-2 association or null), and `state` (`pending` or
`acknowledged`). Existing schema-1 journals explicitly remain PENDING. Applied
association schema 2 and exact resolution binding remain unchanged.

Publication ordering is PENDING durability -> positive ACK file fsync/replace/
directory fsync -> applied candidate materialization/fsync/readback -> fenced
transaction cleanup. Candidate bytes are never newly published before the ACK
barrier succeeds. A legacy PENDING journal with already replaced candidate bytes
first restores its masked previous materialization before attempting ACK. The
fence stays durable across journal creation and every publication failure.

PENDING exposes previous or None and blocks Install. ACK plus previous applied is
unresolved: reads expose previous or None, Status remains non-idle and Install
stays blocked. A failed ACK barrier can leave visible ACK, but applied remains
previous; readback never substitutes for a positive barrier. Recovery validates
the exact journal, re-fsyncs ACK and materializes only its exact candidate.
ACK plus matching applied exposes the candidate. If the applied directory barrier
fails after replacement, durable ACK still owns the candidate; the retained fence
keeps the operation non-idle until recovery confirms durability and finishes cleanup.
Malformed or contradictory state fails closed without selection fallback.

Only `_clear_publication_expected()` can finish the fence. Under the frozen lock
it reads independent exact ACK evidence, requires matching applied candidate and
resolution identity, and positively fsyncs the library directory before removing
the fenced transaction. It takes no library writer lock. Terminal journal cleanup
is optional and first requires matching independently durable applied bytes.
Retained/restored ACK after cleanup ambiguity cannot reverse authority; unresolved
ACK is never garbage-collected.

Crash after fencing but before journal creation is recovered from the exact
fenced identity. A legacy/current COMPLETE record first acquires the same fence.
Startup/resume publication recovery runs before runtime-owner construction and
never replays software/configuration mutation or consults selection. Fenced state
is non-idle even with no pending journal and does not reassert updater quarantine,
since original policy restoration preceded fencing. A different active/restart
owner is not intercepted by retained terminal evidence.

Recovery of an observed journal still uses `_validate_applied_publication()`;
it never recreates a missing observed journal. Already completed same-candidate
recovery is idempotent; a newer completed association supersedes stale recovery
without writes. Another pending/unresolved identity conflicts untouched. The
accepted A/B/C stale-recovery behavior, exact fingerprint lookup and binder remain
unchanged; no timestamp ordering or resolution fallback supplies authority.

Selection, registration, capture, noncomplete outcomes and legacy path installs
never establish an association. Schema-4 restart target ownership is unchanged;
schemas 1-3 do not acquire one. Update / Repair UI remains deferred.

## Validation boundary and next task

Automated tests cover registration, deterministic/idempotent reads, conflicts,
source deletion/change, isolated same-ID packages, selection durability,
corruption, interrupted writes, containment, ancestor swaps, regular-file/size
bounds, privacy, production translation/bridges and no Kodi mutation/network.
Existing G2/G3/configuration suites are included in focused validation, followed
by one full suite at the final unchanged-source boundary. Exact counts/results
are recorded in `.agent/HANDOFF.md`.

No Test.app or live Kodi/device validation is part of this task. The next task
is the native Create Build capture/registration workflow using this foundation.
