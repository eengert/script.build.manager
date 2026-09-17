# Build Manager — Project Plan

## 1. Project Identity

**Name:** Build Manager  
**Kodi add-on ID:** `script.build.manager`  
**Repository:** Eric's `eengert` Kodi repository  
**Primary purpose:** Provision, configure, update, repair, and reconcile Eric's personal Kodi builds across multiple device types.

### Supported target platforms

- Apple TV / tvOS
- Nvidia Shield Pro / Android TV
- Fire TV / Fire OS
- macOS

Future platforms may be supported if they require little additional complexity, but Build Manager is initially a personal tool rather than a general-purpose public build framework.

---

# 2. Project Goal

Build Manager should make it possible to take a fresh Kodi installation and rapidly transform it into one of Eric's desired Kodi configurations.

The target experience is:

```text
Fresh Kodi
    ↓
Install eengert repository
    ↓
Install Build Manager
    ↓
Launch Build Manager
    ↓
Choose device/profile
    ↓
Install / Reconcile Build
    ↓
Repositories installed
Add-ons installed
Dependencies enabled
Skin installed/configured
Portable settings applied
Device-specific settings applied
Portable account state restored where safe
    ↓
Restart/reload Kodi as necessary
    ↓
Validation
    ↓
Ready to use
```

Build Manager should also work on an existing installation:

```text
Existing Kodi
    ↓
Build Manager
    ↓
Compare actual state with desired state
    ↓
Install missing components
Update changed configuration
Disable/remove unwanted components
Repair drift
    ↓
Validate
```

The long-term objective is therefore not merely "install my Kodi build."

It is:

> Maintain a declarative desired Kodi configuration across multiple heterogeneous devices.

---

# 3. Design Philosophy

Build Manager should follow several principles learned from Backup Pro.

## 3.1 Desired state instead of captured state

Backup Pro answers:

> What did this Kodi installation look like when it was backed up?

Build Manager answers:

> What should this Kodi installation look like now?

This distinction should drive the architecture.

## 3.2 Declarative configuration

The desired Kodi setup should be defined through manifests and configuration packages rather than hardcoded throughout the Python implementation.

Example:

```yaml
build:
  id: eric-main
  version: 1.0.0

skin:
  addon: skin.arctic.fuse.3

addons:
  - plugin.video.redlight
  - plugin.video.themoviedb.helper

profiles:
  apple_tv:
    disable:
      - example.android.only

  shield:
    enable:
      - example.android.only
```

The exact serialization format can be JSON, YAML, or another suitable format. JSON may initially be preferable because it is built into Python and requires no additional dependency.

## 3.3 Idempotency

Running Build Manager repeatedly should be safe.

If the device already matches the desired configuration:

```text
Build is current.
No changes required.
```

It should not unnecessarily overwrite settings or reinstall components.

## 3.4 Reconciliation

Build Manager should compare:

```text
Desired State
      vs.
Actual Kodi State
```

and calculate required operations.

Example:

```text
+ Install plugin.video.foo
+ Enable plugin.video.bar
~ Update AF3 configuration
- Disable plugin.video.baz
✓ Red Light already current
✓ Repository already installed
```

## 3.5 Platform-aware behavior

Never assume tvOS, Android/Fire OS, and macOS behave identically.

Platform-specific behavior should live behind explicit abstractions or profile rules rather than scattered conditional statements.

## 3.6 Conservative file management

Only files explicitly owned or managed by Build Manager should be altered.

Unknown Kodi files should remain untouched.

## 3.7 Verification over assumption

Every significant operation should have a corresponding validation mechanism.

For example:

```text
Install addon
→ verify addon exists
→ verify enabled state
```

or:

```text
Apply AF3 configuration
→ rebuild/reload skin
→ verify managed settings/files
```

---

# 4. Scope

## MVP Scope

The first useful Build Manager release should support:

- Build manifest loading
- Platform detection
- Device/profile selection
- Repository installation
- Add-on installation
- Add-on dependency enablement
- Add-on enable/disable state
- AF3 installation
- Controlled AF3 configuration deployment
- Portable add-on settings deployment
- Kodi settings deployment where appropriate
- Build version tracking
- Installation/reconciliation plan
- Restart/reload orchestration
- Post-install verification
- Useful logs
- Safe failure reporting

The MVP does **not** need:

- A visual build designer
- Public/community build support
- Arbitrary third-party builds
- Remote fleet management
- Automatic synchronization between Kodi devices
- A desktop companion application
- Cloud account infrastructure
- Sophisticated secrets management server
- Backup functionality duplicating Backup Pro
- Automatic rollback of every conceivable Kodi change

