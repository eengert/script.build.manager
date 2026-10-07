# Handoff — Install Review Friendly-Name JSON-RPC Correction

- State: COMPLETE offline; stop before runtime qualification.
- Starting state: clean `agent/codex` at `236fdddc18a294c5aaa436f6ef0bd16fac78bfa1`; prior product correction `7118b763bc1782092acd5ec738745eeab69604ab` was present.
- Diagnosis: Kodi JSON-RPC API v12 (Omega) schema confirms `Addons.GetAddonDetails.properties` is `Addon.Fields`; its enum permits `name` and omits `addonid`. `Addon.Details` requires `addonid`, so the old properties list was invalid. The runtime symptom came from the supplied Test.app report; this task did not access or reproduce it live.
- Done: changed only `resources/lib/status.py`, `tests/test_status.py`, and `tests/test_plan_ui.py`. The request now asks for `properties: ["name"]`; response identity validation remains fail-closed. Product commit: `439ab4f8884d59b3c02a096eb1c515e5e661950e`.
- Proof: focused tests cover disabled `repository.eengert` resolving to `Eengert Repository`, Plan rendering `Enable Eengert Repository`, raw-ID fallback when the name is absent, JSON-RPC error and malformed responses, mismatched response identity, and existing name sanitization. This is offline test evidence, not runtime qualification.
- Validation: `python3 -m unittest tests.test_plan tests.test_plan_ui tests.test_status tests.test_status_ui tests.test_install_workflow -q` — 281 tests PASS. `git diff --check` — clean.
- Not done: no Test.app, Kodi/profile, or device access. The previously reported portable controlled drift (`repository.eengert`, version `1.0.0`, disabled) was not accessed or changed; it was not independently re-read in this task. Nothing was pushed, merged, released, or published.
- Smallest next step: stop. A separate task is needed for any later portable Test.app qualification.
- Human input: none needed for this offline correction; separate authorization is required before runtime qualification.
- Usage/model/effort: usage source and exact model tier/effort unavailable; no values inferred.
