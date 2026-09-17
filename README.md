# Build Manager

Kodi program add-on for declarative multi-device provisioning and configuration.

## What It Does

Build Manager lets you define a desired configuration state for each of your
Kodi devices and then apply that state consistently across all of them.
Rather than cloning one device onto another, you declare what each device
should look like and Build Manager provisions it to match.

## Target Platforms

- tvOS (Apple TV)
- Android / Shield TV
- Fire TV
- macOS

## Status

Early development. The repository is initialized; implementation has not
begun. See `BUILD_MANAGER_SUPERVISOR_HANDOFF.md` for current project state.

## Repository Layout

```
script.build.manager/
├── .agent/             # Agent workflow state (status, task, handoff)
├── resources/          # Addon resources (populated during implementation)
├── AGENTS.md           # Shared coding-agent guidance
├── CLAUDE.md           # Claude-specific agent guidance
├── BUILD_MANAGER_PROJECT_PLAN.md         # Canonical project plan (placeholder)
├── BUILD_MANAGER_SUPERVISOR_HANDOFF.md   # Living project-state document
└── README.md
```

## Agent Handoff

This project uses a Codex/Claude agent handoff workflow. See `AGENTS.md` for
shared agent rules and `CLAUDE.md` for Claude-specific guidance.
