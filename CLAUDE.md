# Orchid — architecture notes for Claude Code

Local web app to manage multiple Claude Code sessions across projects. Python 3.12 + uv
+ FastAPI backend, React/Vite/Tailwind SPA. No DB; state is JSON files + the Claude Code
transcripts under `~/.claude/projects/`.

## Run / test
- `uv run orchid` → http://localhost:4242 (single uvicorn worker — state is in-memory)
- Dev UI: `cd web && npm run dev` (Vite proxies `/api` + `/ws` to :4242)
- `uv run pytest` — fast suite (FakeRunner, InMemorySessionStore, live uvicorn + requests/websockets)
- `ORCHID_LIVE_TESTS=1 uv run pytest tests/test_live_sdk.py` — opt-in real-SDK smoke

## Hard rules
- **All `claude_agent_sdk` imports live under `src/orchid/claude/`.** Nothing else touches the SDK.
  SDK is pinned `==0.2.99` (pre-1.0). The JSONL transcript format is internal — only the
  watcher touches files (as a change signal); all reads go through SDK catalog functions.
- **One asyncio task owns each `ClaudeSDKClient`** (anyio task affinity). Everything else
  message-passes via the driver's command queue. `interrupt()` is the only cross-task call.
- **Canonicalize every path** (`store/paths.canonicalize`, resolves `/var`→`/private/var`).
  Project transcript keys only via `project_key_for_directory`.
- Atomic state writes only (`store/jsonio.atomic_write_json`).

## Layout
- `claude/runner.py` — `Runner` protocol + `SdkRunner`; the seam tests fake.
- `claude/driver.py` — per-session client FSM (idle→spawning→streaming→closing). `hold_open`
  only for onboarding. Burst = a turn + queued follow-ups; client closes when the queue drains.
- `claude/driver_manager.py` — one driver per sid; permission broker (`can_use_tool` →
  `permission_request` WS event, 300s timeout-deny); two-writer guard (external 409 + force);
  subagent hooks → `agent_started/stopped` + `live_agents`.
- `claude/catalog.py` — at-rest SDK reads (sessions/messages/subagents/rename/delete/fork).
- `claude/transcript.py` — SDK msg → `NormalizedMessage`; `TranscriptCache` (uuid diff, 2k cap, 16KB block previews).
- `claude/onboarding.py` — hold-open driver + in-process MCP tools (list/inspect/register project).
- `watch/watcher.py` — one `watchfiles` task over `<config>/projects/`; routes changes by key;
  suppressed for driver-active sids (one-writer).
- `services.py` — `ProjectService` (CRUD, shared by API + onboarding tool) and `SessionService`
  (locate/detail/messages/agents/rename/pin/archive/delete/fork). `is_running`/`live_agents` are
  wired from `DriverManager` at startup.
- `bus.py` — pub/sub, per-topic monotonic `seq`. `api/ws.py` multiplexes topics
  `sidebar` (auto), `session:<sid>`, `onboarding`. Clients replay REST backlog then apply
  events with `seq >` watermark; gap → refetch.

## State files
- `~/.orchid/registry.json` — `{projects:[{id, root, added_at}]}` (paths only)
- `<root>/.orchid/project.json` — `{id, name, settings:{model, permission_mode}}`
- `<root>/.orchid/sessions.json` — sparse flags `{<sid>:{pinned, archived, created_by, first_seen_at}}`
- Session titles are owned by the SDK (`rename_session`), never duplicated in our state.
