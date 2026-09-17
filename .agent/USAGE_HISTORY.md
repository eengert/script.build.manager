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
