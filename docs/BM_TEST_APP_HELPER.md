# Build Manager Test.app qualification helper

`tools/bm_test_app.py` is the host-side helper for macOS Beta Qualification. It
stages an exact Git-pinned Build Manager candidate into the portable
`Kodi Build Manager Test.app`, proves what is installed, triggers the BM-023A
adapter over loopback JSON-RPC, and collects secret-blind evidence. It replaces
the retired ai-supervisor actions; it needs no framework state. Tests:
`tests/test_bm_test_app.py` (temporary fixtures only).

**Status.** Implemented and tested offline against fake bundles. The current
six-blocker correction requires fresh independent correction-delta review
before any live staging, launch or runtime qualification.

## Safety boundary

- The only target is `/Applications/Kodi Build Manager Test.app` (portable
  `-p` data under `Contents/Resources/Kodi/portable_data`). The path is a
  constant: there is no command-line or environment override. Internals take an
  injected target so tests use fake bundles.
- Normal `/Applications/Kodi.app` and `~/Library/Application Support/Kodi` are
  refused before filesystem traversal. Leading slashes are collapsed,
  `/System/Volumes/Data` spellings share the ordinary path identity, and opaque
  `.vol`, `.nofollow`, and `.resolve` namespaces fail closed. These rules also
  apply to all four paths in the six-value adapter config; existing symlink
  components are refused. Normal Kodi surfaces are never stat'ed, listed or
  opened. Any Kodi-like process outside the authorized bundle is refused too.
- Every command starts with `identify`: Info.plist identity, no symlink in the
  bundle and portable-data ancestor paths, and either no process or exactly one
  process of the authorized executable (optionally accompanied by the one
  sanctioned auxiliary described below). macOS `proc_pidpath` supplies executable
  identity; `sysctl(KERN_PROCARGS2)` supplies actual argv boundaries. `argv[0]`
  must agree with the kernel path. Portable `-p` must precede any unknown or
  value-taking option; only known boolean launch flags may precede it. Embedded
  text and `--datadir "-p"` are refused; use the documented `--args -p` launch.
  Unreadable process identity fails closed. The one exception is a PID that
  exited after the `ps` snapshot: only when that same `proc_pidpath` call fails
  with `ESRCH` is the stale PID omitted from the census. Any other failure
  (`EPERM`, `EACCES`, errno zero, a malformed result) is `process_listing_failed`.
- **Sanctioned auxiliary process.** A normal portable launch of the Test.app
  starts, besides the main executable, exactly one `XBMCHelper` (observed on
  both an existing and a completely fresh profile). `identify` recognizes only
  the exact kernel executable path
  `Contents/Resources/Kodi/tools/darwin/runtime/XBMCHelper` under the authorized
  bundle (or its already-sanctioned `/System/Volumes/Data` spelling) as that
  auxiliary. It is never matched by basename, substring, suffix, process name,
  argv or parent PID. While one main portable process is present, exactly one
  such auxiliary is accepted; the main process must still pass every check above
  on its own, because the auxiliary proves nothing about it. Everything else
  stays refused with `test_app_process_mismatch`: any other executable inside the
  bundle (with or without the auxiliary), lookalike paths, and more than one
  auxiliary. A detached `XBMCHelper` without a main Kodi process is **not** a
  quiescent `not_running` state: `identify` refuses it, so `require="not_running"`
  (used by `stage`) succeeds only when there is no main process, no sanctioned
  auxiliary and no other in-bundle process. A recognized auxiliary is reported
  as `process.auxiliary: "XBMCHelper"` and `process.auxiliary_process_count: 1`
  (both omitted when there is none); no path, pid or argv of it is emitted.
- Candidate bytes come from Git objects of an explicit full commit id, never
  from working-tree files.
- No password in argv, environment, config, logs, output or evidence.
- Output is JSON only; fixed error codes; no exception text, file contents or
  private values. A final guard blanks any output containing a registered
  secret (password, Basic token, machine-local config paths).

## Commands

All commands print one deterministic JSON document (sorted keys, ASCII) and
accept `--output FILE` (written once, never overwritten).

