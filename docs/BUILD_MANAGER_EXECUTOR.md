# BM-020A production executor

BM-020A exposes `resources.lib.build_manager.BuildManager.reconcile()` as the
stable orchestration entrypoint for one Build Manager reconciliation request.
The request contains only a manifest path and device-profile selector. It does
not contain Kodi runtime objects, current state, mutable managers, or private
configuration values.

## Execution contract

The coordinator runs the existing subsystem boundaries in this order:

1. load and validate the manifest;
2. inspect Kodi state read-only;
3. resolve the selected platform/device layers;
4. resolve configuration packages and perform read-only dependency preflight;
5. create the deterministic planner plan;
6. execute planner actions in order through their owning subsystem;
7. inspect and validate the resulting state read-only.

Repositories, add-on installation, dependency closure, add-on enable/disable,
skin activation, and configuration deployment are not reimplemented here.
Required dependency work is owned by `DependencyAwareInstaller` for each
installation action; there is no executor-wide dependency mutation phase.

The supported planner action mapping is:

| Action | Owner |
| --- | --- |
| `INSTALL_REPOSITORY` | `RepositoryManager` (plus explicit disable reconciliation when required) |
| `INSTALL_ADDON` | `DependencyAwareInstaller` |
| `ENABLE_ADDON` / `DISABLE_ADDON` | `AddonStateReconciler` |
| `SET_SKIN` | `SkinActivator` |
| `CONFIGURE` | `ConfigurationManager` |

Unknown action kinds fail closed. Execution stops at the first failed action;
earlier action results and restart requirements remain in the aggregate. A
failed action contributes no new restart requirement. Successful no-op and
second applications report `RestartRequirement.NONE` when nothing changed.

## Fingerprint and result

The result includes the safe request, ordered plan/action results, a structured
phase failure when applicable, and the aggregated BM-019 `RestartReport`.
The desired-state fingerprint is a SHA-256 over canonical normalized resolved
state. It includes build/profile/repository/add-on/skin/config declaration
identity and restart policy, but excludes current Kodi state and
`private_overlay`. Configuration values and managed file contents enter only
through BM-015's content identity; raw private/authentication values are not
serialized.

BM-020A deliberately does not restart Kodi, persist transaction files, resume
after restart, manage session identity, handle restart loops, or acquire a
process-wide lock. Those concerns remain later BM-020 scope.

Validation uses the existing BM-014 validator and BM-015 validation snapshot;
it does not add a second desired-state or configuration implementation.

## Disposable executor fixture

`tools/kodi_test.py validate-build-manager` uses the explicit test-only
`resources/builds/examples/bm020a-executor.example.json` fixture. It requests
only `skin.arctic.fuse.3` and the checked-in `af3-common` package, and is never
the personal `eric-main` build. The harness prepares the disposable profile by
copying AF3's known dependency closure, initializing AF3's generated runtime
state, and then invoking the normal `BuildManager.reconcile()` API with the
fixture's device selector.

This gate proves top-level inspection, resolution, preflight, planning,
ordered owner dispatch, result aggregation, fingerprinting, post-validation,
and idempotent re-entry. Dedicated disposable gates remain the evidence for
repository bootstrap, general add-on/dependency installation, skin activation,
and the production `af3-common` configuration backend; BM-020A does not claim
that the incomplete personal `family-room` distribution is fresh-installable.

Pending separately from BM-020A is production source/distribution coverage for
the personal build: repository bootstrap, authoritative sources for POV, Red
Light, Umbrella, MyAccounts, and AF3, explicit source-repository binding, and
multiple-provider ambiguity/supply-chain policy.
