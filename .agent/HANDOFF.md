# BM-UI-002C frozen plan / review identity and read-only preview (G3) — PASS (offline); not live-proven

Start HEAD 958b5d7 on agent/claude; result is one bounded local commit (SHA in the report). No push, publication, Test.app, normal Kodi or device access.

Corrections to G2 first (each reproduced against the unfixed code, then fixed):
1. Frozen manifest `build_id` is now checked against the resolved build before any frozen data is used (`resources/lib/build_identity.py`, used by status and plan). Pre-fix, config build A + frozen build B reported CURRENT. Now: INCOMPLETE, every area UNAVAILABLE, nothing verified against the mismatched graph (software or private), gap `BUILD_IDENTITY_MISMATCH` (enum only).
2. `StatusTarget` no longer accepts raw `InstallResolutionRecord` tuples. It takes the installer's own `FrozenInstallResolutionManifest`, trusted only if bound to this build ID and this frozen manifest fingerprint, internally valid, and every record matches a managed node (captured version, desired enabled). Pre-fix, a foreign SKIPPED record flipped a missing add-on from changes_needed to current. Now: INCOMPLETE with `RESOLUTION_IDENTITY_MISMATCH`.

G3: `resources/lib/plan_model.py` (stdlib-only public contract; structurally cannot claim ready while blocked/undecided/unchecked), `plan.py` (`PlanTarget`, `BuildPlanService.preview()/validate()`, `ReadOnlyArtifactStore`, `plan_provider`), `ui/plan_view.py` + `NativeDialogs.review()` (native dialogs only; no Apply; Close is the viewer's own), strings 32541-32542 and 32600-32693. Precedence BLOCKED > INCOMPLETE > DECISION_REQUIRED > CHANGES_READY > NO_CHANGES. Software rows come from `summarize_frozen_recoverability`/`validate_frozen_install_plan`; skin and unsaved managed add-ons from the pure BM-006 `plan_changes` over the post-software state; settings/private/operation from the status read-only views (owners not installed yet count as "will be written", so a fresh device gets a ready plan). G6 cases (different installed version, broken install) and the other conditions the installer only hits after the updater guard is engaged are BLOCKED before apply. Review identity: 11 separately hashed components, opaque, issued only for CHANGES_READY; `validate()` returns CURRENT / STALE(components) / UNVERIFIABLE. Docs: docs/BUILD_PLAN.md (new), BUILD_STATUS.md, TESTING.md, changelog. addon.xml untouched (nothing user-visible: no route reaches the review yet).

Validation: full suite 2671 tests PASS (was 2554). New/changed: `test_plan.py` 81, `test_plan_ui.py` 20, `test_status.py` 93 (was 77), plus import-policy updates. Tripwires on every mutating or file-creating owner plus network and repository fetch, profile-tree equality, sentinel secrets through plan/repr/identity/view/logs.

NOT live-proven: no Test.app run. Kodi-API reads (`Addons.GetAddonDetails` broken flag, settings, JSON-RPC) and Estuary rendering are unit-tested only. No applied-build association or Build Library exists, so Install / Update-Repair routes still show their no-build pages and nothing in the product calls the review yet. No independent review was run for G3 (G2's found 15 issues; one is recommended before acceptance).

Decisions worth a second look: (a) an installed add-on whose saved package is missing and has no recorded resolution is BLOCKED (skip fails and a repository fallback ends in NEEDS_ATTENTION in the current installer); (b) a recorded skip whose add-on is now present is BLOCKED (`_finalize` fails it); (c) a build manages an add-on it did not save -> BLOCKED (`ADDON_NOT_IN_SAVED_SOFTWARE`); (d) a repository fallback is not previewable offline (version/dependencies known only after download) and is refused while pre-activation holds exist; (e) preview/validate read and validate every saved package like the installer, so big builds are slow; (f) no production display-name resolver, so IDs show when no name is known.

REQUIRED before 0.2.0 (not fixed here, by instruction): `redlight_resource.py` verify()/apply() SQLite URIs are not percent-quoted; a `#` in the profile path truncates the URI and can create a stray file. Not an issue for the authorized Test.app or normal Kodi paths (no `#`). The read-only status probe already quotes its URI. Recorded in docs/BUILD_PLAN.md and docs/BUILD_STATUS.md.

Out of scope — noticed: updater-policy residue is still not read by status/plan; `.orchestrator/HANDOFF.md` is ChatGPT-maintained and was not edited (it should record G2/G3, the SQLite `#` hardening item and this task's usage summary).

Usage row appended to `.agent/USAGE_HISTORY.md` (claude-sonnet-5-5, effort max; 5h 3%->32%, weekly 91%->96%, account-wide).

Next bounded task (suggested): independent review of G3, then the Build Library / selected-build association that gives Install and Update-Repair a real target, with G6 (version replacement / broken repair) as its own gated task. Human input: Eric/ChatGPT review. STOP here.

## Retained prior endpoint record

# BM-UI-002B read-only Build Status (G2) — PASS (offline); not live-proven

Done: one production read-only status API (`resources/lib/status.py`, public contract `status_model.py`) wired to the main-menu Build Status route (native page: Overall / Add-ons / Skin / Settings / Private settings + Check Again / Help / Close; Help opens H05). Fresh read per call; never raises; never reports CURRENT while an applicable area is unchecked. Overall precedence: NEEDS_ATTENTION > RESTART_REQUIRED > CHANGES_NEEDED > INCOMPLETE > CURRENT.

Read-only seams added (existing paths mutate or create files): `TransactionStore.read_snapshot`, `FrozenInstallStore.read_snapshot`, `session.peek_current_kodi_session_id`, `PrivateOverlayStore.read_snapshot`, `ConfigurationInspector`/`ReadOnlyConfigurationBackend`, `StructuredPrivateResourceManager.inspect`, `RedLightSettingsAdapter.inspect` (immutable sidecar-free probe; a non-empty `-wal` is UNAVAILABLE). `verify()`/`apply()` unchanged. Dependency metadata never reads repositories (no network).

Validation: 2554 tests PASS (full suite, was 2444); focused `test_status` (77) + `test_status_ui` (32). Zero-mutation proven by tripwires on every mutating/file-creating owner plus network and repository reads, and by profile-tree equality (incl. SQLite sidecars). Secret-blind proven with sentinel values through result, view model, dialogs, logs and serialized evidence. An independent adversarial review reported 15 findings; 14 fixed with regression tests, see docs/BUILD_STATUS.md.

NOT live-proven: no Test.app run. Dialog rendering in Estuary, `xbmcaddon`/JSON-RPC reads, and the Red Light probe against Kodi's SQLite are unit-tested only. There is no applied-build association yet, so production `default_status_target()` is None and build-dependent areas report "Not Fully Checked"; software/skin/settings/private drift is proven by tests with explicit targets only.

Metadata touched for truthfulness (not a release): addon.xml news/description now list Build Status as present; changelog Unreleased entry; stale string 32123 removed; H05 now says "Use Check Again" (button name). No version bump, no icon change.

Out of scope — noticed: `redlight_resource.py` verify/apply SQLite URIs are not percent-quoted (a `#` in the profile path truncates the URI and can create a stray file); frozen manifest `build_id` is not cross-checked against the resolved build; updater-policy residue is not read.

Next: G3 frozen plan/review interface (separate task). Human input: Eric/ChatGPT review; optional portable Test.app visual validation of the Status page. No push, publication, live Kodi or device access.

## Retained prior endpoint record

# BM-UI-001 native-dialog correction — PASS; STOP for visual review

Done: replaced rejected WindowXML shell with native select/text dialogs and direct script.build.manager native Settings. Removed custom XML, six textures and palette. Four workflow placeholders remain non-mutating; H01-H10/contextual Help retained; native Back/Cancel restores selection. Settings now opens directly and returns to main Settings selection, with no intermediary.

Validation: 34 focused tests PASS; git diff --check PASS. Exact final uncommitted product staged/verified in portable Test.app, fingerprint 55c35bcd9f0c2322b7ca4de7af3737915d822189e49d62cfd60029ec41a53c82; all routes/Help/scrolling/direct Settings/mouse transition validated. Final PID25404 gracefully exited; not_running. Census40, updater AUTOMATIC, transactions absent and prior adapter result unchanged. No backend mutation. Report: .qualification-evidence/bm-ui-001-20261006T123436Z/native-final/REPORT.md.

Not done: no G1-G6 or real workflows, normal Kodi/devices, commit/push/publication/Agent Handoff. Existing metadata/icon preserved; portable listing renders generic icon. All 261 prior files verified unchanged before required closeout, authority docs/history remain preserved. Model exact tier/effort and usage unavailable.

Next/human input: Eric/ChatGPT visual review of final screenshots/UI. STOP; item8 acceptance pending, no further implementation/runtime work authorized.

## Retained prior endpoint record

# WF-FRONTEND-BETA-GATE — PASS

Adopted authoritative exit item 8 and approved UI amendments on agent/codex at e24b3cdb119fb8b846dc38c0e066d070e404c3e2. Original backend criteria 1-7 and accepted evidence preserved. Backend qualification alone is not product beta readiness; normal/live Mac Kodi and Shield testing waits for accepted item 8 and named target/action authorization.

Changed BUILD_MANAGER_PROJECT_PLAN.md; .orchestrator/PROJECT.md, WORKFLOW.md, BOOTSTRAP.md, HANDOFF.md, DECISIONS.md (D-027); evidence-local UI_DESIGN.md; normal endpoint records. Persistent terminal result until Done, canonical internal Build Library, Build Transfer Folder, contextual navigation-only Help, distinct outcome semantics and Backup Pro guidance adopted. BM-UI-001 focused tests then interactive portable Test.app validation must STOP for Eric/ChatGPT visual UX review before remaining workflows.

Validation: original seven criterion lines byte-identical; scoped file/hash checks and git diff --check pass; product paths unchanged versus HEAD/reviewed candidate. No product tests needed for documentation; no runtime/UI validation claimed. No implementation, Kodi/Test.app/device access, commit, push, guidance sync or Agent Handoff switch.

Next: separately assigned BM-UI-001 — Dashboard, Help and frontend presentation foundation. Human input: Eric/ChatGPT visual UX review after that task's focused tests and interactive Test.app validation. No further action authorized here.

## Retained prior backend qualification record (historical)

The prior seven-item completion claim below concerns accepted backend evidence only and is superseded for product readiness by the current eight-item milestone.

# Second reconciliation retry — PASS

Exit item 6 live-proven against agent/codex HEAD e24b3cdb119fb8b846dc38c0e066d070e404c3e2 and reviewed candidate 4a02b833178f5cb29e2b596985f1a8641ed3fa25 (tree 5a349a54ca76744727c086f72d50d5da527dad4a). No product/helper/driver changes or commits.

Offline actual ReconcileRequest construction reproduced prior prefixed-input ValueError and passed with raw 64-hex digest. Separate request/reconcile runner stages. Starting stopped HTTP-disabled AUTOMATIC transaction-free state and exact Git binding passed. One HTTP enable, one portable launch PID617 with sanctioned XBMCHelper and exact TCP8080 listener ownership, one production reconciliation: success, 1 CONFIGURE planned, 0 changed, 0 failed, validation passed with 0 failures, restart none. Desired fingerprint sha256:71fa113d645153c17594b45dea1376069477a503282ddb4f8dbee0a4bd717d44. Same main PID through reconciliation to quit.

One graceful quit accepted/exited, forced termination false; exact temporary runner/job/result removed, one HTTP-disable write, no relaunch. Final supported not_running, persisted AUTOMATIC, AF3 active, RedLight2.6.8 enabled; frozen/restart transactions absent, no activation hold/NEEDS_ATTENTION; final Git-bound candidate verification PASS.

Evidence .qualification-evidence/second-reconciliation-retry-20261006-111432Z/ (evidence-sha256.json). Prior evidence preserved unchanged. Runner default SHA b800cb447520bb592ab45e1b4c65fec50c6fa87a4a32458a7fb44c7bf105abb9. Reconcile result SHA10d621f3a6f9ae45616c3e50dc88c99f10d6027f79bf9d04f6611856d67e244b. Candidate full-suite evidence retained because source unchanged; temporary runner compiled and live checks passed.

Exit6 satisfied; together with previously accepted 1,2,3,4,5,7, all seven macOS Beta Qualification exit items evidenced. No frozen installation, retry/recover, restage, product repair, private-value inspection, normal Kodi/device access, push or Agent Handoff. Stop boundary reached. Next step: supervisor qualification closeout; no further runtime action authorized by this task. Human input required only for a new task.
