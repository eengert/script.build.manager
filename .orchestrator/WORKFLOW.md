# Build Manager Manual Workflow

## Core workflow

Eric communicates with ChatGPT in normal Chat mode.

ChatGPT plans and supervises the work. Eric manually copies bounded prompts to Codex or Claude and pastes their reports back to ChatGPT. Coding agents do not autonomously choose the next project task.

The retired ai-supervisor framework is **not** part of the active Build Manager execution path. Do not start or depend on it unless Eric explicitly decides to resurrect it.

## Task design

Every substantive prompt must contain:

- exact repository/worktree path;
- exact branch and relevant baseline SHA when known;
- one bounded objective;
- the beta exit item advanced, or the demonstrated blocker removed;
- files/areas in scope;
- explicit safety and authority boundaries;
- required tests/validation;
- stop conditions;
- expected final report.

Do not use vague prompts such as “continue Build Manager.”

Before issuing a task, answer: **What product state or qualification evidence will materially change when this finishes?**

If the answer is merely a better description of the same known blocker, do not dispatch it unless it tests a genuinely different hypothesis.

## Provider and session policy

Optimize for total task efficiency and correctness, not simplistic per-request cost.

ChatGPT recommends provider/model/effort for each task outside the agent prompt. Do not put model or effort inside prompts intended for Claude/Codex.

Use separate persistent chats when a different model/effort pairing is genuinely needed and preserving session context/cache is valuable.

Typical division of labor:

- implementation: whichever provider is best suited to the task;
- independent review: preferably the other provider or a fresh independent session;
- correction: original implementer unless the review indicates a broader issue;
- re-review: independent reviewer.

No provider automatically fails over to another. Eric/ChatGPT choose deliberately at each task boundary.

## Branch and worktree policy

`matrix` remains the protected integration branch.

Manual work must use the exact branch/worktree named in the task prompt. The normal working worktrees are the Agent Handoff Codex and Claude endpoints described in `.orchestrator/PROJECT.md`; the prompt still names the one it authorizes. Old ai-supervisor-era worktrees (`supervised-*`, `supervisor`) are retired and must not be assumed active.

When repository guidance on `matrix` changes, bring it to the endpoints with an explicit-path, history-preserving copy (for example `git restore --source=<matrix SHA> --staged --worktree -- <paths>` in each endpoint, then a local commit). A guidance update does not merge `matrix` wholesale into an endpoint and does not copy `matrix` `.agent/**`; product source, tests, and assets change only through a deliberate product decision, not through a guidance sync.

Normal implementation should not occur directly on `matrix`. Integration to `matrix` happens only after ChatGPT has reconciled accepted review/validation evidence and Eric's current instructions permit it.

Do not:

- force-push;
- reset/rebase shared history destructively;
- discard another agent's commits or dirty candidate;
- run `git clean` / destructive reset on evidence-bearing worktrees;
- push or release without Eric's explicit authorization.

## Implementation and review lifecycle

For substantive product changes:

1. Establish an exact baseline.
2. Implement only the bounded scope.
3. Run focused tests during iteration.
4. Run the appropriate subsystem/full suite at meaningful candidate boundaries.
5. Return an exact report with changed files, commit/diff identity, tests, and limitations.
6. ChatGPT decides whether independent review is required.
7. Reviewer evaluates the exact candidate/delta without implementing fixes.
8. On NOT PASS, correct only the findings.
9. Re-review the correction delta until PASS.
10. Integrate deliberately and validate the combined result.

Do not repeat an independent review solely because old ai-supervisor checkpoint/provenance bookkeeping is absent. Manual mode binds review to ordinary Git identity/diff evidence plus the reviewer report.

## Handoffs

Agents should leave concise task reports. Repository `.agent/**` files may be updated when the task/worktree already uses them, but they are no longer an autonomous control plane.

The canonical project continuation record is `.orchestrator/HANDOFF.md`, maintained by ChatGPT at meaningful boundaries.

## macOS Test.app safety

Authorized target:

`/Applications/Kodi Build Manager Test.app`

It must run in portable mode:

`open "/Applications/Kodi Build Manager Test.app" --args -p`

Never access normal `/Applications/Kodi.app` or `/Users/eengert/Library/Application Support/Kodi`.

Eric's standing authorization covers routine staging, testing, installation, configuration, restart/quit/relaunch, JSON-RPC interaction, temporary validation adapters, and other Build Manager validation work against the disposable portable Test.app.

In manual mode, the exact prompt must authorize the required operation and preserve host-side credential handling. Old ai-supervisor action names may be useful historical design references, but they are not prerequisites.

If an operation would require exposing a password/token or broadening beyond Test.app, stop and return to ChatGPT.

## Real devices

Do not mutate Family Room Apple TV, Bonus Room Apple TV, Nvidia Shield, Fire TV, or any other household device unless Eric explicitly authorizes a named mutation for that exact device.

Read-only device work also requires the task to name the device and scope when it is not already covered by current standing guidance.

## Secrets/private data

Never print, log, commit, or paste private overlay values, credentials, tokens, or secrets.

Keep Red Light/private-resource values outside Git/public artifacts. Use sanitized fingerprints/metadata only.

## Testing discipline

- Add/update tests for behavior changes.
- Do not weaken tests to make a candidate pass.
- Focused tests during implementation.
- Subsystem/full suite at candidate/integration/qualification boundaries as appropriate.
- Preserve valid unchanged-source evidence; do not rerun expensive suites ceremonially.
- Distinguish unit-tested, integration-tested, and live-proven claims.

## Manual runtime work

Manual agents may use local shell/filesystem tooling only within the prompt's explicit scope.

For Test.app work:

- confirm exact app/process/profile identity before mutation;
- use portable `-p`;
- fail closed on ambiguous identity;
- capture sanitized evidence;
- perform at most the bounded operation authorized by the prompt;
- stop on contradiction rather than retrying speculatively.

## ai-supervisor historical material

The former ai-supervisor framework, its Relay-v1 design, and its unfinished provenance/trusted-action candidates are archived for possible future resurrection.

They are **not current Build Manager prerequisites**.

Do not spend Build Manager time completing:

- ai-supervisor provenance-reconcile framework work;
- autonomous planner/liveness improvements;
- Relay-v1;
- trusted-action checkpoint/pin mechanics that exist only to satisfy ai-supervisor;

unless a manual Build Manager task independently requires the underlying product behavior or Eric explicitly reactivates the framework project.

## Progress reporting

When Eric pastes an agent report, ChatGPT should respond with:

- what was actually accomplished;
- whether the result is accepted, needs review, or needs correction;
- the smallest next manual task;
- any genuine user choice/permission required.

Do not create autonomous work between messages.

## Current milestone

The current outcome remains macOS Beta Qualification. Use the seven exit items in `BUILD_MANAGER_PROJECT_PLAN.md` as the finish line.

Once those exit items are credibly satisfied, stop. Do not turn remaining optional ai-supervisor/framework work into a condition for finishing the hobby project.
