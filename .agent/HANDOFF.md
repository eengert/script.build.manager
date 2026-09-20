# Agent Handoff — synchronized Codex worker

## Current synchronized state

Codex is synchronized with the protected matrix at
`cfd335499123126027741f8e595489cc32b9e207`, idle, and ready for the next
supervisor assignment. This is reconciliation, not a new handoff or milestone
start; the external Agent Handoff active-worker pointer was not changed.

BM-018D compatibility support and supervisor-approved BM-018E are complete and
integrated. The production `af3-common` package contains the approved 16 typed
settings and `files: []`; typed lookup/persistence fallback and AF3 policy
boundaries remain as integrated on matrix. Disposable validation passed BM-018D
17/17 and BM-018E 14/14, with focused tests 461/461 and full suite 1463/1463.
The real Kodi profile remained read-only and no Apple TV or other device was
accessed. BM-017, BM-019, BM-020, and any next milestone were not started.

The legitimate Codex usage history is preserved without adding a duplicate
task row. Next step: await supervisor assignment.

## Historical BM-018E worker record

## Status

BM-018E is complete on `agent/codex` at implementation commit `28b8b90` and
is ready for supervisor review and normal integration. Matrix remains at
`466d431a3de0dd7b35105ef3c13ca4e0cc0058a7`; no matrix, Claude, or Antigravity
branch was changed, and no Codex-to-Agent-Handoff transition has occurred.

## Implemented

- Preserved the approved 16-setting `af3-common` package and its explicit skin
  ownership; no package values or AF3-specific mutual-exclusion policy changed.
- Added generic Kodi skin-setting compatibility for canonical/lowercase typed
  lookup, guarded `-32602` fallback, safe `Skin.SetBool`/`Skin.SetString`/
  `Skin.Reset` writes, strict effective read-back, and bounded persistence
  verification.
- Ensured successful typed JSON-RPC writes also schedule the durable skin XML
  save, because Kodi's JSON-RPC setter alone does not do so.
- Extended disposable harness bootstrap to exercise AF3's missing-on-pristine
  `Skin.*` schema entries without editing XML or copying real profile state.
- Updated AF3 portability/testing documentation with the compatibility and
  validation boundary.

## Live evidence

- `validate-skin-config`: 17/17.
- `validate-af3-package`: 14/14, including all 16 production settings,
  authoritative read-back, idempotency, drift repair, unmanaged preservation,
  ownership zero-mutation failure, restart persistence, and wrong-skin
  failure-before-mutation.
- AF3 3.2.19 plus its complete transitive closure: 18/18 installed, enabled,
  and not broken.
- BM-018A Estuary -> AF3 confirmation/activation passed after the disposable
  AF3 generated-runtime bootstrap; pristine first-ever AF3 provisioning remains
  intentionally unclaimed.
- Full unit suite: 1463/1463. Focused implementation/config/planner/harness
  tests: 461/461. `git diff --check`: clean.

## Boundaries and next step

The real Kodi profile's mtime was unchanged. No Apple TV or other device was
accessed. BM-017, BM-019, BM-020, BM-018D, and any next milestone were not
started. The existing BM-018E usage row remains exactly once; no usage numbers
were fabricated and no duplicate row was added. The smallest next step is
supervisor review, followed by the normal integration workflow if approved.