Those can be reconsidered only if real usage demonstrates a need.

---

# 5. Proposed Architecture

```text
script.build.manager
│
├── Build Manager Engine
│
├── Manifest Parser
│
├── State Inspector
│
├── Planner / Reconciler
│
├── Operation Executor
│
├── Platform Adapter
│
├── Configuration Manager
│
├── Add-on Manager
│
├── Skin Manager
│
├── Authentication/Secrets Layer
│
├── Validator
│
├── Restart Coordinator
│
└── Kodi UI
```

The core workflow:

```text
Manifest
   ↓
Resolve profile
   ↓
Inspect current Kodi state
   ↓
Calculate desired state
   ↓
Create operation plan
   ↓
Execute operations
   ↓
Restart/reload if necessary
   ↓
Validate
   ↓
Report result
```

---

# 6. Repository Structure

Recommended source structure:

```text
script.build.manager/
├── addon.xml
├── icon.png
├── fanart.jpg
├── changelog.txt
├── default.py
│
├── resources/
│   ├── lib/
│   │   ├── build_manager/
│   │   │   ├── __init__.py
│   │   │   ├── manifest.py
│   │   │   ├── planner.py
│   │   │   ├── executor.py
│   │   │   ├── state.py
│   │   │   ├── addons.py
│   │   │   ├── dependencies.py
│   │   │   ├── config.py
│   │   │   ├── skin.py
│   │   │   ├── platform.py
│   │   │   ├── restart.py
│   │   │   ├── validator.py
│   │   │   ├── secrets.py
│   │   │   └── logging.py
│   │   │
│   │   └── ui/
│   │
│   ├── builds/
│   │   ├── eric-main.json
│   │   └── profiles/
│   │       ├── apple-tv.json
│   │       ├── shield.json
│   │       ├── fire-tv.json
│   │       └── mac.json
│   │
│   └── settings.xml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── kodi/
│
├── tools/
│   └── kodi_test.py
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── MANIFEST.md
│   ├── TESTING.md
│   ├── SECURITY.md
│   └── AGENT_WORKFLOW.md
│
├── BUILD_MANAGER_PROJECT_PLAN.md
├── BUILD_MANAGER_SUPERVISOR_HANDOFF.md
├── CLAUDE.md
└── AGENTS.md
```

Exact structure may evolve, but responsibilities should remain separated.

---

# 7. Build Definition Architecture

Build data should be separated into layers.

```text
Base Build
   +
Platform Profile
   +
Device Profile
   +
Optional Components
   +
Personal Configuration
   +
Optional Secrets
   =
Desired Device State
```

## Base Build

Contains settings common to virtually all devices:

- Repositories
- AF3
- Red Light
- TMDb Helper
- POV
- Umbrella
- common helper add-ons
- common Kodi settings
- common AF3 configuration
- common widgets

## Platform Profile

Examples:

```text
tvOS
Android
Fire OS
macOS
```

Controls platform-specific behavior.

## Device Profile

Examples:

```text
bonus-room
family-room
shield
travel-firestick
macbook
```

A device profile should override only what differs from the common build.

Example:

```json
{
  "id": "bonus-room",
  "extends": "apple-tv",
  "disable_addons": [
    "plugin.video.example"
  ]
}
```

---

# 8. Add-on Management

Build Manager should know how to:

- Detect whether an add-on exists
- Detect its version
- Determine enabled/disabled state
- Install from configured repositories
- Enable dependencies
- Disable unwanted add-ons
- Determine whether restart is required
- Validate resulting state

Whenever possible, Build Manager should allow Kodi's normal add-on/repository mechanisms to install binaries and platform-dependent packages.

Avoid shipping copies of arbitrary add-ons inside the build unless necessary.

---

# 9. Dependency Handling

Reuse the lessons from Backup Pro's dependency-closure work.

Given a set of desired add-ons:

```text
A
B
C
```

Build Manager should compute or resolve the required dependency closure:

```text
A
├── X
└── Y
    └── Z
```

and ensure required dependencies are enabled.

The implementation should:

1. Identify required dependencies.
2. Traverse transitively.
3. Detect missing dependencies.
4. Enable required installed dependencies.
5. Allow Kodi to resolve installable repository dependencies.
6. Validate the resulting closure.

Circular dependency protection is required.

---

# 10. Skin Management

AF3 will initially be the managed skin.

