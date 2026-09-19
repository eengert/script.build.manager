# Current Task

## BM-018A correction — verified Kodi skin activation

**Agent**: Codex
**Branch**: `agent/codex`
**Status**: complete; pending supervisor handoff

Corrected the two supervisor-identified runtime blockers: skin selection now
uses strict Settings JSON-RPC, and confirmation is observed before SendClick(11)
with bounded close/final-state verification. BM-017 was not started.

Next action: supervisor review and integration decision.
