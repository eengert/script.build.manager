# Test.app text entry — validated patch, not installed

Task: WF-testapp-text-entry, 2026-11-09. Advances beta item 8 by removing the demonstrated manual text-entry delay; does not qualify A15.

Reconciled `agent/codex` at `70a804388019336ee3657cae7c8fd941553ea09b`; incoming changes were limited to the four `.agent` tracking files. Product code and sealed A15 evidence are unchanged.

## Source findings

Kodi 21.3 supports `Input.SendText` through the standard keyboard used by Build Manager's `resources/lib/ui/native_dialogs.py` Create name and version inputs. The keyboard receives `GUI_MSG_SET_TEXT`; the edit control calls `SetLabel2`, replacing existing text. `done:false` leaves the keyboard open; it does not submit Create. Therefore replacing a suggested version with `1.0.0` is source-supported, but native behavior in these exact dialogs is UNVERIFIED.

Primary sources (21.3-Omega):

- https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/interfaces/json-rpc/InputOperations.cpp
- https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/guilib/GUIKeyboardFactory.cpp
- https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/dialogs/GUIDialogKeyboardGeneric.cpp
- https://github.com/xbmc/xbmc/blob/21.3-Omega/xbmc/guilib/GUIEditControl.cpp

## Candidate

`text-entry.patch` changes only MCP `src/core.js`, `src/runtime.js`, and `src/rpc.js`. `baseline.json` pins their exact installed preimages. No external files were modified.

New tool: `test_app_send_text({field:"name"|"version", text:"..."})`. It accepts only public ASCII name/version strings (1–128 characters; letters, digits, space, dot, underscore, hyphen; version must be three numeric components). No host, path, method, query or submit argument is exposed. This intentionally covers these two public Create fields only.

Caller must first call `test_app_observe`, inspect the returned exact-window screenshot, and verify the intended Build Manager keyboard. A successful screenshot grants one same-process observation valid for 30 seconds. Any subsequent operation consumes it. Before sending, fixed RPC queries require the virtual keyboard active and control 311 heading exactly `Build name` or `Version`. Other languages fail closed. Send uses `done:false`, requires `OK`, then returns a fresh exact-window screenshot. It does not click the keyboard's Done button; existing navigation is used after verifying the text. An ACK alone is not proof of the displayed value.

All existing fixed bundle, kernel process/argv/portable mode, start token, listener ownership, lock, deadline, window capture and transport request-ID checks remain in place. The existing mechanism is loopback TCP with local process/listener identity, not cryptographic or HTTP authentication. Only fixed boolean/label queries and Input.SendText are added to the internal method allowlist. Returned GUI labels are neither logged nor returned as text. Text remains transient; screenshots intentionally show the public input. Existing local peer-turnover and UI-change-between-check-and-send races remain; the queries and send are not atomic. A failed/uncertain send must be observed before any retry.

## Offline validation

Run from this worktree:

```
PYTHONDONTWRITEBYTECODE=1 python3 tools/testapp_text_entry/validate.py
```

Result: 28 focused tests PASS; 43 existing controller/transport regressions PASS. Existing regression source is read from `/Users/eengert/Documents/Kodi/tools/build-manager-testapp-mcp`; only its four-tool expectations are updated to five in the temporary copy. Tests use synthetic PNGs, fake controllers/sockets, native **selftest only**, and a stdio MCP session that lists tools and submits invalid navigation. No live identity, capture, network, launch or quit is used. Replacement test models Kodi's source-documented replacement behavior; it is not native proof. No full Build Manager suite is required for this unapplied host-control patch with unchanged product code.

## Registration boundary / native result

Authoritative MCP source is a separate project: `/Users/eengert/Documents/Kodi/tools/build-manager-testapp-mcp`. Codex executes `/Users/eengert/.codex/mcp/build_manager_testapp/src/server.js`. Current supported interface exposes only observe/navigate/launch/quit; it cannot call SendText.

Stopped at the offline-validated implementation stage as requested. Next separately authorized task must reconcile the MCP source and installed pinned baselines, apply/review this patch in that project, run its complete package tests/build, update the installed bundle, and refresh/reconnect the MCP server in Codex so tool discovery includes the fifth tool. No Codex config edit is expected because the server path is unchanged. Those external edits/install/restart were not performed.

Native smoke: NOT RUN. No public name/version was sent; Create menu, keyboard heading query, cancellation and shutdown have not been live-proven by this task. No Test.app operation was called. Final state: last known stopped per the supplied A15 context, not freshly observed here because registration-boundary instructions required stopping. A15 cannot yet proceed with proven automated typing. After registration, perform only the requested bounded public-string smoke, verify both fields in Create, cancel without confirming Create, and gracefully quit/prove stopped. No A15 retry is authorized.

Cleanup: validation temporary trees self-removed; task-generation script removed. Retained only this README, pinned baseline, unapplied patch, offline tests/runner, and append-only task tracking. Existing caches and qualification evidence were not task-created and are preserved.