Skin handling should be abstract enough that AF3 can later be replaced.

Responsibilities:

- Install desired skin
- Apply managed configuration
- Activate skin
- Handle Kodi's skin confirmation behavior
- Rebuild/reload skin where necessary
- Verify activation
- Verify managed configuration

Backup Pro's discovery that Kodi's skin confirmation can require deterministic interaction should inform implementation.

Do not assume calling `Skin.SetSkin()` alone means the skin change persisted.

---

# 11. Managed Configuration

Build Manager should classify files/settings into:

### Managed

Build Manager owns these values.

Example:

```text
AF3 menu definitions
specific widget configuration
selected Red Light preferences
common Kodi preferences
```

### Unmanaged

Build Manager should leave these alone.

Example:

```text
runtime caches
Kodi logs
temporary databases
generated thumbnails
device-local state
```

### Partially managed

Build Manager owns selected fields but not the entire file.

This will probably be important for settings XML files.

Prefer structured modifications where practical rather than replacing whole files.

---

# 12. Authentication and Secrets

Secrets must be considered separately from ordinary configuration.

Never commit personal account credentials or authorization tokens to the public `eengert` Kodi repository.

Classify authentication state by service.

Example:

```text
Service          Portable?       Strategy
------------------------------------------------
Red Light config Yes             Deploy
Debrid token     Investigate     Private overlay
Trakt            Investigate     Possibly reauthorize
EasyNews         Investigate     Private overlay
Other OAuth      Investigate     Service-specific
```

## Recommended design

```text
Public Build
    +
Private Personal Overlay
```

The public package contains no secrets.

A separate optional local/private package can contain portable credentials if testing establishes that copying them is safe.

Build Manager should also be capable of displaying:

```text
Authorization Required

✓ Real-Debrid
○ Trakt
✓ EasyNews
```

rather than treating reauthorization as an installation failure.

---

# 13. Security Requirements

Build Manager has permission to alter a Kodi installation and therefore needs explicit safety controls.

Required safeguards:

- No shell execution unless absolutely necessary.
- No arbitrary command execution from manifests.
- Validate all manifest paths.
- Prevent path traversal.
- Restrict writes to approved Kodi directories.
- Never log credentials or tokens.
- Sanitize diagnostic bundles.
- Never overwrite unknown files solely because their directory is managed.
- Validate downloaded artifacts where possible.
- Fail closed on malformed manifests.
- Keep destructive operations explicit.

Potential destructive operations should be represented clearly:

```text
INSTALL
UPDATE
ENABLE
DISABLE
DELETE
REPLACE
```

Deletion should be uncommon in early versions.

---

# 14. Build Installation Workflow

Proposed sequence:

```text
1. Load manifest
2. Validate manifest
3. Detect Kodi/platform/version
4. Resolve device profile
5. Inspect installed state
6. Generate execution plan
7. Show plan
8. Install repositories
9. Install required add-ons
10. Resolve/enable dependencies
11. Apply common configuration
12. Apply platform configuration
13. Apply device configuration
14. Apply portable auth state if configured
15. Activate/configure skin
16. Reload/restart Kodi if required
17. Resume install after restart if needed
18. Validate desired state
19. Store installed build version
20. Display result
```

Long operations should persist sufficient state to survive a Kodi restart.

---

# 15. Reconciliation / Repair Mode

Build Manager should eventually provide:

```text
Install Build
Update Build
Repair Build
View Status
```

Repair should calculate differences without blindly reinstalling everything.

Example:

```text
Build Manager Status

Build: Eric Main
Installed: 1.2.0
Desired: 1.3.0

✓ 23 add-ons correct
✓ AF3 active
~ Red Light configuration differs
+ 1 add-on missing
- 1 add-on should be disabled

Repair?
```

---

# 16. Versioning

Use semantic versioning for Build Manager itself:

```text
0.1.0
0.2.0
1.0.0
```

Build definitions should have their own version independent of the add-on.

Example:

```text
Build Manager: 0.4.2
Eric Build:    1.7.0
```

This distinction is important.

A new build configuration should not require a new Build Manager release unless engine functionality changed.

---

# 17. Testing Strategy

The testing approach should borrow heavily from Backup Pro.

## Unit tests

Cover:

- Manifest parsing
- Merge/override rules
- State comparison
- Operation planning
- Dependency traversal
- Platform detection
- Configuration transforms
- Validation rules
- Security/path handling

Most business logic should be testable without Kodi.

## Integration tests

