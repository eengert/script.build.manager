# Usage History

Append-only record of agent/model/effort usage per task. One row per task.

Purpose: build an empirical basis for model and effort recommendations
(§28 of `BUILD_MANAGER_PROJECT_PLAN.md`), optimizing **total** cost to reach a
correct result rather than per-request cost.

See `AGENTS.md` §"Usage Tracking" for the shared rules, `CLAUDE.md`
§"Usage Tracking (Claude)" for the Claude mechanism, and `AGENTS.md`
§"Codex-Specific Notes" for Codex.

## Conventions

- **Never fabricate numbers.** Use `unavailable` when no reliable source
  exists for that agent, `unknown` for a reading that was not captured.
- Claude rows: the metric is the Claude Code plan window, written as
  `5h <n>% / wk <n>%` (percent **used**), from
  `mcp__ccd_session_mgmt__get_usage`. Model and effort come from
  `mcp__ccd_session_mgmt__get_session` and are recorded as reported.
- Codex rows: no usage source exists today, so Start/End/Delta are
  `unavailable`. The remaining columns are still recorded.
- Model/effort terminology stays in each agent's own namespace. Claude uses
  Sonnet/Opus with Claude Code's `effort` value; Codex uses Luna/Sol/Astra
  with Codex effort names. Never translate between them.
- Append new rows at the bottom. Do not rewrite history.

## History

