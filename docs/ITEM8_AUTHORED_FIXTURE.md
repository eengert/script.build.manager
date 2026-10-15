# Item 8 authored qualification inputs

AUTHORED QUALIFICATION FIXTURE — NOT CAPTURED STATE

Eric authorized this separate qualification-data origin on October 15, 2026.
This tool is not protected Create, capture authority, a general import feature,
or a change to product functionality. Independent review is required before
any live use. This implementation task used only isolated temporary roots.

## Authored values and provenance disclosure

The fixture expresses an authored desired software state. Its metadata must
not be presented as observation of an installation or captured user state:

| Value | Meaning and evidence boundary |
| --- | --- |
| `xbmc.python` `3.0.0` | An authored requirement/fallback carried from the PIL package metadata. It is not an observation of the target installation. The independent review observed Test.app's bundled `xbmc.python` metadata at `3.0.1`. |
| `created_at: 2026-10-15T00:00:00Z` | A fixed placeholder timestamp, not the time of capture or creation on a target. |
| `kodi_version: 21.3` | Authored fixture metadata, not evidence that a live Kodi version was checked. |
| `AUTHORED QUALIFICATION FIXTURE` | The label is stored in the external `provenance.json` record. The ordinary Build Library entry has no typed authored-origin flag; that entry alone does not preserve this provenance distinction. |
| Private overlay binding | The overlay is bound to the frozen software graph fingerprint, not uniquely to the public build ID. Build ID/version and existing entry or overlay identities still require separate collision checks before any transfer. |
| `script.module.urllib3` `2.2.3` | The package is pinned at `2.2.3`; Requests declares a `+matrix.1` minimum. The existing generic managed-version comparator is permissive and does not enforce that particular minimum. Independent review assessed `2.2.3` as compatible, but generic graph validation is not proof of the `+matrix.1` minimum. |

The exact public package bytes are validated against their pinned versions,
digests, addon metadata, and ZIP integrity. Those package checks establish
package identity and authored graph inputs; they do not convert authored
metadata into target observations. Keep three claims distinct: authored
desired state, validated public package bytes, and captured user state. This
fixture captures no user state.

## Admission and output

`tools/bm_item8_fixture.py` requires explicit `--archive`, `--pil-xml`, and
`--output` arguments. There is no live profile/library default. Archive and PIL
paths must equal the two fixed public sources in the module; every existing
ancestor and input file is opened through production no-follow readers.
The output must be a new `bm-item8-*` directory directly under `/private/tmp`.
Existing roots (including symlinks and interrupted preparations) are refused.
There is no overwrite, adoption, repair, cleanup, or resume option.

The six public ZIPs are pinned by version and SHA-256, checked against the
archive SHA256SUMS, validated with `validate_addon_zip`, and CRC checked. Their
dependency edges come from their exact addon.xml bytes. PIL metadata comes
only from the fixed Test.app application add-on root, never any portable data.
Its ID/type/version/dependency declarations are checked. This is an authored
desired graph, not an observation of runtime enablement or target usability.
Actual D-028 target authority and usability must still pass at runtime.

Dependency minima use the existing production comparison contracts: strict
dotted-decimal comparison for platform requirements; existing generic managed
dependency comparison otherwise. The version-specific urllib3 limitation and
review assessment are disclosed above; the helper does not introduce a new
version-ordering rule.

An isolated ArtifactStore holds the exact bytes. A schema-v2
FrozenBuildManifest carries six managed nodes, PIL as platform-provided with
no artifact, and Python as a system requirement. COMPLETE describes validated
software graph material; it is not a claim that any user state was captured.
No repository-verified installed provenance is invented: authored nodes use
MANUAL_OR_UNKNOWN. `validate_frozen_install_plan` validates exact artifacts,
graph order, cycles and completeness before registration.

PreparedPublicBundle canonicalizes the generated public envelope and supplies
only public registration inputs to BuildLibrary. The audited
`redlight_declaration()` declares the private resource; its values never enter
the public envelope. PrivateOverlayStore saves the separately validated
overlay at an isolated profile root. Its source binding is exactly `sha256:`
plus the frozen software fingerprint. Selection refers to the newly
registered entry and qualification profile only.

The final sanitized `provenance.json` is written last. It records the authored
qualification label and explicitly reports that capture and runtime were not
performed. An absent, truncated, or invalid provenance record means incomplete
preparation. Keep the entire root for assessment and do not rerun into it.
Temporary public registration inputs are managed and removed by
PreparedPublicBundle's production context manager. The helper never writes a
transaction, activation hold, applied association, publication or completion
result. It cannot launch, install, or operate Kodi.

## Red Light runtime safety gates

The following package behavior was established by source review of the pinned
package, without importing or running its code:

- The first Red Light UI render may fetch `icons.json` from
  `repo.redwizard.xyz` or fallback `zeus-768.com` without authentication.
- Service startup can repeatedly rewrite package-owned
  `resources/skins/Default/1080i` XML files and `extras.xml`. A separate
  runtime qualification, if later authorized, must take installed-tree
  snapshots before and after startup. Record expected startup drift separately
  from source identity; drift does not change the pinned source identity.
- `router.py` uses `exec()` on a `plugin://` mode parameter. The route through
  GUI, JSON-RPC, or web-control surfaces has not been established.
- Premiumize token-to-URL handling presents a dangerous path if real
  credentials exist. The inspected fixture sentinel does not provide a token
  and does not establish safety in a destination with inherited state.
- The Red Light initializer imports package modules in-process. The effects of
  those imports at module scope have not been independently qualified.
- Bundled third-party credential blobs are not approved fixture inputs. Do not
  use them, decode them for authentication, expose them, or transmit them.

