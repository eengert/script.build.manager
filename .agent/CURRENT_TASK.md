# Current Task

## Worker State — synchronized with current matrix

**Agent**: Claude
**Branch**: `agent/claude`
**Status**: Synchronized and idle; no Agent Handoff has occurred.

Current protected matrix: `466d431a3de0dd7b35105ef3c13ca4e0cc0058a7`.

Current matrix includes the approved WF-002 helper, tests, and guidance. The
helper preserves
distinct named Gemini and Claude/GPT pools, account/source/login metadata when
available, and sanitized bounded failure results.

Focused tests: 11/11 passing. The live helper smoke test was attempted
read-only; the current CodexBar invocation timed out and the helper returned
the sanitized unavailable result without exposing stderr or private data.

Integrated substantive commits:

- `28a6fd4` — `feat(BM-018D): add typed skin configuration support`
- `5a3cc9a` — `fix(BM-018D): resolve AF3 disposable live gate`

BM-018D generic typed skin-setting support is complete. The disposable AF3
live gate passed 17/17 and the full suite passed 1438/1438. The disposable
environment must install, enable, and verify the complete AF3 dependency
closure, with no dependency broken. AF3's first-run generated-state
initialization caused the original transient fallback; the harness performs
that generated-runtime bootstrap only inside `.kodi-test`, then validates the
actual BM-018A Estuary -> AF3 confirmation/activation path. Completely
pristine first-ever AF3 provisioning is not overstated as proven.

AF3 key normalization and non-boolean string-setter return handling are
implemented in the skin backend/runtime adaptation. AF3-specific mutual
exclusion policy remains isolated from the generic backend.

- Focused BM-018D tests: 765/765 passing.
- Full suite: 1438/1438 passing.
- `git diff --check`: passing.
- Real Kodi profile remained read-only; no Apple TV access occurred.
- No production `af3-common` package was created.
- BM-018E, BM-017, BM-019, and BM-020 were not started.

Claude is ready for a future assignment. Do not claim a new handoff or revive
BM-016 as current work. BM-018E remains a Codex worker task and is not being
worked by Claude.
