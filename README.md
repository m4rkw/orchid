# ⚘ Orchid

Local web UI for managing Claude Code sessions across projects: onboard a project by
pointing a Claude-powered chat at its directory, watch projects → sessions → subagents
live in a tree, drive any session from the browser, and jump into any session from a
terminal with `claude --resume`.

## Run

```sh
uv sync
(cd web && npm install && npm run build)
uv run orchid          # → http://localhost:4242
```

Dev mode (hot reload): `uv run orchid` in one shell, `cd web && npm run dev` in another
(Vite proxies `/api` and `/ws` to :4242).

## Tests

```sh
uv run pytest
```

## State

- `~/.orchid/registry.json` — index of onboarded project roots
- `<project>/.orchid/` — per-project state (self-gitignored)
- transcripts stay in `~/.claude/projects/…` (Claude Code owns them; Orchid only reads)
