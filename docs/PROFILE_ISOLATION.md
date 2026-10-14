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

There is no automatic rollback. Empty, partial, corrupt or missing records,
both/neither rename endpoints, changed identities, unexpected trees, or invalid
history stop with all available trees and records retained. An interruption
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
copy or a weakened check. Any persisted transaction/hold/lock filename in the
Build Manager data directory, or a `.bm-stage` area, blocks the move, including
terminal transaction evidence: this helper does not clear or interpret it.

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
parking, restoration or recovery, and each launch/quit/restart action. No live
operation occurred during this implementation. Existing qualification archives,
installed candidate, normal Kodi/profile and household devices remain untouched.

Validation recorded for this candidate:

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
Implementation is ready for independent review, with live use separately gated.
