# Build Status — read-only status interface (BM-UI-002B / G2)

`resources/lib/status.py` answers, from a **fresh read** of Kodi and Build
Manager state, whether a device matches its build. It is observational only.
Calling it never installs, enables/disables, changes the skin, writes settings
or private data, changes the updater policy, creates/changes/clears a
transaction, acquires or releases an activation hold, reconciles, repairs,
retries or recovers.

```python
from resources.lib.status import BuildStatusService, StatusTarget, check_build_status

status = BuildStatusService(owners).check(target)   # target: StatusTarget | None
status = check_build_status()                       # production wiring, for the UI route
```

`check()` never raises. Every call re-reads; nothing is cached, there is no
background polling, and every result carries the UTC time it was checked.

## Public contract (`resources/lib/status_model.py`, standard library only)

Every field is an enum, a bool, a bounded count, a validated identifier or a
timestamp. The only text is an optional add-on display name: at most 64 plain
characters with no control, format or Kodi-markup characters (`[`, `]`, `$`). A
status cannot carry a setting value, credential, overlay payload, exception
message, path or fingerprint; constructing one that tries to raises
`ValueError`.

| Part | Contents |
|---|---|
| `overall` | `CURRENT`, `CHANGES_NEEDED`, `RESTART_REQUIRED`, `NEEDS_ATTENTION`, `INCOMPLETE` (not fully checked) |
| `software` | level + one item per managed add-on: `CURRENT`, `MISSING`, `WRONG_VERSION`, `WRONG_ENABLED_STATE`, `UNCHECKABLE` (optional display name) |
| `skin` | level, expected skin, current skin, `matches` |
| `configuration` | level + counts only: total / differing / unreadable managed targets |
| `private` | level + one status per private-data group (`private-settings`, each declared resource ID): `CURRENT`, `CHANGES_NEEDED`, `UNAVAILABLE` |
| `operation` | `NONE`, `RESTART_REQUIRED`, `NEEDS_ATTENTION`, `UNAVAILABLE` + a stable code + a sanitized product status code + whether an activation hold is still in force |
| `gaps` | stable enums saying why part of the check could not complete |

Area levels are `CURRENT`, `CHANGES_NEEDED`, `UNAVAILABLE` (could not be
checked) and `NOT_APPLICABLE` (the build does not use the area).
`BuildStatus.to_safe_dict()` is the serializable evidence form.

## Overall precedence

`NEEDS_ATTENTION` > `RESTART_REQUIRED` > `CHANGES_NEEDED` > `INCOMPLETE` >
`CURRENT`. Proven drift outranks "not checked". `CURRENT` is only possible when
a build was selected, at least one area was checked and matched, no area is
unchecked or changed, every listed add-on and private-data group is current, no
operation is pending and no gap remains; the model refuses to construct
anything else. A selected build that lists nothing to compare is `INCOMPLETE`
(`NOTHING_TO_COMPARE`), never healthy.

## What is compared

A `StatusTarget` names the desired build: the resolved build manifest and device
profile (skin, supported settings, private data, managed add-on states), an
optional frozen software graph (exact versions), and optional recorded install
resolutions (an accepted skip, or a repository fallback version). With no
target the build-dependent areas are `UNAVAILABLE` (`NO_BUILD_SELECTED`) and the
overall result is `INCOMPLETE`; pending-restart and needs-attention state is
still reported. Build Manager records no applied-build association yet, so the
production default target is `None` until Install records one.

* **Software** — each managed node of the frozen graph (system and
  absent-optional nodes excluded, accepted skips excluded) must be installed at
  its exact version and enabled state; the resolved manifest's add-ons,
  repositories and dependency closure are checked by the existing BM-014
  validator. A frozen capture that is not complete describes no whole build and
  leaves software `UNAVAILABLE` (the installer accepts only an incomplete-artifact
  capture whose gaps were covered by recorded resolutions). Dependency metadata
  comes from installed add-ons only; repositories are never consulted and nothing
  is downloaded. Unmanaged add-ons are never examined.
* **Skin** — BM-014 skin check; the active skin is reported either way.
* **Settings** — `ConfigurationInspector` compares each managed setting and
  file with its desired value (same `values_equal` as apply) over a view that
  exposes only read methods. A target that cannot be read is `UNAVAILABLE`, not
  drift.