Use mocked/stubbed Kodi APIs where practical.

Test complete workflows such as:

```text
blank state
→ desired state
→ plan
→ execute
→ validate
```

## Disposable Kodi profile

Reuse the Backup Pro philosophy around `tools/kodi_test.py`.

Desired commands may eventually include:

```text
reset
install
install-dependencies
configure
enable-webserver
launch
restart
stop
prepare-validation
apply-build
validate-build
```

Do not force all of these commands into the first milestone.

## Live platform validation

At minimum test:

### macOS
Primary rapid-development target.

### Apple TV
Important because tvOS behavior differs significantly from desktop Kodi.

### Nvidia Shield Pro
Primary Android target.

### Firestick
Validate after Android behavior stabilizes.

---

# 18. Golden Validation Scenarios

Maintain deterministic scenarios.

## Scenario A — Fresh Kodi

```text
Fresh Kodi
→ Build Manager
→ Install Eric Build
→ Restart
→ Validate
```

Expected:

- desired skin active
- expected add-ons installed
- expected add-ons enabled/disabled
- common configuration present
- no unexpected errors

## Scenario B — Partial installation

Start with:

```text
AF3 installed
Red Light missing
TMDb Helper disabled
old config
```

Run Build Manager.

Expected:

```text
Red Light installed
TMDb Helper enabled
configuration updated
AF3 preserved
```

## Scenario C — Already current

Run on a correctly configured installation.

Expected:

```text
No changes required
```

## Scenario D — Drift

Modify one managed setting manually.

Expected:

```text
Build Manager detects drift.
Repair restores desired value.
```

## Scenario E — Platform overlay

Apply the same base build to Apple TV and Shield.

Verify profile differences.

---

# 19. Volatile / Generated State

Apply one of the biggest Backup Pro lessons early:

Do not validate everything by raw file checksum.

Some Kodi and add-on files are generated or rewritten during normal operation.

Build Manager validation should distinguish:

```text
Semantic state
vs.
Raw byte-for-byte state
```

Where possible validate:

- setting values
- enabled state
- installed version
- selected skin
- existence of managed records

rather than entire generated files.

---

# 20. Restart Orchestration

Restart handling should be designed early rather than bolted on later.

Operations should be able to declare:

```text
NONE
SKIN_RELOAD
KODI_RESTART
```

The planner should aggregate requirements.

Example:

```text
Install addon       NONE
Change AF3 config   SKIN_RELOAD
Change skin         KODI_RESTART
```

Only perform the strongest required action once.

Build Manager should persist progress before restart and resume deterministically afterward.

---

# 21. Backup Pro Relationship

Build Manager should be a separate add-on.

Do not turn Backup Pro into Build Manager.

However, reusable concepts or code may be extracted where appropriate.

Potential shared areas:

- Kodi JSON-RPC helpers
- dependency traversal
- add-on enabling
- platform detection
- restart orchestration
- AF3 handling
- validation helpers
- sanitized logging

Avoid directly coupling Build Manager to Backup Pro unless there is a compelling benefit.

Build Manager should be able to operate when Backup Pro is not installed.

---

# 22. Development Workflow

The project should use the same supervisor-driven multi-agent model that worked well for Backup Pro.

Participants:

```text
ChatGPT
    Project supervisor / architect / reviewer

Codex
    Coding agent

Claude Code
    Coding agent
```

Neither coding agent should be treated as the permanent owner of a subsystem.

Tasks should be assigned based on:

- current context
- task complexity
- available quota
- observed model performance
- risk
- required reasoning depth

---

# 23. Supervisor Responsibilities

The ChatGPT supervisor should:

- maintain project architecture
- choose the next highest-value task
- prevent unnecessary scope growth
- review agent results
- compare implementation against requirements
- detect potentially dangerous actions
- assign validation work
- decide when independent second-agent review is warranted
- maintain project handoff context
- track unresolved issues
- prevent Codex and Claude from working on overlapping files without coordination
- decide when to commit/release
- recommend model and reasoning effort

The supervisor should **not** micromanage implementation line-by-line unless necessary.

---

# 24. Agent Task Design

Tasks should be bounded.

Good:

> Implement manifest parsing and profile inheritance. Do not modify execution logic. Add unit tests covering base manifest, platform override, device override, malformed profile, and unknown parent.

Bad:

> Build the manifest system, installer, profiles, and UI.

Each task should define:

```text
Goal
Scope
Out of scope
Relevant files
Acceptance criteria
Required tests
Safety constraints
Expected handoff
```

