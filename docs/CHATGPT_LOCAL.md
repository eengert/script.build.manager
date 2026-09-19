# ChatGPT Local Developer Bridge

This is the fallback coding path for **normal ChatGPT chat** when Codex and/or
Claude Code usage is unavailable.

It must not use ChatGPT Work mode. Work mode is intentionally outside this
workflow because it draws from the Codex usage pool.

## Architecture

```text
Normal ChatGPT chat
        |
        v
Custom MCP app (ChatGPT Developer Mode)
        |
        v
OpenAI Secure MCP Tunnel
        |
        v
tools/chatgpt_local/server.py  (stdio MCP)
        |
        v
dedicated agent/chatgpt git worktree
        |
        +--> scoped file read/search/write/patch
        +--> local Git status/diff/log/stage/commit
        +--> Python unittest runner
        +--> tools/kodi_test.py disposable Kodi harness
```

The MCP server does not call an OpenAI model, Codex, or Claude. ChatGPT is the
reasoning layer; the local process only exposes deterministic tools.

## Security model

The bridge is intentionally narrower than a terminal.

Allowed:

- worktree-relative UTF-8 file reads
- repository text search
- guarded file creation/replacement
- unified patch application
- Git status/diff/log
- staging explicit paths
- local commits
- unittest execution
- explicitly allowlisted disposable Kodi harness commands

Not exposed:

- arbitrary shell execution
- `git push`, merge, reset, clean, rebase, force operations, or history rewrite
- direct `.git` reads/writes
- file deletion through the patch tool
- paths outside the configured worktree
- obvious secret/key files by default
- real Kodi profile/device operations

Existing files can only be replaced when the caller supplies the SHA-256 value
returned by a previous `read_file` call. This prevents a stale ChatGPT turn from
silently overwriting a file changed by another process.

Symlink/path traversal is checked after path resolution, so a repository symlink
cannot be used to escape the configured workspace.

## One-time Build Manager setup

From the normal Build Manager checkout:

```sh
git fetch origin
git worktree add \
  /Users/eengert/Documents/Kodi/worktrees/script.build.manager-chatgpt \
  -b agent/chatgpt origin/agent/chatgpt
```

If the local `agent/chatgpt` branch already exists:

```sh
git worktree add \
  /Users/eengert/Documents/Kodi/worktrees/script.build.manager-chatgpt \
  agent/chatgpt
```

Then:

```sh
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-chatgpt
sh tools/chatgpt_local/setup.sh
```

The setup script creates its Python environment under:

```text
~/.local/share/chatgpt-local/venv
```

No credentials are written to the repository.

## Secure MCP Tunnel

Install OpenAI's tunnel client if it is not already present:

```sh
brew install openai/tools/tunnel-client
```

In ChatGPT Business Developer Mode, create/configure the custom MCP app and
Secure MCP Tunnel, then export the credentials supplied for that tunnel:

```sh
export CONTROL_PLANE_API_KEY='...'
export CONTROL_PLANE_TUNNEL_ID='...'
```

Do not place those values in this repository or a tracked shell script.

Launch:

```sh
cd /Users/eengert/Documents/Kodi/worktrees/script.build.manager-chatgpt
sh tools/chatgpt_local/run_tunnel.sh
```

The launcher uses the bridge worktree as the default workspace. To use the same
bridge implementation against another dedicated ChatGPT worktree:

```sh
CHATGPT_LOCAL_WORKSPACE=/path/to/other-chatgpt-worktree \
  sh tools/chatgpt_local/run_tunnel.sh
```

Only one active `tunnel-client` instance should use a given tunnel ID when
the MCP binding is stdio.

## ChatGPT custom app

In ChatGPT Developer Mode, scan the tools exposed through the tunnel before
creating/publishing the app. Keep it as a draft while iterating on the tool
surface; write actions may require confirmation in ChatGPT.

A useful app name is:

```text
Kodi Local Developer
```

Normal ChatGPT chat should invoke this app whenever it needs fresh local
worktree state or a local action.

## Exposed tools

| Tool | Purpose |
|---|---|
| `workspace_info` | configured worktree + Git status |
| `list_directory` | scoped directory listing |
| `read_file` | text read + SHA-256 |
| `search_text` | scoped text search |
| `write_file` | guarded atomic create/replace |
| `apply_patch` | checked unified patch |
| `git_status` | local status |
| `git_diff` | unstaged/staged diff |
| `git_log` | recent commits |
| `git_stage` | stage explicit paths |
| `git_commit` | local commit only |
| `run_tests` | full or targeted unittest |
| `kodi_harness` | allowlisted disposable Kodi validation |

Current Kodi allowlist:

```text
reset
install
configure
enable-webserver
launch
wait
stop
restart
inspect
status
validate
validate-repo
validate-addon
validate-dependencies
validate-addon-state
validate-post-operations
validate-config
```

## Local validation before first real task

From the ChatGPT worktree:

```sh
python3 -m unittest tests.test_chatgpt_local_bridge
python3 -m unittest discover tests
```

Then, with the tunnel connected from a normal ChatGPT chat:

1. call `workspace_info`
2. read `README.md`
3. run `git_status`
4. run a targeted unit test
5. create a harmless untracked test file, verify it, then remove it manually
6. run `kodi_harness("status")`
7. only after those pass, hand ChatGPT a real bounded development task

The first live task should be low risk and should end with a local commit and
normal supervisor review before any merge to `matrix`.

## Reusing for another Kodi project

The MCP server itself is project-agnostic. Give every coding agent its own
worktree in each repository:

```text
agent/codex
agent/claude
agent/chatgpt
```

Point `CHATGPT_LOCAL_WORKSPACE` at that repository's ChatGPT worktree. Project
specific test tools can be added later as named allowlisted MCP tools rather than
opening an unrestricted shell.
