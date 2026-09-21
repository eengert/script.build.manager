# BM-020B/C1 restart transactions and manual handoff

BM-020B provides the durable handoff foundation. BM-020C1 adds the typed
capability decision and manual-restart caller contract; it does not yet resume
reconciliation. No current project platform has an approved automatic Kodi
application-restart adapter.

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
  AWAITING_RESTART → manual/automatic handoff point
RESUMING         → reserved for BM-020C
NEEDS_ATTENTION   → explicit recovery/diagnostic state
```

## Preparation and atomicity

`prepare_restart_transaction(request, reconcile_result, session_id)` creates a
record only when reconciliation succeeded, the typed restart requirement is
`KODI_RESTART`, the fingerprint and request are valid, and no active record
already exists. `NONE` creates no record. A failed reconciliation never creates
a restart transaction, even if an earlier operation reported a restart
requirement.

`RestartCapabilityResolver` maps the currently supported platform identities
(`macos`, `android`, `shield`, `fire_os`, and `tvos`) conservatively to
`MANUAL_APP_RESTART_REQUIRED`; unknown identities use the same conservative
default. The resolver is injectable so a separately approved automatic adapter
can be added later without scattering platform conditionals through the
coordinator.

`RestartCoordinator` is the production caller seam. A successful
`RestartRequirement.NONE` result returns `COMPLETE` and creates no transaction.
A failed reconciliation returns `FAILED` and never prepares a transaction. A
successful `KODI_RESTART` result on the current manual capability creates and
read-backs `AWAITING_RESTART`, then returns `MANUAL_RESTART_REQUIRED` with the
safe guidance `Restart Kodi completely to continue.` It never quits, restarts,
or invokes host process management. Repeated same-session calls reuse the
matching durable handoff without reconciling again or creating a duplicate.

The transaction's `restart_attempt_count` counts automatic restart attempts,
not observed process boundaries. The manual path creates the record with count
`0` and leaves it at `0`; a later session change is sufficient evidence that a
genuine new Kodi process exists. BM-020C resume work must accept that
`AWAITING_RESTART` plus a different session and count `0` is
`READY_FOR_RESUME`.

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
locking, session identity, and startup classification. BM-020C still owns
pre-resume fingerprint validation, `RESUMING` claim, resumed reconciliation,
success clearing, restart-loop prevention, and recovery after resume failures.