---

# 25. Codex / Claude Task Prompt Template

```text
PROJECT: Build Manager

TASK:
<single bounded objective>

GOAL:
<desired outcome>

IN SCOPE:
- ...
- ...

OUT OF SCOPE:
- ...
- ...

CONSTRAINTS:
- Do not alter unrelated files.
- Do not perform destructive operations on real Kodi profiles.
- Use disposable test profiles for integration testing.
- Preserve existing behavior.
- Add/update tests.

ACCEPTANCE CRITERIA:
1. ...
2. ...
3. ...

VALIDATION:
Run:
<commands>

HANDOFF:
Report:
- files changed
- implementation summary
- tests run/results
- unresolved concerns
- recommended next step
```

---

# 26. Agent Handoff Format

Each task should end with a compact structured handoff.

```text
## Result

Completed:
- ...

Files changed:
- ...

Tests:
- 48 passed

Validation:
- ...

Risks / unresolved:
- ...

Suggested next task:
- ...
```

Avoid long narrative handoffs unless something unusual occurred.

---

# 27. Cross-Agent Review

Use the second coding agent when:

- security-sensitive behavior changes
- destructive file operations are introduced
- restart/resume logic changes
- manifest semantics change
- credential handling changes
- large refactors occur
- a stubborn bug survives multiple attempts
- the primary agent expresses uncertainty

Typical pattern:

```text
Codex implements
      ↓
Claude reviews

or

Claude implements
      ↓
Codex reviews
```

The reviewer should inspect code rather than simply trust the previous agent's summary.

---

# 28. Model / Effort Strategy

Continue the empirical strategy developed during Backup Pro.

The optimization goal is:

> Lowest total cost to reach a correct result.

Not:

> Lowest model tier or lowest reasoning setting per request.

Track observed performance over time and adjust recommendations separately for Codex and Claude Code.

## 28.1 Codex

### Routine/easy coding

Default:

**Luna — XHigh or Ultra**

Examples:

- adding tests
- straightforward parser changes
- UI labels
- small refactors
- documentation
- clear bugs with known cause

Do not automatically lower reasoning effort simply because the task is easy.

Higher effort can reduce retries and total usage.

### Complex/high-risk work

Prefer:

**Sol or Astra — Ultra / very-high reasoning**

Examples:

- reconciliation architecture
- dependency-resolution design
- restart/resume state machine
- secrets handling
- cross-platform filesystem behavior
- security review
- difficult state bugs
- destructive-operation safeguards

## 28.2 Claude Code

Choose between **Sonnet** and **Opus** based on task complexity, risk, and observed efficiency. Use Claude's available thinking/reasoning settings rather than Codex effort names.

### Routine/easy to moderately complex coding

Prefer:

**Sonnet** with a high or maximum practical thinking/reasoning setting when additional reasoning is likely to reduce retries.

Examples:

- repository/bootstrap work
- straightforward implementation tasks
- tests
- bounded refactors
- documentation
- clear bug fixes

### Complex/high-risk work

Prefer:

**Opus** with an appropriately high thinking/reasoning setting when the task materially benefits from deeper reasoning.

Examples:

- reconciliation architecture
- restart/resume state-machine design
- security-sensitive changes
- authentication/secrets handling
- difficult cross-platform bugs
- large architectural refactors
- independent review of high-risk changes

Do not use Codex model names or effort terminology when recommending Claude Code settings.

---

# 29. Parallel Work Rules

Codex and Claude may work concurrently only when scopes do not overlap.

Good:

```text
Codex:
manifest parser

Claude:
test harness improvements
```

Risky:

```text
Codex:
planner.py

Claude:
planner.py
```

If overlapping work is necessary, serialize the tasks.

One agent should finish, commit/handoff, then the next reviews or extends it.

---

# 30. Source Control Workflow

Recommended initially:

```text
main
```

plus short-lived task branches if useful.

Examples:

```text
feature/manifest-parser
feature/reconciler
fix/skin-activation
test/android-profile
```

Avoid complex Git-flow-style branching.

Every logical milestone should produce a clean commit.

Commit messages:

```text
feat: add build manifest parser
feat: reconcile addon enabled state
fix: persist install progress across restart
test: add AF3 activation validation
docs: document device profile schema
```

---

# 31. Agent Safety Rules

Codex and Claude should never:

