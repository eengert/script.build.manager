# Build Manager — Project Plan

**Addon ID**: `script.build.manager`
**Repository**: `eengert/script.build.manager`
**Status**: Active — BM-001 in progress

---

## Architecture Principles

Build Manager uses **desired-state provisioning**, not backup/restore cloning.

- A *build specification* (structured declaration file) describes what a Kodi
  device should have installed and configured.
- Build Manager reads the current device state, compares it to the
  specification, and applies the delta to reach the desired state.
- Provisioning is idempotent: applying the same spec twice produces the same
  result without side effects.
- No files are cloned from one device to another. State is expressed
  declaratively, not by copying a device image.

## Target Platforms

- tvOS (Apple TV)
- Android / Shield TV
- Fire TV
- macOS (local Kodi)

## Kodi Add-on Type

Kodi program add-on (`xbmc.python.script`). Invoked on demand; no persistent
background service in early phases.

---

## Phases

### Phase 1 — BM-001: Project Skeleton *(current)*

Create the Kodi add-on scaffold without provisioning logic.

**Deliverables**:
- `addon.xml` — metadata, platform declaration, MIT license
- `default.py` — minimal entrypoint (launches safely, shows placeholder UI)
- `resources/lib/` — importable Python package
- `resources/lib/build_manager.py` — stub `BuildManager` class
- `resources/settings.xml` — placeholder settings section
- `resources/language/resource.language.en_gb/strings.po` — initial strings
- `tests/__init__.py`, `tests/test_imports.py` — basic import tests
- `changelog.md` — initial entry

**Does not include**: provisioning logic, manifest parsing, platform adapters,
network operations, or skin management.

**Acceptance**: `addon.xml` parses correctly; Python modules import outside
Kodi; `tests/test_imports.py` passes; no secrets or machine-specific paths.

---

### Phase 2 — Build Specification Format

Define and parse the declarative build specification.

- Choose format (JSON or YAML)
- Define schema: `addons`, `settings`, `profiles`, targeting
- Parser: load and validate a specification file
- Unit tests for parse/validate
- No provisioning yet; spec is read but not applied

---

### Phase 3 — Current State Reader

Read what is currently installed and configured on this device.

- Add-on inventory via Kodi JSON-RPC `Addons.GetAddons`
- Enabled/disabled state
- Key per-add-on settings (non-sensitive)
- Return a structured current-state object comparable to a spec

---

### Phase 4 — Reconciliation Engine

Diff the desired spec against the current state.

- Compute add-on install/enable/disable/remove deltas
- Compute settings-change deltas
- Produce an ordered action plan
- Unit tests against known desired/current pairs
- No provisioning yet; plan is computed but not applied

---

### Phase 5 — Provisioning Operations

Apply the action plan to provision the device.

- Install add-ons (from configured repository)
- Enable/disable add-ons
- Apply settings changes
- Idempotent: re-running the same plan produces no unnecessary actions
- Integration tests using disposable Kodi profile

---

### Phase 6 — Platform Adapters

Platform-specific handling where behavior diverges.

- tvOS: adapt for tvOS restrictions (no user-initiated installs from outside
  Kodi; limited settings paths)
- Android/Shield: standard Android Kodi behavior
- Fire TV: Fire TV-specific constraints
- macOS: local validation and development environment

Each adapter implements a shared interface; the reconciler is platform-agnostic.

---

### Phase 7 — Multi-Device Distribution

Distribute specifications to multiple devices.

- Store specs in a location reachable by all target devices
- Device selection (which spec applies to which device)
- Status reporting: which devices are current vs drifted

---

### Phase 8 — UI and Settings

Kodi UI for Build Manager.

- Main menu: spec status, apply, compare
- Settings: spec location, device identity, logging level
- Apply results screen: what changed, what failed

---

### Phase 9 — Packaging and Repository Publication

Package and publish Build Manager to `repository.eengert`.

- Whitelist-based packager (same pattern as Backup Pro)
- Repository publication via `scripts/build_repository.py`
- Public verification

---

## Implementation Rules

- Normal implementation work happens on `agent/codex` or `agent/claude`.
  Never work directly on `matrix` for implementation.
- Add or update tests for every behavior change.
- Do not touch real Kodi profiles or Apple TV devices unless the task
  explicitly authorizes a named action on a named device.
- Use disposable Kodi profiles for integration testing.
- See `AGENTS.md` for the full shared ruleset.
