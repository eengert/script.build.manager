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
