# Portable Test.app profile isolation helper

Task: Item 8 reversible profile isolation; scratch-only implementation from
`1ad67d2e0583d66d125eeade172a23dca7baa6b9`, branch `agent/codex`.
This helper removes a host-side blocker to future restart qualification. It
neither accepts Item 8 nor runs qualification or stages product code.

`tools/bm_profile_isolation.py` exposes only the exact
`/Applications/Kodi Build Manager Test.app` target through its CLI. Portable
layout is fixed to `Contents/Resources/Kodi/portable_data`. There is no target,
profile, storage-location, copy, delete, launch, quit, or force override.
The `scratch=True` Python wiring accepts only fabricated bundles beneath
`/private/tmp/`; it is for offline tests, not an alternate live interface.

## Explicit operations

Choose one 32-character lowercase hexadecimal operation ID and retain it.
A lexical `preview --operation ID` prints intended paths and phase preconditions
without profile probes or hashing. It reports current state as unobserved;
mutating operations establish actual state through guards.
Every mutation separately requires its matching `--confirm ACTION` and
`--portable`. Future commands, requiring separate live authorization, are:

```
python3 tools/bm_profile_isolation.py preview --operation ID
python3 tools/bm_profile_isolation.py preserve --operation ID --confirm preserve --portable
python3 tools/bm_profile_isolation.py park --operation ID --confirm park --portable
python3 tools/bm_profile_isolation.py restore --operation ID --confirm restore --portable
python3 tools/bm_profile_isolation.py recover --operation ID --confirm recover --portable
python3 tools/bm_profile_isolation.py reconcile --operation ID --confirm reconcile --portable
```

Preserve moves the entire stopped original to `portable_data.bm-original-ID`.
It leaves the active path absent. Creation and use of a fresh portable profile
belong to a separately authorized qualification task; this helper creates no
fresh profile. Park moves that distinct fresh profile to
`portable_data.bm-qualified-ID`. Restore requires the active path absent and
both original and parked integrity evidence valid; it moves only the recorded
original back to `portable_data`. Park and restore are separate gates.

The adjacent `.bm-profile-isolation-ID/` stores append-only mode-0600 JSON
records in a mode-0700 directory. Each binds exact target/layout, bundle plist
hash, parent device/inode, original per-node device/inode, opaque bytes and
metadata evidence, fresh evidence once observed, phase, and prior record hash.
No private path names, xattr names/values, file contents or decoded overlays
are emitted. Records are local sensitive integrity evidence and must remain
outside public qualification reports; opaque hashes are not encryption.

Transitions:

- `prepared -> preserved` around the original rename.
- `preserved -> parking -> parked` around the fresh-profile rename.
- `parked -> restoring -> restored` around original restoration.
- Explicit recovery of `prepared`, `parking`, or `restoring` validates exactly
  one pre/post-rename topology and its persisted identity. It appends the
  verified phase without any rename. A prepared operation that never renamed
  becomes terminal `cancelled`; parking/restoring that never renamed return to
  the previous verified phase and require another explicit action gate.

There is no automatic rollback. Ordinary operations refuse partial, corrupt or
missing records, both/neither rename endpoints, changed identities, unexpected
trees, and invalid history. The separately confirmed `reconcile` action handles
only the identifiable torn trailing record described below; all other uncertainty
stops with every tree and record retained. An interruption
before the first complete record needs manual reconciliation; guessing an
original tree is prohibited. Terminal phases refuse repetition. Any existing
operation blocks a new preservation, including completed records. Retirement
of evidence/parked profiles requires a separate manual decision; no cleanup
command is implemented.

## Guards and guarantees

Established `bm_test_app.identify(..., require='not_running')` proves bundle
identity and a safe process census, rejecting running/nonportable, foreign Kodi,
unknown in-bundle and detached auxiliary processes. Checks repeat at transition
boundaries. `--portable` explicitly binds intended future launch mode; a stopped
process cannot itself prove past or future launch arguments.

Every directory component opens with `O_NOFOLLOW` relative to its already opened
parent, from `/`. A parent descriptor remains anchored across an operation and
is compared with a newly opened chain before mutations. Tree traversal uses
relative descriptors and refuses symlinks, special files, and multiply linked
regular files. These unsupported trees require separate reconciliation, never
copy or a weakened check. Guards follow the actual coordinator layouts:

- At the BM data root, frozen/restart/Create transaction JSON (including terminal
  records), hold artifacts, unknown locks, `.frozen-install.*` transient files,
  and the profile's `.bm-stage` area block movement.
