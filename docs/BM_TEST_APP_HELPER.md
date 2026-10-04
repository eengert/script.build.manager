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
  matched lexically and refused everywhere; they are never stat'ed, listed or
  opened. Any Kodi-like process outside the authorized bundle is refused too.
- Every command starts with `identify`: Info.plist identity, no symlink in the
  bundle path, and either no process or exactly one process of the authorized
  executable launched with a standalone `-p` argument.
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

1. Build in a private temp workspace (removed afterwards).
2. Create `portable_data/.bm-stage` (exclusive; its existence is the lock and a
   stale one is never deleted) and write both new trees there, then verify them
   against the manifest. It must share a device with `addons/`.
3. Copy every tree about to be replaced into the evidence directory
   (`<evidence-dir>/stage-<UTC>-<sha12>/replaced/<addon-id>`) and verify the copy.
4. Re-check that the Test.app is not running, then rename live to `old/` and new
   to live for both add-ons; verify the live trees; roll back on any failure
   (also on interrupt). If a rollback itself fails the area is kept untouched.
5. Only after the evidence copy is re-verified is `.bm-stage` removed.

Evidence per run: `stage_manifest.json`, `stage_result.json`, `replaced/`.
`userdata` is never touched.

## `run`

Checks, in order: identity (running, one portable process), installed trees ==
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
snapshot --manifest ...
```

If a held retry fails or state is contradictory, stop and preserve evidence; do
not improvise another recovery. The helper has no reset or delete command and
never edits transaction or lock files.