- modify Eric's real Kodi profile unless explicitly authorized
- delete Kodi userdata outside a disposable profile
- publish secrets
- commit credentials
- force-push without explicit instruction
- rewrite Git history casually
- modify unrelated repositories
- install arbitrary system packages without justification
- alter macOS system configuration unnecessarily

Testing should default to disposable Kodi environments.

---

# 32. Project Context Files

Maintain these files from early development.

## `BUILD_MANAGER_PROJECT_PLAN.md`

This document.

Stable architectural/project guidance.

## `BUILD_MANAGER_SUPERVISOR_HANDOFF.md`

Living project state.

Should contain:

```text
Current version
Current architecture
Completed milestones
Current branch/commit
Known issues
Recent discoveries
Next recommended tasks
Important commands
Testing status
Agent/model usage observations
```

This is the primary file used when starting a new supervisor chat.

## `AGENTS.md`

Instructions intended for Codex and other coding agents.

## `CLAUDE.md`

Claude-specific working instructions if useful.

---

# 33. Supervisor Handoff Discipline

The supervisor handoff should not become a chronological diary.

Keep:

- current truth
- architectural decisions
- unresolved issues
- commands still relevant
- current tests
- next actions

Remove:

- obsolete debugging trails
- abandoned hypotheses
- superseded implementation details

The objective is to minimize context cost while preserving operational knowledge.

---

# 34. Logging

Build Manager logs should be concise but diagnostically useful.

Example:

```text
[BUILD] Loading eric-main 1.2.0
[PROFILE] shield
[PLAN] 4 operations required
[ADDON] Installing plugin.video.redlight
[ADDON] Enabling script.module.example
[CONFIG] Applying AF3 managed settings
[SKIN] Activating skin.arctic.fuse.3
[VERIFY] 17/17 checks passed
[BUILD] Complete
```

Sensitive values must be redacted.

Avoid logging entire configuration files unless sanitized.

---

# 35. Diagnostic Bundle

Later releases may provide:

```text
Export Diagnostic Bundle
```

Include:

- Build Manager version
- build version
- Kodi version
- detected platform
- operation plan
- validation results
- sanitized Build Manager log
- relevant sanitized Kodi log excerpts

Never include authentication secrets.

The sanitization lessons from Backup Pro should be applied from the beginning.

---

# 36. UI Strategy

Keep the UI deliberately simple.

Initial menu:

```text
Build Manager

Install Build
Update / Repair Build
Build Status
Settings
```

Profile selection:

```text
Select Device Profile

Apple TV — Bonus Room
Apple TV — Family Room
Nvidia Shield Pro
Fire TV
MacBook
```

Do not spend early development effort creating a highly graphical interface.

Functionality and reliability come first.

---

# 37. Phase Plan

## Phase 0 — Research / Prototype

Goal:

Prove the important assumptions before building substantial infrastructure.

Tasks:

1. Inspect portable Kodi configuration.
2. Test Red Light `addon_data`.
3. Test account authorization portability.
4. Determine AF3 configuration subset.
5. Identify platform-specific differences.
6. Decide manifest schema.
7. Create disposable Build Manager test environment.

Exit criteria:

We know which state is safe and useful to provision.

---

## Phase 1 — Core Engine

Implement:

- manifest parser
- profile merging
- platform detection
- state inspector
- desired-state representation
- operation planner

No significant Kodi mutation initially.

Example output:

```text
Desired:
AF3 installed
Red Light installed
POV disabled

Current:
AF3 installed
Red Light missing
POV enabled

Plan:
INSTALL Red Light
DISABLE POV
```

Exit criteria:

Planning logic is deterministic and thoroughly unit tested.

---

## Phase 2 — Add-on Provisioning

Implement:

- repository detection
- repository installation
- add-on installation
- add-on enable/disable
- dependency closure
- validation

Exit criteria:

A disposable Kodi profile can be provisioned with the desired add-on set.

---

## Phase 3 — Configuration Deployment

Implement:

- common configuration
- platform overlays
- device overlays
- structured settings merge
- managed-file policy

Exit criteria:

A clean Kodi profile receives the intended configuration without overwriting unrelated state.

---

## Phase 4 — Skin Provisioning

Implement:

- AF3 installation
- activation
- skin confirmation handling
- configuration application
- rebuild/reload
- verification

Reuse Backup Pro knowledge.

Exit criteria:

Fresh Kodi reliably ends in AF3 with the expected managed configuration.

---

## Phase 5 — Restart / Resume

Implement:

- operation restart requirements
- persistent transaction state
- Kodi restart orchestration
- automatic continuation
- failure recovery

Exit criteria:

