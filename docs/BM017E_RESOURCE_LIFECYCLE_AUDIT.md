# BM-017E — Structured Private Resource Initialization & Quiescence

Status: **complete as a static investigation**. Result:
`BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`.

No Red Light code was executed for this investigation. The only inspected input
was the public `plugin.video.redlight` 2.6.8 package with SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`. No
Family Room database, protected overlay value, Kodi device, or portable Mac
test profile was accessed.

## Why BM-023A-R1 stopped

BM-023A-R1 reached a clean destination where the Red Light add-on had not yet
been installed or initialized. The absence of
`addon_data/plugin.video.redlight/databases/settings.db` was therefore expected;
the blocker was that Build Manager had no verified lifecycle for getting from
package installation to a valid resource that could be changed while Red Light
was quiesced.

## Red Light 2.6.8 source audit

| Concern | Source evidence | Finding |
|---|---|---|
| Add-on identity | `addon.xml:2,8,11` | Exact version is 2.6.8. It declares both a plugin source and an `xbmc.service` entrypoint. |
| Resource path | `caches/base_cache.py:84-93` | `settings_db` maps to `databases/settings.db` below the add-on profile. |
| Schema | `caches/base_cache.py:9-23` | `settings` has `setting_id`, `setting_type`, `setting_default`, and `setting_value`, all text; `setting_id` is unique. |
| Database open/WAL | `caches/base_cache.py:107-111` | `connect_database()` opens with a 20-second timeout, autocommit, `synchronous=NORMAL`, and sets `journal_mode=WAL`. |
| Narrow table helper | `caches/base_cache.py:121-132` | `ensure_database_tables(name)` creates the `databases` directory and applies that add-on-owned DDL with `IF NOT EXISTS`; for `settings_db` it creates only the settings table. It does not populate defaults. |
| Listing helper | `caches/base_cache.py:134-142`, `modules/router.py:18-25` | `ensure_listing_databases_ready()` creates both settings and navigator DB tables, then calls settings sync. It is wired to directory-listing plugin modes, not exposed as a standalone Build Manager API. |
| Default rows and migrations | `caches/settings_cache.py:808-1056` | `sync_settings()` seeds defaults on a fresh DB. It also contains obsolete-row deletion, upgrade migrations, cache sanitization, and optional property/bootstrap behavior. Fresh DB state skips the `had_existing_settings` migrations, but the function is broader than an initializer contract. |
| Database maintenance | `caches/base_cache.py:162-198`, `service.py:57-62` | The automatic service calls integrity maintenance. Any missing, corrupt, or unexpected-table-count database is deleted; if one fails, `make_databases()` recreates the add-on's full database set. This is unsafe as a repair path for an existing incompatible resource. |
| Service startup | `addon.xml:11`, `service.py:368-396` | Enabling the add-on starts `RedLightMonitor`, which runs constants setup, database maintenance, settings sync, XML checks, and starts bootstrap/background workers. |
| Background work | `service.py:16-17,118-359,387-396` | Daemon workers include bootstrap, window preparation, playback remote processing, four account monitors, widget refresh, autostart, and expiry alerts. Account monitors can call providers when accounts are active. A clean first-run defaults `auto_start_redlight` to false (`settings_cache.py:1654`). |
| Pause/shutdown | `service.py:10,141-142,181-182,215-216,249-250,304,398-411`; `modules/kodi_utils.py:903-915` | `redlight.pause_services` gates only several loops. The disabled notification sets a shutdown property and cancels widget alarms; it does not join workers or close settings-cache state. The monitor workers exit on Kodi abort. |
| Settings cache / handles | `caches/settings_cache.py:50-52,277-355,357-475,523` | The process owns a module-level cache singleton and bootstrap lock. Several methods open SQLite connections without an explicit `close()` or `finally`; the adapter cannot infer quiescence from a successful SQLite read/write. |
| Import/export | `modules/settings_backup.py:16-60,195-225` | Backup import/export is UI-driven. Import replaces whole database files and then invokes broad reload/integrity paths; it is not a safe structured-field initializer or apply API. |

The narrow helpers are deterministic in isolation, and the clean-path
`sync_settings({'silent': 'true', 'load_properties': False})` seeds the package's
own defaults without opening settings UI. That establishes a source-level
initialization candidate, but does not establish a safe production call point:
the helper is internal, and the ordinary enabled-addon startup path runs
concurrently with Build Manager and includes broad maintenance and background
work.

## Quiescence and existing restart ordering

Build Manager's BM-017C Red Light adapter currently requires an existing,
WAL-mode `settings.db` and an explicitly quiesced owner. It fails closed when
the resource is absent, and never changes journal mode or creates the file.

The current production flow cannot carry a verified disabled-owner stage across
the two durable coordinators:

1. `FrozenInstallCoordinator.install()` registers exact packages and enforces
   each manifest `desired_enabled` state before invoking the configuration
   runner (`resources/lib/frozen_install.py`, install loop and
   `_handle_configuration_result`). Thus the service can start before
   structured private application.
2. BM-020 persists one restart handoff, but its transaction does not identify a
   resource lifecycle stage. `ResumeCoordinator.resume()` reruns normal
   reconciliation and moves to `NEEDS_ATTENTION` if that reconciliation still
   requires another Kodi restart (`resources/lib/resume.py`).
3. BM-022 has its own updater-policy transaction. Its
   `resume_after_restart()` reasserts the updater guard and finalizes the frozen
   install; it does not rerun the configuration runner. There is no single
   coordinator that proves the owner remains disabled while initialization and
   private application resume, then enables it only after the values commit.

Disabling Red Light and relying on a Kodi restart could terminate its process,
but the currently supported flow does not preserve or validate the required
stage ordering across BM-020 and BM-022. Directly setting `redlight.pause_services`
is not equivalent to quiescence. Reusing Red Light's own immediate
disable/enable toggle is not safe either: it swallows errors and has no wait or
process-boundary verification (`modules/kodi_utils.py:1003-1008`).

This is the stop condition for BM-017E. A production implementation would need
one reviewed durable sequence that holds the owner disabled across the restart,
invokes only the Red Light-owned settings initializer after Kodi has discovered
the exact add-on metadata, applies the overlay while disabled, then enables
Red Light and verifies the reloaded resource while the BM-022 updater guard is
still in force. That sequence must be integrated with the existing BM-020 and
BM-022 transactions rather than run as an independent state machine. The
current production order cannot prove those invariants, so no lifecycle code
was added and no add-on code was executed.

## Compatibility and recovery contract for a future implementation

- Exact supported owner remains `plugin.video.redlight` 2.6.8 and schema
  `redlight-settings-v1` only.
- `settings.db` absence is valid before installation. Once a resource exists,
  malformed or incompatible schema must fail closed; no delete/recreate path is
  acceptable.
- The audited Red Light open path establishes WAL. Any future initializer must
  verify WAL after using Red Light's own implementation; Build Manager must not
  set an unrelated PRAGMA to satisfy its adapter.
- The current per-field transaction, allowlist, in-transaction read-back, and
  unrelated-row preservation guarantees remain required. Lifecycle metadata
  may contain only resource/owner IDs, exact version, stage, and overlay
  identity/fingerprint. It must never contain private values.
- Initialization side effects and partial completion need bounded,
  secret-blind outcomes. Existing resources must not be overwritten, and
  uncertain partial initialization must remain for diagnosis rather than be
  deleted automatically.

## Validation and disposition

No fake resource tests, package execution, disposable Kodi run, or repository
tests were performed because no production lifecycle was accepted for
implementation. The exact package identity was verified from its SHA-256 and
`addon.xml`. The BM-023A-R1 matrix validation remains **288/288 focused** and
**1647/1647 full**; compileall, JSON parsing, and `git diff --check` passed
during matrix integration.

Classification:

- BM-017E: complete as investigation;
  `BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`.
- Red Light clean-destination private-resource lifecycle: **UNSUPPORTED** by
  the current Build Manager production ordering.
- macOS BM-023A retry: **STILL_BLOCKED**; do not start it from this task.
- tvOS: **NOT VALIDATED**.
