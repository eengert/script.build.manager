# Repository Current preparation before Apply

This backend removes the missing-package review gap for library Install. It is
an explicit preparation step; Plan preview remains read-only. Existing native
Install and Update / Repair frontends already invoke preparation, display its
retrieval step, and request a fresh review. These callers retain their library
source and prior accepted-record behavior. This correction adds the standalone
adapter to the same backend service; it adds no second transaction owner.

The caller keeps the exact `PlanTarget` returned from the selected library,
records `DecisionChoice.INSTALL_CURRENT`, and calls:

```python
result = RepositoryPreparationService(artifact_store).prepare(chosen_target)
if result.code is PreparationCode.READY:
    prepared_target = dataclasses.replace(
        chosen_target, prepared_resolution=result.prepared)
    plan = plan_service.preview(prepared_target)
    # Present this fresh plan, including its actual package version.
    # After user approval, validate this exact target and plan.review.
    check = plan_service.validate(prepared_target, plan.review)
    if check.is_current:
        install_target = LibraryInstallTarget.from_plan_target(prepared_target)
        coordinator.install_target(
            install_target,
            prepared_resolution=prepared_target.prepared_resolution,
            resolution_choices={aid: ResolutionChoice(choice.value)
                                for aid, choice in prepared_target.choices})
```

Only a `CHANGES_READY` preview has a review identity. Preparation success itself
is neither approval nor permission to Apply. Preserve the exact target and
choices across review/validation/execution; never follow a later library
selection. Library Repository Current without preparation fails before mutation.
Standalone/path-based unresolved resolution now returns outcome
`preparation_required`, code `PREPARATION_REQUIRED`, before transaction/updater or
Kodi mutation. Its message names the explicit prepare/review continuation.

Standalone callers use the same service and Plan:

```python
source = StandalonePreparationSource(
    software_manifest_path=absolute_frozen_path,
    admitted_fingerprint=admitted_frozen.fingerprint(),
    device_profile_id=profile_id,
    policies=tuple(explicit_policies),
    configuration_manifest_path=absolute_public_path_or_None,
    configuration_packages_root=absolute_packages_root,
)
target = PlanTarget(
    source.configuration_manifest_path or "", profile_id,
    source.software_manifest_path, standalone_source=source,
    choices=((addon_id, DecisionChoice.INSTALL_CURRENT),),
)
result = preparation_service.prepare(target)
if result.code is PreparationCode.READY:
    target = dataclasses.replace(target, prepared_resolution=result.prepared)
    plan = plan_service.preview(target)
    # Present the actual prepared versions/actions; obtain fresh operator approval.
    # Only an approved CHANGES_READY plan with its exact review can continue.
    coordinator.install_prepared(target, plan.review)
```

The standalone source explicitly admits the frozen fingerprint, source paths,
profile, and policies. `None` explicitly declares no configuration; it projects
software-only desired state with no configuration runner. A supplied public
manifest resolves the chosen profile and its configuration packages. A configured
standalone continuation must supply the existing configuration/restart runner
wired to that same configuration source and packages root (including its resume
owner); absence returns `CONFIGURATION_RUNNER_REQUIRED` before mutation. The
adapter never silently skips requested configuration or chooses a different loader.
No new durable configuration-root format is introduced. This adapter
does not manufacture a library entry or inspect installed repositories. Its
source identity, selected effective configuration and policy identities are
rechecked after preparation and at the final execution boundary. Offline callers
may inject a `BuildPlanService` into `install_prepared` using synthetic read-only
owners; production uses the standard Plan owners with the coordinator's artifact
store and platform backend.

Unresolved previews may truthfully show `DECISION_REQUIRED` or
`RESOLUTION_REQUIRED` (preparation required), with no review identity or Apply
permission. Exact structural validation still runs. Unknown package requirements
are never represented as skipped or as `NO_CHANGES`; final D-028 admission is
reserved for a fully prepared/verifiable plan. Prepared approval binds source,
profile/configuration, policies/choices, exact and replacement artifacts, actual
requirements, actions/versions, and verified platform evidence.

`PreparedRepositoryResolution` is separate from the terminal
`FrozenInstallResolutionManifest`. It is serializable for callers that need to
save preparation, but this stage persists only immutable ArtifactStore objects.
Its identity includes a digest of the exact library root/entry or explicit standalone source, profile, build,
frozen source fingerprint, policy/plan fingerprint, effective build/configuration
fingerprint, and typed RESOLVED records. Each record binds add-on, captured and
resolved versions, permitted repository ID, desired enabled state, SHA-256 and
size. URLs and local paths are absent from the record and result. Dependency
metadata lives in the exact ZIP and is reconstructed read-only for each Plan
and install preflight, rather than trusting a separate dependency claim.

Repository authority is the captured repository ZIP referenced by the frozen
manifest and validated by the frozen recovery model. Preparation validates and
reads that ZIP's `addon.xml`, then fetches only its index and the target package
under its ZIP datadir using the established add-on/version/filename convention.
It neither inspects nor installs/enables Kodi repositories. The production
fetcher enforces HTTP/HTTPS, rejects embedded credentials and unsafe redirects,
uses a 30-second timeout, and bounds index/package downloads to 10/100 MiB.
Existing ZIP validation enforces exact add-on/version and archive limits.

Supported metadata is one unambiguous repository `dir`, with plain `info` and
`datadir zip="true"`. Multiple or version-conditioned directories, compressed
indexes, unsafe URLs, datadir queries/fragments, ambiguous duplicate target index
entries, malformed versions and XML entity/DTD declarations fail closed. This
initial seam deliberately does not guess platform/version selection or fall
back to other repositories. The supported form matches the existing repository
package convention; unsupported metadata needs a separately scoped extension.

Preparation checks required dependencies against the frozen graph and choices
before import. Uncaptured, skipped or incompatible dependencies fail. Fresh Plan
reconstructs the same dependencies and blocks invalid graphs, private ownership
and activation holds before review. The existing held lifecycle's restriction on
Repository Current is preserved. Safe result codes carry no untrusted exception
text; failure creates no frozen/restart transaction or updater guard and makes
no Kodi mutation. An interrupted multi-package preparation may leave already
imported immutable objects; they are not approval or install state.

Apply rereads the library or standalone source, profile, source/plan identity, artifact metadata/bytes
and dependency compatibility before transaction creation. Its initial resolution
records contain the prepared RESOLVED identities; resolved packages never invoke
`resolve_repository_current()` again. The existing frozen transaction persists
records and resolution/software fingerprints, and its existing library target
and BM-020 restart owner retain continuity. No new lifecycle owner exists.

Offline coverage is in `tests/test_repository_preparation.py`, alongside the
existing Plan, frozen resolution/install, library install, repository/add-on,
BuildManager and transaction suites. This is backend evidence, not runtime or
frontend qualification.