| Command | Purpose |
| --- | --- |
| `identify` | Read-only bundle/process identity. Launches nothing. |
| `stage --candidate SHA --config CFG --evidence-dir DIR [--repo R] [--dry-run]` | Install the candidate while the Test.app is **not running**. `--dry-run` builds and reports only. |
| `verify --manifest M [--repo R] [--no-git-binding]` | Read-only proof that installed trees equal the manifest (and, by default, the Git commit). |
| `run MODE --manifest M [--config CFG] [--rpc-host H] [--rpc-port N] [--rpc-user U] [--timeout S]` | `MODE` is `install`, `retry`, `recover` or `status`. Needs a running portable Test.app. |
| `quit [--config CFG] [--rpc-host H] [--rpc-port N] [--rpc-user U] [--timeout S]` | Gracefully quit the running portable Test.app (`Application.Quit`) and prove it exited. Never sends a signal. |
| `snapshot [--manifest M] [--library-baseline]` | Read-only, secret-blind census of the portable data. |

Exit codes: `0` success, `1` failed closed, `2` usage/config, `4` the adapter
reported failure (fresh evidence was captured), `130` interrupted.

`--repo` defaults to this checkout (object data only; a dirty or different
checked-out tree does not matter). `--no-git-binding` is weaker: the output then
says `installed_equals_candidate: false`.

## Machine-local config (`stage`, optionally `run`)

A JSON file owned by you and not group/world writable. It holds no credentials;
any key resembling a credential is refused. Real values stay out of Git.

```json
{
  "schema": "bm-test-app-config/1",
  "adapter": {
    "MANIFEST_PATH": "/abs/path/frozen-manifest.json",
    "ARTIFACT_ROOT": "/abs/path/artifacts",
    "CONFIGURATION_PATH": "/abs/path/configuration.json",
    "OVERLAY_SOURCE": "/abs/path/private-overlay.json",
    "DEVICE_PROFILE_ID": "device-profile-id",
    "EXPECTED_OVERLAY_ID": "overlay-id"
  },
  "rpc": {"host": "127.0.0.1", "port": 8080, "username": "kodi"}
}
```

`rpc.host` must be a loopback IP literal (`127.0.0.1`, `::1`, or `localhost`,
which maps to `127.0.0.1` without resolving). The port has no default.

## Candidate binding and the stage manifest

`stage` reads the product set with `git ls-tree` + `git cat-file --batch`
(replace refs, user config and attribute filters cannot alter bytes; every blob
is re-hashed). The product set is exactly `addon.xml`, `default.py`,
`service.py` and `resources/**` (regular files only; symlinks, gitlinks and
case/Unicode path collisions are refused). `.agent/**`, `.orchestrator/**`,
tests and docs are never staged.

The driver is built by running the **candidate's own**
`tools/build_bm023a_adapter.py` against a temporary export of that commit. The
six config values reach it through a private 0600 file, never argv. The helper
then checks the output: exactly the five driver files, four of them byte-equal
to candidate blobs, `adapter_config.py` carrying the configured values and the
candidate's `frozen_install.py` digest, and driver version == `ADAPTER_VERSION`.

`stage_manifest.json` records the candidate commit/tree/blob ids, per-file path,
SHA-256 and size for both add-on trees, add-on and adapter versions, the driver
tree and entry-point hashes, a creation time, a configuration fingerprint (never
the values), and the helper's own SHA-256.

## Staging semantics

1. Build in an exclusive private temp workspace under validated `/private/tmp`
   (removed afterwards). Inherited `TMPDIR` never chooses workspace placement.
2. Validate the entire bundle/portable-data component chain before staging,
   and recheck the chain immediately before swapping. Create
   `portable_data/.bm-stage` (exclusive; its existence is the lock and a
   stale one is never deleted) and write both new trees there, then verify them
   against the manifest. It must share a device with `addons/`.
3. Copy every tree about to be replaced into the evidence directory
   (`<evidence-dir>/stage-<UTC>-<sha12>/replaced/<addon-id>`) and verify the copy.
