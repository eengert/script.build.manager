# BM-017C — Structured Private Resource Foundation

Status: **complete on `agent/codex` when the accompanying implementation is
approved**. This document records the architecture and audit boundary. It
contains no private values, database payloads, or Family Room capture.

## Why BM-017B stopped

BM-017B found that Red Light `2.6.8` stores required provider/authentication
state in a mixed SQLite resource:

`special://profile/addon_data/plugin.video.redlight/databases/settings.db`

That resource also contains ordinary preferences, derived display rows,
migration state, and generated/runtime data. BM-017A owns typed Kodi settings,
not arbitrary rows in an add-on-owned mixed database. Replacing the database
would therefore overwrite state Build Manager does not own. BM-017B correctly
captured no values, retained no raw database, and added no file copier.

## Red Light 2.6.8 audit

The audit used the public Red Wizard package published at:

`https://repo.redwizard.xyz/redwizardrepo/main/plugin.video.redlight/plugin.video.redlight-2.6.8.zip`

The inspected package SHA-256 was
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`.
No real Family Room private file was retrieved for BM-017C.

The package declares `plugin.video.redlight` version `2.6.8`, requires
`xbmc.python`, PIL, and Requests, and stores its custom settings at the path
above. `resources/lib/caches/base_cache.py` creates:

```text
settings(setting_id text not null unique,
         setting_type text,
         setting_default text,
         setting_value text)
```

The add-on opens this database with a 20-second timeout, `isolation_level=None`,
`synchronous=NORMAL`, and `journal_mode=WAL`. Its settings cache retains values
in memory. `settings_cache.set()` and `write_db()` are internal implementation
helpers, not a stable external Build Manager API; they also update derived
properties and can trigger provider synchronization. `reload_auth_from_db()`
clears and repopulates selected cache properties. The backup/import module is
UI-driven and replaces whole databases, then runs a broad reload/bootstrap.
Neither path is a safe structured Build Manager import surface.

The selected application mechanism is therefore a narrowly scoped direct
SQLite adapter, but only under a strict lifecycle contract:

1. the exact add-on version and schema must match;
2. `settings.db` must already exist and pass the exact table/column/type check;
3. Red Light must be **quiesced**, not merely running with SQLite permitting a
   write;
4. the connection must observe the audited WAL journal mode;
5. `BEGIN IMMEDIATE` must succeed within a bounded timeout;
6. only declared `setting_id` rows may be updated, with `setting_type` and
   `setting_default` preserved; and
7. the owner must explicitly restart/reload Red Light before live verification.

Missing initialization, unknown schema/version, active runtime, lock/busy
state, missing declared rows, and read-back failure all fail closed. The
adapter never creates `settings.db`, changes journal mode, runs arbitrary SQL
from a manifest, replaces a database, or serializes old values for rollback.

## Generic model

`resources/lib/private_resource.py` defines the generic protocol:

- a public resource declaration contains only resource type, owner add-on,
  exact supported version(s), schema ID, logical resource ID, adapter ID,
  lifecycle requirement, and declared fields;
- each field has a type, required/optional status, sensitivity class, and
  field-level ownership;
- an overlay contains typed values only for those declared fields and can
  coexist with ordinary BM-017A private-setting entries;
- duplicate resources/fields, undeclared fields, wrong types, missing required
  fields, and unsupported adapters fail before mutation;
- fingerprints include private values in protected local overlay storage, but
  results, public manifests, logs, and durable restart transactions contain
  only safe identities and metadata; and
- capture results report field status only. Captured values remain in memory
  until the protected overlay store writes them.

The existing BM-017A overlay store remains protected local plaintext with
atomic writes and restrictive permissions where supported. Encryption at rest
is not claimed and no custom cryptography was introduced.

## Red Light declaration

The initial reviewed Red Light declaration is exact-version and exact-schema:

| Metadata | Value |
|---|---|
| Owner | `plugin.video.redlight` |
| Version | `2.6.8` only |
| Resource | `redlight.settings` |
| Schema | `redlight-settings-v1` |
| Adapter | `redlight.sqlite.settings.v1` |
| Relative resource path | adapter-owned `databases/settings.db` |
| Lifecycle | `quiesced`, then explicit restart/reload |

The first reviewed field allowlist is limited to typed string targets found in
the BM-017B non-secret inventory: `mdblist.refresh`, `mdblist.token`,
`mdblist.user`, `pm.account_id`, `pm.token`, `tb.token`, `trakt.expires`,
`trakt.refresh`, `trakt.token`, and `trakt.user`. They are optional at the
field level by default because BM-017B did not prove that every provider is
configured on every destination. No wildcard, arbitrary key, composite JSON
field, generated display field, cache, expiry-derived state, device ID, or
whole-file target is declared.

## Initialization, locking, and rollback

An absent database is `RESOURCE_NOT_INITIALIZED`; the adapter does not
synthesize it. Red Light initialization must happen through Red Light's own
normal lifecycle before a future application attempt. A schema mismatch or
unknown version is `PRIVATE_RESOURCE_UNSUPPORTED`.

The adapter uses a read-only SQLite connection for capture. Application uses a
bounded connection timeout, verifies WAL without changing it, starts
`BEGIN IMMEDIATE`, updates only owned rows, reads each updated value back in
the same transaction, and commits only after all owned fields verify. A lock
or busy result fails closed. Unrelated ordinary, generated, cache, and unknown
rows are never selected for writing.

Atomicity is guaranteed per structured resource. There is no plaintext secret
rollback journal: if a resource transaction cannot complete, it rolls back
before commit; after a committed resource write, the explicit restart/reload
boundary owns runtime reinitialization. Cross-resource rollback is not claimed.

## Restart/resume boundary

Existing BM-020/BM-022 transaction records persist only the private overlay ID,
fingerprint, and required flag. They do not persist resource field values. On
restart, the overlay is reopened by ID, its fingerprint is checked, resource
version/schema/lifecycle compatibility is rechecked, and only then may the
adapter be invoked. Missing overlay, fingerprint drift, missing resource,
unsupported version/schema, or unsafe lifecycle produces a fail-closed
attention state.

## Fake/disposable validation

`tests/test_private_resource.py` uses a temporary SQLite database with fake
secrets, declared rows, ordinary preference rows, generated rows, and unknown
rows. It proves declaration/type/ownership rejection, optional and required
field handling, secret-blind capture/application results, exact schema/version
checks, absent-resource handling, active-runtime rejection, WAL/transaction
behavior, unchanged unrelated rows, protected overlay round-trip, and
structured-resource coexistence with BM-017A's normal private overlay.

No test uses the real Family Room profile, private values, Apple TV, device
installation, retention/pinning/scheduling, or an `af3-common` package.

## Explicit non-claims and next boundary

This foundation does not create a real Family Room private overlay, prove
real-device frozen installation, or prove that a pristine first-ever Red Light
provisioning is safe. Those are separate future work. The next possible task
is BM-017D for a separately authorized real Red Light structured-private
capture; it is not started here.
