# BM-020B restart transactions

BM-020B provides the durable handoff foundation for a later BM-020C restart
and resume implementation. It does not restart Kodi, rerun reconciliation, or
claim that a restart completed.

## Storage and schema

The transaction is stored at the Kodi-resolved profile location:

```text
special://profile/addon_data/script.build.manager/restart_transaction.json
```

The location is resolved with `xbmcvfs.translatePath`; source files, Git,
`.kodi-test` fixtures, and `.agent` metadata are never used for transaction
state. Schema version `1` is explicit and currently contains only:

- transaction UUID and phase;
- the safe `ReconcileRequest` selectors (`manifest_path` and
  `device_profile_id`);
- the deterministic desired-state fingerprint;
- the typed `KODI_RESTART` requirement;
- the originating Kodi session UUID;
- restart-attempt count and bounded diagnostic timestamps.

Resolved Kodi state, plan actions, runtime objects, configuration contents,
credentials, tokens, passwords, and private overlays are not serialized.

The phase enum is deliberately small:

```text
AWAITING_RESTART → BM-020C handoff point
RESUMING         → reserved for BM-020C
NEEDS_ATTENTION   → explicit recovery/diagnostic state
```

## Preparation and atomicity

`prepare_restart_transaction(request, reconcile_result, session_id)` creates a
record only when reconciliation succeeded, the typed restart requirement is
`KODI_RESTART`, the fingerprint and request are valid, and no active record
already exists. `NONE` creates no record. A failed reconciliation never creates
an automatic-restart transaction, even if an earlier operation reported a
restart requirement.

Writes use a same-directory temporary file, flush and file `fsync`, validated
JSON, and atomic `os.replace`. The existing record is not removed before the
replacement. Read-after-write validation and restoration of the prior bytes
protect updates from destroying a valid record after a persistence failure.

## Locking

All create, inspect, update, and clear operations use a profile-local lock file
with an OS-backed `fcntl.flock` exclusive lock. The lock is non-blocking and a
busy acquisition returns an explicit failure. `flock` ownership is released by
the operating system when the Kodi process exits, so a crash does not leave a
stale lock that can be stolen based only on wall-clock age. If the primitive is
unavailable, the operation fails closed; it does not fall back to a check-then-
create lock. Explicit transaction clearing remains the recovery surface for a
durable record that needs administrative abandonment.

macOS, Android/Shield, Fire OS, and tvOS are POSIX-based supported targets;
the implementation still checks for the runtime primitive and refuses to
operate if it is absent.

## Session identity and startup service

The first Build Manager call in a Kodi process creates a UUID in the global
Kodi home-window property `script.build.manager.kodi_session_id`. Later calls
in that process reuse it. A new Kodi process receives a new UUID; the UUID is
not persisted outside the transaction's originating-session field.

`addon.xml` exposes the thin startup entrypoint:

```xml
<extension point="xbmc.service" library="service.py" />
```

`service.py` obtains the session identity and delegates to the startup
foundation. It performs one classification pass and exits; it does not poll,
display a dialog, call `BuildManager.reconcile()`, or restart Kodi.

With no transaction, startup takes the no-transaction fast path and creates no
transaction record. An `AWAITING_RESTART` record from the same session is
classified as `SAME_SESSION_AWAITING_RESTART`, remains intact, and is not
eligible for resume. A record from a different session is classified as
`READY_FOR_RESUME`, remains durable, and is handed to BM-020C without being
claimed or resumed.

Malformed JSON, unsupported schema versions, missing fields, invalid enum
values, invalid requests, and invalid fingerprints fail closed. The original
record remains available for diagnosis. Corruption and future failed resumes
are not automatically deleted; `TransactionStore.clear()` is an explicit
abandon/clear operation.

BM-020A remains complete. BM-020B supplies transaction storage, validation,
locking, session identity, and startup classification. BM-020C owns production
restart invocation, resume reconciliation, restart-loop prevention, and
recovery after resume failures.
