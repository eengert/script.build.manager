# Build Manager — Supervisor Handoff

Living project-state document. Keep current truth; remove obsolete trails.
See §32–33 of `BUILD_MANAGER_PROJECT_PLAN.md` for maintenance discipline.

---

## Project Identity

| Field | Value |
|---|---|
| Name | Build Manager |
| Addon ID | `script.build.manager` |
| Repository | `eengert/script.build.manager` |
| Integration branch | `matrix` (protected) |
| Agent branches | `agent/codex`, `agent/claude` |
| Active agent | Claude (Codex temporarily unavailable) |

## Target Platforms

- Apple TV / tvOS
- Nvidia Shield Pro / Android TV
- Fire TV / Fire OS
- macOS

## Canonical Project Plan

**`BUILD_MANAGER_PROJECT_PLAN.md`** — supervisor-approved, 51 sections.

Key sections for quick reference:

| § | Topic |
|---|---|
| 2 | Project goal (fresh-install and reconciliation flows) |
| 3 | Design philosophy (desired-state, idempotency, reconciliation) |
| 4 | MVP scope |
| 5 | Proposed architecture |
| 6 | Repository structure |
| 7 | Build definition layers (base → platform → device → secrets) |
| 8–14 | Add-ons, dependencies, skin, managed config, auth, security, workflow |
| 15 | Reconciliation / repair mode |
| 17–19 | Testing strategy, golden scenarios, volatile state |
| 20 | Restart orchestration |
| 21 | Backup Pro relationship |
| 22–31 | Supervisor/agent workflow, model guidance, parallel rules, source control |
| 37 | Phase plan (0: research → 9: 1.0 release) |
| 38 | Initial development backlog (BM-001 through BM-020) |
| 45–47 | Definition of done, MVP criteria, scope-control rule |
| 49 | Recommended first milestone (planner output before mutation) |

Do not treat any shorter summary as a substitute for the canonical plan.

## Current State

**BM-009 and BM-010 on agent/claude — awaiting supervisor review and merge**

| Task | Status | matrix SHA | Notes |
|---|---|---|---|
| BM-001 Project skeleton | Merged | `5442f13` | |
| BM-002 Manifest schema v1 | Merged | `89039d6` | |
| BM-003 Manifest parser/validator | Merged | `a5d263e` | |
| BM-004 Profile merge/inheritance | Merged | `2ad253f` | |
| BM-005 Kodi/platform state inspector | Merged | `6d41279` | |
| BM-006 Desired-vs-actual diff / planner | Merged | `70504e0` | |
| BM-007 | Absorbed by BM-006 | — | desired-state model = BM-004; planner = BM-006 |
| BM-008 | Absorbed by BM-006 | — | reconciliation tests = BM-006 test suite |
| BM-009 Disposable Kodi harness | On agent/claude | — | pending review |
| BM-010 Repository detection/install | On agent/claude | — | pending review |

**matrix HEAD**: `70504e0` (unchanged)

## Completed Deliverables

### BM-001 (merged `5442f13`)
- `addon.xml`, `default.py`, `resources/lib/`, `resources/settings.xml`,
  `resources/language/resource.language.en_gb/strings.po`
- `tests/test_imports.py` — 3/3 passing

### BM-002 (merged `89039d6`)
- `docs/MANIFEST.md` — schema reference (layering, merge semantics, field docs)
- `resources/builds/schema-v1.json` — JSON Schema Draft 7
- `resources/builds/examples/minimal.json`
- `resources/builds/examples/eric-main.example.json`
- `tests/test_manifest_schema.py` — 48 structural validation tests

### BM-003 (merged `a5d263e`)
- `resources/lib/manifest.py` — loader, validator, typed representation.
  Public API: `load_manifest_file`, `load_manifest_json`, `validate_manifest`.
  Errors: `ManifestError`, `ManifestParseError`, `ManifestValidationError`.
  Stdlib only — no `jsonschema` runtime dependency.
- `tests/test_manifest_loader.py` — 162 BM-003 tests (127 original + 35 null-rejection)
- `docs/MANIFEST.md` — updated runtime-validation note (stdlib, not jsonschema)
- Null-vs-omission correction included: explicit JSON `null` rejected for all
  non-nullable fields; omission still returns documented defaults.

