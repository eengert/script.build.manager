# BM-023A isolated macOS test runtime

This document describes the prepared replacement environment. Kodi was not
launched while preparing it.

## Preserved portable evidence

The original `Kodi Build Manager Test.app` bundle and its `portable_data`
contents remain in place. A byte-preserving copy is stored under the
git-ignored `.bm023a-test-runtime/evidence/portable_data.pre_retry/` directory.
The copy contains 8,403 regular files totaling 302,642,596 bytes; a sorted
path/type/mode/size/SHA-256 manifest matched the source during copying and in a
subsequent read-only comparison. No file contents were printed or decoded.

The source tree contained these top-level folders: `addons`, `media`,
`system`, `temp`, and `userdata`. `userdata` contains `Database` and
`addon_data`; the frozen transaction and its lock files are under
`userdata/addon_data/script.build.manager/`. `addons/packages` contains the
Kodi package cache. `media` and `system` were empty. `temp` contains temporary
and log data. These names were inspected without opening their contents.

## Profile mapping

The [Kodi special-protocol guide](https://kodi.wiki/view/Special_protocol)
documents macOS `special://home` as the directory beneath
`$HOME/Library/Application Support/Kodi`; the [portable-mode guide](https://kodi.wiki/view/Portable_mode)
documents macOS `-p` as using a `portable_data` directory. The project harness
implements the same ordinary macOS mapping in `tools/kodi_test.py`: it sets
`HOME`, derives `userdata` and `addons` below
`Library/Application Support/Kodi`, and removes `KODI_HOME` from the child
environment.

For this replacement runtime, the state migration maps:

| Old portable state | Isolated HOME destination | Handling |
| --- | --- | --- |
| `addons/` | `Library/Application Support/Kodi/addons/` | Copy, including `addons/packages/` |
| `media/` | `Library/Application Support/Kodi/media/` | Copy if present; empty in the preserved tree |
| `userdata/` | `Library/Application Support/Kodi/userdata/` | Copy databases, add-on data, settings, profiles, and transaction files byte-for-byte |
| `system/` | None | Keep only in forensic backup; empty in the preserved tree |
| `temp/` | None | Keep logs and transient cache only in forensic backup |

The `userdata` copy retains the full profile layout, so the frozen transaction,
database state, and add-on data remain together. The current active profile
selection inside `userdata` was not read because this task limits inspection to
path names. The helper therefore copies all of `userdata`, rather than
assuming which named profile Kodi selects. Future logs are isolated at
`<HOME>/Library/Logs/kodi.log`, following the project harness. The current
portable `temp/kodi.log` remains in the preserved backup.

The migration helper is deterministic and non-destructive: it refuses a
pre-existing destination, rejects symlinks and special files in the source,
copies only `addons`, `media`, and `userdata` to a staging directory, and
compares source and destination path/mode/size/content hashes before the final
rename. It hashes the source both before and after copying. It has not been run
against the preserved tree; the migration is reserved for the next task.

## Isolated HOME and launcher

The persistent, git-ignored test root is `.bm023a-test-runtime/`. It has an
explicit `BM023A_TEST_STATE.txt` marker. The HOME is
`.bm023a-test-runtime/home/`; the future Kodi profile is derived as
`<HOME>/Library/Application Support/Kodi`. This HOME is separate from
`.kodi-test` and from all app bundles. No symlink into any Kodi profile is
created.

The staged app path is `.bm023a-test-runtime/distribution/Kodi.app/`. The
launcher accepts explicit `--app` and `--home` arguments but fails closed
unless they resolve to that dedicated staged bundle and HOME. It reads the
bundle's `Info.plist`, checks the expected 21.3 version and x86_64 architecture,
requires a nonempty bundle identifier and non-ad-hoc signing authority/Team ID,
runs strict deep code-signature verification before launch. It invokes the
`Contents/MacOS` executable directly with no arguments, sets `HOME`, `TMPDIR`,
and XDG paths under the isolated runtime, and removes Kodi/XBMC/Python path
overrides that could redirect the process. It never adds `-p`.

Example for a separately authorized future launch:

```text
python3 tools/bm023a_runtime.py launch \
  --app .bm023a-test-runtime/distribution/Kodi.app \
  --home .bm023a-test-runtime/home \
  --suppress-python-bytecode
```

The launcher first requires the marker and a prepared `Kodi/userdata` and
`Kodi/addons` profile. It does not create or reset the profile when launching.

## Bundle-mutation defense and Python cache setting

The launcher stores a before/after manifest pair for each run outside the app
bundle. Each manifest hashes the full directory structure, file bytes, modes,
modification times, symlink targets, and extended attributes when the Python
runtime exposes those APIs. The current Python runtime does not expose
`os.listxattr`/`os.getxattr`, so its manifest records that extended attributes
were unavailable. The launcher also verifies the code signature before use.
Any added, removed, or changed bundle entry makes the run fail with
`BundleMutationError`; it never repairs or re-signs the bundle.

Kodi 21.3's [source](https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/interfaces/python/XBPython.cpp)
calls `Py_Initialize()` for its embedded Python interpreter. The official
[CPython environment documentation](https://docs.python.org/3.8/using/cmdline.html#envvar-PYTHONDONTWRITEBYTECODE)
says a nonempty `PYTHONDONTWRITEBYTECODE` prevents `.pyc` creation during
source imports. This
makes the option a technically valid candidate, but this task did not run the
embedded interpreter, so it is not claimed as live-proven. By default the
launcher redirects Python bytecode cache to `<HOME>/.cache/python-bytecode`;
the optional `--suppress-python-bytecode` flag also sets
`PYTHONDONTWRITEBYTECODE=1`. The bundle manifest remains the authoritative
check if Kodi or an add-on writes into the bundle despite these settings.

## Current gates

The original app bundle remains untouched and is still classified as damaged
and untrusted. No known-good Kodi 21.3 x86_64 distribution has yet been verified
for the replacement staging path. Do not stage, launch, or migrate until a
local official distribution is found and its signature, identity, and
isolation checks pass. The supported `FrozenInstallCoordinator.abandon()`
recovery is for the cloned profile only and was not invoked during preparation.
