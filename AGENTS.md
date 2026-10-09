# Agent Guidance — Build Manager

Shared rules for all coding agents (Codex, Claude, or any future agent)
working on this project. Read this before beginning any task.

## Scope

Work only on the task explicitly assigned. Do not modify files that are not
part of the current task. Do not refactor, restructure, or "clean up"
unrelated code while implementing a feature or fix.

## Outcome and task admission

Read the current milestone and its exit evidence in `.orchestrator/PROJECT.md`
and `BUILD_MANAGER_PROJECT_PLAN.md`. During macOS Beta Qualification, every
task must advance one of the seven exit items or fix a demonstrated blocker to
one. Before work, identify the project state or acceptance evidence expected
to change. Do not infer success from agent activity, reviews, bookkeeping,
or orchestration work. If a task would only rediscover an unchanged blocker,
stop unless it tests a materially different hypothesis that can produce new
evidence.

## Branch Policy

- The task prompt names the exact branch/worktree you may use. The normal
  manual working worktrees are the Agent Handoff Codex and Claude endpoints
  (`agent/codex`, `agent/claude`; see `.orchestrator/PROJECT.md`), but do not
  infer which one to use: work only in the one the prompt names.
- Normal implementation never happens directly on `matrix`.
- The `matrix` branch is protected. Do not push or merge to it unless the
  task explicitly authorizes an integration operation.
- Do not create additional branches/worktrees without explicit task authority.

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
- Run focused tests during iteration and related subsystem tests after
  meaningful changes. Run the full suite at candidate, integration,
  qualification, or release boundaries. Documentation changes, tiny harness
  edits, checkpoint transitions, and unchanged-source provenance recovery do
  not require repeated full-suite runs; preserve valid full-suite evidence when
  the candidate source is unchanged. Record the checks relevant to this task.

## End-of-task cleanup

Before reporting completion, remove ephemeral material created by the task: temporary code copies/worktrees, mutation-test scratch trees, compiler or module caches, disposable logs/JSON/text files, and screenshots/recordings that are not retained qualification evidence. Do not leave large scratch artifacts in `/private/tmp`, the repository, or evidence directories after they stop serving the task.

Preserve canonical or still-unaccepted qualification evidence, checksummed/manifesteed evidence, and the minimum screenshots/logs needed to support accepted claims. Never delete the only evidence copy and never use broad `git clean` or destructive cleanup. If classification is uncertain, keep the artifact and say so.

Every final report must include a `Cleanup` line or section stating what was removed and what non-source artifacts intentionally remain.

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
`.orchestrator/HANDOFF.md`. The project handoff (`.orchestrator/HANDOFF.md`,
maintained by ChatGPT in the manual workflow) carries only short summarized
observations (e.g. "<model> <effort> completed <task> efficiently" / "showed
higher burn than expected on a comparable task"). The historical
`BUILD_MANAGER_SUPERVISOR_HANDOFF.md` is no longer updated.

### Known constraint

Neither the `codex` nor the `claude` CLI exposes a documented, machine-readable
quota/usage API. This was confirmed during Backup Pro and again during the
historical ai-supervisor work. The retired ai-supervisor archive preserves that
investigation; Build Manager must not depend on restoring the framework merely
to inspect usage.

The former ai-supervisor project contained a reactive post-run exhaustion
classifier, but ai-supervisor is retired from the active Build Manager
workflow and must not be restored merely to collect usage telemetry.

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