### BM-004 (merged `2ad253f`)
- `resources/lib/resolver.py` — profile resolver.
  Public API: `resolve_manifest(manifest, device_profile_id) -> ResolvedBuild`.
  Error: `ManifestResolutionError`. Output: `ResolvedBuild` (frozen dataclass).
  Layer order: base → platform → device → optional groups.
  Optional-group de-duplication: platform-first, then device, first-occurrence wins.
  Stdlib only — no new runtime dependencies.
- `tests/test_manifest_resolver.py` — 78 BM-004 tests
- `docs/MANIFEST.md` — optional-group dedup rule documented; open question #5 closed

### BM-005 (merged `6d41279`)
- `resources/lib/inspector.py` — Kodi state inspector.
  Public API: `KodiStateInspector(backend=None).inspect() -> KodiState` and
  `inspect_kodi_state() -> KodiState`.
  Error: `KodiInspectionError`. Output types: `KodiState`, `InstalledAddon`
  (both frozen dataclasses).
  Injectable backend: `KodiBackend` (abstract), `KodiRuntimeBackend` (lazy xbmc).
  Pure-function JSON-RPC helpers: `_parse_addon_response`, `_parse_version_response`.
  Fail-closed add-on parsing: all entry fields validated; duplicates rejected;
  no partial KodiState returned on any malformed response.
  Platform mapping: tvos/android/macos/ios/windows/linux/unknown with documented
  precedence. bool/int distinguished for Kodi version major/minor.
  All JSON-RPC calls read-only. No Kodi state mutated.
  Stdlib only — no new runtime dependencies.
- `tests/test_kodi_inspector.py` — 67 BM-005 tests (58 original + 9 correction)

### BM-009 (on agent/claude — pending review)
- `tools/__init__.py` — empty package marker
- `tools/kodi_test.py` — standalone disposable Kodi test harness.
  Isolation via HOME env override → `.kodi-test/home/`. Commands: reset,
  install, configure / enable-webserver, launch, wait, stop, restart,
  inspect, status, validate.
  Safety: `verify_isolation()` before every mutating op; stop refuses to SIGTERM
  non-Kodi process; reset double-checks path before rmtree.
  Install: copies only addon.xml, default.py, resources/ — excludes tests/tools/docs.
  Inspect: HTTP JSON-RPC queries (platform, version, skin, addons) — read-only.
  Validate: 11-step live sequence; real profile mtime compared before/after.
  Webserver port 8920 (distinct from Backup Pro 8899 to allow simultaneous use).
  Stdlib only — no runtime dependencies.
- `tests/test_kodi_harness.py` — 74 BM-009 unit tests; no real Kodi required.
  Covers path safety, isolation guards, reset, install source validation,
  copy filtering, PID file, status, stop guard (non-Kodi process refusal),
  command dispatch (12 routes + error handling), readiness polling, and
  webserver configuration.
- `docs/TESTING.md` — harness documentation (isolation model, safety, usage,
  port table, INSPECT command, out-of-scope notes).
- `.gitignore` — added `.kodi-test/`

Live validation results (Kodi 21.1 macOS, 2026-09-17): platform=macos,
kodi_version=21.1, active_skin=skin.estuary, addon_count=30.
script.build.manager visible (enabled=False — freshly installed add-ons start
disabled in Kodi, as expected). Real profile untouched.

### BM-010 (on agent/claude — pending review)

