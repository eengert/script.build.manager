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
  process (service `BM-TestApp-HTTP-RPC`, account `kodi`), so an agent
  that runs it never receives the password. The lookup result is captured inside
  the wrapper process and is never displayed. The lookup uses a fixed argument
  list, no shell, stdin closed, stderr discarded, fixed minimal environment,
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
For foreground PID/window inspection use `tools/bm_test_app_window.swift`,
the exact source copied from Claude's validated read-only runtime helper.
See `AGENTS.md` for command sequence and guarded restoration. `open -g`
alone does not prove unchanged focus. The obsolete
`tools/bm_test_app_launch.py` hides Test.app and must not be used.

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

## Qualification-only AF3 fixture

`run af3_fixture` provisions one fixed, original-byte AF3 3.3.12 closure into
the disposable portable Test.app. This is not a general installer or a saved
build Apply. Native use requires independent review and separate authorization;
adding these modes does not authorize staging, launch or execution.

The modes require HTTP loopback, authenticated PID-bound listener admission,
an exact Git-bound stage manifest and the existing source-isolated adapter.
Both fixture modes require successful HTTP authentication after Ping; an
unchallenged connection refuses with `rpc_auth_failed` before adapter dispatch.
TCP and `--no-git-binding` are refused. The fixed target is
`/Applications/Kodi Build Manager Test.app/Contents/Resources/Kodi/portable_data`.
No target, package-set, version, digest or acquisition override is provided.

Prepare a new matching diagnostic adapter through the existing stopped-state
staging workflow. Its configuration must use these exact existing public inputs:

- `MANIFEST_PATH`: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-d028-trusted-admission-20261020/authored-af3-manifest.json`
- `ARTIFACT_ROOT`: `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex/.qualification-evidence/item8-d028-public-artifact-store-20261022`

The manifest SHA256 is
`30bd44d3f6897b0e17b40afdd44881dcf24acca906cdad8827dad7c095101420`.
The adapter pins all 17 package IDs, versions, sizes and original ZIP SHA256s
in `_AF3_PACKAGES`, and checks the reviewed 22-node/45-edge graph with production
validation before any package publication. The font's declared ID remains
`resource.font.robotocjksc`, with original ZIP root `resource.font.robotcjksc`.
No repacking occurs. Configuration and overlay inputs required by the existing
adapter builder are not read or applied by these two modes.

After separately authorized admission, staging and portable launch, use the
existing `tools/bm_test_app.py run af3_fixture --manifest <new-stage-manifest>
--repo <exact-worktree> --config <approved-http-config> --output <new-output>`
interface. Existing secure credential handling applies. Never place a password
in command arguments, configuration, environment, logs or evidence.

Before publishing, the adapter requires current native builtin/ABI/closure and
application-origin PIL verification, Estuary, an authenticated matching applied
and selected association, Keymap 1.4.0, and no frozen/restart/capture transaction,
activation hold or pending publication. Every fixture ID must be absent from
both native registration and the add-ons directory. Even an exact pre-existing
version refuses; it is not adopted. The operator must separately establish
`general.addonupdates = 2` (`NEVER_CHECK`) before native admission. AUTOMATIC,
NOTIFY_ONLY, unavailable and malformed values refuse. This gate is checked at
initial admission, between publications, at completion and during verify.
Keymap's enabled state and the required updater policy are observed and
preserved, never configured by this helper. NEVER_CHECK does not establish
general network isolation; TMDb Helper service/network effects require a
separate native-admission decision before enablement is authorized.

The existing `publish_package` performs exclusive validated extraction and
atomic publication in dependency order. `UpdateLocalAddons`, exact native
registration checks and targeted enablement establish the closure. No generic
Install from ZIP, repository acquisition, coordinator, skin activation,
configuration application or saved-build publication is invoked. Completion
requires exact version, enabled/nonbroken native state, HOME metadata origin,
original installed member bytes, fresh platform verification and unchanged
scoped public library/resolution/settings/nonfixture inventory observations.

An exclusive, fsynced `userdata/bm-af3-fixture-v1.jsonl` journal binds source,
manifest, baseline and ordered progress. Any interruption or refusal preserves
published packages and journal evidence. A later provision attempt refuses;
there is no automatic retry, resume, overwrite, adoption or destructive rollback.
Do not delete this fence to rerun. A separately authorized read-only
`run af3_fixture_verify` uses the same bindings and requires a complete journal,
exact installed bytes and native health; it cannot complete a partial attempt.
The normal bounded diagnostic result file is still updated by verify mode.
If final-record fsync fails after `complete` was written, the original run
remains failed; a later authorized verify may observe complete bytes and healthy
state, but cannot prove that the failed fsync made the record durable. Never
infer safe retry from this ambiguity. Interrupted publisher staging remnants
may also remain; preserve them for separately authorized inspection.

The host execution-window witness permits changes only to the 17 fixture roots
and the add-ons parent timestamps; its inode, protected product/driver sources
and all nonfixture top-level entries remain bound. Ordinary `platform_check`
keeps its original stricter witness. These observations are not an atomic global
lock, full-profile preservation proof or a restriction on independent Kodi
background activity. Transient nonfixture entries created and removed directly
under the add-ons parent, and parent metadata-only changes, may go unobserved.
Unexpected native-generated files, updater activity or
state drift can cause safe refusal. Native compatibility remains unverified
until a separately authorized disposable run passes. Preserve failure evidence
and stop rather than weakening checks or improvising cleanup.

## Existing AF3 native health inspection

`af3-health` is a host-only inspection command for the already-published fixture.
It adds no in-Kodi mode and does not stage a new adapter. **Independent review
and explicit separate authorization are required before native use.** This
command does not launch Test.app, install/enable packages, repair anything,
change the updater or complete the failed provisioning attempt.

It requires the exact original installed candidate
`ecc1ee15a72fe375629108d5341768938378f473` and original stage-manifest SHA256
`529851628778a71c82077e517871881cbbb16f478af6766093a89118eb29d8e5`.
Git binding cannot be disabled. The new host helper is used with that original
installed source; do not restage merely to use this host inspection surface.
HTTP is fixed to authenticated PID-bound `127.0.0.1:8080`, user `kodi`; no TCP
fallback, unchallenged connection, configurable package set or recovery option.
The existing reviewed Keychain wrapper supports this command with its unchanged
credential protection and fail-closed lookup behavior.

After separate native authorization and portable-target admission, the interface
is `tools/bm_test_app_keychain.py af3-health --manifest <original-stage-manifest>
--repo <exact-worktree> --rpc-transport http --rpc-host 127.0.0.1 --rpc-port 8080
--rpc-user kodi --output <new-protected-output>`. Passwords never belong in
arguments, environment, configuration, logs or evidence. Current authorization
does not follow from the existence of this example.

The host authenticates the fixed sealed stopped-state package audit (seal
`6654e02f0c3da67667d6944bc4501105e953d773257b5910fb9550bfe4a3bd21`)
and the unchanged failed journal (SHA256
`576aeb430b5d86fcdacb1c6be837ecf2f1d57c9653b4f5e800814c327d252344`).
It uses the **existing** source-only `platform_check` invocation for fresh
native build/builtin/ABI/PIL requirements. That read-only diagnostic writes its
normal bounded result witness inside Test.app; the health operation is not a
zero-write filesystem observation. Both diagnostic and inspection connections
must authenticate. The driver must already be enabled; no transition is made.

Ordinary host reads then require all 17 exact native versions, enabled=true,
broken=false, Estuary and integer updater policy 2. Strict malformed responses
refuse. The original journal is re-read, source/Git and execution-window
identities are rechecked, and PID/listener guards remain in force. The only
adapter execution requested is the original platform diagnostic; no third-party
add-on import/execution is requested by the health operation.

Results keep four independent facts separate:

- `original_package_source_integrity`: HISTORICAL_VERIFIED from the sealed audit,
  explicitly not a fresh installed-byte observation.
- `native_registration_health`: PASS only for successful current health reads;
  fresh platform proof is separately included.
- `executable_cache_extras`: the audit's 76 .pyc / 13 cache directories remain
  historical observations with UNVERIFIED trust/provenance. No cache is read as
  code, imported, executed, removed, authenticated or blanket-excluded here.
- `original_provisioning`: FAIL / INCOMPLETE, 35 records, zero complete records,
  unchanged journal. Health success never rewrites that history.

Native health does not authenticate executable caches or claim current package
source-byte integrity, atomic/full-profile preservation, original provisioning
success, AF3 activation safety or authorization for Auto-Keep. Kodi services
already running may have their own code/cache/network activity; this inspection
does not isolate them or retroactively authorize a launch. Any failed guard is
a refusal, with no retry, configuration change or recovery. Preserve evidence
and stop for Supervisor.

### Standalone Auto-Keep qualification (separate native authorization required)

`run auto_keep` is a qualification-only operation for the fixed
`skin.arctic.fuse.3` **3.3.12** target. It does not enter an Install coordinator,
create a saved build, publish an association, apply captured configuration or
activate the dormant two-approval protocol. Production `SkinActivator`,
`KodiRuntimeSkinBackend`, `default.background_busy` and
`NativeDialogs.execute_install` run unchanged.

Before any future execution, separately authorize staging the reviewed adapter
and matching Git-bound product, using a **new** stage manifest. The previously
installed ecc1ee15 adapter has no such mode. Keep the approved configuration's
fixed authored AF3 manifest and artifact store; neither is captured runtime
state. Then, with independently admitted portable Test.app running, the bounded
host interface is:

```text
DEVELOPER_DIR=/Library/Developer/CommandLineTools \
/Users/eengert/.pyenv/versions/3.10.9/bin/python3 -B tools/bm_test_app_keychain.py \
run auto_keep --manifest <NEW_REVIEWED_STAGE_MANIFEST> \
--repo /Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex \
--rpc-transport http --rpc-host 127.0.0.1 --rpc-port 8080 --rpc-user kodi \
--output <NEW_PROTECTED_OUTPUT>
```

This is documentation, not authorization to stage, launch or execute it.
Authentication is mandatory before dispatch, with the existing target/PID-bound
HTTP listener, source-only adapter bootstrap, Git binding, source-window checks
and sanitized result projector. TCP, arbitrary endpoints/skins and Git bypass
are refused. The unchanged credential wrapper has no password fallback.

Runtime admission requires Estuary, NEVER_CHECK, all 17 pinned packages enabled
and nonbroken, the fixed authored graph's native platform/ABI/PIL verification,
no frozen/restart/capture transaction or hold or pending publication, and the
expected selected/applied Build 999 / 1.0.1 association and resolution. It also
requires the exact original failed 35-record fixture-journal digest. That
journal is read only; its incompleteness does not gate standalone activation.
Both standalone admission checks accept only the integer `9999` (Kodi's
`WINDOW_INVALID`) as no modal; `-1`, `0`, real dialog IDs and non-integer values
refuse. The production activator separately checks
preparation-time conflicts, localized Keep heading/body and the topmost modal,
then rechecks immediately before its one `SendClick(11)`.

A new, mode-specific `userdata/bm-auto-keep-attempt-v1.json` exclusive marker is
written and fsynced **before** the callback. Its existence permanently fences
another attempt, including after failure, a crash or lost output. This is an
at-most-once invocation contract, not guaranteed completion: zero activations
may occur after a consumed claim. Never delete/reset/adopt the marker to retry.
No automatic rollback or return to Estuary is implemented. A successful run
leaves AF3 selected; a return transition needs separate authorization.

The sanitized result reports initial prerequisites, callback and progress-cleanup
return, production status/failure code, final reported setting/skin and a scoped
public preservation comparison. Exceptions use the existing value-free failure
payload; they do not imply successful cleanup or unchanged state. Source checks
and observations are discrete, not atomic. The remaining dialog replacement
after the final check can still misdirect the click; no label-plus-click or
window identity proves atomic dialog ownership. The independent offline review
reproduced a replacement receiving Yes while the operation returned `ok=true`.
This unresolved risk requires an explicit Supervisor decision before native
activation; the no-modal sentinel correction does not address it. Stable configured/reported skin
is not authenticated loaded-object identity or disk durability. A future task
must also observe beyond Kodi's Keep/revert timeout and gracefully stop the
exact target, comparing its bounded baseline without assuming a safe rollback.

Original provisioning remains FAIL/INCOMPLETE. Historical original-file audit
and native-health observations do not authenticate the 76 historical bytecode
cache files or prove current cache contents. Cache trust remains UNVERIFIED;
this operation neither cleans caches nor establishes a new cache policy.
AF3/services may execute code and change their own runtime data. Such effects
are not an atomic/full-profile preservation guarantee. A focused Auto-Keep proof
does not qualify full A11 user-facing Create/Install/configuration reconciliation,
Item 8 or beta acceptance. D-029/D-030 restrictions remain unchanged.

The Auto-Keep result's `failure_stage` refines only
`failed / CONFIRMATION_ACTION_FAILED`, using exact fixed production outcomes:

| Stage | Meaning |
|---|---|
| `initial_prompt_rejected` | The initial expected-prompt predicate returned false. |
| `final_prompt_read_failed` | The final confirmation reinspection raised. |
| `final_prompt_changed` | The final expected-prompt predicate returned false. |
| `sendclick_exception` | The SendClick call raised, possibly after dispatch. |
| `unknown` | A success, different failure, unrecognized outcome or old result without the field. |

Only these fixed values are exported. Raw `SkinResult.message`, exceptions,
heading/body text, localized values and credentials are not emitted. Matching
requires the exact typed failure code/status and exact fixed message; there is
no substring matching or normalization. The host projector validates the enum
and its failure-code/status consistency. Malformed refinements refuse;
recognized historical results without the field remain `unknown` and cannot
be retrospectively classified. The ordinary failure code and success decision
are unchanged. `sendclick_exception` proves neither delivery nor non-delivery;
`initial_prompt_rejected` does not identify which presentation predicate failed.

This output-only refinement does not change the confirmation checks, clicks,
progress lifecycle, retry/rollback behavior or permanent marker. The original
native attempt remains consumed. No new attempt ID, reset path, versioned
marker, alternate activation route or native permission is introduced. Any
future native observation needs separate authorization and an independently
reviewed safe procedure respecting the retained marker. The known dialog race,
cache uncertainty and original provisioning FAIL remain unchanged.

### A15 stopped-state preservation acquisition (host API only)

`tools.bm_preservation_acquisition.AcquisitionSession` supplies a fixed five-file
bridge to the existing semantic projections. It has no command-line mode,
daemon, native-operation callback, persisted baseline or cross-process resume.
Use one foreground host process for both observations:

```python
with AcquisitionSession(services, manifest=validated_manifest, git_repo=repo) as session:
    before = session.begin()
    # Only ACQUIRED permits separately authorized native work outside this API.
    # After independently verified graceful shutdown:
    after = session.finish()
