# Orchid

Local web app to manage multiple Claude Code sessions across projects. Python 3.12 + uv
+ FastAPI backend, React/Vite/Tailwind SPA. No DB; state is JSON files plus the Claude
Code transcripts under `~/.claude/projects/`. Ships a companion `orchidd` daemon.

## Layout
- `src/orchid/` — backend. `claude/` holds the SDK seam (runner, driver, driver_manager,
  catalog, transcript, onboarding, roles, planning, git_tools); `services.py`, `bus.py`,
  `api/` (REST + WS), `store/`, `watch/`.
- `src/orchidd/` — companion daemon.
- `web/` — React/Vite/Tailwind SPA (`.tsx`/`.ts`).
- `tests/` — pytest suite (FakeRunner + live uvicorn via requests/websockets).

## Build / test / run
- `uv sync` then `(cd web && npm install && npm run build)` to set up.
- `uv run orchid` → http://localhost:4242 (single uvicorn worker — state is in-memory).
- Dev UI: `cd web && npm run dev` (Vite proxies `/api` + `/ws` to :4242).
- `uv run pytest` — fast suite. `ORCHID_LIVE_TESTS=1 uv run pytest tests/test_live_sdk.py`
  for the opt-in real-SDK smoke test.

## Conventions / gotchas
- All `claude_agent_sdk` imports live under `src/orchid/claude/` — nothing else touches
  the SDK. It's pinned `==0.2.99` (pre-1.0); the JSONL transcript format is internal.
- One asyncio task owns each `ClaudeSDKClient`; everything else message-passes via the
  driver's command queue (`interrupt()` is the only cross-task call).
- Canonicalize every path (`/var`→`/private/var`); atomic JSON writes only.
- Orchid only surfaces/streams sessions it created (`created_by == "orchid"`).
- Agent roles stay lean: orchestrator + worker/reviewer/verifier only; router/retriever/
  memory/tool-action ship off (covered by Orchid/the model).
- Orchestrators work in feature branches, commit often, then `request_review`.

## Agent roles
orchestrator (plans + delegates, persists plans to `.orchid/plans/`), worker (implements),
reviewer (critiques), verifier (runs tests).
