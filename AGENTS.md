# Agent Guidance — Build Manager

Shared rules for all coding agents (Codex, Claude, or any future agent)
working on this project. Read this before beginning any task.

## Scope

Work only on the task explicitly assigned. Do not modify files that are not
part of the current task. Do not refactor, restructure, or "clean up"
unrelated code while implementing a feature or fix.

## Branch Policy

- Normal implementation work happens on your agent branch (`agent/codex` or
  `agent/claude`), never directly on `matrix`.
- The `matrix` branch is protected. Do not push or merge to it unless the
  task explicitly authorizes it (e.g., a bootstrap or release operation with
  supervisor approval).
- Do not create additional branches without explicit authorization.

## Kodi Profiles and Devices

- Use **disposable Kodi profiles** (isolated, non-production environments)
  for all integration testing.
- **Do not alter Eric's real Kodi profiles** (e.g., Family Rm, Bonus Rm,
  or any Apple TV) unless the task explicitly and specifically authorizes
  a named action on a named device.
- Do not restart, reconfigure, or access any Apple TV without explicit
  per-device, per-action authorization.
- Disposable validation profiles must be isolated from the real profile
  (use a separate `HOME` override or equivalent).

## Secrets and Credentials

- Do not log, print, or commit credentials, API keys, tokens, or private
  setting values.
- If your task involves settings that may contain credentials (e.g., remote
  path, Dropbox token), ensure they are redacted in all log output.
- Do not read or write `NSUserDefaults` or platform-level keychain entries.

## Tests

- Add or update tests for every behavior change.
- Do not reduce test coverage.
- Run the full test suite before marking a task complete and include the
  pass count in your handoff.

## Handoff

After completing a task, write a concise structured handoff to
`.agent/HANDOFF.md` and update `.agent/CURRENT_TASK.md` and
`.agent/AGENT_STATUS.json`. Include:

- What was done (files changed, commits, test results)
- What was not done and why (scope boundary, human gate, etc.)
- The smallest next step
- Any human input required before the next agent can proceed

Do not pad the handoff. Be precise about what was live-proven versus
what is covered only by unit tests.

## Usage Tracking

Applies to every agent (Codex, Claude, or any future agent).

The goal is empirical: over time, learn which model/effort combination reaches
a correct result for the least total usage. See §28 of
`BUILD_MANAGER_PROJECT_PLAN.md` for the current strategy this data informs.

### What to capture

At the **start** and **end** of a meaningful task — and only when a reliable
usage source is actually available to you — record:

| Field | Meaning |
|---|---|
| Agent | `codex` or `claude` |
| Model | The model that actually ran, in that agent's own naming |
| Effort | Reasoning/thinking/effort setting, in that agent's own naming |
| Task ID | e.g. `BM-003`, or a `WF-` id for workflow/doc tasks |
| Task type | e.g. schema, parser, tests, docs, integration, review |
| Difficulty | Approximate: `easy` / `moderate` / `hard` |
| Start | Remaining usage (or equivalent metric) at task start |
| End | Remaining usage (or equivalent metric) at task end |
| Delta | Observed burn between the two readings |
| Result | Did the task complete cleanly? |
| Notes | Notable retries or tool churn, only if materially relevant |

### Rules

- **Never fabricate or estimate usage numbers.** If the reliable source is
  unavailable, record `unavailable` (or `unknown` for a single missing
  reading) and move on. A missing measurement is fine; an invented one
  corrupts the dataset it exists to build.
- If only the end reading was captured, record `start = unknown`,
  `end = <actual value>`, `delta = unknown`.
- Check **once near task start** and **once near task completion**. Do not
  poll repeatedly during normal work — polling burns the usage being
  measured. Repeated checks are justified only when troubleshooting usage
  behavior itself.
- Record the model and effort **actually observed**, not the ones the task
  prompt requested. If they differ, record the observed values and flag the
  discrepancy in the handoff.
- Keep each agent's terminology separate. Codex model/effort names and Claude
  model/thinking names describe different systems and must never be
  translated into each other, even when a label happens to coincide.

### Where it goes

Raw rows go in `.agent/USAGE_HISTORY.md` — one append-only table, one row per
task. Keep it compact.

Do **not** put raw usage telemetry in `BUILD_MANAGER_PROJECT_PLAN.md` or
`BUILD_MANAGER_SUPERVISOR_HANDOFF.md`. The supervisor handoff carries only
short summarized observations (e.g. "<model> <effort> completed <task>
efficiently" / "showed higher burn than expected on a comparable task").

### Known constraint

Neither the `codex` nor the `claude` CLI exposes a documented, machine-readable
quota/usage API. This was confirmed during Backup Pro and is documented in
`/Users/eengert/Documents/Kodi/tools/ai-supervisor/README.md` under
"Usage/quota detection"; the CLI help output was re-checked for this project
and still shows no such command.

The existing proven fallback in that tooling is **reactive** classification of
a finished invocation (`ai_supervisor/usage_detect.py` plus
`USAGE_EXHAUSTION_PHRASES` in `ai_supervisor/constants.py`), which sorts a run
into `yielded` / `exhausted` / `crash` / `clean` / `error`. That mechanism
detects exhaustion after the fact; it does not report remaining allowance.

Agent-specific sources that *do* report remaining allowance are documented per
agent (see `CLAUDE.md` for Claude, and "Codex-Specific Notes" below).

### If usage runs low

Follow the checkpoint procedure proven on Backup Pro
(`script.backup.pro/AGENT_WORKFLOW.md` §"Quota or Session Limits"):

1. Finish the smallest coherent unit.
2. Run targeted tests if practical.
3. Commit a checkpoint.
4. Update `.agent/HANDOFF.md` (and the usage row, if a reading is available).
5. Exit normally.

## Codex-Specific Notes

Per §32 of `BUILD_MANAGER_PROJECT_PLAN.md`, this file is the Codex instruction
file. Claude-specific instructions live in `CLAUDE.md`.

### Usage source

**None currently available.** `codex --help` lists no usage, quota, status, or
allowance command, and the Backup Pro investigation additionally checked
`codex exec --help` and `codex doctor` with the same result.

Therefore, for Codex tasks, record `start`, `end`, and `delta` as
`unavailable` in `.agent/USAGE_HISTORY.md`, and still record agent, model,
effort, task ID, type, difficulty, and result — those remain useful for
comparing outcomes even without a burn figure.

If a future Codex release adds a documented usage-introspection command, wire
it in here rather than inferring numbers from output text.

### Model / effort selection

Use Codex terminology (see §28.1 of `BUILD_MANAGER_PROJECT_PLAN.md`):

- **Routine / easy / normal work** — Luna, with XHigh or Ultra where
  appropriate.
- **Complex / reasoning-heavy / high-risk / high-value work** — Sol or Astra,
  with very high or Ultra effort.

Do not automatically lower the model tier or reasoning effort just because a
task looks easy. Higher effort often reduces retries, and the optimization
target is **lowest total cost to reach a correct result**, not lowest
per-request cost.

These names apply to Codex only. Never use them for Claude.

## Desired-State Architecture

Build Manager provisions devices to a declared desired state. It is not a
backup/restore tool. When designing or implementing features:

- Express configuration declaratively
- Apply idempotently where possible
- Do not clone device state by copying files from one device to another
- Prefer structure that makes the current desired state easy to read and diff