```

Production services must name the fixed authorized portable Test.app. Each
acquisition brackets its reads with stopped-state admission and full installed
product/driver/manifest/Git verification. The bundle identity is bound across
both observations; all five source bytes and file identities are re-read after
projection and final admission. This detects observed source changes, but is
not an atomic snapshot or global writer-exclusion guarantee. The caller must
separately establish quiescence; never infer writer-free from stopped alone.

Only the five fixed paths declared by `bm_public_preservation_witness.FILES`
are acquired: Addons33, Textures13, guisettings, Estuary settings and keyboard
settings. Existing parsers, bounds, no-follow readers, sidecar/WAL refusals and
semantic comparison rules are reused. A missing baseline file refuses; a
stably missing after-file is CHANGED_OR_MISSING. Unsupported schema/state or
uncertain acquisition/cleanup is UNVERIFIED. Changed maintenance fields are
not deemed harmless. Addons33 covers only add-on IDs/enabled flags; other
content remains UNVERIFIED. Complete preservation and qualification are never
claimed. Existing public library/artifact/association/transaction/hold/updater/
publication witnesses remain separate and must still be collected.

Private projections remain in process memory, never in returned evidence or
value digests. Sessions refuse copying/pickling, consume finish before reads,
and discard references on completion, failure or context exit. Repeated calls
refuse. Do not log private attributes, dump locals, or serialize the process.
Reference disposal is not secure erasure; OS memory handling is not controlled.
The accepted SQLite projector still uses private 0600 copies in temporary 0700
directories, linked through query/close and removed before success. Crash or
cleanup failure can leave those copies; no crash-residue or secure-erasure
guarantee is added. No raw five-file baseline is written for the UI interval.

Loss of the host process loses the baseline: refuse qualification rather than
reconstructing it from hashes, saving private state or retrying a native action.
This API grants no native operation, staging, recovery or Auto-Keep authority.

### A15 foreground driver (requires separate native authorization)

From the exact Codex worktree, use the pinned interpreter and reviewed host
commit with `-B -m tools.bm_preservation_driver --host-commit <full-reviewed-SHA>
--manifest <verified-stage-manifest> --evidence-dir <new-unused-directory>`.
The evidence directory must be a new direct child of this worktree's `.qualification-evidence`
and its parent must already exist. No target/repository override, native action,
RPC endpoint, private baseline save/load or timeout override is provided.

One foreground process owns one unchanged AcquisitionSession. It first proves
host Git source bytes, loads the existing validated manifest, creates exclusive
0700 evidence, obtains separate supported public witnesses and calls begin once.
Only successful acquisition produces durable `ready.json` and the fixed stdout
line `READY`. The receipt says native_operation_authorized=false: READY supplies
no independent authority to launch or mutate Kodi. The external controller must
hold separate authorization and confirm the driver remains alive.

Keep stdin open and empty until READY. The only accepted coordination lines are
`FINISH` or `CANCEL`, each followed by newline. Waiting is bounded to 900 seconds.
Unknown, queued out-of-order or coalesced repeated input refuses. Terminal exit
consumes the session; later signals cannot start another acquisition or action.
No native action is invoked by the driver, including on timeout or cancellation.

Before FINISH, the separately authorized controller must gracefully quit the
exact target and write a fresh `quit.json` in the new evidence directory using
the existing trusted bm_test_app.py/keychain-wrapper `quit --output` path.
It must be the original sanitized successful helper result, mode 0600, from
after READY, with matching bundle, authenticated PID-bound Application.Quit,
accepted/exited shutdown and no forced termination. The driver does not obtain
credentials or issue RPC. It validates that receipt, rechecks source and stopped
public state, calls finish at most once, and compares the separate witnesses.
The receipt is trusted operator-supplied helper evidence, not a cryptographic
attestation; same-UID forgery or hostile host control is not excluded.

Public coverage uses the existing snapshot, typed applied/selected/publication
and resolution readers, plus creation-free public library/resolution/artifact
trees. Present install/restart/capture owners refuse; no creating transaction
lock is acquired. Inventory, updater and Estuary must be known. Private overlays,
AF3 fixture records, caches and the consumed Auto-Keep marker are not traversed.
Native schema compatibility and safe UI fixture admission must still be proved
for each separately authorized run. The driver does not establish the actual
Create conflict wording, confirmation count or absence of unrelated UI actions;
those require external native UI evidence.

`DONE` means only that terminal output was attempted. Acceptance requires exit
0 AND a complete durable result.json with state=SCOPED_PRESERVED, as well as the
external UI evidence. Nonzero exit invalidates acceptance even if an optimistic
result file exists after a close/output failure. Missing result, process loss,
EOF, CANCEL, timeout, failed acquisition, drift or differences are non-PASS.
Do not restart/resume from ready.json or retry the native scenario automatically.
An orphaned UI session needs separately authorized target-specific safe closure.
Only sanitized status/projection summaries are written; private baseline values
remain in the original process. All bridge limitations and crash-copy risks above
remain. This driver supplies neither complete preservation nor beta acceptance.