- `resources/lib/repository.py` — repository detection and installation.
  Public API: `RepositoryManager(backend).is_installed(addon_id)` and
  `RepositoryManager(backend).install(repository) -> RepositoryInstallResult`.
  Errors: `RepositoryError`, `RepositoryValidationError`, `RepositoryInstallError`.
  Result: `RepositoryStatus` enum (ALREADY_INSTALLED|INSTALLED|FAILED),
  `RepositoryInstallResult(addon_id, status, message)` frozen dataclass.
  Backend interface: `RepositoryBackend` (5 abstract methods); production
  backend: `KodiRuntimeRepositoryBackend` (lazy xbmc/xbmcvfs import).
  Security: `_validate_url_policy()` (https/http only, no credentials),
  `_SafeRedirectHandler` (rejects file:// and credential-containing redirects),
  `_build_safe_opener()` (no FileHandler), `_download_artifact()` (50 MB limit,
  30s timeout, chunked reads). ZIP safety: `validate_repository_zip()` (path
  traversal rejection, addon.xml presence+ID match, xbmc.addon.repository
  extension required). Extraction: `_extract_zip_to_directory()` (handles
  prefixed and flat ZIPs, path containment check before every write).
  Idempotent: ALREADY_INSTALLED returned if add-on already present (no mutation).
  Installation mechanism: ZIP extraction + `xbmc.executebuiltin('UpdateLocalAddons')`.
  Verification: `poll_addon_installed()` via JSON-RPC polling.
  Stdlib only — no new runtime dependencies. No dependency on tools/kodi_test.py.
- `tests/test_repository.py` — 87 BM-010 unit tests; no real Kodi required.
  Covers: detection (is_installed), idempotency, URL validation (schemes,
  credentials, empty), redirect safety (_SafeRedirectHandler), download (size
  limit, network error, empty), ZIP entry validation (traversal, absolute paths,
  null bytes), ZIP validation (valid/invalid, wrong ID, missing extension),
  extraction (prefixed/flat/nested), install happy path (6 checks), all failure
  paths (10 cases), result types (enum values, immutability, hashability),
  security policy (max size constant, data/javascript/empty URLs), error
  hierarchy, backend abstract interface, KodiRuntimeRepositoryBackend without Kodi.
- `tools/kodi_test.py` — `validate-repo` command added.
  `_make_test_repo_zip()`: minimal `repository.build-manager-test` ZIP.
  `_HttpRepositoryBackend`: harness backend using HTTP JSON-RPC + direct
  filesystem; `trigger_addon_scan()` restarts Kodi (stop→launch→wait) since
  `UpdateLocalAddons` is not accessible via HTTP JSON-RPC.
  `_SingleFileHandler`: serves one file at 127.0.0.1:8921.
  `validate_repo()`: 12-step live sequence (port 8921 for HTTP server).
- `docs/TESTING.md` — updated test counts, validate-repo usage and port table.

Live validation results (Kodi 21.1 macOS, 2026-09-17): 12/12 steps passed.
repository.build-manager-test (392 bytes) installed; is_installed() confirmed
True after install; Kodi restarted once for UpdateLocalAddons trigger. Real
profile untouched. Stdlib HTTP server bound to 127.0.0.1 only.

### BM-006 (on agent/claude `7735e7a` — pending merge)
- `resources/lib/planner.py` — desired-vs-actual planner.
  Public API: `plan_changes(desired: ResolvedBuild, actual: KodiState) -> Plan`.
  Error: `PlanningError`. Output types: `Plan`, `PlanAction` (both frozen dataclasses).
  Action kinds: `INSTALL_REPOSITORY`, `INSTALL_ADDON`, `ENABLE_ADDON`, `DISABLE_ADDON`,
  `ENSURE_ABSENT`, `SET_SKIN`, `CONFIGURE`.
  Deterministic ordering: repos→installs→enable/disable→absent→skin→config,
  lexical by addon_id within category.
  Cross-category dedup: INSTALL_REPOSITORY suppresses INSTALL_ADDON for same addon_id;
  desired_state="disabled" propagated when overlapping desired add-on state is disabled.
  Skin dedup: planned_install_ids (union of repo + addon installs) prevents duplicate
  INSTALL_ADDON for skin even when skin-as-repo pathological manifest is used.
  Contradictory-state validation: raises PlanningError when desired skin also declared
  absent, or when required repository also declared absent.
  Unmanaged add-ons in actual state are never touched.
  CONFIGURE always `current_state="unchecked"` (BM-005 does not inspect config state).
  `PlanningError` on duplicate addon_ids in KodiState.
  Pure Python — no Kodi imports, no filesystem/network access, no mutation.
  Stdlib only — no new runtime dependencies.
- `tests/test_planner.py` — 86 BM-006 tests (70 initial + 16 correction)

## Test Status

`python3 -m unittest discover tests` — **605/605 passing** (outside Kodi runtime)

Live validation (BM-009): **11/11 steps passed** against Kodi 21.1 macOS (2026-09-17)
Live validation (BM-010): **12/12 steps passed** against Kodi 21.1 macOS (2026-09-17)

## Schema Summary

Format: JSON, JSON Schema Draft 7. Top-level structure:

```json
{
  "schema_version": 1,
  "engine_min_version": "0.1.0",
  "build": { "id": "...", "version": "...", "name": "...", "description": "..." },
  "repositories": [...],
  "addons": [...],
  "skin": { "addon_id": "skin.*", "config_packages": [...] },
  "config": { "packages": [...], "managed_settings": [...], "managed_files": [...] },
  "platform_profiles": { "<platform-id>": { ... } },
  "device_profiles": { "<device-id>": { "extends": "<platform-id>", ... } },
  "optional": [ { "id": "...", "addons": [...] } ],
  "private_overlay": { "type": "local_file", "path_hint": "..." },
  "restart_policy": { "allow_skin_reload": true, "allow_kodi_restart": true }
}
```

Key constraints:
- `device_profile.extends` is **required** — every device profile must extend a platform profile
- `additionalProperties: false` everywhere — malformed manifests rejected
- Add-on states: `enabled` | `disabled` | `absent`; omitted = inherit (not disabled)
- No credentials in public manifest; `private_overlay` is reference only
- Full JSON Schema validation deferred to BM-003 (no `jsonschema` dependency yet)

## Next Recommended Tasks

1. **BM-009 + BM-010 review + merge** — supervisor review of agent/claude:
   - `tools/kodi_test.py` harness (BM-009 + validate-repo from BM-010)
   - `tests/test_kodi_harness.py` (74 tests, BM-009)
   - `resources/lib/repository.py` (BM-010)
   - `tests/test_repository.py` (87 tests, BM-010)
   - `docs/TESTING.md`

2. **BM-011** — General add-on detection and installation (distinct from repository bootstrap)

## Open Questions (from BM-002)

1. Private overlay schema — format not yet defined; needed before auth work
2. Config package resolution — package names defined; format TBD
3. `bootstrap_url` validation — checksum/signature strategy TBD
4. `firetv` vs `android` platform split — defer to cross-platform testing
5. Optional group deduplication — BM-004 must deduplicate when platform + device both include same group

## Agent/Model Usage Policy

Usage tracking is **enabled where reliable data is available**.

- Model/effort recommendations should be driven by **empirically observed burn
  and task success**, not by assuming a lower model or lower reasoning setting
  is cheaper. The target is lowest total cost to a correct result (§28).
- **Raw usage history lives in `.agent/USAGE_HISTORY.md`**, not here and not in
  `BUILD_MANAGER_PROJECT_PLAN.md`. This file carries only short summarized
  observations.
- **Never fabricate usage data.** Missing readings are recorded as `unknown` or
  `unavailable`. An absent measurement is acceptable; an invented one is not.
- Available sources, as of 2026-09-17:
  - **Claude** — Claude Code reports plan limit windows (5-hour, weekly) and
    the session's model/effort. Documented in `CLAUDE.md`.
  - **Codex** — no usage/quota source exists. Codex rows record
    `unavailable` for start/end/delta. Documented in `AGENTS.md`.
- Claude and Codex model/effort terminology are separate namespaces and are
  never translated into each other. Claude: Sonnet/Opus with Claude Code's
  `effort` value. Codex: Luna/Sol/Astra with Codex effort names.

### Observations

*(none yet — WF-001 recorded a partial reading only; no comparable-task
baseline exists)*

## Worktree Paths

| Branch | Worktree |
|---|---|
| `agent/codex` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-codex` |
| `agent/claude` | `/Users/eengert/Documents/Kodi/worktrees/script.build.manager-claude` |

## Agent Workflow

See §22–31 of `BUILD_MANAGER_PROJECT_PLAN.md` for full workflow guidance.

Normal implementation work happens on `agent/codex` or `agent/claude`.
Supervisor reviews and merges to `matrix`.

## History

| Date | Milestone |
|---|---|
| 2026-09-17 | Repository initialized; bootstrap committed to `matrix` (`a970e83`) |
| 2026-09-17 | BM-001 skeleton complete and merged to `matrix` (`5442f13`) |
| 2026-09-17 | BM-002 manifest schema v1 complete and merged to `matrix` (`89039d6`) |
| 2026-09-17 | WF-001 usage-tracking docs merged to `matrix` (`a983df8`); project idle |
| 2026-09-17 | BM-003 manifest parser/validator merged to `matrix` (`a5d263e`); project idle |
| 2026-09-17 | BM-004 profile resolver merged to `matrix` (`2ad253f`); project idle |
| 2026-09-17 | BM-005 Kodi state inspector merged to `matrix` (`6d41279`); project idle |
