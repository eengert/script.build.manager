# Current Task

- Task: Correct the remaining Install Review friendly-name defect (offline; no assigned task ID).
- State: COMPLETE; STOP after the correction, before runtime qualification.
- Starting state: clean `agent/codex` at `236fdddc18a294c5aaa436f6ef0bd16fac78bfa1`; prior product correction `7118b763bc1782092acd5ec738745eeab69604ab` present.
- Diagnosis: confirmed against Kodi JSON-RPC API v12 (Omega) schema. `Addons.GetAddonDetails.properties` references `Addon.Fields`, which allows `name` but excludes `addonid`; returned `Addon.Details.addonid` is mandatory. The old request was invalid. No runtime reproduction was performed in this task.
- Correction: changed the request to `properties: ["name"]`; retained fail-closed response identity validation (`addon.addonid` must equal the requested ID). Product commit `439ab4f8884d59b3c02a096eb1c515e5e661950e`.
- Validation: `python3 -m unittest tests.test_plan tests.test_plan_ui tests.test_status tests.test_status_ui tests.test_install_workflow -q` — 281 tests PASS. `git diff --check` — PASS. Coverage includes disabled `repository.eengert` resolving to `Eengert Repository`, error/malformed/mismatched responses failing closed, Plan review text, raw-ID fallback, and existing name sanitization.
- Not done: no Test.app, normal Kodi/profile, or device access; preserved portable controlled drift was not read or changed; no push, merge, release, publication, or runtime qualification.
- Next: stop for this task. Any portable Test.app qualification requires a separate explicit task.
- Human input: none required for this offline correction; a separate task is required before runtime qualification.
- Usage/model/effort: usage and exact model tier/effort unavailable; recorded as unavailable per Codex-specific guidance.
