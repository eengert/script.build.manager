# Handoff — Install Review Changes Friendly Add-On Name Correction

- State: COMPLETE offline; stop before runtime qualification.
- Starting state: clean `agent/codex` at `8021d4e11a71408f5cddc1894db0c460b688304f` (36 commits ahead of `origin/agent/codex`); reviewed Install candidate `98fc27bf0966a37bc26114b0e50c077a3a3ee8ec` was an ancestor.
- Root cause: production `default_status_owners()` did not supply `name_resolver`, even though Plan and Status already consume and sanitize friendly names. Kodi Omega's `xbmcaddon.Addon(id)` requires enabled add-ons; read-only `Addons.GetAddonDetails` uses `OnlyEnabled::CHOICE_NO` and works for installed disabled add-ons.
- Done: `resources/lib/status.py` now supplies a lazy resolver that validates IDs, requests only `addonid` and `name`, fails closed on unavailable/malformed/exceptional results, and returns metadata for existing Plan/Status sanitizers. Added resolver and end-to-end tests in `tests/test_status.py` and `tests/test_plan_ui.py`. Product commit: `7118b763bc1782092acd5ec738745eeab69604ab`.
- Proof: offline JSON-RPC stub models `repository.eengert` installed with `enabled=false` and returns `Eengert Repository`; Plan row is `ENABLE` with that display name and Review Changes renders `Enable Eengert Repository`. Missing metadata still renders `Enable repository.eengert`. Production-style Status owners also return friendly names. Kodi Omega source confirms the disabled-add-on lookup behavior; this is not live runtime proof.
- Validation: `python3 -m unittest tests.test_plan tests.test_plan_ui tests.test_status tests.test_status_ui tests.test_install_workflow -q` — 281 tests PASS. `git diff --check` — clean.
- Not done: no Test.app/Kodi/profile/device access and no runtime qualification. The preserved qualification evidence and controlled disabled-state drift were not accessed or changed. Nothing was pushed, merged, released, or published.
- Smallest next step: a separate bounded portable Test.app qualification rerun against the preserved controlled drift.
- Human input: a separate task prompt must authorize/start that runtime rerun; none was needed for this offline correction.
- Usage/model/effort: usage unavailable per Codex-specific guidance; no measurements inferred.
