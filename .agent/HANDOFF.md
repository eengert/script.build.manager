# Agent Handoff — BM-020A1 integrated

## BM-020A1 integration complete

BM-020A1 is complete, supervisor-approved, and integrated on protected
`matrix`; the matrix state is neutral with `active_agent: none`. The
substantive integration commit is `e0c8536` (`feat(BM-020A1): integrate action
ownership prerequisites`). Worker-specific Codex metadata was not copied.

The supported add-on states are `enabled` and `disabled`; omission is
unmanaged; `absent` is rejected with the public-Kodi-API limitation; and
`ENSURE_ABSENT` is removed. Required dependency closure is owned by the target
install operation, preflighted before mutation, and returned as a nested
aggregate result. Explicit desired-disabled required dependencies fail closed,
dependency failures prevent target installation, optional dependencies remain
optional, and BM-019 restart requirements propagate through the nested result.

Validation from the integrated tree: focused tests **988/988**, full suite
**1462/1462**, and `git diff --check` clean. The real Kodi profile, Apple TV,
and all devices remained untouched. BM-020A production executor work,
BM-020B/C, BM-017, and later milestones remain unstarted.

## Prior integrated state

## BM-019 integration complete

BM-019 is complete and integrated on protected `matrix`; the matrix state is
neutral with `active_agent: none`. The substantive integration commit is
`202f41d` (`feat(BM-019): integrate restart requirement aggregation`).

The typed contract exposes `NONE` and `KODI_RESTART`. Operation results declare
requirements locally, and central aggregation retains only the strongest
successful changed requirement. Idempotent/no-change operations do not create
restart requirements. Failed/uncommitted operations do not establish one, and
a later failure cannot erase an earlier successful requirement. The planner
does not infer restart requirements from action kinds.

`docs/RESTART_REQUIREMENTS.md` documents the contract and the BM-019/BM-020
boundary. BM-018D/BM-018E paths remain `NONE`; no current production operation
legitimately requires restart, so no synthetic live restart scenario was run.
BM-020 restart execution, transaction persistence, and resume/re-entry remain
unstarted.

Validation from the integrated tree: focused tests **813/813**, full suite
**1476/1476**, and `git diff --check` clean. The real Kodi profile and all
devices remained untouched.

## Prior integrated state

## Current matrix state — BM-018D compatibility extension + BM-018E

**Status**: Complete, supervisor-approved, and integrated on `matrix`.
`active_agent = none`; no worker identity or Agent Handoff pointer was copied
into the matrix state.

Integrated substantive commit: `1c024e9` —
`feat(BM-018E): integrate AF3 compatibility and package`.

- The approved `af3-common` package contains exactly 16 reviewed bool/string
  targets and `files: []`.
- Generic Kodi skin-setting compatibility handles canonical-to-lowercase
  access, guarded fallback after double `-32602`, safe Skin.* persistence,
  strict typed/effective read-back, and bounded persistence verification.
- XML remains eligibility/persistence evidence only; it is not the effective
  runtime backend.
- AF3 mutual-exclusion validation remains in the AF3-specific policy layer;
  BM-018A confirmation behavior is unchanged.
- BM-018D disposable validation passed 17/17; BM-018E production validation
  passed 14/14; the AF3 dependency closure was 18/18 healthy; focused tests
  passed 461/461; and the full suite passed 1463/1463.
- The JSON-RPC setter persistence quirk is handled generically. AF3's
  first-run generated-state bootstrap is disposable-only, so pristine
  first-ever AF3 provisioning remains intentionally unclaimed.
- The real Kodi profile remained read-only. No Apple TV or other device was
  accessed. BM-017, BM-019, BM-020, and no next milestone were started.

The existing WF-002 handoff record follows as historical integration context.

**Status**: WF-002 is complete and supervisor-approved. The helper and tests
are integrated on matrix; `active_agent = none` and matrix awaits the next
assignment.

## What was done

- Implemented `tools/antigravity-usage` helper around `/usr/local/bin/codexbar`:
  - Queries `provider = antigravity`, `source = auto`, JSON format, no-color.
  - Parses and preserves named rate windows from `usage.extraRateWindows`
    (e.g., "Gemini weekly" and "Claude/GPT weekly") without collapsing them.
  - Preserves account email, source, login method, and reset descriptions.
  - Calculates remaining percent strictly as `100.0 - usedPercent`.
  - Fails closed with normalized, sanitized unavailable result on error or missing data.
  - Supports `--human` summary output and JSON output.
- Created `tests/test_antigravity_usage.py` covering:
  - Multi-window parsing and distinct Gemini vs. Claude/GPT pool separation.
  - Remaining percentage calculation.
  - Fallback to primary/secondary windows if extraRateWindows is absent.
  - Error handling: malformed JSON, command exit code, missing binary, timeout,
    missing provider record, missing usage section, sanitized error output.
  - All 11/11 tests pass.
- Updated `AGENTS.md` with Antigravity-Specific Notes documenting the authoritative
  command, helper usage, distinct pool preservation, and usage conventions.
- Updated `.agent/USAGE_HISTORY.md` with task convention note and WF-002 row.
- Updated `.agent/AGENT_STATUS.json` and `.agent/CURRENT_TASK.md`.

## Validation

- Focused tests: `python3 -m unittest tests/test_antigravity_usage.py` — 11/11 passing.
- Live read-only smoke test: attempted; current CodexBar invocation timed out.
  The helper returned a sanitized unavailable result and exposed no raw stderr
  or private account data.
- `git diff --check`: passed cleanly.
- Real Kodi profile untouched; no Apple TV access; no BM milestone work started.

## Prior BM-018D boundary

- BM-018D remains complete: 17/17 disposable AF3 live checks and 1438/1438
  full tests were previously recorded.
- No production `af3-common` package was created.
- BM-018E, BM-017, BM-019, and BM-020 were not started.
- Real Kodi profile remained read-only; no Apple TV access occurred.

## WF-002 usage record

The Antigravity worker's measured WF-002 usage row is preserved exactly once
in `.agent/USAGE_HISTORY.md`; no Codex usage figures were fabricated.

Next task awaits supervisor assignment.
