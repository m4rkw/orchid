---
{
  "version": 2,
  "title": "Orchid — Architecture",
  "status": "active",
  "created_at": "2026-06-16T20:13:01.051581+00:00",
  "updated_at": "2026-06-16T20:27:55.750185+00:00"
}
---

This describes HOW Orchid is built — its structure, components, boundaries, and
the decisions that shape them. It is the foundation the specification is derived
from. Keep it current as the structure changes; keep the spec consistent with it.

## Shape

Three processes, no database:

1. **orchid** — a FastAPI backend (single uvicorn worker; state in-memory + flat
   JSON) serving a React/Vite/Tailwind single-page app. Runs as the user.
2. **orchidd** — a separate privileged daemon for elevated filesystem/exec
   operations, reached over a Unix socket and gated by an ACL. Runs with
   elevation; orchid never elevates directly.
3. **Claude Code** — driven through the Claude Agent SDK as a subprocess/client;
   its transcripts under `~/.claude/projects/` are the source of truth for
   conversation history.

## Backend layout (`src/orchid/`)

- `api/` — FastAPI routers (`projects`, `sessions`, `plans`, `reviews`, `specs`,
  `architecture`, `policies`, `permissions`, `onboarding_api`, `collaborations`,
  `elevation`, `ws`) plus `app.py` (composition root / lifespan) and `health`.
- `claude/` — the ONLY place that imports `claude_agent_sdk`. Contains:
  - `runner.py` — `Runner` protocol + `SdkRunner`; the seam tests fake.
  - `driver.py` — per-session client FSM; one asyncio task owns one
    `ClaudeSDKClient` (anyio task affinity); a command queue feeds it.
  - `driver_manager.py` — one driver per session; permission broker
    (`can_use_tool` -> `permission_request`); two-writer guard; subagent hooks;
    builds orchestrator sessions (roles-as-subagents + plan/git/spec/architecture
    MCP servers); usage capture; notifier fan-out.
  - `catalog.py` — at-rest SDK reads (sessions/messages/subagents/rename/...).
  - `transcript.py` — SDK message -> `NormalizedMessage`; `TranscriptCache`.
  - `onboarding.py` — hold-open "console" driver + in-process MCP tools.
  - `roles.py` — built-in role templates; `assemble_orchestrator` builds the
    `agents=` map + the system-prompt append (roster, goal, planner/branch
    instructions, policy, architecture, spec, AGENTS.md).
  - in-process MCP tool servers: `planning.py`, `git_tools.py`, `spec_tools.py`,
    `architecture_tools.py`, `policy`/`consult`, `elevated_tools.py`.
- `store/` — flat-JSON persistence, atomic writes (`jsonio.atomic_write_json`):
  `registry`, `project_store`, `agents_store`, `plan_store`, `review_store`,
  `spec_store`, `architecture_store`, `usage_store`, `policy_store`, `paths`.
- `bus.py` — in-process pub/sub with per-topic monotonic `seq`.
- `watch/watcher.py` — one `watchfiles` task; routes external transcript changes
  for Orchid-owned sessions only, suppressed while a driver is active.
- `services.py` — `ProjectService` + `SessionService` (reads spanning registry,
  catalog, cache); `is_running`/`live_agents` wired from `DriverManager`.
- `notify.py` — desktop + optional Pushover notifications (push owns task refs).
- `config.py` — `Settings` from env (orchid_home, host/port, Pushover, base_url).

## Frontend layout (`web/src/`)

- `api/client.ts` + `api/types.ts` — typed REST client and wire types.
- `state/stores.ts` — Zustand store; single `apply(WsEvent)` reducer; React
  Query for REST cache, invalidated by bus events.
- `ws/socket.ts` — WS manager (subscribe, seq watermark, resync on gap).
- `components/` — console (onboarding), session transcript, project dashboard,
  plans, reviews, spec, architecture, settings.
- `notify.ts` — browser desktop notifications off WS events.

## orchidd daemon (`src/orchidd/`)

- `server.py` — Unix-socket JSON-RPC dispatch; validates op against `VALID_OPS`,
  resolves the ACL grant, then runs the op.
- `ops.py` — privileged primitives (read/write/edit/chmod/mkdir/delete/stat/exec);
  all writes atomic tmp+rename; `edit_file` preserves the file's mode.
- `acl.py` — grant matching: file ops by `file_read`/`file_write`/`file_delete`
  per project root; `exec` by exact-or-`prefix *` allow-list. Scoped by blast
  radius. `client.py` (under `orchid/orchidd/`) is the in-app caller.

## Key decisions & boundaries

- **SDK isolation**: every `claude_agent_sdk` import lives under `claude/`; the
  `Runner` protocol is the seam tests fake. The pinned, pre-1.0 SDK and the
  internal transcript format are quarantined behind it.
- **Task affinity**: exactly one asyncio task touches each client; all else
  message-passes via the command queue. `interrupt()` is the only cross-task call.
- **No database**: state is flat JSON under each project's `.orchid/` plus the SDK
  transcripts; atomic writes only; reads of transcripts go through the catalog.
- **Ownership**: Orchid only surfaces sessions it created (`created_by ==
  "orchid"`); a session it did not create is treated as terminal-owned to avoid
  two-writer transcript corruption.
- **Privilege separation**: orchid (user) asks orchidd (elevated) over a socket
  gated by a per-project ACL; orchid never elevates in-process.
- **Event-sourced UI**: the bus + per-topic `seq` + WS multiplex drive a
  replay-then-apply client; a `seq` gap triggers REST refetch.
- **Living documents**: architecture -> spec -> plans/reviews, all per-project
  JSON, injected into the orchestrator's prompt; the architecture is the root.
- **Reviews track real PRs**: on a repo with a GitHub remote, `request_review`
  pushes the branch and opens (or finds) a PR via `gh`, storing pr_number/url on
  the review; approve/merge goes through `gh pr merge` and read reconciles PR
  state. Repos without a remote fall back to a local-branch merge. One review
  trail — agents must use request_review, not raw `gh pr create`.

## Request / data flow

1. Web action -> REST (`api/`) or a prompt -> `DriverManager` -> a `SessionDriver`
   task -> `SdkRunner` -> `ClaudeSDKClient` -> Claude Code.
2. Streamed SDK messages -> `transcript` normalize -> `TranscriptCache` + bus
   `message` events -> WS -> store.
3. A tool call -> `can_use_tool` broker: read-only tools auto-approved; others
   emit `permission_request` (300s timeout-deny) and, on first-of-burst, a push.
4. `turn_completed` -> `usage_store` accrual + `usage_updated`.
5. Elevated need -> `elevated_*` MCP tool -> orchidd client -> daemon (ACL) -> op.
6. External transcript write -> watcher -> session refresh (Orchid-owned only).

## Testing seams

`Runner`/`SdkRunner` (faked by `FakeRunner`), an in-memory bus, a live uvicorn +
requests/websockets for API/WS, and an opt-in real-SDK smoke test. The project's
own pytest suite is the verification ground truth.