Installations requiring restart complete reliably without manual state recovery.

---

## Phase 6 — Personal Authentication

Investigate and implement safe portable authentication.

Per service:

```text
Test
Document
Classify
Automate if safe
Prompt if not
```

Exit criteria:

Build Manager automatically restores safe portable credentials and clearly identifies services needing manual authorization.

---

## Phase 7 — Update / Repair

Implement:

- installed build version
- drift detection
- update planning
- repair mode
- changed-setting reconciliation

Exit criteria:

Existing installations can be moved from one build version to another without reinstalling everything.

---

## Phase 8 — Cross-Platform Hardening

Validate:

- macOS
- Apple TV
- Shield
- Firestick

Document differences and add platform abstractions where necessary.

Exit criteria:

The same build definition can produce known-good installations on all supported platforms.

---

## Phase 9 — Release 1.0

Requirements:

- reliable fresh install
- reliable reconciliation
- reliable skin setup
- supported device profiles
- safe auth handling
- useful diagnostics
- clean repository packaging
- complete documentation
- full test suite passing

---

# 38. Initial Development Backlog

Recommended first tasks, in order:

### BM-001
Create project skeleton for `script.build.manager`.

### BM-002
Create manifest schema v1.

### BM-003
Implement manifest validation/parser.

### BM-004
Implement profile inheritance/overrides.

### BM-005
Implement Kodi/platform state inspector.

### BM-006
Create desired-state model.

### BM-007
Implement operation planner.

### BM-008
Add unit tests for reconciliation planning.

### BM-009
Adapt/create disposable Kodi test harness.

### BM-010
Implement repository detection/install.

### BM-011
Implement add-on detection/install.

### BM-012
Implement dependency closure.

### BM-013
Implement enable/disable reconciliation.

### BM-014
Implement post-operation validation.

### BM-015
Prototype configuration deployment.

### BM-016
Research Red Light configuration portability.

### BM-017
Research account/token portability.

### BM-018
Implement AF3 provisioning.

### BM-019
Implement restart requirement aggregation.

### BM-020
Implement restart/resume state.

That is enough backlog to start development without designing the entire future product prematurely.

---

# 39. Release Strategy

Early versions:

```text
0.1.x architecture/prototype
0.2.x addon provisioning
0.3.x configuration
0.4.x AF3
0.5.x restart/reconciliation
0.6.x device profiles
0.7.x authentication
0.8.x cross-platform hardening
0.9.x release candidate
1.0.0 stable personal release
```

Actual numbering may compress if development progresses cleanly.

---

# 40. eengert Repository Publishing

Build Manager should ultimately be distributed through Eric's Kodi repository like other add-ons.

Typical user flow:

```text
Install eengert repository
      ↓
Program Add-ons
      ↓
Build Manager
      ↓
Install
```

The repository package should contain only the Build Manager add-on itself and public/non-secret assets.

Private credentials must not be distributed through the public repository.

---

# 41. Build Data Location

Keep build-definition location flexible.

Possible sources:

### Embedded

Simple initially.

```text
resources/builds/eric-main.json
```

### Remote

Later:

```text
eengert-hosted manifest
```

Benefits:

Build definitions can change without releasing Build Manager.

Recommended progression:

```text
MVP → embedded manifest
Later → remote versioned manifest
```

Do not introduce network dependency before it provides real value.

---

# 42. Failure Model

Each operation should report one of:

```text
SUCCESS
SKIPPED
WARNING
FAILED
```

A warning should not automatically make the entire build fail.

Example:

```text
✓ 26 operations successful
⚠ Trakt requires manual authorization
✓ AF3 active
✓ Build configuration verified

Build installed successfully with 1 authorization pending.
```

Differentiate configuration incompleteness from actual installation failure.

---

# 43. Transaction Philosophy

Build Manager does not initially need Backup Pro-level rollback.

Instead:

1. Calculate changes before applying.
2. Make small deterministic operations.
3. Validate after operations.
4. Persist progress.
5. Allow Repair to reconcile partial results.

This is safer and simpler than attempting a universal rollback system.

Backup Pro already exists if a user wants to capture their Kodi state before making major changes.

---

# 44. Backup Pro Integration Opportunity

A later optional feature could be:

```text
Create safety backup before Build Manager update
```

If Backup Pro is installed:

```text
Build Manager detects Backup Pro
→ optionally invokes/coordinates backup
→ proceeds with update
```

This should remain optional.

Build Manager must not require Backup Pro.

---