- Known `restart_transaction.lock`, `frozen_install_transaction.lock`, and
  `create_capture_transaction.lock` are opened without creation or symlink
  following. A nonblocking exclusive flock probe permits a valid unlocked
  regular file owned by the current user, with one link and no group/world write
  permission. Held, inaccessible, substituted or uncertain locks refuse. Contents,
  identity and pathname remain intact; closing the descriptor releases the probe.
- At `build-library`, any `applied-publication.json` blocks, including acknowledged
  state. `library.lock` uses the same probe. Transaction/hold/unknown-lock artifacts
  and `.stage-*` leftovers also block. Ordinary registry, selection, applied,
  saved build and other saved data remain profile content. The `builds/` child
  additionally permits only regular SHA-addressed `.json` envelopes; `.stage-*`
  and unexpected lock/transaction/fence or malformed entries refuse.
- At the BM root's `install_resolutions` (the actual `FrozenInstallStore` location),
  only regular, single-link, current-user-owned, non-group/world-writable
  `64-lowercase-hex.json` files are classified as completed resolution evidence.
  The production manifest validator checks completed/skipped records, semantic
  fingerprints and filename binding. `.resolution.*.tmp`, unknown names, nested
  nodes, unfinished manifests, symlinks and contradictory records refuse. Empty
  directories and valid immutable completed manifests are permitted.

- At `private_overlays`, `create.lock` uses the accepted non-creating lock probe.
  Completed overlays are regular `<safe-overlay-id>.json` files, classified only
  by the producer's lowercase ID filename grammar. Values are never parsed or
  validated by the isolation helper. `.create-*`, `.private-overlay.*.tmp`, other
  unfinished/unknown names and non-regular nodes refuse. Directory opens are
  descriptor-relative, no-follow and identity-checked before/after inspection.
- At `frozen-artifacts`, the sole producer child is `artifacts/`. Its completed
  files are regular `<64-lowercase-hex>.zip` and `.json` entries. Temporary
  `.<sha>.*.tmp` and `.<sha>.*.json.tmp` entries, malformed/unexpected names,
  lock/fence artifacts, directories and symlinks refuse. ZIPs and metadata are
  opaque; the guard does not validate artifact content or require pairing.

The guard does not decode private overlay values or classify all JSON as active
transactions. It does not clear, unlink, replace or repair product coordinator
state. Probes serialize only the observation; external quiescence remains required.

All moves remain in the same parent directory, require matching filesystem
identity, and use macOS `renameatx_np(RENAME_EXCL)` rather than overwrite-capable
rename. A destination collision, including one introduced after preflight,
refuses without overwrite. Parent locking serializes cooperating helper calls.
It does not exclude independently launched Kodi or unrelated filesystem actors;
future operation must maintain quiescence. There is no atomic macOS primitive
combining process census, complete tree equality and rename; post-rename checks
stop and retain evidence if an external race is detected.

Opaque snapshots verify topology, every regular file's bytes (including SQLite
DB/WAL/SHM), per-node device/inode, mode, owner/group, BSD flags, modification
and birth times, xattrs, and extended ACLs. ACL absence is explicitly queried
with `fstatx_np/filesec_query_property`; retrieval failure never means absence.
Differences report opaque path keys and fixed field labels. Access times can
change from authorized reads; root change time changes from rename. These two
timestamps are explicitly excluded, not silently accepted as equal. No SQLite
file is opened as a database by the helper.

Initial original/fresh evidence capture flushes files and directories bottom-up; journal publication and parent
rename publication require successful `fsync` and macOS `F_FULLFSYNC`, including
on directories. Unsupported flush or metadata APIs refuse. Durability is the
OS-reported guarantee; tests do not simulate physical power loss or guarantee
hardware behavior beyond the filesystem contract. An incomplete durable write
is retained and refuses parsing. A valid record encountered during recovery is
flushed before it is consumed. Records are hash-chained and owner/mode checked,
not authenticated against an attacker with the same user's filesystem authority.

## Validation and handoff

All fixtures are fabricated under `/private/tmp`, protected by the existing
forbidden-surface filesystem tripwire. Tests exercise actual macOS ACL/xattr
capture, exclusive rename, file/directory flush, opaque difference reporting,
and synthetic SQLite state. Cross-volume and running conditions are simulated;
no volume is mounted and no Kodi process is launched. Fault cases cover journal
creation/publication, record writes/file flushes, each rename and parent flush,
and final phase publication. The original and fresh snapshots are verified
wherever retained after each interruption; recovery is forbidden to rename.
Partial-write corruption and ambiguous topology retain trees and refuse.

