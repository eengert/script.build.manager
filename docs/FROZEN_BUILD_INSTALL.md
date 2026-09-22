# BM-022 Frozen Build Installation

BM-022 installs a complete BM-021B frozen build from its immutable artifact
store. It is deliberately separate from repository resolution: the manifest
selects the exact add-on version and SHA-256 artifact, and the installer does
not ask Kodi to choose a newer repository version.

## Safety boundary

The installer accepts only a typed schema-v1 manifest whose capture status is
`COMPLETE`. Every non-system node must have a matching artifact-store record,
verified ZIP identity, exact version, size, and SHA-256 digest. System
dependencies remain declarations only. Missing artifacts, malformed ZIPs,
duplicate nodes, invalid edges, cycles, and an existing wrong-version or
broken installation fail closed before the next mutation.

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
original `general.addonupdates` policy. `NEVER_CHECK` is reasserted before
BM-020 startup/resume and remains active until final exact-state validation
completes. Only then is the original policy restored and the frozen
transaction cleared. Explicit abandon restores the policy and clears the
transaction, but does not pretend to roll back installed software.

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
- durable BM-020 restart handoff and restart-time updater reassertion before
  BM-020 startup;
- existing Build Manager configuration through the production path;
- final exact versions, enabled-state validation, policy restoration, and
  clearing of both BM-022 and BM-020 transactions; and
- no mutation of the real Kodi profile.

The harness uses the AF3/BM-021B pattern of disposable-only runtime state and
does not claim that a pristine first-ever installation of every arbitrary Kodi
add-on is proven beyond the tested exact-artifact boundary.