# 45. Definition of Done for Any Task

A development task is complete only when:

- implementation is finished
- existing tests pass
- new relevant tests are added
- disposable profile validation succeeds where appropriate
- no unrelated files changed
- logs contain no secrets
- documentation is updated if behavior changed
- agent provides concise handoff
- supervisor accepts the result

---

# 46. Definition of Done for MVP

The MVP is successful when Eric can:

1. Start with a fresh disposable Kodi installation.
2. Install Build Manager.
3. Select a device profile.
4. Run Install.
5. Have expected repositories installed.
6. Have the desired add-on superset installed.
7. Have dependencies correctly enabled.
8. Have unwanted profile-specific add-ons disabled.
9. Have AF3 installed and activated.
10. Have portable configuration applied.
11. Restart Kodi where required.
12. Run validation.
13. Receive a truthful success/failure result.

Manual authorization of some external services is acceptable for the MVP.

---

# 47. Scope-Control Rule

Before accepting a new feature, ask:

> Does this materially reduce the effort of configuring or maintaining Eric's Kodi devices?

If not, defer it.

Examples likely worth doing:

- device profiles
- repair
- add-on reconciliation
- auth portability
- build updates

Examples probably not worth doing initially:

- theme marketplace
- graphical build designer
- public build hosting
- multi-user support
- fleet web dashboard
- remote Kodi control center
- community manifest ecosystem

This rule is important to keep Build Manager significantly smaller than Backup Pro.

---

# 48. Expected Development Character

Backup Pro required solving:

```text
arbitrary state
+ backup consistency
+ restore consistency
+ rollback
+ verification
+ skin state
+ dependencies
+ remote storage
+ failure recovery
```

Build Manager works from controlled desired state:

```text
known manifest
+ known configuration
+ known profiles
→ deterministic provisioning
```

Therefore the expected development difficulty should be substantially lower than Backup Pro unless scope expands significantly.

The hardest likely areas are:

1. Kodi restart/resume behavior
2. AF3 managed configuration
3. portable authentication
4. platform-specific differences
5. avoiding accidental overwrites of device-local state

---

# 49. Recommended First Milestone

Do **not** begin by trying to install the whole build.

The first engineering milestone should be:

> Given a manifest and a disposable Kodi installation, Build Manager can inspect actual Kodi state and produce a correct, deterministic, non-destructive installation plan.

Example:

```text
BUILD MANAGER

Profile: Shield

Required changes:

INSTALL
  plugin.video.redlight

ENABLE
  script.module.foo

DISABLE
  plugin.video.bar

CONFIGURE
  skin.arctic.fuse.3

No changes have been made.
```

This gives us the architectural foundation before mutation is introduced.

Once the planner is trustworthy, execution becomes much safer.

---

# 50. Recommended Project Startup Sequence

### Step 1
Create the Build Manager repository/source skeleton.

### Step 2
Save this document as:

```text
BUILD_MANAGER_PROJECT_PLAN.md
```

### Step 3
Create:

```text
BUILD_MANAGER_SUPERVISOR_HANDOFF.md
AGENTS.md
CLAUDE.md
```

### Step 4
Have one strong reasoning agent review the architecture before substantial coding.

### Step 5
Assign BM-001 through BM-004 as small bounded implementation tasks.

### Step 6
Use the second agent to review manifest/profile semantics.

### Step 7
Develop the state inspector/planner before allowing Build Manager to modify Kodi.

### Step 8
Begin live Kodi mutation only after the planning layer is stable.

---

# 51. Overall Architectural Target

The desired final system is:

```text
                     eengert Kodi Repository
                              │
                              ▼
                    ┌──────────────────┐
                    │  Build Manager   │
                    │ script.build...  │
                    └────────┬─────────┘
                             │
                   Load desired build
                             │
                             ▼
                 ┌─────────────────────┐
                 │   Build Manifest    │
                 └──────────┬──────────┘
                            │
             ┌──────────────┴──────────────┐
             │                             │
       Common Config                 Device Profile
             │                             │
             └──────────────┬──────────────┘
                            ▼
                     Desired State
                            │
                     Compare against
                            │
                            ▼
                      Actual Kodi
                            │
                            ▼
                     Operation Plan
                            │
                            ▼
                        Execute
                            │
                            ▼
                        Verify
                            │
                            ▼
                  Known-Good Kodi Build
```

Build Manager should ultimately make the specific physical device almost irrelevant.

Eric defines what Kodi should look like.

Build Manager makes the device conform to that definition.
