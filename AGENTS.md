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

## Desired-State Architecture

Build Manager provisions devices to a declared desired state. It is not a
backup/restore tool. When designing or implementing features:

- Express configuration declaratively
- Apply idempotently where possible
- Do not clone device state by copying files from one device to another
- Prefer structure that makes the current desired state easy to read and diff
