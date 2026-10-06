# Build Plan and Review (BM-UI-002C / G3)

A read-only answer to "what would installing this saved build do on this
device?" and, later, "is the plan I reviewed still the plan?". It is a preview.
Nothing here installs, enables, repairs, switches a skin, writes a setting,
downloads a package, or creates a file, and the Review Changes page offers no
Apply action. Install, Update / Repair and the Build Library are separate work:
no menu route reaches this yet, and the page is callable only with an explicit
target (tests and future Library wiring).

## Entry points

| Code | Purpose |
|---|---|
| `resources/lib/plan_model.py` | The public contract. Standard library only. |
| `resources/lib/plan.py` | `PlanTarget`, `BuildPlanService.preview()` / `.validate()`, `preview_build_plan()`, `validate_reviewed_plan()`, `plan_provider()`. |
| `resources/lib/build_identity.py` | Proves the inputs belong to one build (shared with Build Status). |
| `resources/lib/ui/plan_view.py`, `NativeDialogs.review()` | The native Review Changes page. |

`PlanTarget` holds the configuration manifest path, device profile, frozen
software manifest path, an optional `FrozenInstallResolutionManifest` (a prior
accepted outcome) and the user's missing-package choices. `preview()` and
`validate()` never raise; a failure becomes `INCOMPLETE` / `UNVERIFIABLE` with a
stable gap code and no exception text.

## Inputs must describe one build

Before any frozen or recorded data is used, the frozen manifest's build ID must
equal the resolved build's ID and a recorded resolution must be bound to this
build and this frozen manifest (see `BUILD_STATUS.md`). A mismatch leaves the
plan `INCOMPLETE` (`BUILD_IDENTITY_MISMATCH` / `RESOLUTION_IDENTITY_MISMATCH`);
nothing is planned against it.

Stored resolutions must also match `frozen_resolution.install_plan_fingerprint()`
for the selected frozen manifest and effective install policies. The shared binder
requires current policies from both callers and rejects a mismatch before any
record can affect comparison, accepted skips, enabled state or software projection.
Changing repository fallback or skip policy requires a new plan/resolution; returning
to the original policy restores the original binding. A matching digest still must
pass record eligibility: repository fallback must be allowed and use the policy's
repository, and Skip must be allowed. Existing terminal-state validation remains.
Failure uses `RESOLUTION_IDENTITY_MISMATCH`, leaves the target unchecked and issues
no review identity. Logs carry only stable identity codes, including
`resolution_plan_mismatch`; UI output contains no paths, IDs or fingerprints.

## Plan states and precedence

`BLOCKED` > `INCOMPLETE` > `DECISION_REQUIRED` > `RESOLUTION_REQUIRED` >
`CHANGES_READY` > `NO_CHANGES`.

* `BLOCKED`: a proven reason the work cannot proceed. Proven facts outrank "not
  checked", as in Build Status.
* `INCOMPLETE`: something required could not be checked. A plan is never ready
  while any applicable area is unavailable, and a build that lists nothing to
  compare proves nothing (`NOTHING_TO_COMPARE`).
* `DECISION_REQUIRED`: the user must choose for an add-on whose saved package is
  missing before anything is proposed.
* `RESOLUTION_REQUIRED`: Install Current was selected but the exact repository
  package is not yet resolved. This is waiting for resolution, not a blocker.
  It has no review identity and cannot proceed.
* `CHANGES_READY` / `NO_CHANGES`.

The model enforces this structurally: it will not construct a ready plan with a
blocker, an undecided add-on, an unresolved repository package, an unchecked area or a gap, and only a
`CHANGES_READY` plan can carry a review identity (`can_proceed`).

## What each part comes from

| Part | Owner reused |
|---|---|
| Saved-package availability, recovery policy, install order, skip permission | `summarize_frozen_recoverability`, `validate_frozen_install_plan` (read-only; the packages are read through `ReadOnlyArtifactStore`, which creates nothing) |
| What remains after the software stage: skin, add-ons the build manages but did not save | the pure BM-006 `plan_changes` over the state the software stage would leave |
| Settings and files | `ConfigurationInspector` (counts only); owners that are not installed yet count as "will be written", not "unavailable" |
| Private settings | the Build Status private inspection, secret-blind; owners not installed yet count as "will be restored" |
| Pending restart / unfinished operation | the Build Status operation view (lock-free, creation-free) |
| Activation holds and the restart expectation | the installer's rule: pre-activation resource owners and their dependents are held, so a Kodi close/reopen is expected. No automatic relaunch is promised. |

Add-on rows are `CURRENT`, `INSTALL_EXACT`, `INSTALL_REPOSITORY`, `ENABLE`,
`DISABLE`, `ACCEPTED_SKIP`, `DECISION`, and the blocked kinds `DIFFERENT_VERSION`,
`BROKEN`, `PACKAGE_MISSING`, `NOT_SAVED`, `BLOCKED`, plus `UNAVAILABLE`. There is
no remove or uninstall action; add-ons the build does not manage never appear.

## G6: what the installer cannot do yet

