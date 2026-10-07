# Repository Current preparation before Apply

This backend removes the missing-package review gap for library Install. It is
an explicit preparation step; Plan preview remains read-only. No frontend is
wired by this change.

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
Standalone/path-based resolution retains its existing behavior.

`PreparedRepositoryResolution` is separate from the terminal
`FrozenInstallResolutionManifest`. It is serializable for callers that need to
save preparation, but this stage persists only immutable ArtifactStore objects.
Its identity includes a digest of the exact library root/entry, profile, build,
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

Apply rereads the library, profile, source/plan identity, artifact metadata/bytes
and dependency compatibility before transaction creation. Its initial resolution
records contain the prepared RESOLVED identities; resolved packages never invoke
`resolve_repository_current()` again. The existing frozen transaction persists
records and resolution/software fingerprints, and its existing library target
and BM-020 restart owner retain continuity. No new lifecycle owner exists.

Offline coverage is in `tests/test_repository_preparation.py`, alongside the
existing Plan, frozen resolution/install, library install, repository/add-on,
BuildManager and transaction suites. This is backend evidence, not runtime or
frontend qualification.
