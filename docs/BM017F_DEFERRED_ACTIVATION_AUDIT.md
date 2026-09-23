# BM-017F — Deferred Activation & Structured-Resource Lifecycle

Status: **complete as an investigation/implementation attempt**. Result:
`BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE`.

This is the historical result of the first BM-017F attempt. It requires local
revalidation before it can be accepted: BM-023A-R1 reported 30 exact
artifact-backed installed managed add-ons, with Red Light 2.6.8 among them and
YouTube 7.4.4+unofficial.2 as the single exact-artifact gap. The retained frozen
manifest and ArtifactStore must be checked through the production model before
concluding that the Red Light object is unavailable.

BM-017F did not modify product code or begin a later milestone. The exact
Red Light 2.6.8 package is required to re-inspect its source before choosing an
initializer and to prove the complete clean-destination lifecycle. The
maintainer's published Omega metadata URL
(`https://repo.redwizard.xyz/redwizardrepo/21omega/addons.xml`) and the derived
exact package URL
(`https://repo.redwizard.xyz/redwizardrepo/21omega/plugin.video.redlight/plugin.video.redlight-2.6.8.zip`)
redirected to generic Google HTML in this run. The returned content was not a
ZIP and had SHA-256
`8cc849b78b499dd61b1cdc010f7e6446fe307c1bae069de7e53956eade4d3593`, which does
not match the previously verified package SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`. It was
rejected. No substitute, repack, or unverified archive was used.

## Current production ordering

The existing BM-022 install path stages and atomically renames the exact ZIP,
then calls Kodi's `UpdateLocalAddons` and polls for registration
(`KodiRuntimeFrozenArtifactBackend.install_exact()` in
`resources/lib/frozen_install.py`). Kodi discovery reports a newly added
non-system/non-optional add-on disabled. The coordinator then enforces each
manifest node's final `desired_enabled` state in the install loop. Only after
all resolved packages reach their terminal state does it enter `CONFIGURING`
and call the ordinary reconciliation runner (`FrozenInstallCoordinator.install()`).
For a desired-enabled service this remains:

```text
install -> register -> final enable -> configure/public config/private apply
```

The ordinary BM-020 planner also orders `ENABLE_ADDON` and `DISABLE_ADDON`
before `CONFIGURE`. `BuildManager` applies public configuration and then the
prepared private overlay, including structured private resources, within that
configuration action. Kodi's service manager starts an enabled service
extension on the `Enabled` event and runs its Python entrypoint asynchronously.
Thus applying a final enabled state before private configuration may start the
owner too early.

Restart ownership is split today:

1. `service.py` calls `run_startup()` before BM-022 finalization.
2. `run_startup()` calls `ensure_frozen_install_guard()` before it invokes
   BM-020 resume. The guard is reasserted before resumed reconciliation, and
   fails closed if it cannot be restored. `run_frozen_install_startup()` repeats
   this check defensively after BM-020.
3. BM-020 `ResumeCoordinator` validates the desired-state and overlay identity,
   runs ordinary reconciliation once, and moves to `NEEDS_ATTENTION` if that
   reconciliation still requests another restart.
4. BM-022 `resume_after_restart()` verifies a different Kodi session, reasserts
   updater quarantine, reloads and validates frozen resolution identities, and
   finalizes the frozen install. It does not rerun the configuration runner.

The updater guard therefore is reasserted before BM-020 startup work in the
current service path. However, neither transaction stores a structured-resource
lifecycle stage or activation-hold identity. BM-020 owns reconciliation and its
restart transaction; BM-022 owns frozen software, resolution, and updater
quarantine. There is no single durable owner for the sequence “hold, prove
quiescence, initialize, apply and verify private fields, release, then validate
runtime.” BM-020's one-restart contract also cannot advance through repeated
resource stages. A safe generalized coordinator design was not selected or
implemented without the exact resource package.

## Kodi 21.1 Omega activation findings

The disposable harness runtime reported Kodi 21.1. Source review used the
matching `21.1-Omega` tag:

- `CAddonDatabase::SyncInstalled()` inserts new IDs with `enabled=0`, except
  system and optional-system add-ons. `CAddonMgr::FindAddons()` scans the addon
  directories, synchronizes the installed registry, and refreshes caches.
- The `UpdateLocalAddons` builtin calls `FindAddons()` directly. This discovery
  path does not enable the new add-on or publish the enabled event that starts a
  service. Kodi's service manager starts enabled service extensions on startup
  and on the `Enabled` event; disabling emits a stop event.
- Kodi's separate native installer path calls `CAddonMgr::LoadAddon()` after
  copying a package. `LoadAddon()` enables the add-on if it is disabled. That
  path is not Build Manager's staged extraction plus local scan and must not be
  used for a deferred-activation install.
- For the staged local-scan path on Kodi 21.1, a new ordinary add-on is
  discoverable as installed while disabled. An existing ID with an extant
  disabled database record remains subject to that stored state; Build Manager
  does not edit Kodi's Addons database. No direct database manipulation was
  used.

Primary source links: [AddonDatabase.cpp](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonDatabase.cpp#L354-L415), [AddonManager.cpp: discovery](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonManager.cpp#L652-L684), [AddonBuiltins.cpp](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/interfaces/builtins/AddonBuiltins.cpp#L358-L366), [Service.cpp](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/Service.cpp#L34-L90), [native installer reload](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonInstaller.cpp#L729-L750), and [AddonManager.cpp: load/enable](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonManager.cpp#L711-L747).

## Disposable service proof

A synthetic helper and fake service were created only under `.kodi-test`, then
removed by resetting that harness. Kodi was launched with the harness's
disposable `HOME`; no Kodi Build Manager Test app, device, Red Light package,
provider, or private value was used. A separate version-check command mistake
without that `HOME` is disclosed in the worker handoff; a later process check
found no running Kodi process, but no normal profile was inspected and
transient startup or profile access cannot be ruled out.

| Check | Observation |
|---|---|
| Staged folder followed by `UpdateLocalAddons` | `scan_registered=true` |
| State after registration | `enabled_after_scan=false` |
| Explicit disabled hold via Kodi JSON-RPC | `hold_rpc_no_error=true`; `enabled_after_hold=false` |
| Fake service before and after hold | Startup marker absent |
| Same disabled state after a full harness restart | Disabled; marker absent |
| Enable after creating a fake readiness sentinel | Service marker appeared and recorded readiness true |

This proves the synthetic Kodi 21.1 registration/activation path. It does not
prove Red Light initialization, Red Light's background behavior, dependency
startup interactions, or end-to-end lifecycle safety. The disposable harness is
currently stopped and reset.

For a newly staged standalone ordinary add-on under this Kodi version, the
evidence supports a no-race registration hold. It does not prove safety against
another coordinator enabling that add-on as a dependency. An already-enabled
owner that may have executed earlier in the same process still requires a
process restart while disabled before structured private mutation can claim
quiescence. Native Kodi installer reinstallation is not an acceptable
substitute because its load path may enable the owner immediately.

## Dependency and activation safety

Kodi distinguishes installed presence from enabled state. Its dependency
resolver looks up dependencies including disabled add-ons, so a held add-on
remains present for package dependency resolution. However, `CAddonMgr::EnableAddon()`
walks required dependencies, then enables the dependency closure; each transition
publishes `Enabled`, which can start service extensions. A separately enabled
dependent can therefore undo an add-on's temporary disabled state.

Build Manager makes the same distinction: BM-012 reports an installed-disabled
dependency separately from a missing package, but
`DependencyResolver.reconcile_dependencies()` enables required disabled
dependencies before `DependencyAwareInstaller` installs the requested root.
BM-020 preflights required closures of desired-enabled roots; that closure
currently protects dependencies from inappropriate disable actions, but does
not implement a deferred-activation barrier. This is not permission to disable
unrelated add-ons.

Because the exact package and its dependency metadata could not be re-inspected,
and no package-specific enabled-root graph was validated in this disposable
probe, this run does not prove that no other managed startup add-on can enable
or invoke Red Light before private configuration. A future generic lifecycle
coordinator must account for the affected required dependency/dependent closure
and either propagate a narrow activation barrier or fail closed when it cannot
prove safe ordering. That graph behavior remains unimplemented and untested.

Source: [AddonManager.cpp: dependency lookup and enable](https://github.com/xbmc/xbmc/blob/21.1-Omega/xbmc/addons/AddonManager.cpp#L771-L876).

## Red Light initialization and validation disposition

BM-017E's previously verified source audit remains historical evidence for the
exact package SHA above. It identified `base_cache.ensure_database_tables()` as
the add-on-owned DDL helper and `settings_cache.sync_settings()` as the default
seed/migration path. The latter performs broader settings work than a narrow
initializer contract. BM-017F could not repeat this audit against the exact ZIP,
prove import-time or call-time side effects, inspect the package's current schema
and WAL contract, or test initialization without provider/network/UI/service
activity. No initializer was called and no generic SQL or file-copy substitute
was introduced.

Accordingly, BM-017F did not attempt resource initialization, fake private
field application, restart continuation, activation release, second-run
idempotence, or package-specific runtime verification. The existing
`resources/lib/redlight_resource.py` continues to fail closed for an absent
resource and an uninitialized lifecycle. No success or retry readiness is
claimed.

## Exact next step and historical classification

Revalidate the retained Family Room frozen manifest's Red Light artifact
reference and resolve that reference through the production ArtifactStore API.
If the exact object exists, check the pinned SHA-256
`64036b818ed44f4fc56cbf6fd32a48a0713517624ae711a108b737f907f05927`, size,
ZIP integrity, package root, traversal/symlink safety, and addon ID/version
before opening its source. If it is missing or the manifest reference is
inconsistent, report that precise retained-state result. Do not use a
substitute.

- BM-017E historical result:
  `BLOCKED_CROSS_COORDINATOR_QUIESCENCE_STAGE_UNSUPPORTED`.
- BM-017F first attempt: complete as investigation/implementation attempt;
  historical result `BLOCKED_PINNED_RED_LIGHT_2_6_8_ARTIFACT_UNAVAILABLE`,
  pending retained-manifest and ArtifactStore revalidation.
- Red Light clean-destination lifecycle: **UNSUPPORTED**.
- macOS BM-023A retry: **STILL_BLOCKED**; not started.
- tvOS: **NOT VALIDATED**.
- Product implementation: **none**.

## Validation

- Focused BM-017A/C, BM-020, BM-022, BM-023B, planner, dependency, and manifest
  regressions: **703/703**.
- Full repository suite: **1647/1647**.
- `compileall`: passed.
- JSON parsing: **7 files** parsed successfully.
- `git diff --check`: passed.
- Disposable fake-service probe: registration remained disabled across the
  tested scan/hold/restart path; it started only after the fake readiness
  sentinel was present and Kodi enabled the service.
