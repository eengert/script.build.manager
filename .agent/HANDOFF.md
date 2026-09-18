# Agent Handoff — BM-011 Merged to Matrix

**Date**: 2026-09-18
**Agent**: Claude (claude-sonnet-4-6, effort max)
**Branch**: `agent/claude` = `5bc6325` / `matrix` = `5bc6325`
**Status**: BM-011 complete and merged. Project idle. Next task: BM-012.

---

## What Was Done This Session

### Cleanup commit: `5bc6325`

Two pre-merge cleanups applied to `agent/claude`, then fast-forward merged to `matrix`.

**Cleanup 1 — Deterministic repository resolution order**:
- `_resolve_package_url` now uses `repo_ids = sorted(...)` before iterating
- "First match wins" resolution is now deterministic regardless of Kodi's
  return order for installed repositories
- Added `test_repo_order_is_lexical_regardless_of_kodi_return_order` in
  `TestRepoResolution`: both orderings of `[repository.alpha, repository.zeta]`
  yield alpha's datadir URL, confirming alpha always wins lexically
- Updated `_resolve_package_url` docstring to document the sorted order

**Cleanup 2 — Stale desired-state module documentation**:
- Updated module docstring (Desired state section) to accurately describe the
  symmetric finalization logic
- Updated architecture step 7 from "ENABLE if desired_state=enabled" to
  "FINALIZE — symmetric state enforcement: if discovered ≠ desired → SetAddonEnabled"
- Both enabled and disabled paths now documented correctly

### Merge

- `matrix` fast-forwarded from `031e405` → `5bc6325`
- No squash, no rebase, no history rewrite
- 836/836 tests confirmed on matrix post-merge

---

## BM-011 Complete — Architecture Summary

### Constrained package-install fallback (Option A)

Production `KodiRuntimeAddonBackend.invoke_install`:
1. Enumerate installed+enabled repos (sorted lexically) → check each for addon_id
2. Fetch `addons.xml` from repo's `<info>` URL → find version
3. Construct ZIP URL from `<datadir zip="true">` + standard convention
4. Download ZIP (http/https only, no credentials, 100MB cap, 30s timeout)
5. Validate ZIP (safe paths, no traversal, addon.xml present, ID/version match)
6. Staged extract → atomic rename to `special://home/addons/{addon_id}/`
7. `UpdateLocalAddons` builtin → Kodi discovers new add-on

### State finalization (symmetric)

After poll: `if info.enabled != desired_enabled: set_addon_enabled(addon_id, desired_enabled)`
Both "enabled" and "disabled" paths symmetrically enforced and verified.
Only "enabled" and "disabled" accepted; other values → FAILED before any backend call.

### Security

- Redirect safety: `_SafeRedirectHandler` rejects non-http/https, credentials, bad host
- `_build_safe_opener()` removes FileHandler (file:// blocked even on redirect)
- `_validate_url`: http/https only, no credentials, no missing host
- ZIP: safe paths, no traversal, ID match, version match

### BM-013 boundary

BM-011 finalizes state of add-ons it just installed. BM-013 handles drift
reconciliation for already-installed add-ons.

---

## Branch State

| Branch | SHA | Notes |
|--------|-----|-------|
| `matrix` | `5bc6325` | BM-011 merged |
| `agent/claude` | `5bc6325` | same |
| `agent/codex` | `a970e83` | intentionally stale, unchanged |

---

## Test Results

- 836/836 tests on both `agent/claude` and `matrix`

---

## What Is NOT Done

- BM-012 not started (dependency closure)

---

## Risks / Human Decisions Before BM-012

1. BM-012 will require understanding the full dependency graph of a target add-on.
   Recommend reviewing Kodi 21's JSON-RPC `Addons.GetDependencies` API availability
   before BM-012 is scoped.

---

## Out of Scope — Noticed

- None.

---

## Usage

Start: 5h 53% / wk 73% (claude-sonnet-4-6, max effort).
End: 5h 56% / wk 73%.
Delta: +3% / ~0%.
See USAGE_HISTORY.md for the appended row.