These are different evidence classes: source review establishes that the
package contains the behaviors above; it does not establish caller
reachability, harmlessness, or runtime safety. In particular, before any live
activation, require proof that untrusted callers cannot reach the `router.py`
execution path. Do not invoke a `plugin://` route except as part of an
explicitly approved native workflow.

Before any separately authorized Red Light startup, prove that the disposable
destination has no inherited credentials or tokens, account-manager
integration, or Red Light service setup. The exact fixture sentinel is not
proof of that destination precondition. Do not invoke debrid, metadata, or
authentication services, or `kodi_utils.upload_logfile`.

Default network policy for this fixture is **NO outbound requests**. Do not
assume that an icon or other request is harmless. If egress is unavoidable,
stop and obtain explicit supervisor/operator approval before runtime
qualification. This documentation correction authorizes no runtime probe or
activation.

The sole authored private value is the exact package's unauthenticated/revoked
`empty_setting` sentinel for the audited string field `pm.account_id`. There
is no invented account marker, username, token, refresh token, or real private
input. The preparer accepts no arbitrary overlay/value argument.
`validate_authored_overlay` rejects anything other than this exact payload,
including another declared credential field or a different graph binding.

Analysis was performed by reading the pinned ZIP, not importing its code:

- `resources/lib/caches/settings_cache.py:1991` declares that account field
  and its sentinel default; `_new_setting_value` returns static defaults for
  a fresh resource (`104–116`).
- `resources/lib/modules/settings.py:122–124` checks a service's **token**
  for authorization; the account-ID sentinel supplies no authorization.
- `resources/lib/apis/premiumize_api.py:16–17` loads `pm.token`. Account-ID
  references at `59` and `67` write authorized account information or restore
  the revoked sentinel; they do not send that ID as authentication.
- Other literal `pm.account_id` references in the Python package are the
  default declaration and local settings-preservation set. A search for
  dynamic `account_id` formatting found no Premiumize account-ID
  reader/transmitter.
- `service.py` starts account monitors. Trakt, Simkl, MDBList and PunchPlay
  monitors check their respective authorization conditions; this fixture
  supplies none of those credentials. Service-expiry checks use the token
  authorization guard. The package default auto-start setting is false.

This source analysis establishes that this payload does not introduce an
account marker or credential that would trigger authentication. It does not
establish that the enabled package has no unrelated network behavior, that
module-level imports are safe, or that a real destination has no inherited
secrets. An unexpected value, authentication attempt, incompatible
initialization, or transmission of an authored input is a stop condition, not
permission to patch the add-on or disable product guards.

## Exact production transfer preconditions

The offline output is not the canonical production Build Library root. The
canonical locations are:

| Data | Canonical destination |
| --- | --- |
| Build Library | `special://profile/addon_data/script.build.manager/build-library` |
| Frozen artifacts | `<profile>/addon_data/script.build.manager/frozen-artifacts/artifacts` |
| Private overlays | `<profile>/addon_data/script.build.manager/private_overlays` |

Tests using `isolated_library_install_authority` exercise an isolated library;
they do not establish runtime authentication for the canonical root. Do not
substitute another root or bypass canonical-root authority.

Any separately authorized transfer must be exact-or-refuse and use existing
production primitives. Before writing, detect and refuse collisions involving
the same `build_id`/version or an existing entry or overlay identity. Preserve
all existing Build Library entries, current selection, applied state, and prior
qualification evidence. Never overwrite an existing private overlay with
`PrivateOverlayStore.save()`.

Before any actual Install Apply, require a fresh load from the canonical root,
target verification, profile binding, a plan preview, and explicit native
review. Preserve the external authored-provenance record separately; an
ordinary Build Library entry has no typed authored-origin flag. This
documentation correction authorizes no transfer, registration, runtime
launch, Create, Install, or restart.

## Tests and later runtime boundary

Run `python3 -B -m unittest tests.test_item8_fixture -q` with
`PYTHONDONTWRITEBYTECODE=1`. The real-input tests explicitly skip when the
pinned archive or bundled PIL is unavailable; a skipped run is not admission
evidence. Tests exercise the real library target and plan service using
disposable inspection collaborators. No successful restart/resume is claimed
by them.

Review must include the helper's path/output ownership assumptions, exact
package provenance, version contract, sentinel analysis and failure retention.
The new 0700 temporary output is task-owned; hostile concurrent same-user
mutation of that directory is outside this preparer's operating contract. Do
not point it at shared or externally modified output.

A separate runtime task must explicitly authorize transfer/registration of
the reviewed inputs into Test.app. It must satisfy the canonical-root,
collision, preservation, Red Light preflight and native-review requirements
above, and revalidate the exact entry/profile/graph/overlay binding and target
platform requirements. Only the real installer may establish the hold and
awaiting_restart record. Only a verified complete process exit, portable
relaunch, startup continuation, private verification, hold release and
truthful final association/status can close restart/resume qualification.
Authored setup supplies no additional protected Create evidence.

## Implementation validation (October 15, 2026)

- New focused tests: 15 passed, using the six pinned real public archives.
- Related library, overlay/resource, frozen graph/install, library install,
  plan, and Create capture/workflow suites: 571 tests, 570 passed, one existing
  failure in `test_plan.ImportPolicy.test_the_presentation_modules_import_no_engine`.
  The unchanged test also fails alone on the committed presentation sources;
  no presentation or product library source was changed by this work.
- Git whitespace check passed. Four pre-existing `.agent` files retained
  their original hashes. Test-owned output roots and public registration
  scratch were removed by their test/context cleanup. No live profile writes
  or Kodi operations occurred. This is review input, not independent approval
  or live restart/resume evidence.
