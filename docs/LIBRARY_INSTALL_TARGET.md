# Durable library installs

`LibraryInstallTarget.from_plan_target(plan_target)` derives an execution
selector from the exact `PlanTarget.library_source` and device profile. Keep
that target throughout review and execution. Plan review identity includes the
registered root and entry ID, even if another source resolves identically.
The future frontend still owns review freshness checks and confirmation; this
backend bridge does not grant approval or implement those interactions.

Call `FrozenInstallCoordinator.install_target(target, resolution_choices=choices)`
with a mapping of add-on IDs to existing `ResolutionChoice` values when explicit
missing-artifact decisions were approved. Target execution defaults to
noninteractive. An incomplete approved-choice mapping returns
`user_resolution_required`; it does not open an implicit decision dialog.
Profile policies come exclusively from the library-owned resolved profile;
`install_target` has no policy override. Standalone `install` retains explicit
policy overrides, and existing resolution deciders remain supported.

The selector persists only:

- `mode: library`;
- the absolute library root;
- the registered content-addressed entry ID;
- the device profile ID.

Durable deserialization and every target load authenticate the root against
`default_build_library()` for the active Kodi profile. Offline tests can inject
a scoped `isolated_library_install_authority(BuildLibrary(root))`; serialized
records cannot establish that authority. The schema and selector shape are unchanged.

The root is an internal local selector. Do not render it in frontend diagnostics.
No manifest, package payload, private overlay value, temporary file, or Python
closure is persisted. Exact software artifacts remain in ArtifactStore.

Each target load goes through BuildLibrary registry/envelope validation and
profile validation, returning the public manifest, frozen manifest, and owned
configuration package loader from the same snapshot. Selection changes do not
redirect it. Initial installation revalidates before plan evaluation and again
before transaction creation, after interactive resolution. Resume/retry reload
through `load_transaction_manifest`, checking build and frozen fingerprints.
Configuration requests carry the same selector and fingerprint; BuildManager
reloads their public manifest and packages through the library, including
preview/reconciliation after a BM-020 restart. Library mode never uses the
standalone manifest or global package loader.

Frozen transaction schema 4 adds required `library_target` metadata. Null means
standalone path mode; a typed library selector requires both legacy path fields
to be empty and its profile to match the transaction. Schemas 1, 2, and 3 remain
readable as standalone transactions; they cannot declare library mode.
Transitions preserve the selector along with policies, resolution records,
software/plan/resolution fingerprints, and activation holds.

BM-020 restart schema 2 requires a library selector inside the reconciliation
request. Schema 1 remains the emitted/read format for standalone requests.
Parsers reject conflicting source modes and invalid selectors. Historical
transactions load normally; no bulk migration is needed. New library state is
not readable by older product versions.

Missing, corrupt, unregistered, changed, or profile-invalid entries fail closed.
An initial failure creates no install transaction or runtime mutation. A resume
failure retains quarantine/holds and records needs attention for explicit
recovery. Library load outages at the durable manifest/profile boundaries use
`FROZEN_MANIFEST_INVALID`, preserving eligibility for the existing held retry
after the exact source is restored. Equivalent-active library reuse requires
the same root, entry and profile as well as the existing fingerprints.
Quiescence retry, configuration-awaiting-restart registry readiness,
and final frozen resume use the same durable source. Private-resource behavior
remains owned by the existing private/configuration owners.

Validation is offline. The lifecycle tests use disposable library/artifact and
transaction roots, real BuildManager/ConfigurationManager execution for public
configuration, fresh owners for BM-020 and frozen resume, and an injected private
owner outcome for the representative held-resource boundaries. This is backend
candidate evidence, not frontend or Kodi runtime qualification.
