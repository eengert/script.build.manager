# Item 8 authored qualification inputs

AUTHORED QUALIFICATION FIXTURE — NOT CAPTURED STATE

Eric authorized this separate qualification-data origin on October 15, 2026.
This tool is not protected Create, capture authority, a general import feature,
or a change to product functionality. Independent review is required before
any live use. This implementation task used only isolated temporary roots.

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
dependency comparison otherwise. Requests' urllib3 minimum contains
`+matrix.1`, which the generic comparator handles permissively; the helper
does not introduce a new version-ordering rule. The six exact supplied versions
and that limitation are part of independent review, not concealed provenance.

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
the public envelope. PrivateOverlayStore saves the separately validated overlay
at an isolated profile root. Its source binding is exactly
`sha256:` plus the frozen software fingerprint. Selection refers to the newly
registered entry and qualification profile only.

The final sanitized provenance.json is written last. An absent, truncated, or
invalid provenance record means incomplete preparation. Keep the entire root
for assessment and do not rerun into it. Temporary public registration inputs
are managed and removed by PreparedPublicBundle's production context manager.
The helper never writes a transaction, activation hold, applied association,
publication or completion result. It cannot launch, install, or operate Kodi.

## Overlay and activation analysis of the pinned package

The sole authored value is the exact package's unauthenticated/revoked
`empty_setting` sentinel for the audited string field `pm.account_id`.
There is no invented account marker, username, token, refresh token, or real
private input. The preparer accepts no arbitrary overlay/value argument.
`validate_authored_overlay` rejects anything other than this exact payload,
including another declared credential field or a different graph binding.

Analysis was performed by reading the pinned ZIP, not importing its code:

- resources/lib/caches/settings_cache.py:1991 declares that account field and
  its sentinel default; `_new_setting_value` returns static defaults for a
  fresh resource (104–116).
- resources/lib/modules/settings.py:122–124 checks a service's **token** for
  authorization; the account-ID sentinel supplies no authorization.
- resources/lib/apis/premiumize_api.py:16–17 loads pm.token. Account-ID
  references at 59 and 67 write authorized account information or restore the
  revoked sentinel; they do not send that ID as authentication.
- Other literal pm.account_id references in the Python package are the default
  declaration and local settings-preservation set. A search for dynamic
  account_id formatting found no Premiumize account-ID reader/transmitter.
- service.py starts account monitors. Trakt, Simkl, MDBList and PunchPlay
  monitors check their respective authorization conditions; this fixture
  supplies none of those credentials. Service-expiry checks use the token
  authorization guard. The package default auto-start setting is false.

This establishes that this payload does not introduce a marker or credential
that would trigger authentication. It does not claim that the enabled package
has no unrelated network behavior. Before a separately authorized live run,
the fresh Red Light destination must still be absent/unconfigured and contain
no inherited credentials or account-manager integration. An unexpected value,
authentication attempt, incompatible initialization, or transmission of an
authored input is a stop condition, not permission to patch the add-on or
disable product guards.

## Tests and later runtime boundary

Run `python3 -B -m unittest tests.test_item8_fixture -q` with
PYTHONDONTWRITEBYTECODE=1. The real-input tests explicitly skip when the pinned
archive or bundled PIL is unavailable; a skipped run is not admission evidence.
Tests exercise the real library target and plan service using disposable
inspection collaborators. No successful restart/resume is claimed by them.

Review must include the helper's path/output ownership assumptions, exact
package provenance, version contract, sentinel analysis and failure retention.
The new 0700 temporary output is task-owned; hostile concurrent same-user
mutation of that directory is outside this preparer's operating contract.
Do not point it at shared or externally modified output.

A separate runtime task must authorize transfer/registration of the reviewed
inputs into Test.app and then use native review and Apply. That task must
revalidate the exact entry/profile/graph/overlay binding, target platform
requirements and process safety. Only the real installer may establish the
hold and awaiting_restart record. Only a verified complete process exit,
portable relaunch, startup continuation, private verification, hold release and
truthful final association/status can close restart/resume qualification.
Authored setup supplies no additional protected Create evidence.

## Implementation validation (October 15, 2026)

- New focused tests: 15 passed, using the six pinned real public archives.
- Related library, overlay/resource, frozen graph/install, library install,
  plan, and Create capture/workflow suites: 571 tests, 570 passed, one existing
  failure in test_plan.ImportPolicy.test_the_presentation_modules_import_no_engine.
  The unchanged test also fails alone on the committed presentation sources;
  no presentation or product library source was changed by this work.
- Git whitespace check passed. Four pre-existing .agent files retained their
  original hashes. Test-owned output roots and public registration scratch
  were removed by their test/context cleanup. No live profile writes or Kodi
  operations occurred. This is review input, not independent approval or live
  restart/resume evidence.
