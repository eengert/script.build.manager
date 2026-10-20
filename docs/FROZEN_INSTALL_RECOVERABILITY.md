# Frozen install recoverability

Build capture, artifact availability, and installation readiness are separate
facts. A source capture records the desired software state. Exact frozen
coverage reports whether each installed managed add-on has its captured ZIP.
Install recoverability reports what Build Manager can safely do when an exact
ZIP is missing.

`FrozenBuildCaptureResult.to_dict()` exposes the aggregate readiness and a
per-add-on recoverability list. The list contains only safe metadata: add-on
ID, captured version, whether the source had the add-on installed, exact
artifact availability, known repository ID when proven, policy permission,
current fallback eligibility, skip eligibility, likely behavior, and whether
manual action may be needed. It does not expose provenance details or private
configuration values.

## Exact-first policy

Every managed add-on defaults to `exact_required`. If its exact artifact is
available, Build Manager validates its digest, size, ZIP structure, add-on ID,
and version, then installs that package. It does not query a repository for an
exact artifact that is already available.

An explicit device or platform profile can opt an add-on into one of these
policies:

```json
{
  "frozen_install_policies": [
    {
      "addon_id": "plugin.video.example",
      "policy": "exact_first_with_repository_fallback_or_skip",
      "repository_id": "repository.example"
    }
  ]
}
```

Supported policy values are `exact_required`,
`exact_first_with_repository_fallback`, and
`exact_first_with_repository_fallback_or_skip`. A policy may omit
`repository_id` when fallback is permitted in principle but no trusted
repository is known. In that case the report marks fallback unavailable; the
user may only skip if the policy permits it. All critical add-ons remain
exact-only unless a profile explicitly changes their policy. Dependency
optionality, add-on type, name, and past artifact availability never grant
skip permission.

## Repository trust and fallback

Build Manager offers repository fallback only for the concrete repository ID
declared by policy and represented by an exact captured, enabled repository
add-on. It validates that repository ZIP and uses only its captured endpoint metadata,
without requiring the repository to be installed on the target. It does not infer a repository from vague
provenance text, another installed repository, an add-on name, or a placeholder
origin.

After the user chooses **Install Current Version**, the explicit execution model
is **PREPARE -> REVIEW -> APPLY**. `RepositoryPreparationService` reads the
captured repository ZIP, uses the shared bounded downloader to obtain its index
and replacement ZIP, validates identity/version/size/hash and actual dependency
closure, verifies D-028, and imports admitted immutable ArtifactStore objects.
It rereads source authority after preparation. This happens before transaction
creation, updater quarantine, prerequisite installation or other Kodi mutation.
Unsupported repository metadata fails closed; no installed repository supplies
source authority. See [Repository preparation](REPOSITORY_PREPARATION.md).

A fresh Plan shows the actual prepared version for approval. Apply revalidates
the exact source, policies, choices, stored bytes, actual dependency requirements,
target evidence and review freshness before mutation. Later remote changes have
no effect on the pinned installation. Missing/corrupt bytes block execution;
changed prepared identity requires fresh approval. Exact packages remain
exact-first and require no network preparation. Skip and Cancel remain explicit.

Standalone unresolved fallback returns `preparation_required` with code
`PREPARATION_REQUIRED` and instructions to prepare/review. It creates no
transaction or updater quarantine. Standalone callers continue through
`StandalonePreparationSource`, the shared preparation service, Plan, and
`FrozenInstallCoordinator.install_prepared(target, review)`. This preserves
repository fallback through an explicit interface. Captured versions and source
manifests are never rewritten to claim replacement versions existed on source.

Resumption uses exact saved replacement bytes and durable resolved identities,
never a new download. Legacy incomplete repository `SELECTED` records require
Needs Attention with transaction/quarantine evidence preserved. Held retries
validate source archive requirements and D-028 before importing artifacts. Linked
frozen restart hooks run common package/D-028 admission before returning for
operations without activation holds; registry refresh remains held-only.

For a known repository the dialog offers **Install Current Version**, **Skip**
when policy and dependency rules permit it, and **Cancel Build**. The dialog
states the original captured version and warns that the repository version may
differ. When no trusted repository is known it offers **Skip** and **Cancel
Build**, with a manual-install warning. It does not show an install-current
choice in that case.

## Skip, cancel, and unattended runs

Skip is an explicit installation resolution. It does not mark the add-on as
installed and cannot satisfy a required dependency. Build Manager offers or
accepts Skip only when policy permits it, no captured managed add-on has a
required edge to the skipped node, and the add-on is absent on the target.
Build Manager does not remove a previously installed add-on to implement
Skip. Optional dependency edges alone do not grant this choice. The selected
resolution is passed into the normal configuration reconcile request; a skipped
add-on is removed from that in-memory desired set and the configuration
dependency preflight rejects any required edge back to it. The original
manifest is unchanged. BM-020's durable restart request stores the same safe
resolution records so post-restart reconciliation preserves the choice.

Cancel Build returns before transaction creation or software mutation. The
updater guard and existing transaction lifecycle continue to apply after a
user selects an install resolution. If an unattended run reaches a required
choice, it returns `USER_RESOLUTION_REQUIRED`; it does not choose fallback or
Skip. A valid recorded choice is persisted with the transaction and reused
across the supported restart boundary without prompting again.

## Validation and resolution identities

`validate_frozen_manifest()` remains strict and exact-only. A separate
`validate_frozen_install_plan()` can accept only policy-authorized missing
artifacts with a coherent dependency graph. It still validates every exact
artifact and fails closed on unsupported states.

The immutable resolution sidecar has its own deterministic identity and
records the source version, selected resolution (`exact`, `repository_current`,
or `skipped`), repository ID if used, resolved version, artifact digest and
size, desired enabled state, and terminal install state. Transaction state
stores the safe selection and progress fields needed to resume. It stores no
package bytes, private values, credentials, or repository URLs.

The fingerprints are distinct:

1. **Source software fingerprint** identifies the captured desired software
   state.
2. **Install-plan fingerprint** identifies the source software plus explicit
   recovery policy.
3. **Resolution fingerprint** identifies the selected per-add-on outcomes and
   resolved artifacts.
4. **Resolved software fingerprint** identifies the resulting installed
   versions, enabled states, and explicit skips.

No derivative identity replaces or mutates the original capture.

## Private overlay compatibility

Resolution compatibility is checked only against public declarations naming
private-setting owners and structured-resource owners with supported versions.
The check does not open or inspect overlay values. A resolution that changes an
add-on owning declared private settings is rejected. A structured-resource
owner may change only to a declared compatible version and cannot be skipped.
Unrelated add-ons do not require a source-fingerprint rebind. In the current
Family Room example, YouTube is unrelated to the Red Light resources, so an
explicit YouTube skip or repository version can be accepted without reading or
rewriting the Red Light overlay.

## Sanitized Family Room example

The retained Family Room capture records YouTube `7.4.4+unofficial.2` as
installed and enabled, with its exact ZIP unavailable. Retained evidence did
not establish a trustworthy repository ID. Its device-profile policy now
permits exact-first repository fallback when a trusted repository can be
proven, or an explicit Skip. For the retained capture, Build Manager reports
repository fallback unavailable, Skip permitted, and manual installation may
be needed later. No other optional-edge add-on receives that policy.

The tracked readiness is 30 exact frozen artifacts out of 31 installed,
managed, non-system add-ons, with captured desired state complete. This is
architecture and fixture evidence only; it does not claim a macOS install
retry, Kodi test-app launch, tvOS validation, or real-device validation.
