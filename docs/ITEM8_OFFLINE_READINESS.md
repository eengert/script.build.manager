# Item 8 offline safety and candidate readiness — 2026-10-17

Status: **CORRECTION C1 — INDEPENDENT RE-REVIEW PENDING**.
The October 18 review accepted the acquisition refusal, integrated empty-scope
Status, import policies, synthetic fixture isolation and prior evidence. C1
corrects remaining harness claims and hardens direct Status evaluation; it does
not reopen those accepted behaviors.
Item 8 remains OPEN. No native qualification, staging, archive acquisition,
installation, activation or private transfer occurred in this task. The accepted
Help correction at `8c569d6` is unchanged and still needs a separately authorized
final-candidate native recheck.

## Implemented blockers

| Area | Change | Evidence boundary |
| --- | --- | --- |
| Legacy AF3 sourcing | Removed household-installed source derivation and dependency copying. Direct copy entrypoint and all six AF3 validation entrypoints reject with `AF3_SOURCE_ACQUISITION_UNSUPPORTED` before imports, probes, reset, copy, RPC or launch. No source override/fallback exists. | Synthetic filesystem/runtime tripwires and direct/CLI regressions; no protected source touched. |
| Other legacy profile probes | Removed normal-profile mtime preservation reads throughout `tools/kodi_test.py` and the corresponding mtime-based success claims. The remaining normal-profile constant is lexical only. | AST check forbids references to that constant inside any function; no claim of general runtime clearance for this historical harness. |
| Empty configuration Status | A successfully resolved and validated public configuration with no setting/file targets is NOT_APPLICABLE, presented as “Not part of this build.” | Zero observed targets alone do not suffice. Missing/failed resolution, absent checks, stale identity and omitted expected targets remain UNAVAILABLE; FAIL and actual drift remain visible. Private results stay separate and overall aggregation remains truthful. |
| Import policies | Added the actual `typing.Optional` dependency to exact module allowlists; retained the existing three pure Create label/version validation helpers in their existing native-dialog consumer only. | Engine, mutation, relative, wildcard, plain-import and lookalike-prefix negative controls remain rejected. No product UI import was added. |
| Fake-credential tests | The two shared minimum-policy tests now own and clean a fresh synthetic Git fixture and restore the previous fixture object. | Standalone/repeated execution succeeds; fake runner only, no real credentials or Keychain query. |

Implementation commits: `2b7759b` (source safety), `91cb672` (zero scope),
`dd685f3` (import policies), `0659367` (test-fixture isolation). Starting HEAD
`8c569d607d3a7ef3714d3bb43534691502d72138`. Independent review is pending;
implementer validation is not independent acceptance.

Validation: harness 128/128; Status/configuration/validator/native presentation
539/539; import-policy/native-foundation checks 39/39; fake-credential module
32/32. Full repository-root suite **3,820/3,820 PASS**, 330.662 seconds, with
host process visibility for synthetic process tests. Bytecode writes disabled.
The safety and zero-scope regressions reproduced before correction; both old
import-policy failures reproduced using starting-HEAD test source. Negative
import controls and AST/source checks pass. No known full-suite failure remains.

Historical offline evidence is in `.qualification-evidence/item8-offline-readiness-20261017/`:
before/after logs, full-suite log, public-source metadata/key audit, tool
capability metadata, tracking-preservation record and final completion/checksums.
It is checksummed, Git-excluded and local to this worktree. Checksums establish
integrity against the retained manifest, not durable off-machine preservation;
no off-machine copy or recovery guarantee has been established. C1 evidence is
separately retained in `.qualification-evidence/item8-c1-20261018/` under the
same local retention limits.

## Legitimate AF3 options — metadata research, no selection or acquisition

