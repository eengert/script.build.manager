# Build Manager Test.app qualification helper

`tools/bm_test_app.py` is the host-side helper for macOS Beta Qualification. It
stages an exact Git-pinned Build Manager candidate into the portable
`Kodi Build Manager Test.app`, proves what is installed, triggers the BM-023A
adapter over loopback JSON-RPC, and collects secret-blind evidence. It replaces
the retired ai-supervisor actions; it needs no framework state. Tests:
`tests/test_bm_test_app.py` (temporary fixtures only).

**Status.** Implemented and tested offline against fake bundles. It has had no
live use and needs independent review before it touches the real Test.app.

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
| `snapshot [--manifest M]` | Read-only, secret-blind census of the portable data. |

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
4. Re-check that the Test.app is not running, then rename live to `old/` and new
   to live for both add-ons; verify the live trees; roll back on any failure
   (also on interrupt). If a rollback itself fails the area is kept untouched.
5. Re-verify the evidence copy and fingerprint the actual moved-aside `old/`
   trees against the backup digests. If presence or contents differ, fail closed
   and retain `.bm-stage/old` and all evidence. A later stage refuses that retained
   area. Only matching, verified old trees may be discarded with `.bm-stage`.

Evidence per run: `stage_manifest.json`, `stage_result.json`, `replaced/`.
`userdata` is never touched.

## `run`

Checks, in order: identity (running, one portable main process, optionally with
the sanctioned `XBMCHelper` auxiliary), installed trees ==
manifest, result path safe, then for every request the listener on the RPC port
must be exactly the authorized PID. Kodi's own view of the driver and Build
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
verified again after the run.

## `quit`

The normal, graceful shutdown for the qualification restart. Kodi persists
global settings (including `general.addonupdates`) through its normal application
stop, not when a setting is changed, so a signal-terminated Test.app can lose a
policy that a graceful exit keeps.

Checks, in order: identity (running, one portable main process, optionally with
the sanctioned `XBMCHelper` auxiliary), loopback RPC settings (same
`--config`/`--rpc-*` model as `run`; the port has no default), `JSONRPC.Ping`,
then exactly one `Application.Quit`. The listener on the RPC port must be the
authorized PID before every request, and credentials come through the same
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

Reads only: add-on `addon.xml` files, the newest `Addons*.db` (read-only,
immutable), two values from `guisettings.xml` (updater policy, skin id; the
rest is discarded unread), and the four frozen/restart transaction and lock
files plus the adapter result through the product's bounded status reader. A
positive allowlist guards every read; `addon_data/plugin.video.redlight/**` and
`private_overlays/**` are explicit denials. `guisettings.xml` and the database
may lag a running Kodi; `run status` reports the in-Kodi state.

## Typical sequence

```text
identify
stage --candidate <sha> --config <cfg> --dry-run            # inspect the manifest
stage --candidate <sha> --config <cfg> --evidence-dir <dir>
verify --manifest <dir>/stage-.../stage_manifest.json
(start the Test.app yourself: open ".../Kodi Build Manager Test.app" --args -p)
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
(relaunch: open ".../Kodi Build Manager Test.app" --args -p)
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
