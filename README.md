# Orchid

A local web app for orchestrating Claude Code across multiple projects. Onboard
repos through a Claude-powered console, spin up sessions, watch agents work in
real time, and manage everything from the browser — or pick up any session in a
terminal with `claude --resume`.

Orchid sits on top of the Claude Agent SDK. It doesn't replace Claude Code — it
gives you a control plane for running it at scale across your projects.

## What it does

**Project management** — register project directories, set goals and intent
(ad-hoc tasks vs. milestone-driven work), track progress, view git activity.
Meta-projects group related repos so a single orchestrator has cross-project
context.

**Session orchestration** — create and drive Claude Code sessions from the
browser. Each session streams messages, tool calls, and subagent activity live
over WebSocket. Pin, archive, fork, or resume sessions at any time.

**Agent roles** — projects get a lean set of agent roles (orchestrator, worker,
reviewer, verifier) assembled as SDK subagents. The orchestrator gets planning
tools to persist structured plans and git tools for a branch-based workflow:
work in feature branches, commit often, submit for review.

**Code review** — orchestrators submit branches via `request_review`. Reviews
show diffs in the web UI; approval merges the branch, rejection sends feedback
back to the orchestrator. Review mode is manual (human) or autonomous (reviewer
agent).

**Collaboration** — open a cross-project conversation between agents from
different repos. The relay prompts each participant in turn with the
conversation context; you observe and interject as needed.

**Permission brokering** — tool-use requests surface in the UI for
allow/deny decisions. A companion `orchidd` daemon handles elevated file
operations (root-owned paths) behind an ACL.

## Stack

Python 3.12 + FastAPI backend, React/Vite/Tailwind frontend, Claude Agent SDK
(`claude_agent_sdk`). No database — state is JSON files under `~/.orchid/` and
`<project>/.orchid/`, plus Claude Code's own transcripts under
`~/.claude/projects/`.

## Quick start

```sh
uv sync
(cd web && npm install && npm run build)
uv run orchid          # → http://localhost:4242
```

Dev mode (hot reload): `uv run orchid` in one shell, `cd web && npm run dev` in
another (Vite proxies `/api` and `/ws` to :4242).

## Tests

```sh
uv run pytest          # 174 tests — fakes, in-process uvicorn, no SDK needed
```

## State

- `~/.orchid/registry.json` — index of onboarded project roots
- `~/.orchid/collaborations/` — cross-project collaboration sessions
- `<project>/.orchid/` — per-project config, session flags, plans, reviews
- Transcripts stay in `~/.claude/projects/` (Claude Code owns them; Orchid reads only)

## Status

Experimental. Built for personal use, shared as-is. Expect rough edges.