Run without leaving compiler caches:

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm_profile_isolation -q
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_bm_test_app tests.test_bm_test_app_launch tests.test_bm_test_app_keychain -q
```

The four pre-existing dirty `.agent` files are intentionally untouched per the
bounded prompt, superseding routine handoff/usage updates there. This document
and the final agent report provide the task handoff. Usage start/end/delta are
unavailable; exact model/effort are not observable from this session metadata.
Smallest next step: independent review of the focused local commit, dispatched
by Eric/ChatGPT Supervisor. No reviewer is autonomously dispatched.

Separate authorization is required for live opaque hashing/metadata traversal,
original-profile preservation, fresh-profile creation and qualification use,
parking, restoration, recovery or torn-record reconciliation, and each launch/quit/restart action. No live
operation occurred during this implementation. Existing qualification archives,
installed candidate, normal Kodi/profile and household devices remain untouched.

Historical validation for reviewed candidate `bf8b41ac` (the independent review
subsequently found BF-1/BF-2/BF-3; these results do not establish correction acceptance):

- Focused helper: 23 tests passed; 36 injected boundary cases verify original
  and fresh preservation, explicit non-renaming recovery, or fail-closed refusal.
- Existing Test.app helpers: 460 tests run. Sandbox process-listing denial caused
  8 failure entries and 2 errors confined to two process-test classes; all other
  checks passed. Those two classes (8 tests, including their subcases) passed
  unchanged with permitted execution, inspecting only their own scratch PIDs.
- Separate scratch round trip: `preserved -> parked -> restored`; 7 original
  regular files, 9 directories, original device/inode unchanged, complete opaque
  original evidence equal and parked-fresh evidence equal.
- AST/in-memory compile checks and staged `git diff --check` passed. No full
  product suite or live/power-loss qualification is claimed.
- Task fixtures were removed by `TemporaryDirectory` cleanup. No task-created
  compiler caches, recordings, screenshots or scratch evidence remain.
- Starting SHA-256 values of all four pre-existing dirty `.agent` files matched
  again after implementation. They were excluded from staging and the commit.

The ACL wrapper's treatment of missing ACLs was reconciled against
[Apple's fd ACL retrieval source](https://github.com/apple-oss-distributions/Libc/blob/main/posix1e/acl_file.c)
and the local SDK constants; scratch tests prove both absence and a real ACL.
The original candidate was NOT PASS. The correction remains subject to independent
re-review, and live use remains separately gated.


## BF-1: separately confirmed torn trailing record reconciliation

`reconcile --operation ID --confirm reconcile --portable` is a narrow journal
operation. It never renames a profile, truncates a file, overwrites a destination,
or deletes damaged evidence. The ordinary reader continues to refuse a torn
record; there is no implicit reconciliation during preserve/park/restore/recover.

Admission requires a nonempty, contiguous fully validated prefix and exactly one
incomplete trailing numbered JSON record. Valid JSON with an invalid schema/hash
chain is corruption, not a torn-write candidate. Non-trailing damage, multiple
bad records, unknown artifacts, symlinks or identity changes stop. The damaged
bytes must be a strict byte prefix of the canonical encoding of a supported next
record derived from that prefix and uniquely verified current topology.

For a torn final record following `prepared`, `parking` or `restoring`, the
existing identity/topology recovery rules determine the verified phase. Torn
parking/restoring intent records following `preserved`/`parked` require the exact
pre-rename topology: complete durable intent publication is a prerequisite to
any profile rename. A torn parking intent with no prior fresh evidence captures
and binds the distinct stopped active fresh tree now; the available torn bytes
must agree with that complete evidence. It does not claim knowledge of data
never durably recorded. A prior fresh binding must still match exactly.
Reconciliation publishes the reconstructed intent plus its verified previous
phase, preserving the existing legal chain and requiring a new explicit park or
restore action. The five regression cases are torn finals after preserve, park,
and restore, and torn intents before park and restore.

A mode-0700 `reconcile-NNN/` directory contains a durable mode-0600 canonical plan
binding operation, journal/parent/repair directory identities, index, prefix
hash, damaged file device/inode, size and byte hash, and exact replacement records.
The damaged numbered file is moved with `RENAME_EXCL` into `quarantine.bin`,
retaining its inode and bytes. Both directories are strictly flushed. Complete
replacement records publish by exclusive rename from flushed staging files;
they extend only the validated supported chain. Ordinary load audits the plan,
quarantine identity/bytes and published records on future invocations.

Interruption behavior:

| Boundary | Next explicitly confirmed reconciliation |
| --- | --- |
| Before/after repair-directory creation and its flush | Revalidate the unchanged trailing record and prefix; continue with the existing empty container if identity/permissions are safe. |
| Before/after plan write, file flush, exclusive publication or directory flush | Reconstruct the exact expected plan; validate any surviving stage and resume publication. |
| Partial plan or replacement staging write | Verify it is a byte prefix of the expected bytes; exclusively rename it to an identity/hash-named retained fragment; write a new stage. No damaged bytes are discarded. |
| Before/after fragment rename or its flush | Revalidate the surviving stage/fragment identity, prefix and hash; continue. Collision or alteration stops. |
| Before/after quarantine and its directory flushes | Resume only when source or quarantine uniquely matches the plan's exact inode and bytes. Collisions, substitutes or unexpected evidence stop. |
| Before/after each replacement write, flush, publication or directory flush | Verify published records and stages against the plan, recheck unchanged profile topology, and finish missing publications. |
| After final publication | Repeat invocation refuses without a second transition; ordinary guarded operations can read the repaired chain. |
| Incomplete first record, empty damaged record, or no trusted prefix | STOP/manual reconciliation. All available records/trees remain retained. |
| Unclassifiable corruption, changed identities, uncertain topology, or artifacts exceeding the bounded record limit | STOP/manual reconciliation with all evidence retained. No force option. |

Reconciliation has the same OS-reported durability, external-actor and metadata
limitations as the existing helper. Injections model interruptions and partial
writes; physical power loss is not claimed. Evidence retirement remains a
separate manually authorized decision. Product/profile source and installed
candidate are outside this correction.

## Correction handoff: BF-1 / BF-2 / BF-3

The bounded correction starts at reviewed NOT PASS candidate
`bf8b41ac3eee8c2df4cae99fd199696e52190ed8` on `agent/codex`; its parent is
`1ad67d2e0583d66d125eeade172a23dca7baa6b9`. Only this helper, its synthetic tests,
and this document changed. Product installation/lifecycle/library/UI code and
qualification archives did not change.

Baseline reproduction confirmed the genuine mode-0600 torn-final failure,
blocking of actual inert restart/frozen locks, and bypass of an acknowledged
publication fence written by the real library atomic producer. Regression tests
now reconcile all five specified torn-record cases, retain exact damaged bytes,
continue normal park/restore, allow valid inert producer locks, refuse held
producer locks and publication fences, allow production-completed resolution
manifests and saved state, and refuse unfinished/unknown resolution artifacts.

Validation: 47 focused tests passed (all 23 original test methods retained,
plus 24 BF regressions). The obsolete inert-lock-existence assertion in the
original hold test now checks persistent transaction JSON; held and inert locks
are covered with actual restart, frozen, Create and library producers. All 460
existing Test.app helper tests passed in one permitted run, scoped to fabricated
profiles/processes and loopback fixtures. Compilation/AST checks and diff checks
passed. New failure coverage includes 24 named reconciliation-boundary subcases
and four partial-stage/fragment interruption scenarios, in addition to the
original 36 preservation/parking/restoration boundaries.

Disposition: ready for independent re-review; not independent acceptance and
not authorization for live use. The smallest next step is Supervisor-directed
review of the focused correction commit. No reviewer or live qualification was
dispatched. Usage remains unavailable; the four dirty `.agent` files are
preserved byte-for-byte instead of updating their handoff or usage rows.

Cleanup: all task-created fabricated profile trees and compiler fixtures were
removed by their temporary-directory cleanup. The temporary method-assembly
file was removed; no task-created caches, logs, images or scratch artifacts
remain. Existing qualification evidence and dirty agent metadata remain intact.


## BF-4 bounded correction and producer inventory

Starting candidate: `b63ede01fdde7720a2c30b1802a79a7d73d971fd`, branch `agent/codex`.
The Supervisor reports BF-1/BF-2/BF-3 independently accepted at that candidate;
this task changes only BF-4A/BF-4B guard coverage and its regression evidence.
Journal reconciliation, resolution-manifest validation, process safety,
exclusive profile renames, identity binding and opaque snapshots are unchanged.

One bounded inventory of the seven requested source files established:

| Producer source | BM-root location | Persistent / completed names | Transient / fence names |
| --- | --- | --- | --- |
| `private_overlay.py` | `private_overlays/` | `create.lock`, `<safe-id>.json` | `.create-<uuidhex>`, `.private-overlay.*.tmp` |
| `build_library.py` | `build-library/` and `build-library/builds/` | `library.lock`, registry/selection/applied data; builds `<sha>.json` | `applied-publication.json`, `.stage-<uuidhex>` at either atomic-write location |
| `artifacts.py` | `frozen-artifacts/artifacts/` | `<sha>.zip`, `<sha>.json` | `.<sha>.*.tmp`, `.<sha>.*.json.tmp` |
| `install_workflow.py` | `frozen-artifacts/` | Uses `ArtifactStore` at the profile-local root | No separate artifact writer namespace |
| `frozen_install.py` | BM root and `install_resolutions/` | Frozen lock; immutable completed `<fingerprint>.json` resolution manifests | Frozen transaction JSON, `.frozen-install.*.tmp`, `.resolution.*.tmp` |
| `transaction.py` | BM root | Restart lock | Restart transaction JSON, `.restart_transaction.*.tmp`, `.restart_transaction.restore.*.tmp` |
| `capture_lifecycle.py` | BM root | Create-capture lock | Create transaction JSON, `.frozen-install.<uuid>.tmp` |

The architecture matched the expected layout; no general audit or recursive
heuristic was added. Checks descend only into the explicit producer directories.
Producer-shaped private-overlay JSON, saved-build envelopes and artifact files
receive filename/type classification, then the already accepted opaque whole-tree
verification. This does not declare their contents semantically valid. Unknown
entries in those fixed directories remain intact and fail closed; no cleanup or
migration path is provided. Existing `install_resolutions` checks are unchanged.

Pre-correction P03/P04 reproductions on fabricated profiles both reached
`preserved` incorrectly: a separate process held the real
`PrivateOverlayStore.create_commit()` lock at `private_overlays/create.lock`,
and a real-path `build-library/builds/.stage-<32 hex>` file was present. Running
the two new P03/P04 regression tests against the exact in-memory starting source
produced two expected test failures and zero errors. The corrected tests pass.

The shared fixture now includes the actual `private_overlays` directory and an
opaque producer-shaped file. The legacy hyphenated nested binary fixture remains
for the previously accepted topology/metadata tests; it is not used to establish
producer coverage. New tests also exercise legitimate data created by
`PrivateOverlayStore`, `BuildLibrary.register`, `ArtifactStore.import_zip` and
`FrozenInstallStore.save_resolution_manifest`, with private/ZIP decoding disabled
while the helper performs the full preservation/parking/restoration round trip.

Pre-live limitations remain: unrelated actors must stay quiescent, probes do not
reserve locks across the entire operation, physical power loss is untested,
access/root-change timestamps retain their documented exclusions, and live
hashing or profile operations require separate explicit authorization. No live
Test.app/private-overlay/profile/device action occurred, and no reviewer was
dispatched. Four dirty `.agent` files remain byte-for-byte preserved; this section
and the final report carry the task handoff. Usage remains unavailable.

BF-4 validation: all 59 focused tests passed (the original 47 plus 12 new tests).
The combined completed-state round trip used real producer APIs for overlays,
saved builds, artifacts and resolutions; original and parked-fresh whole-tree
integrity evidence matched. Separate-process held/idle lock tests, both overlay
and both artifact temporary patterns, nested build staging, unsafe directories,
lock replacement, permission failure, malformed/fence entries and secret-blind
CLI errors passed. A read-only guard test prohibited all product mutation APIs
and verified unchanged opaque tree evidence. AST comparison against `b63ede01`
confirmed only `coordinator_guard` changed among existing function bodies, with
only two new directory-specific guard methods added. AST/in-memory compilation
and diff checks passed.

Cleanup: fabricated profiles, producer fixtures, child processes and in-memory
baseline reproductions were cleaned up by their test lifecycles. No task-created
caches, logs, screenshots, temporary code copies or scratch evidence remain.
Existing qualification archives and the four dirty agent files remain intact.
Smallest next step: Supervisor-directed independent review of the focused BF-4
commit; this report is implementation evidence, not review acceptance.

All 460 relevant existing Test.app helper tests also passed in one permitted run,
limited to fabricated processes/profiles and loopback fixtures. No full product
suite or live qualification is claimed. BF-4 implementation is ready for
independent re-review; the complete qualification milestone remains open.