`install_exact` refuses to replace a different installed version and refuses a
broken installation, but only after the updater guard is engaged. The plan finds
both before apply and reports `BLOCKED` ("A different version of this add-on is
already installed. Build Manager can't safely replace it yet."). It mirrors the
other conditions the installer would only hit mid-run: a skipped add-on that is
present, an installed add-on with no saved package (neither skip nor fetch can
work), a skip of the skin, a required repository or a private-data owner, a
repository fallback while pre-activation holds exist, and an earlier operation
that is waiting for a restart or did not finish. G6 itself is not implemented here.

## Missing packages and choices

Choices occur before a new installation starts, as in the installer. Each
missing package is `DECISION_REQUIRED` with the choices policy allows
(`INSTALL_CURRENT`, `SKIP`, `CANCEL`), or `BLOCKED` when policy allows none. A
choice is data in the `PlanTarget`; selecting one is not a mutation, and it is
part of the plan's identity, so changing it makes an earlier review stale.
Selecting Install Current yields `RESOLUTION_REQUIRED`, never a reviewed ready
plan. The UI explains that Build Manager needs the repository version before
final changes can be reviewed. Preview itself never downloads anything.

The future flow is: choose Install Current; resolve/download the exact package
in a later explicitly authorized stage; persist its identity and dependencies
in a resolution record bound to the selected build and frozen graph; preview
again from the saved package; review its exact ordered actions; only then issue
a ReviewIdentity. That resolution stage and Apply are not implemented here.

For a completed bound prior repository-current resolution, G3 reads the exact
saved ZIP and reconstructs its required dependencies through
`stored_repository_dependencies`, the same read-only helper used by the
installer's `_restore_resolution()`. Both use the strict requirement parser,
resolved dependency versions, optional/system rules, skip conflict checks and
`validate_frozen_install_plan(..., extra_dependencies=...)` for order and cycle
validation. Added dependencies contribute to order and feasibility even when
the repository-resolved add-on is already installed. Missing/tampered packages
are rejected. The existing frozen dependency edges are retained exactly as in
the installer; repository requirements supplement that graph.

## Review identity and stale-plan validation

`ReviewIdentity` binds a reviewed plan to everything that materially affects it,
hashed per component over canonical JSON (never values): the resolved build and
effective configuration, the device profile, the frozen build ID and software
fingerprint, the install policy, recorded resolution and chosen resolutions,
saved-package availability and identity (including reconstructed repository
package semantics), all installed managed add-on states and broken flags in Kodi, the
active skin, configuration verification state, a secret-blind private
verification state and overlay fingerprint, pending-operation state, and the
resulting ordered plan. It is a stale-plan guard, not a credential: `repr` is
opaque, the digest is never rendered or serialized in public output, and it is
issued only for a `CHANGES_READY` plan. Unmanaged add-ons and check time are not
part of it. Constructor parts must be the exact canonical IdentityComponent set,
each appearing once in order, with a valid SHA-256 digest; extra, unknown,
duplicate, missing, out-of-order and malformed parts are rejected.

Broken-state inspection covers frozen nodes, declared add-ons outside the
frozen graph, required repositories and the managed skin. A broken managed
installation blocks with `INSTALLED_ADDON_BROKEN` instead of receiving an
ordinary enable/disable action; a health change invalidates an earlier review.
Unmanaged broken add-ons are ignored. No G6 repair is added.

Private inspection uses `UNAVAILABLE > CHANGES_NEEDED > CURRENT` within the
private area. An unreadable setting or resource cannot hide behind another
item's drift. Useful item statuses remain available, but such a plan is never
ready and receives no review. An earlier review becomes unverifiable.

`validate(target, review)` re-reads all of that, with the same read-only
owners, and returns `CURRENT`, `STALE` (with the changed components) or
`UNVERIFIABLE` (an inspection was unavailable). Anything but `CURRENT` requires a
new preview and a new review; a different plan is never silently accepted under
the old approval. It is intended to be called immediately before any mutation.

## Zero mutation, privacy

Tests instrument every mutating or file-creating owner (stores, locks,
installers, reconcilers, skin and updater-policy setters, private appliers,
artifact-store writers, repository fetches, sockets) and assert none is touched
across drift, blocked, pending-restart and unreadable states; profile trees are
identical before and after. Sentinel secrets are absent from plans, `repr`,
`to_safe_dict`, review identities, view text and logs. The presentation text
never shows hashes, paths, enum names or developer terms.

## Known limitations

* Not live-proven; no Test.app run. Reads that go through Kodi APIs are
  read-only by their contracts but need live proof.
* No production name resolver: add-ons without a display name show their ID.
* Plans and reviews validate every saved package the way the installer does, so
  a large build can take a while; the Library phase can cache.
* An installed add-on whose saved package is gone is `BLOCKED`, because neither
  skipping nor fetching it can succeed in the current installer.
* **Required before 0.2.0 (not fixed here):** the existing private-resource
  `verify()` / `apply()` SQLite URI in `redlight_resource.py` is not
  percent-quoted, so a `#` in the profile path truncates the URI and can create
  a stray file. It does not affect the authorized Test.app or normal Kodi paths
  (neither contains `#`). The read-only status probe already quotes its URI.
