# Create Build capture engine (BM-UI-003B)

`resources.lib.create_capture` prepares current, explicitly owned Kodi state
for the accepted Build Library. This engine supplies G1's capture foundation
for beta exit item 8. It does not create dialogs, register/select a build,
install, repair, restart, or change Kodi state.

## Supported contract and ownership

`CreateBuildRequest` is frozen and uses tuple collections. It contains build
ID/semver/name/description, platform and device profile IDs/labels, selected
root add-on IDs, active-skin inclusion, one `PublicCaptureSpecification`, a
public package ID, and optional existing private setting/resource declarations
with an overlay ID. Invalid IDs, duplicate/overlapping targets, noncanonical
file destinations, and known private public-package targets are rejected with
`INVALID_CREATE_REQUEST` before backend reads. No output/source/profile path
is accepted in this request. Skin keys share the runtime adapter's lowercase
fallback collision identity (`CustomID`/`customid`, `CUSTOMID`/`customid`, and
`HomeSwitcher.Foo`/`homeswitcher.foo`). Public/public, private/private and
public/private aliases are rejected before any getter runs. Ordinary add-on
setting keys retain case-sensitive identities.

Every public setting is a `PublicSettingTarget` with owner ID, key,
`SettingTargetKind` and `ConfigSettingType`. Add-on values support the existing
string/bool/int/number types; skin values retain the existing bool/string
restriction. Public files are explicit canonical Kodi-profile-relative
managed destinations. Targets are never discovered by inspecting settings or
walking profile files. Setting owners must belong to the captured software
graph; skin targets must belong to the included active skin. Optional absent
private owners represented in the frozen graph retain their absence semantics.

Trusted application composition injects the existing `InventoryBackend`,
`ArtifactStore`, `ConfigurationBackend`, `KodiStateInspector.inspect` callable
and, when needed, `StructuredPrivateResourceManager`. Existing Kodi inventory
and runtime configuration adapters satisfy these interfaces. Application code
owns runtime/profile resolution; the UI cannot supply roots. `describe_capture`
returns only roots, skin inclusion, public target counts and private opt-in,
without acquisition or backend reads.

## Public assembly

`capture(request, created_at=...)` inspects the current platform/Kodi version
and active skin through the existing state-inspection contract, then calls
`capture_frozen_build` with selected roots plus the included skin. Dependencies
stay in the frozen graph, not additional top-level managed roots. Enabled state,
exact acquisition status, artifact identity, provenance classification and
optional dependency absence come from the existing engine. No installed-folder
ZIP or repository fallback policy is synthesized.

Declared public values are read through `get_setting`/`get_skin_setting`, and
files through `read_file`. Exact bytes become independent per-capture assets.
The generated package descriptor and manifest ownership use the existing
ConfigPackage parser, loader and ownership checks via the accepted library
bundle validator. Missing required targets produce no prepared bundle.

The existing-schema manifest has BuildInfo, managed root states, optional skin,
exact ConfigDeclarations, the requested platform profile and extending device
profile, and optional private declarations/reference. Current platform identity
also resides in the frozen source. No repository declarations or permissive
install policies are invented; the existing exact/safe default remains.

Public/frozen build IDs, frozen self-fingerprint, produced and referenced
package IDs, and device profile resolution are checked before completion.
Raw frozen diagnostic maps/node error text are removed from public material,
while typed capture statuses/provenance remain. The canonical frozen fingerprint
is recomputed over that public graph; private binding uses this same identity.
Ordering is deterministic for a fixed request/state/timestamp. `created_at` is
explicit so separate confirmations can retain a timestamp without clock drift.

## Private boundary

Private capture is opt-in. Existing `PrivateSettingDeclaration` values are
read through the same typed read-only configuration backend and validated in
`PrivateOverlayEntry`. Existing structured declarations go only through
`StructuredPrivateResourceManager.capture`, including the established Red Light
adapter. Adapter results must report `captured` with verified fields; resource
owner/version must agree with captured software. Overlay ownership/completeness
and software-fingerprint binding pass existing private-overlay validation.

Private payloads reside only in the result's separate `private_overlay` field,
excluded from result repr and `safe_dict`. They cannot be reached through public
bundle serialization or public staging. This task never saves PrivateOverlayStore.
Optional actual absence may be omitted; infrastructure errors are not treated
as optional absence. Required failures discard the entire overlay and bundle.

Red Light capture preserves its existing quiesced/held/disabled and initialized
resource prerequisites. If they are unavailable, this engine reports incomplete;
it does not establish a hold, disable an owner, initialize a DB, or reload it.
Structured capture must not alter managed resource files or sidecars. Red Light
reads bounded main DB and optional WAL bytes through no-follow descriptors for
all ancestors and files. Two reads and inode/size/mtime/ctime checks establish
one stable snapshot; source and lifecycle checks bracket the temporary query.
A changed/replaced source fails safely as incomplete, with no prepared outputs.
SQLite queries only a private disposable DB/WAL copy, so committed WAL values
are current and any SQLite SHM writes occur only in scratch. Live SHM is never
copied. Scratch is removed before return, including failure paths, and its paths
and private content stay outside all public material. Each DB/WAL file is
bounded to 64 MiB; one deterministic attempt is made without retries. Status
inspection retains its immutable/no-sidecar, uncheckpointed-WAL fail-closed
behavior; apply and verify behavior are unchanged.
The existing pre-0.2.0 SQLite URI `#` hardening finding remains unchanged.

## Result and registration boundary

`CreateBuildResult` distinguishes COMPLETE, INCOMPLETE and FAILED. Its safe
summary includes build name/version, managed-root/add-on counts, skin inclusion,
declared public/private target counts, exact/uncaptured artifact counts, stable
gap codes and validated add-on ID/status pairs for software gaps. It excludes
contents, private values, absolute paths and exception/diagnostic payloads.
COMPLETE requires all requested required captures and public library validation.
INCOMPLETE reports missing software or unreadable required targets. FAILED reports
invalid runtime identity, ownership, values or bundle identity/validation.
Neither incomplete nor failed results expose partial bundles/overlays.

`PreparedPublicBundle` owns immutable canonical JSON containing only the accepted
library envelope: existing public manifest, canonical frozen manifest and public
package descriptors/base64 assets. It returns detached copies from `to_dict`.
Validation includes registration's file, aggregate package and envelope limits.

Because the accepted `BuildLibrary.register` API takes three paths, the future
confirmed commit step uses:

```python
with result.public_bundle.registration_inputs() as inputs:
    entry = library.register(*inputs)
```

This context stages only validated public material in a new temporary directory
and cleans it on exit. Capture does not invoke it or register/select a build.
Existing identity/version conflicts or library I/O failures remain registration
errors for the later confirmed step. Artifact ZIPs remain in ArtifactStore.

Incomplete captures expose no registration inputs. No Create-time Skip or
repository-current substitution is implemented, and the accepted library
contract is unchanged. Known private target checks do not classify secrets
hidden in arbitrary caller-declared public text/files; the explicit supported
public specification must be curated by trusted product code.

## Evidence and next step

Offline tests use deterministic injected inventory/configuration backends,
exact ZIP fixtures, disposable libraries and a disposable SQLite Red Light
fixture. Tests cover package ownership/typing/bytes/isolation, identity,
optional absence, real adapter capture, sentinel privacy and mutation tripwires.
No Test.app or live Kodi/device acceptance is claimed.

Next: independent review, then native Create Build dialogs with explicit
preview/confirmation and separate confirmed public registration/selection and
private-overlay persistence. Install/Repair Apply and G6 remain out of scope.
