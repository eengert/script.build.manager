# BM-UI-003C helper Build Library baseline projection

Status: PASS offline implementation; live-use clearance PENDING independent review.

## Done
- Branch agent/codex; clean start 2be4c01a711c164d652511887c379bbc5919cafd.
- Substantive local commit 4ceed8bdf2ccc76abd8f4484d7615ba5fc7edb64.
- Changed tools/bm_test_app.py, tests/test_bm_test_app.py, docs/BM_TEST_APP_HELPER.md only.
- Snapshot adds fixed registry.json/selection.json allowlist and secret-blind public-v1 projection; exact schema, duplicate rejection, registry/profile cross-check, bounded safe profile identity, stable safe errors.
- No-follow pinned ancestor descriptors, regular/nonblocking bounded leaves, no envelope/private reads or writes. Missing root/registry and absent/null selection supported.
- 11 new focused test methods PASS (2.738s), covering the requested 35 scenarios with subtests; complete helper-focused suite 448 tests PASS (90.312s) with permitted macOS process/socket fixtures.
- Initial sandbox suite had expected process/socket denials plus a too-broad new audit assertion (allowed Red Light addon.xml); assertion corrected to prohibited addon_data reads before final permitted run. No protections weakened.
- Standalone disposable probes A-G PASS, repeated after substantive commit. Exact projection, envelope/overlay sentinel exclusion and unopened paths, absent selection entry/malformed registry closed, ancestor symlink refused, identical unchanged projections/bytes.
- git diff --check PASS. Helper blob a6ada3141bfaa570073f48390944396fdcc840dc.

## Not done
- No runtime qualification, live Test.app commands/access, real credentials, normal Kodi/profile, or device access. No product/shared-runtime or Keychain-wrapper changes. No push/publication/integration.
- Offline validation is implementation evidence, not independent clearance or live qualification.

## Next step / human gate
Independent review of this helper delta and renewed live-use clearance; only after PASS restart BM-UI-003C Test.app qualification from Phase 1. Eric/ChatGPT must relay that review task. Stop here.
