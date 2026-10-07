# Current Task

- Task: Correct the runtime-discovered friendly add-on name defect in Install Review Changes (offline only; no assigned task ID).
- State: COMPLETE; STOP before runtime qualification.
- Starting state: clean `agent/codex` at `8021d4e11a71408f5cddc1894db0c460b688304f`; reviewed candidate `98fc27bf0966a37bc26114b0e50c077a3a3ee8ec` was an ancestor.
- Root cause: production `default_status_owners()` omitted `name_resolver`; Plan and Status therefore kept their correct raw-ID fallback. Kodi Omega's `xbmcaddon.Addon(id)` rejects disabled add-ons, so the resolver uses read-only `Addons.GetAddonDetails` JSON-RPC, which includes disabled installed add-ons.
- Correction: added the lazy fail-closed production resolver and focused Status/Plan/Review Changes coverage; product commit `7118b763bc1782092acd5ec738745eeab69604ab`.
- Validation: 281 requested focused tests PASS; `git diff --check` PASS. Source/test evidence only; no runtime qualification.
- Not done: no Test.app, normal Kodi, profile, evidence-folder, or device access; no push, merge, release, or publication.
- Next: run a separately bounded portable Test.app qualification rerun against the intentionally preserved `repository.eengert` disabled-state drift.
- Human input: a separate task prompt is required before runtime qualification; no input was needed for this offline correction.
- Usage/model/effort: unavailable per Codex-specific guidance in `AGENTS.md`; no usage values inferred.