4. Durably publish the backup hierarchy bottom-up (files, symlinks and directory
   entries), the run directory and its evidence parent with strict directory
   fsync. Publish the new staging hierarchy too. Any durability failure prevents
   the swap. Re-check that the Test.app is not running, then pin device/inode
   identities for the entire bundle ancestor chain, `addons`, `.bm-stage`, and
   its `new`, `old`, and `failed` directories.
5. Rename live to `old/` and new to live for both add-ons; strictly fsync both
   source and destination parents after every rename. Until the durable commit
   boundary, any exception or interrupt attempts bounded rollback. Before each
   rollback inspection/rename, check every pinned directory shallowest-first.
   A symlink or a different real directory is `rollback_ancestor_unsafe`: stop
   without further mutation and preserve stage, old trees and evidence. Rollback
   renames also sync both parents; a rollback failure preserves the area.
6. Verify the live candidate, recheck evidence backups, fingerprint moved-old
   trees against backup digests, and complete the final directory fsync/identity
   checks. Only then reach the explicit durable commit boundary (`durable_commit:
   true`) and allow conservative stage cleanup to discard old trees. Successful
   rollback restores originals and re-raises the original exception (interrupt
   remains exit 130). A backup mismatch retains staging evidence even after
   originals are restored. Cleanup and result reporting follow commit; their
   failures cannot undo a committed stage. Unit tests prove fsync ordering and
   failure handling, not power-loss survival on hardware.

Evidence per run: `stage_manifest.json`, `stage_result.json`, `replaced/`.
`userdata` is never touched.

## `run`

Checks, in order: identity (running, one portable main process, optionally with
the sanctioned `XBMCHelper` auxiliary), installed trees ==
manifest, result path safe, then before every request (including authenticated
retries) refresh the full trusted executable and portable argv identity, require
one authorized process with the original PID, and check the listener on the RPC
port is exactly that PID. Kodi's own view of the driver and Build
Manager (`Addons.GetAddonDetails`) must be enabled with the staged versions;
nothing is enabled for you. The driver is invoked once with
`Addons.ExecuteAddon {params: MODE, wait: false}`.

If the web interface demands authentication the password is requested on the
controlling terminal (`/dev/tty`, never stdin) and kept only in memory. With no
terminal the command fails closed.

Success is the adapter's fresh result file, not Kodi's `OK`: it must have a new
inode or new content since before the call, be written after the invocation, and
carry the requested `adapter_mode`. Only allowlisted fields survive; unknown
keys and invalid values are withheld and counted. The installed trees are
verified again after the run. `adapter_ok` reports the adapter result separately;
overall `ok` requires both adapter success and final installed-tree equality.
Source drift retains the verification problems and exits 1; adapter failure
retains exit 4. Invalid final runtime identity or a verification error fails
closed even when a fresh adapter result exists.

## `quit`

The normal, graceful shutdown for the qualification restart. Kodi persists
global settings (including `general.addonupdates`) through its normal application
stop, not when a setting is changed, so a signal-terminated Test.app can lose a
policy that a graceful exit keeps.

Checks, in order: identity (running, one portable main process, optionally with
the sanctioned `XBMCHelper` auxiliary), loopback RPC settings (same
`--config`/`--rpc-*` model as `run`; the port has no default), `JSONRPC.Ping`,
then exactly one `Application.Quit`. Full executable/portable argv identity is refreshed before every request;
the listener on the RPC port must then be the authorized original PID, and credentials come through the same
`Services.password_prompt` seam as `run`. It then waits up to `--timeout`
seconds (default 60, 1 to 300) for `identify(require="not_running")` to hold: no
main process, no sanctioned auxiliary, no other in-bundle process. While the
census only says the shutdown is unfinished (main still running, a lingering
auxiliary, or a process that vanished between the listing and its identity read)
the helper keeps polling. A foreign Kodi, a second main process, a non-portable
instance or an unreadable listing fails immediately.

Success prints `graceful: true` and `shutdown.forced_termination: false` together
with the identity before and after. Failures:

- `kodi_quit_rejected`: Kodi answered `Application.Quit` with an RPC error or
  anything other than `"OK"`. Nothing is waited for.