| Task | Agent | Model | Effort | Type | Difficulty | Start | End | Delta | Result | Notes |
|------|-------|-------|--------|------|------------|-------|-----|-------|--------|-------|
| WF-001 | claude | Opus 5 (`claude-opus-5`) | xhigh | docs/workflow | easy | unknown | 5h 94% / wk 35% | unknown | clean | Usage-tracking instructions. Start not captured (this task established the convention); first reading, taken mid-task, was 5h 92%. Task prompt specified Sonnet 4.6; session actually ran `claude-opus-5` — observed values recorded. No retries. |
| WF-001-merge | claude | claude-sonnet-4-6 | max | integration | trivial | 5h 96% / wk 35% | 5h 96% / wk 35% | ~0% / 0% | clean | Matrix integration of WF-001 usage-tracking commit (a983df8). Fast-forward. No implementation changes. 51/51 tests. |
| BM-003 | claude | claude-sonnet-4-6 | max | parser/validation | moderate | 5h 19% / wk 39% | 5h 31% / wk 41% | +12% / +2% | clean | Manifest loader, validator, typed representation. 127 new tests; 181/181 total passing. Stdlib-only (no jsonschema). One test fix (UNC path check ordering). |
| BM-003-correction | claude | claude-sonnet-4-6 | max | bug-fix | low | 5h 33% / wk 41% | 5h 40% / wk 42% | +7% / +1% | clean | Null-vs-omission fix throughout manifest.py. 32 new TestNullRejection tests; 213/213 total passing. schema-v1.json unchanged. |
| BM-003-merge | claude | claude-sonnet-4-6 | max | integration | trivial | 5h 41% / wk 42% | 5h 42% / wk 42% | +1% / 0% | clean | Fast-forward matrix a983df8→a5d263e. 213/213 tests passing on matrix. No squash/rebase. Codex untouched. BM-004 not started. |
| BM-004 | claude | claude-sonnet-4-6 | max | resolver | moderate | 5h 44% / wk 42% | 5h 50% / wk 43% | +6% / +1% | clean | Profile resolver (resources/lib/resolver.py). 78 new tests; 291/291 total. Docs updated: optional-group dedup rule documented, open question #5 closed. |
| BM-004-merge | claude | claude-sonnet-4-6 | max | integration | trivial | 5h 52% / wk 44% | 5h 52% / wk 44% | ~0% / 0% | clean | Fast-forward matrix a5d263e→2ad253f. 291/291 tests passing on matrix. No squash/rebase. Codex untouched. BM-005 not started. |
| BM-005 | claude | claude-sonnet-4-6 | max | inspector | moderate | 5h 56% / wk 44% | 5h 63% / wk 45% | +7% / +1% | clean | Kodi state inspector (resources/lib/inspector.py). 58 new tests; 349/349 total passing. KodiStateInspector with injectable backend; KodiRuntimeBackend with lazy xbmc import; _parse_addon_response/_parse_version_response pure-function helpers. Stdlib only. |
| BM-005-correction | claude | claude-sonnet-4-6 | max | bug-fix | low | 5h 64% / wk 45% | 5h 64% / wk 45% | ~0% / 0% | clean | Fail-closed add-on parsing: _parse_addon_entry raises on non-object, missing/empty/non-str addonid, missing/non-bool enabled, non-str version-if-present, duplicate addonid. _parse_version_response excludes bool from int check for major/minor. 9 new tests; 358/358 total passing. |
| BM-005-merge | claude | claude-sonnet-4-6 | max | integration | trivial | 5h 67% / wk 46% | 5h 67% / wk 46% | ~0% / 0% | clean | Fast-forward matrix 2ad253f→6d41279. 358/358 tests passing on matrix. No squash/rebase. Codex untouched. BM-006 not started. |
| BM-005-live-validation | claude | claude-sonnet-4-6 | max | validation | low | 5h 75% / wk 47% | 5h 78% / wk 48% | +3% / +1% | clean | 9/9 validation items passed against disposable Kodi 21.1 (macOS). Platform flags (macos=True), version (21.1), skin (skin.estuary), 29 add-ons parsed cleanly, determinism confirmed, read-only proven. No code change. Discovery: XBMC.GetInfoBooleans is the correct HTTP JSON-RPC proxy for xbmc.getCondVisibility(); Addons.GetAddons includes extra "type" field (correctly ignored). |
| BM-006 | claude | claude-sonnet-4-6 | max | planner | moderate | 5h 78% / wk 48% | 5h 90% / wk 49% | +12% / +1% | clean | Desired-vs-actual planner (resources/lib/planner.py). 70 new tests; 428/428 total passing. Pure Python, no Kodi imports. All 7 action kinds implemented. Deterministic ordering. Skin dedup. PlanningError on duplicate addon_ids. Integration tests against eric-main.example.json. Committed 7735e7a. Pending merge to matrix. |
| BM-006-correction | claude | claude-sonnet-4-6 | max | bug-fix | low | 5h 90% / wk 49% | 5h 95% / wk 50% | +5% / +1% | clean | Cross-category install dedup (INSTALL_REPOSITORY suppresses INSTALL_ADDON for same ID; desired_state="disabled" hint propagated). Contradictory-state validation (_validate_no_contradictions). 16 new tests; 444/444 total passing. Committed b686153. |
| BM-006-merge | claude | claude-sonnet-4-6 | max | integration | trivial | 5h 95% / wk 50% | 5h 97% / wk 50% | +2% / 0% | clean | Fast-forward matrix 6d41279→70504e0. 444/444 tests passing on matrix. No squash/rebase. Codex untouched. BM-007 not started. |
| BM-009 | claude | claude-sonnet-4-6 | max | harness | moderate | 5h 8% / wk 52% | 5h 17% / wk 53% | +9% / +1% | clean | Disposable Kodi harness (tools/kodi_test.py). 74 new tests; 518/518 total passing. Full live validation passed (11/11 steps). BM-007/BM-008 absorbed by BM-006 (recorded in handoff). Committed and pushed to agent/claude. |
| BM-010 | claude | claude-sonnet-4-6 | max | repository | moderate | 5h 19% / wk 53% | 5h 33% / wk 55% | +14% / +2% | clean | Repository detection/install (resources/lib/repository.py). 87 new tests; 605/605 total passing. Full live validation passed (12/12 steps). validate-repo command added to harness. |
| BM-010-R | claude | claude-sonnet-4-6 | max | bug-fix/research | high | unknown (context continuation) | 5h 60% / wk 59% | unknown | clean | Supervisor-mandated correction. Research: no supported non-interactive Kodi 21 ZIP install API; C++ CAddonInstaller::InstallFromZip not exposed. Decision: Path B → Option 3 (temp+rename extraction + UpdateLocalAddons + Addons.SetAddonEnabled). Fixes: no rmtree of existing target (fail closed), atomic temp→rename, new enable_addon() using Addons.SetAddonEnabled JSON-RPC, poll_addon_installed() now checks enabled=True via Addons.GetAddonDetails. 21 new tests (626/626 total). validate_repo() expanded to 13 steps (restart persistence, idempotency). Live validation pending. |
| BM-010-R-validation | claude | claude-sonnet-4-6 | max | validation | low | 5h 62% / wk 60% | 5h 63% / wk 60% | +1% / ~0% | clean | 13/13 live steps passed. Kodi 21.1 macOS, disposable .kodi-test only. Explicit API proof: GetAddonDetails enabled=True before restart; enabled=True after restart; type=xbmc.addon.repository confirmed. ALREADY_INSTALLED on second call. Real profile untouched. 626/626 unit tests. |
| BM-010-merge | claude | claude-sonnet-4-6 | max | integration | trivial | 5h 65% / wk 60% | 5h 66% / wk 60% | +1% / ~0% | clean | Fast-forward matrix 70504e0→031e405. Includes BM-009 + BM-010-R commits. 626/626 tests on matrix. Architectural note added to handoff. agent/codex untouched. BM-011 not started. |
| BM-011 | claude | claude-sonnet-4-6 | max | addon-install | high | 5h 66% / wk 60% | 5h 95% / wk 65% | +29% / +5% | in_progress | General addon detection/installation (resources/lib/addons.py). 132 new tests (113 addon_manager + 19 harness); 758/758 total passing. live validation blocked at step 10: trigger enable fix landed, UpdateAddonRepos triggered, but InstallAddon poll times out (Kodi may not index test repo). Next: add HTTP logging, try zip=true in repo addon.xml. |
| BM-011-validation | claude | claude-sonnet-4-6 | max | validation/debug | high | unknown (context continuation) | 5h 18% / wk 67% | unknown | clean | 17/17 live steps pass. Root cause of step 10 failure: Kodi 21 InstallAddon builtin always shows interactive dialog, cannot be driven headlessly. Also fixed repo addon.xml schema (Kodi 21 requires <dir> wrapper + zip=true). _HttpAddonBackend.invoke_install redesigned to use direct ZIP extraction + Kodi restart + SetAddonEnabled. 760/760 unit tests. Commits: cdcaa2f (production) + 08fd2de (validation fixes). |
| BM-011-C | claude | claude-sonnet-4-6 | max | correction/rewrite | high | 5h 37% / wk 70% | 5h 37% / wk 70% | ~0% / ~0% | clean | Supervisor-mandated correction: TEST != PRODUCTION mismatch. Implemented Option A (constrained package-install fallback). Production KodiRuntimeAddonBackend.invoke_install: resolve repo metadata → download → validate → staged install → UpdateLocalAddons. Harness _HttpAddonBackend mirrors same algorithm (restart instead of UpdateLocalAddons). New shared helpers: _validate_url, _fetch_bytes, _validate_addon_zip, _staged_install. AddonManager.install acts on desired_state (enable_addon after poll). 51 new tests; 811/811 total. 17/17 live. HTTP evidence proves production algorithm ran. Commit 0eb8133. |
| BM-011-C-final | claude | claude-sonnet-4-6 | max | security/correction | moderate | 5h 52% / wk 72% | 5h 52% / wk 72% | ~0% / ~0% | clean | Two supervisor-mandated corrections to BM-011-C. Issue 1: redirect security — _SafeRedirectHandler + _build_safe_opener added to addons.py (mirrors BM-010 pattern); rejects file/ftp/credentials/invalid-host on redirect; _fetch_bytes uses opener.open(). Issue 2: desired_state validation (FAILED before any backend call for invalid values) + symmetric set_addon_enabled(addon_id, enabled: bool) replacing asymmetric enable_addon. 24 new tests; 835/835 total. 19/19 live (new steps 13-14 prove disabled path). Commit 500217f. |
