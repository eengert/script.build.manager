# BM-022 Frozen Build Installation

BM-022 installs a complete BM-021B frozen build from its immutable artifact
store. It is deliberately separate from repository resolution: the manifest
selects the exact add-on version and SHA-256 artifact, and the installer does
not ask Kodi to choose a newer repository version.

## Safety boundary

The installer accepts only a typed schema-v1 manifest whose capture status is
`COMPLETE`. Every installed non-system node must have a matching
artifact-store record, verified ZIP identity, exact version, size, and SHA-256
digest, even when its incoming dependency edges are optional. An optional
dependency captured as absent is represented by a node with
`capture_status: missing`, disabled desired state, and no artifact; the
validator retains that node for graph
validation but excludes it from the installation order. System dependencies
remain declarations only. Missing artifacts for installed nodes, malformed
ZIPs, duplicate nodes, invalid edges, cycles, and an existing wrong-version or
broken installation fail closed before the next mutation.

Capture marks a manifest complete only when these same conditions hold, but
the installer validates them independently. An optional edge never excuses a
missing artifact for a node that was installed and included in the captured
software state.

Kodi 21 does not expose a non-interactive exact local-package install API for
this workflow. BM-022 therefore reuses Build Manager's previously reviewed
staged-package boundary: extract into a same-filesystem temporary directory,
validate the add-on identity and version, atomically rename into the Kodi
add-ons directory, request `UpdateLocalAddons`, and verify the registered
version and health. Existing exact healthy versions are idempotently reused;
replacement or downgrade is not silently attempted.

## Transaction and updater quarantine

The profile-local frozen transaction is persisted before the first updater
guard mutation. Its phases are:

`preparing` → `installing_software` → `configuring` → `awaiting_restart` →
`resuming` → `validating` → `complete`

Any failed phase becomes `needs_attention`. The durable record retains the
original `general.addonupdates` policy. The initial install captures the
original policy, persists the transaction, sets `NEVER_CHECK` once, and reads it
back. That is the only quarantine write. After a process restart `NEVER_CHECK` is
only **verified** before BM-020 startup/resume (startup, the quiescence
continuation, and the held retry all read the setting and never write it) and
remains active until final exact-state validation completes. Only then is the
original policy restored and the frozen transaction cleared. Explicit abandon
restores the policy and clears the transaction, but does not pretend to roll
back installed software.

Kodi 21.3 can deadlock on a changing write to `general.addonupdates` while it is
starting, and it persists global settings through its normal application stop.
The quarantine must therefore already be on disk when Kodi restarts, which is
why the qualification restart uses a graceful quit (see
`BM_TEST_APP_HELPER.md`) rather than a signal. If the policy read after a restart
is not `NEVER_CHECK`, the transaction fails closed with
`FROZEN_UPDATER_NOT_QUARANTINED` (or `FROZEN_UPDATER_STATE_UNAVAILABLE` when it
cannot be read or is malformed): no setting is written, BM-020 does not resume,
no configuration or finalization runs, the policy is not restored, and the
transaction keeps its identity, lifecycle stage and activation hold in
`needs_attention`. This is a hard stop for a person to investigate, not a case
that recovers automatically.

Normal qualification restart sequence:

`quit` → prove the process stopped → snapshot the persisted updater policy →
**require `NEVER_CHECK`** → relaunch the Test.app with `-p` → identify the
portable process → continue with the verify-only resume.

BM-020 remains the owner of the ordinary configuration and restart transaction.
BM-022 calls the existing Build Manager reconciliation path after the exact
software graph is installed, records the restart handoff, and permits frozen
finalization only after a new Kodi session has successfully resumed BM-020.

## Disposable proof

The disposable `validate-frozen-install` gate uses real Kodi ZIP structure, a
repository node, an ordinary add-on, a required dependency, the real
content-addressed artifact store, and a complete typed manifest. It proves:

- exact artifact hashes and deterministic repository → dependency → ordinary
  add-on installation order;
- durable BM-020 restart handoff and a restart-time updater quarantine check
  before BM-020 startup (the gate's log marker keeps its historical
  "reasserted" wording; the product now verifies instead of writing);
- existing Build Manager configuration through the production path;
- final exact versions, enabled-state validation, policy restoration, and
  clearing of both BM-022 and BM-020 transactions; and
- no mutation of the real Kodi profile.

The harness uses the AF3/BM-021B pattern of disposable-only runtime state and
does not claim that a pristine first-ever installation of every arbitrary Kodi
add-on is proven beyond the tested exact-artifact boundary.