- `kodi_quit_timeout`: the census was not `not_running` before the deadline
  (`last_observation` and `polls` say why). The process is left alone.

On either failure the helper stops. It never sends a signal, never escalates, and
contains no `kill`, `pkill`, `killall` or `osascript` behavior. A forced
termination is an external emergency action and is never graceful qualification
evidence. If the reply to `Application.Quit` is lost (`rpc_transport_failed`),
run `identify` before trying again: the helper does not assume Kodi quit.

## Credentials for `run` and `quit`

`run` and `quit` need a password only if Kodi's web interface answers `401`. Two entry
points supply it through the same reviewed `Services.password_prompt` seam; every
other protection (Test.app identity, portable `-p`, exact listener PID, loopback
validation, Git binding, installed-tree verification, result freshness, the
secret registry and the output leak guard) stays inside `bm_test_app.py`.

- `tools/bm_test_app.py` (direct): a hidden prompt on the controlling terminal
  (`/dev/tty`, never stdin). Use it when the password is entered by hand.
- `tools/bm_test_app_keychain.py`: same arguments, JSON output and exit codes,
  but the password comes from one fixed macOS Keychain item read inside the local
  process (service `ai-supervisor.test-app-kodi`, account `kodi`), so an agent
  that runs it never receives the password. The lookup is exactly
  `/usr/bin/security find-generic-password -a kodi -s ai-supervisor.test-app-kodi -w`:
  argv list, no shell, stdin closed, stderr discarded, fixed minimal environment,
  15 s timeout, strict validation of the item. The item identity is a constant of
  that file; it cannot come from the command line, environment, config or stdin.

Both entry points require a password of at least **8 characters**. After a 401,
the shared helper rejects shorter supplied passwords with fixed
`credential_unsupported` before any authenticated retry. Supported passwords
and Basic tokens are registered with the output leak guard. The Keychain path
uses this same policy and never falls back to interactive prompting.

No password belongs in a config file, argument, environment variable or stdin;
neither entry point accepts one. The Keychain wrapper **fails closed and never
falls back to the interactive prompt**, so an unattended run cannot hang waiting
for a person: an unusable item is `credential_missing`, a lookup that could not
run (missing binary, timeout, OS error) is `credential_prompt_unavailable`, and
neither carries `security` output. A stale password is not masked: Kodi rejecting
it still ends as `rpc_auth_failed`. The wrapper is host-side qualification
tooling; it is never staged into Kodi and is not part of the Build Manager
product.

## `snapshot`

Ordinary `snapshot` omits `build_library` and does not read Build Library paths;
its existing supported running/stopped process states remain available.

`snapshot --library-baseline` is an opt-in STOPPED / WRITER-FREE qualification
operation. Full helper identity with `require="not_running"` is enforced before
any library read: exact authorized bundle, zero Test.app main processes, no
foreign/ambiguous Kodi process, and valid portable layout. Two complete,
independent library censuses open and close their own no-follow descriptors.
Their secret-blind projections must match exactly, including absence, hashes,
sizes, counts, IDs and selection. A mismatch fails with the fixed error
`build_library_state_changed`, without samples or old/new values. Immediately
before success, full `not_running` identity is enforced again. A running app or
ambiguous identity fails closed without returning a library baseline.

Test.app must remain stopped for the entire operation. No separate host process
may invoke BuildLibrary mutation APIs against this profile concurrently; the
qualification controller/agent must exclude such writers during the bounded
operation. There is no product-wide lock for an absent library root that this
read-only helper can acquire without mutation. No helper lock/root is created.
The stopped contract excludes Kodi's normal product writer; two matching samples
provide additional change detection. This is not atomic against arbitrary host
processes: an injected external writer after the final sample is outside the
supported contract, as is launching and stopping Test.app between identity checks.

The PUBLIC Build Library baseline reads exactly `build-library/registry.json`
and `build-library/selection.json` beneath the authorized portable BM data root.
It reports root/file presence, SHA-256 and byte size, sorted registry entry IDs
and count, and selected entry/profile identity. Registry metadata is validated
but never emitted. No build envelopes, packages, private overlays, or Red Light
addon data are read. This is intended for before/after qualification baselines;
the helper does not compare snapshots or validate selected bundle semantics.