* **Private settings** — typed private settings are compared in memory against
  the saved private data (read through `PrivateOverlayStore.read_snapshot`, which
  cannot block on a FIFO or follow a symlink); structured resources are checked
  through `StructuredPrivateResourceManager.inspect`, which returns status only.
  Missing, unreadable, mismatched, or wrong-build private data, an unsupported
  overlay reference, or a store that cannot be inspected without touching it is
  `UNAVAILABLE`, never `CURRENT`.
* **Restart / attention** — the restart transaction and frozen-install
  transaction are read with `read_snapshot()` (no lock, no directory or lock
  file created; writers replace records atomically). An awaiting-restart record
  from this Kodi session is `RESTART_REQUIRED`; one from an earlier session, an
  interrupted phase, an invalid record (malformed, unsupported, or a symlink,
  FIFO, directory or oversized file), or a `needs_attention` phase is
  `NEEDS_ATTENTION` (the existing startup classification). A record that exists
  but cannot be read (permissions, I/O) makes the operation state `UNAVAILABLE`.

## Read-only seams

| Owner | Read-only path | Why the existing path was not used |
|---|---|---|
| `TransactionStore` | `read_snapshot()` | `inspect()` takes a lock, creating the directory and lock file |
| `FrozenInstallStore` | `read_snapshot(root)` (static) | constructing a store creates its directory; `inspect()` creates the lock file |
| `session` | `peek_current_kodi_session_id()` | `get_current_kodi_session_id()` stores a window property when absent |
| `ConfigurationManager` | `ConfigurationInspector` over `ReadOnlyConfigurationBackend` | the manager only has `apply()` |
| `StructuredPrivateResourceManager` | `inspect()` | `verify()` raises for drift and cannot tell "absent/different" from "unverifiable" |
| `RedLightSettingsAdapter` | `inspect()` | a read-only SQLite open of a WAL database rewrites or creates its `-shm` index. The status read opens the store `immutable=1` through a percent-quoted URI, which touches nothing; that is only exact when no committed frame waits in the `-wal`, so a non-empty `-wal` (Red Light has uncheckpointed writes) is reported `UNAVAILABLE` rather than read in a way that writes beside the store |
| `PrivateOverlayStore` | `read_snapshot()` | `load()` follows symlinks, has no size cap and blocks on a FIFO |
| dependency metadata | `DependencyResolver` over a backend that refuses install/enable and never reads repository metadata | `read_available_addon_xml` can download packages over the network |

`verify()`/`apply()` behavior is unchanged.

## Proof of the zero-mutation boundary (`tests/test_status.py`)

Every mutating or file-creating owner method (install, enable/disable, skin,
configuration and private-resource apply/write, updater-policy setters,
transaction and frozen-store create/transition/clear, lock acquisition, hold
re-arm, retry, abandon/recover, startup/resume/restart coordinators, session
identity creation) is replaced by a tripwire during checks across current,
drifted, restart, hold and needs-attention states. Network access
(`urlopen`, `socket.create_connection`, `socket.connect`) and repository
metadata reads are tripwired the same way. The profile directory tree (names,
sizes, mtimes, digests, including SQLite sidecars) is identical before and after,
a held operation lock does not block a check, and an AST test pins that
`status.py` imports and calls none of the mutating owners.

## Known limitations

* No applied-build association exists yet, so the production default compares
  nothing and reports "Not Fully Checked" for build-dependent areas; software,
  skin, settings and private-data drift are proven by unit tests with explicit
  targets, not against a live Kodi.
* The updater policy is not read, so a residual quarantine without a
  transaction is not reported.
* Display names are optional; none is supplied in production yet, so the details
  list shows validated add-on IDs.
* A structured resource whose store is absent is reported as `CHANGES_NEEDED`
  (it is not set up); unsupported schema, locked or unreadable store, or a
  `-wal` with unflushed frames, is `UNAVAILABLE`.
* Reads that go through Kodi's own APIs (`xbmcaddon` settings, JSON-RPC, skin
  settings) are read-only by their contracts, but that cannot be shown outside
  Kodi; it needs live proof.
* The pre-existing `verify()`/`apply()` SQLite URIs in `redlight_resource.py` are
  not percent-quoted, so a `#` in the profile path truncates the URI (noticed,
  not changed here).
* Without a frozen software graph, version drift is not examined (presence and
  enabled state still are).
