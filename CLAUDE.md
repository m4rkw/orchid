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
- **Orchid only ever surfaces/streams sessions it created** — those flagged
  `created_by == "orchid"` (`project_store.is_orchid_session`). Only `create_orchestrator_session`
  and `fork` set that flag. A project directory's SDK catalog also
  lists terminal-started transcripts; the session list, project `session_count`, and watcher all
  filter them out. (`prompt(force=True)` is the one deliberate escape hatch for an outside session.)
- **Agent roles stay lean**: only the orchestrator (the driven session) + worker/reviewer/verifier
  (SDK subagents via `agents=`) are materialized. Router/retriever/memory/tool-action are
  off-by-default templates — already covered by the model or the permission broker; don't make them
  real agents. The orchestrator persists plans to `.orchid/plans/` so they survive its context window.

## Layout
- `claude/runner.py` — `Runner` protocol + `SdkRunner`; the seam tests fake.
- `claude/driver.py` — per-session client FSM (idle→spawning→streaming→closing). `hold_open`
  only for onboarding. Burst = a turn + queued follow-ups; client closes when the queue drains.
- `claude/driver_manager.py` — one driver per sid; permission broker (`can_use_tool` →
  `permission_request` WS event, 300s timeout-deny); two-writer guard (external 409 + force);
  subagent hooks → `agent_started/stopped` + `live_agents`. `create_orchestrator_session` builds
  the roles-as-subagents + plan-tools spec (runs under acceptEdits).
- `claude/catalog.py` — at-rest SDK reads (sessions/messages/subagents/rename/delete/fork).
- `claude/transcript.py` — SDK msg → `NormalizedMessage`; `TranscriptCache` (uuid diff, 2k cap, 16KB block previews).
- `claude/onboarding.py` — hold-open driver ("console") + in-process MCP tools (list/inspect/register
  project, analyse → write AGENTS.md, write_spec, assign_roles, git_init, set_project_intent,
  scaffold_project, add_child_project, remove_child_project).
- `claude/roles.py` — built-in agent-role templates (lean: orchestrator + worker/reviewer/verifier
  subagents; router/retriever/memory/tool-action ship off as "covered by Orchid/model").
  `assemble_orchestrator(root, child_roots=)` → SDK `agents=` map + system-prompt append (roster +
  AGENTS.md + spec + planner/branch workflow instructions). For meta-projects, child AGENTS.md
  files are injected under headings so the orchestrator has full cross-project context.
- `claude/planning.py` — in-process MCP `orchid_plan` tools the orchestrator uses to persist a plan
  to `.orchid/plans/`; each mutation emits `plan_upserted` on `sidebar`.
- `claude/spec_tools.py` — in-process MCP `orchid_spec` tools (get_spec, update_spec) for the
  project's living specification; agents verify work against it and update it when behaviour changes.
- `claude/git_tools.py` — in-process MCP `orchid_git` tools (create_branch, git_status, git_commit,
  git_diff, request_review) wired into orchestrator sessions alongside planning and spec tools.
- `watch/watcher.py` — one `watchfiles` task over `<config>/projects/`; routes changes by key
  for `created_by == "orchid"` sids only; suppressed for driver-active sids (one-writer).
- `services.py` — `ProjectService` (CRUD, shared by API + onboarding tool) and `SessionService`
  (locate/detail/messages/agents/rename/pin/archive/delete/fork). `is_running`/`live_agents` are
  wired from `DriverManager` at startup.
- `bus.py` — pub/sub, per-topic monotonic `seq`. `api/ws.py` multiplexes topics
  `sidebar` (auto), `session:<sid>`, `onboarding`. Clients replay REST backlog then apply
  events with `seq >` watermark; gap → refetch.

## State files
- `~/.orchid/registry.json` — `{projects:[{id, root, added_at}]}` (paths only)
- `<root>/.orchid/project.json` — `{id, name, settings:{model, permission_mode}, intent, goal, review_mode, project_type, children}`
- `<root>/.orchid/sessions.json` — sparse flags `{<sid>:{pinned, archived, created_by, role, first_seen_at}}`
  (`role:"orchestrator"` marks an orchestrator session)
- `<root>/.orchid/agents.json` — sparse per-role overrides on top of the `claude/roles.py` built-ins
- `<root>/.orchid/spec.json` — the living specification (canonical reference agents verify against)
- `<root>/.orchid/plans/<id>.json` — the orchestrator's durable plans (planner MCP tools own these)
- `<root>/.orchid/reviews/<id>.json` — branch review requests (pending/merged/changes_requested)
- `<root>/AGENTS.md` — project memory written during onboarding; injected into every orchestrator prompt
- Session titles are owned by the SDK (`rename_session`), never duplicated in our state.

## Project workflow
- **Intent:** each project is `adhoc` (quick tasks) or `goal` (working towards an end state with
  milestones). Goal-oriented projects track progress as plan-step completion percentage.
- **Review mode:** `manual` (human reviews branches in the web UI) or `autonomous` (reviewer agent).
  Set during onboarding, changeable per project or per work block.
- **Branch workflow:** orchestrators always work in feature branches (`create_branch`), commit
  frequently, then `request_review` to submit. Reviews are persisted in `.orchid/reviews/`.
  Approval merges the branch; rejection sends feedback to the orchestrator.
- **Git enforcement:** onboarding checks for `.git`; offers `git_init` if missing.
- **Changelog:** derived from `git log` via `GET /projects/{pid}/activity` — no separate state.
- **Dashboard:** clicking a project name shows goal, progress, pending reviews, active sessions,
  plans, and recent git activity.
- **Meta-projects:** `project_type: "meta"` with `children: [project_id, ...]` linking other
  registered projects. Meta-project orchestrators get all children's AGENTS.md injected into
  context. Children remain independent (can still be added standalone). Console has
  `scaffold_project` (creates dir + git init + registers), `add_child_project`, and
  `remove_child_project` tools. Sidebar nests children visually under their meta-project.