Only public state schema v1 is supported, with exact key sets, integer version,
64 lowercase hex entry IDs, string metadata and string-list profiles. Duplicate
JSON keys are rejected. A selected entry must exist in the registry and its
profile must occur in that entry's metadata. Safe profile IDs use 1–100 ASCII
letters, digits, dots, underscores or hyphens; other strings become a stable
SHA-256 digest marker. Arbitrary metadata strings and paths are never emitted.

An absent root or registry means an empty registry; absent or JSON-null selection
means no selected build. Existing files retain hash/size even for JSON null.
Malformed, inconsistent, unreadable, oversized, nonregular or unsafe state fails
snapshot with `build_library_state_invalid`, without raw values or paths. Each
file is limited to 1 MiB. Reads pin no-follow directory descriptors for every
ancestor and open only regular no-follow, nonblocking leaves. Nothing is created,
repaired, locked, selected or written.

**This helper source change invalidates the previous live-use clearance until
the new helper blob receives independent review. Live-use clearance is PENDING;
this version is not cleared.**


Other snapshot reads: add-on `addon.xml` files, the newest `Addons*.db` (read-only,
immutable), two values from `guisettings.xml` (updater policy, skin id; the
rest is discarded unread), and the four frozen/restart transaction and lock
files plus the adapter result through the product's bounded status reader. A
positive allowlist guards every read; `addon_data/plugin.video.redlight/**` and
`private_overlays/**` are explicit denials. `guisettings.xml` and the database
may lag a running Kodi; `run status` reports the in-Kodi state.

For BM-UI-003C, take the pre-staging/pre-Create baseline with Test.app stopped
using `snapshot --library-baseline`. For Preview-Cancel, perform the UI scenario,
gracefully stop Test.app using the cleared helper, take the same baseline and
compare with pre-Create, then relaunch for successful Create. Post-Create, verify
Build Status while running, gracefully stop Test.app, and take the opt-in
baseline to prove registry/selection persistence. These are qualification steps;
the helper does not orchestrate them. Live-use clearance remains PENDING
independent review of this correction.

## Typical sequence

Use this normal/default background launch command; `-p` is mandatory. A
specific validation task may explicitly require foreground activation.

```text
identify
stage --candidate <sha> --config <cfg> --dry-run            # inspect the manifest
stage --candidate <sha> --config <cfg> --evidence-dir <dir>
verify --manifest <dir>/stage-.../stage_manifest.json
open -g "/Applications/Kodi Build Manager Test.app" --args -p
run status --manifest ... --config <cfg>
run install | retry | recover --manifest ... --config <cfg>
quit --config <cfg>                                          # graceful stop; see the restart sequence below
snapshot --manifest ...
```

## Qualification restart sequence

A restart in the middle of a frozen install must keep the global updater
quarantine. Build Manager writes `general.addonupdates = NEVER_CHECK` once, at the
initial install; after a process restart it only **reads** the policy and
continues only if it is still `NEVER_CHECK` (see `FROZEN_BUILD_INSTALL.md`).
Restart the Test.app like this:

```text
quit --config <cfg>                       # graceful Application.Quit; proves not_running
snapshot --manifest ...                   # persisted guisettings: settings.updater_policy
                                          #   REQUIRE "NEVER_CHECK"; anything else is a HARD STOP
open -g "/Applications/Kodi Build Manager Test.app" --args -p
identify                                  # one portable process
(the Build Manager service continues with a verify-only resume)
run status --manifest ... --config <cfg>  # or snapshot, to observe the outcome
```

A persisted policy other than `NEVER_CHECK` (or an unreadable one) is a hard stop:
do not relaunch to "see what happens", and do not rewrite the setting by hand or
with a signal-based restart. A failed `quit` is evidence too; preserve it and
investigate.

If a held retry fails or state is contradictory, stop and preserve evidence; do
not improvise another recovery. The helper has no reset or delete command and
never edits transaction or lock files.