Maintainer-controlled [AF3 source](https://github.com/jurialmunkey/skin.arctic.fuse.3)
and [Jurialmunkey distribution repository](https://github.com/jurialmunkey/repository.jurialmunkey)
provide independently attributable public options. These are candidate sources,
not a claim that downloaded bytes or target behavior were verified. The
repository calls itself an Alpha Repository; neither presence nor a version
label establishes beta compatibility.

Distribution metadata was pinned to repository commit
`20f13a1fee706091ddb1c64400b78aeab1731265`. The exact archive URLs below point to
that commit, not a floating branch. Only UTF-8 metadata/source text was fetched;
no ZIP or dependency payload was fetched, unpacked or executed.

| Option | Published version | Declared archive bytes | Git blob SHA-1 from directory metadata | Attributable upstream version commit |
| --- | --- | ---: | --- | --- |
| P: current published candidate | 3.3.12 | 58,482,102 | `cb697255ab4d70e1f959b0e34ee4047863660635` | `660a05c35546718e90a88be7798bb0a92632abce` |
| H: historical alternative, explicit choice required | 3.2.19 | 53,823,580 | `796b738f0263f2c19a688dd1d0649ee16371de1d` | `fb96e8794725b88f88891af7a4f19f2fd4fa6502` |

- [Pinned archive directory metadata](https://api.github.com/repos/jurialmunkey/repository.jurialmunkey/contents/omega/zips/skin.arctic.fuse.3?ref=20f13a1fee706091ddb1c64400b78aeab1731265)
- P archive URL: `https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/20f13a1fee706091ddb1c64400b78aeab1731265/omega/zips/skin.arctic.fuse.3/skin.arctic.fuse.3-3.3.12.zip`
- H archive URL: `https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/20f13a1fee706091ddb1c64400b78aeab1731265/omega/zips/skin.arctic.fuse.3/skin.arctic.fuse.3-3.2.19.zip`

A Git blob SHA-1 is **not** an archive SHA-256. No archive SHA-256 was published
in the inspected directory metadata; none was calculated because no archive was
acquired. Future acquisition must compare exact byte count and Git blob identity,
calculate and retain SHA-256, and validate ZIP contents/ID/version/paths before
use. No installed directory may be repackaged into an artifact.

The upstream `omega` head observed was
`907082d682569437361a56a60da41980145224b7`, also labelled 3.3.12, but newer than
the distribution submodule's `660a05c...`. A version label alone does not bind
that head to the published ZIP. The key comparison below uses the distribution
version commit and the separately identified historical commit. Neither source
comparison proves archive/source equivalence before inspecting acquired bytes.

## Dependencies and compatibility prerequisites

Option P is AF3 **3.3.12**; option H is the historical **3.2.19** alternative.
Neither is selected. Published addon metadata gives the following direct minima:

| Requirement | P: 3.3.12 minimum | H: 3.2.19 minimum |
| --- | --- | --- |
| `xbmc.gui` | 5.17.0 | 5.17.0 |
| `script.skinvariables` | 2.2.9 | 2.2.2 |
| `script.texturemaker` | 0.2.9 | 0.2.9 |
| `plugin.video.themoviedb.helper` | 6.17.9 | 6.14.3 |
| `resource.images.weathericons.white` | 0.0.1 | 0.0.1 |
| `resource.images.studios.coloured` | 0.0.1 | 0.0.1 |
| `resource.font.robotocjksc` | 0.0.3 | 0.0.3 |

Sources: [P addon metadata](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/660a05c35546718e90a88be7798bb0a92632abce/addon.xml),
[H addon metadata](https://github.com/jurialmunkey/skin.arctic.fuse.3/blob/fb96e8794725b88f88891af7a4f19f2fd4fa6502/addon.xml).

An import version specifies a minimum dependency version, not an exact pin.
A numerically newer candidate may meet that minimum without proving runtime
compatibility, API behavior or a trustworthy complete dependency closure. The
transitive research below concerns the listed P-era package versions. H's
complete dependency closure has **not been established**; P-era dependencies
must not be described as H-qualified without separate evidence.

The maintainer repository's pinned metadata also exposes these exact public
packages. These are researched options, not a selected or complete dependency
closure:

| Package | Version | Bytes | Git blob SHA-1 |
| --- | --- | ---: | --- |
| `script.skinvariables` | 2.2.9 | 236,686 | `bfefebb8b028fb3391dad9fe8a13357093c24295` |
| `script.texturemaker` | 0.2.11 | 171,850 | `b854eeaa2430362dca9e99fb8454d0023486e790` |
| `plugin.video.themoviedb.helper` | 6.17.9 | 4,322,239 | `c92b7efedf6b526d02f5e1bfa71f91bf85839dff` |
| `resource.font.robotocjksc` | 0.0.3 | 51,599,422 | `d8557a883b420aa2e9cae95d35f77c6d463622b6` |
| `script.module.jurialmunkey` | 0.2.35 | 55,792 | `98556ddadf9ea88db9809728663ddc08fe9a0990` |
| `script.module.infotagger` | 0.0.9 | 23,148 | `b7ba107887ec168248cd84247134bd960cc2df35` |

Exact immutable URLs are retained in
`maintainer-dependency-archive-metadata.json`. No per-archive SHA-256 was
established for these packages.

Inspected transitive edges:

- Skin Variables 2.2.9 requires Python 3.0.0, Jurialmunkey common 0.2.28 and InfoTagger 0.0.5.
- Texture Maker 0.2.11 requires Python 3.0.0, PIL 1.1.7 and Jurialmunkey common 0.2.28.
- TMDb Helper 6.17.9 requires Python 3.0.1, Requests 2.9.1, PIL 1.1.7, Addon Signals 0.0.6, Jurialmunkey common 0.2.35, InfoTagger 0.0.9 and QRCode 6.1.0.
- Jurialmunkey common 0.2.35 requires Python 3.0.1, Requests 2.9.1 and InfoTagger 0.0.5. InfoTagger 0.0.9 requires Python 3.0.1.
- Roboto CJKSC 0.0.3 requires `kodi.resource` 1.0.0.

These edges and exact source URLs/blob IDs are retained in `af3-research.json`.
[Team Kodi weather-icons metadata](https://github.com/XBMC-Addons/resource.images.weathericons.white/blob/master/addon.xml)
currently names 0.0.6 and `kodi.resource` 1.0.0;
[studio-icons metadata](https://github.com/XBMC-Addons/resource.images.studios.coloured/blob/master/addon.xml)
names 0.0.24 with the same platform requirement. Exact distributable identities,
archive sizes/hashes and remaining transitive requirements for the Kodi-supplied
Requests/Signals/QRCode/resource packages were not established. Official index
reads did not yield usable archive metadata in this environment. Do not silently
substitute a mirror or a locally installed copy.

Before dependency acquisition, finish a metadata-only, exact version/URL/size/hash
manifest for that closure and obtain approval for its rows. Platform-provided
nodes (including PIL if proven application-bundled) require D-028 target-origin,
version, type, enabled/usability and closure checks; they are never downloaded,
replaced or enabled as a shortcut. This task did not inspect the target.

## Sixteen-key comparison

Published source references at both P and H commits support the following 15
names and are consistent with the catalog's declared types. This is source-level
evidence, not a complete skin schema or target read/write test:

| Catalog target | Type | Source evidence at both version commits |
| --- | --- | --- |
| `HomeSwitcher.Vertical` | bool | `Includes_SkinSettings.xml`, toggle/read |
| `HomeSwitcher.EnableIcons` | bool | `Includes_SkinSettings.xml`, toggle |
| `HomeSwitcher.EnableIconText` | bool | **UNCONFIRMED**: absent from inspected files; current upstream code search returned no match |
| `HomeSwitcher.DisableHeader` | bool | `Includes_SkinSettings.xml`, bool/reset/read |
| `HomeSwitcher.DisableDate` | bool | `Includes_SkinSettings.xml`, bool/reset/read |
| `HomeSwitcher.DisableSearch` | bool | `Includes_Home.xml`, boolean read; shortcut source also uses toggle |
| `HomeSwitcher.DisableFirstWidgetFocus` | bool | `Includes_SkinSettings.xml`, toggle/read |
| `HomeSwitcher.LoopBack` | bool | `Dialog_DialogShortcuts.xml`, toggle/read |
| `Spotlight.EnableSlide` | bool | `Includes_SkinSettings.xml`, toggle/read |
| `Spotlight.UseMenuButton` | bool | `Includes_SkinSettings.xml`, toggle |
| `View.UseDetailedListLabels` | bool | `Includes_SkinSettings.xml`, toggle |
| `Widgets.EnableShowMore` | bool | `Includes_SkinSettings.xml`, toggle/read |
| `Widgets.DisableNoResultsItem` | bool | `Includes_SkinSettings.xml`, bool/reset |
| `Navigation.OnBack` | string | `Includes_SkinSettings.xml`, Parent/Previous; catalog uses Previous |
| `Seekbar.TimeDisplay` | string | `Includes_SkinSettings.xml`, Remaining/Combined/reset; catalog uses Combined |
| `Skin.FlixArt.Size` | string | `Includes.xml`, Large/ExtraLarge; catalog uses ExtraLarge |

Exact file URLs, blob IDs and line evidence for both commits are in
`af3-research.json`. No exhaustive absence or incompatibility claim is made for
the unconfirmed key. Do not infer all 16 keys work, remove/rename a key merely to
get a pass, or assume historical 3.2.19 solves the gap. Native package admission
must settle that key, verify acquired bytes correspond to the reviewed source,
and establish supported runtime reads/writes and persistence before applying.
The checked-in catalog was not modified.

## Concrete acquisition approval text — for a later task

No approval is requested or consumed by this offline package. The Supervisor can
present the following after the operator explicitly chooses P or H:

> Approve offline acquisition of exactly option P **or** option H from the pinned
> immutable URL and byte-count/Git-blob row above, into a new task-owned quarantine
> directory. Verify byte count and Git blob identity, calculate SHA-256, validate
> the exact ZIP ID/version/path safety and inspect public source only. Do not
> execute, install, activate, repackage installed directories, read household
> Kodi files, or access private values. Stop if identity/size/source differs.
> No dependency archive is included in this root-only approval.

For dependencies, a separate approval must explicitly name the selected rows of
a completed closure manifest, each with ID, version, immutable URL, byte count,
published hash type/value, provider attribution and target platform assumptions.
The six maintainer rows above can be nominated by exact row; unresolved Kodi
package rows cannot be filled with “latest” or blanket repository authorization.
Acquisition approval does not authorize Test.app staging, installation, skin
activation, private operations, or a restart. Those need a named later runtime
scope after independent review and complete prerequisite admission.

## Useful public configuration independently of AF3

The existing configuration backend supports declared typed add-on settings and
managed files without AF3. `tests/test_config.py`, the validator, Status and
configuration executor tests cover matching state, drift, verification failure,
ownership and non-destructive behavior. The checked-in `bm022-fixture` package
is an explicitly synthetic add-on-setting input, not real captured user state.

The ordinary Create UI's `TrustedCaptureCatalog.compose()` currently offers
non-empty public settings only for the included active AF3 skin. Other ordinary
public roots (such as the retained Keymap Editor build) capture no public
settings/files. The native menu currently provides no public configuration
authoring/import route that supplies a legitimate non-AF3 configuration build.
Thus backend synthetic testing can advance safety evidence independently, but
cannot substitute for native non-empty public configuration capture/application.
No new fixture or capture catalog was invented in this task.

## Structured private-resource coverage — not waived

The supported `redlight.settings` owner/version boundary remains Red Light
2.6.8. Existing BM-017F historical disposable evidence is retained; it does not
become current-candidate native Item 8 qualification automatically.

| Claim | Existing offline proof | Native limit / remaining obligation |
| --- | --- | --- |
| Metadata ownership/version and declared fields | `test_private_resource`: duplicate ownership, unknown adapter/version and undeclared/wrong typed fields reject | Verify exact admitted owner/resource on the later disposable target; no real credentials |
| Capture/private separation | `test_create_capture`: real adapter over synthetic SQLite, read-only declared-field capture, public/private overlap rejection, required/optional absence and safe incomplete results | No current native private Create acceptance. D-029 still prohibits bypassing protected Create quiescence/restart contracts |
| Read-only/WAL truth | `QuietWalReadCompatibilityTests`: quiet WAL reads/status, committed-frame refusal where unsupported, URI paths and concurrent-change refusal | Observe the actual supported target state without touching household/private production data |
| Apply/init/hold safety | `StructuredResourceTest`: disabled owner/durable hold requirements, verified-source initializer, schema failures, owned-row-only writes and sanitized failure stages | Admit the initializer's code/network/file effects and lifecycle first; no Red Light activation in this task |
| Final validation and presentation | Synthetic resource final-validation failure, private missing/unusable Status and secret-blind UI tests; frozen-install gating/order tests | Show truthful native terminal result, private Status, final association, permitted second-run behavior and preservation for the exact candidate |

D-030 defers only genuine restart-producing Install/Update/Repair **live restart/
resume demonstrations**. It does not waive structured private-resource correctness,
offline safeguards, required ordinary non-restart coverage, truthful failure or
preservation. A legitimately admitted non-restart existing-resource inspection/
verification scenario may help, but it cannot prove unexercised initialization,
application or private Create. Never force a non-restart outcome or mark a held/
incomplete operation successful.

Any future native private scenario needs explicit separate authority for the
exact disposable target, pinned package/owner/resource and authored
unauthenticated value, allowed network behavior, initialization/file effects,
activation/hold and shutdown boundary. `docs/ITEM8_AUTHORED_FIXTURE.md` remains
mandatory where applicable. Synthetic values are not real account state. Do not
read/transfer household private values. Under D-029, advanced interrupted-Create
recovery is post-beta; ordinary supported Create, safe failure with no BM-caused
loss and honest failure/status presentation remain required. Production protected
Create admission remains NO-GO on supported Kodi mechanisms for external
operation exclusion. Do not weaken the fail-closed `competing_operation()` and
`verify_restart()` contracts, P5, D2 Option A, or existing activation holds.
Accepted offline reservation/witness research is not runtime authority; do not
wire it into runtime to fill this gap. A policy change requires a subsequent explicit decision.

## Next substantial package and remaining gates

After independent review: settle AF3 version/key/closure admission and approved
image retention, acquire only explicitly approved public archive rows offline,
then use a separately authorized final-candidate portable Test.app package for
Help and zero-scope Status rechecks plus legitimate non-empty public capture,
reviewed application, truthful validation, second-run reconciliation and scoped
preservation. See `ITEM8_NATIVE_EVIDENCE_PLAN.md` for the concrete evidence steps.

Remaining Item 8 gates: native qualification of changed Help/Status; unresolved
AF3 key/version/runtime compatibility and complete trusted closure; structured
private coverage within unchanged D-029/D-030 policy; broader supported-failure
preservation; durable native image retention and exact final-candidate evidence.
No integration, repository publication or device operation is authorized.

## Separate legacy safety issues — outside correction C1

The historical harness still has legacy normal `Kodi.app` launch behavior,
and bm023a migration protections remain a separate safety issue. Removing
normal-profile probes and unsupported claims does not clear either path for
execution. C1 neither modifies nor runs them. Their safety review/correction
requires a separately scoped task; no historical validator is authorized here.

C1 direct Status hardening requires exact setting/file target coverage, unique
observations, a nonempty observation identity and PASS evidence before Current
or empty-scope Not Applicable. Missing/inconsistent evidence is Unavailable;
actual drift, unreadability and failed validation retain their classifications.
The existing integrated validator's package/scope/identity gates are unchanged.
