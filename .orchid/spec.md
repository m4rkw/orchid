---
{
  "version": 9,
  "title": "Orchid — System Specification",
  "status": "active",
  "created_at": "2026-06-15T20:02:19.158052+00:00",
  "updated_at": "2026-06-17T19:18:26.457511+00:00"
}
---

## Purpose

Orchid is a local, single-user web application for managing multiple Claude Code
sessions across many projects from one place. It onboards repositories, drives an
orchestrator-plus-subagents workflow with branch-based review, brokers tool
permissions, and surfaces live progress, cost, and history. It runs entirely on
the user's machine with no cloud dependency.

## Non-goals

- Not a multi-tenant or hosted service; single user, localhost-first.
- Not a model abstraction layer: Orchid is deliberately coupled to the Claude
  Agent SDK and uses Claude Code's own transcripts as the source of truth.
- Not a parallel multi-writer agent runner: one driven orchestrator per session,
  subagents for delegation — not fleets of concurrent writer agents.
- No database, no vector store, no separate eval harness. The project's own test
  suite is the eval; flat JSON files + SDK transcripts are the state.

## Core concepts

## Core concepts

- **Project**: a registered directory Orchid manages. Holds `.orchid/` state.
- **Session**: one Claude Code conversation. Orchid only surfaces/streams the
  sessions it created (`created_by == "orchid"`); terminal-started transcripts in
  the same project are filtered out everywhere.
- **Orchestrator**: the single driven session for a project. Plans, delegates to
  subagents, works in branches, and requests review.
- **Roles**: lean by design — orchestrator + worker / reviewer / verifier
  (materialized as SDK subagents via `agents=`). Router / retriever / memory /
  tool-action ship off by default (covered by the model and the permission
  broker).
- **Plan**: a durable, on-disk decomposition of a goal the orchestrator persists
  so it survives the context window.
- **Spec**: this document — the single living specification per project. It is
  injected into every orchestrator's prompt as a standing rule: agents verify their
  work against it, create it if missing, and keep it current. Any change to behaviour
  MUST be reflected here BEFORE review — this is enforced for all agents, not optional.
- **Review**: a request to merge a feature branch, resolved manually (human) or
  autonomously (reviewer agent).
- **Inbox item**: a generic unit of human decision. Any program — Orchid or an
  external tool — creates one when it has automated as far as it can but needs a
  person to choose; the human picks an option and the originator acts on the
  outcome. See the Inbox section.
- **Meta-project**: a project of `project_type: "meta"` linking child projects;
  its orchestrator receives every child's AGENTS.md for cross-repo context.

## Architecture

- The canonical, living architecture lives in the architecture document (`.orchid/architecture.json`, get_architecture); it precedes and informs this spec. Summary:
- **Backend**: Python 3.12, FastAPI, a single uvicorn worker (state is in-memory
  + flat JSON). Managed with `uv`. Tests with pytest.
- **Frontend**: React + Vite + Tailwind single-page app.
- **orchidd**: a separate privileged daemon for elevated filesystem/exec
  operations, reached over a Unix socket and gated by an ACL.
- **State**: JSON files under each project's `.orchid/`, plus Claude Code
  transcripts under `~/.claude/projects/` (read via SDK catalog functions only).

## Hard invariants

1. All `claude_agent_sdk` imports live under `src/orchid/claude/`. Nothing else
   touches the SDK. The SDK is pinned (pre-1.0); the transcript format is
   internal and only the watcher touches files (as a change signal).
2. Exactly one asyncio task owns each `ClaudeSDKClient` (anyio task affinity).
   Everything else message-passes via the driver's command queue; `interrupt()`
   is the only cross-task call.
3. Every path is canonicalized (`/var` -> `/private/var`); project transcript
   keys only via `project_key_for_directory`.
4. All state writes are atomic (`store/jsonio.atomic_write_json`).
5. Orchid only ever surfaces/streams sessions flagged `created_by == "orchid"`.
   `prompt(force=True)` is the one deliberate escape hatch for an outside session.
6. Two writers on one transcript corrupt it: a session Orchid did not create is
   treated as terminal-owned until the user explicitly takes it over.

## State files

## State files

- `~/.orchid/registry.json` — registered projects (paths only).
- `<root>/.orchid/project.json` — id, name, settings, intent, goal, review_mode,
  project_type, children.
- `<root>/.orchid/sessions.json` — sparse per-session flags (created_by, role,
  pinned, archived, first_seen_at).
- `<root>/.orchid/agents.json` — sparse per-role overrides on the built-ins.
- `<root>/.orchid/spec.json` — this living specification.
- `<root>/.orchid/plans/<id>.json` — durable orchestrator plans.
- `<root>/.orchid/reviews/<id>.json` — branch review requests.
- `<root>/.orchid/inbox/<id>.json` — inbox work items awaiting / carrying a
  human decision.
- `<root>/.orchid/usage/<sid>.json` — accumulated per-session cost / turns.
- `<root>/AGENTS.md` — project memory, injected into every orchestrator prompt.
- `~/.orchid/orchidd_acl.json` — elevated-operation grants for the daemon.

## Onboarding

A hold-open "console" agent onboards projects conversationally: inspect the
directory, propose a name and an AGENTS.md, register on confirmation, assign the
default roles, ensure a git repo, then set intent and review mode. Questions with
a fixed answer set (intent, review mode, yes/no) are presented as one-click
quick-reply buttons via the `ask_choice` tool, while still being phrased in prose
so they work without the buttons. The console can also scaffold new projects and
compose meta-projects.

## Project workflow

- **Intent**: each project is `adhoc` (quick, unrelated tasks) or `goal` (working
  toward an end state). Goal projects track progress as plan-step completion %.
- **Review mode**: `manual` (human reviews/merges in the web UI) or `autonomous`
  (a reviewer agent reviews and approves). Changeable per project / work block.
- **Branch workflow**: orchestrators always work in feature branches, commit
  frequently, then `request_review`. Approval merges; rejection returns feedback.
- **Git enforcement**: onboarding requires (or offers to initialise) a repo.
- **Dashboard**: per project — goal, progress, pending reviews, active sessions,
  plans, recent git activity (changelog derived from `git log`), and total cost.
- **Changelog/activity**: derived from git; never stored separately.

## Quality model

Quality comes from closing feedback loops against ground truth, not from trusting
agent self-report. Concretely:

- The **verifier** role runs the project's real checks (tests/typecheck/lint).
- `request_review` MUST carry `verification`: the observed check output. A review
  submitted without evidence is treated as UNCONFIRMED.
- Each review is enriched server-side with deterministic, agent-proof signals:
  `touches_tests` (does the diff modify tests?) and `files_changed`. The reviewer
  confirms against the evidence and checks that tests were not weakened.
- Work happens in small, reviewable, reversible units (feature branches).
- Reviews are backed by real GitHub PRs when the repo has a remote (opened and
  merged via `gh` through request_review); Orchid reconciles PR merge state so a
  PR merged on GitHub resolves the review. No-remote repos use local-branch merge. Open PRs raised outside Orchid (e.g. via gh) are adopted into the reviews list. Verification evidence is drawn from the PR's CI checks and an on-demand Run-checks action (runs the project test_command against the branch in a throwaway git worktree), not only agent-attached output.

## Permissions & elevated operations

- **Broker**: every tool call a driven session makes is brokered. Risky tools
  surface as a `permission_request` to the web UI and auto-deny after 300s if
  unanswered. Provably read-only tools (Read, Grep, Glob, NotebookRead,
  git_status, git_diff, elevated_stat) are auto-approved without prompting.
- **orchidd ACL**: elevated file/exec operations are gated per project root.
  File ops map to `file_read` / `file_write` / `file_delete`; `exec` is an exact
  (or `prefix *`) command allow-list. Grants are scoped by blast radius, not by
  command novelty: a two-byte `chmod` is no harder to land than a file write.
  Elevated tools: read_file, write_file, edit_file (preserves the existing file
  mode), chmod, mkdir, delete_file, stat, exec. `edit_file` MUST NOT change a
  file's permission bits.

## Observability

- The cost / duration / turn count the SDK reports per turn is persisted per
  session under `.orchid/usage/` and rolled up per project. Session detail
  exposes cumulative cost and turns; the dashboard shows the project total.
  A `usage_updated` event keeps the UI live.

## Notifications

## Notifications

- Orchid surfaces "needs you" moments out of band: a desktop browser
  notification (default; fires only when the tab is unfocused) on a pending
  permission request, a new review request, or a new inbox item, and an optional
  Pushover push (enabled when token + user are configured) carrying a deep link
  (`?project=&session=`, `?project=&review=`, or `?project=&inbox=`) that routes
  straight to the relevant view. Per-session permission pushes are burst-suppressed
  to one per pending window; inbox pushes are burst-suppressed to one per item
  group. Pushover credentials come from `PUSHOVER_APP_KEY` / `PUSHOVER_USER_KEY`
  (or the `ORCHID_PUSHOVER_*` aliases) in the environment.

## Inbox (work items)

The inbox is a generic, project-agnostic human-decision surface — a sibling of
reviews and permission requests. Its purpose is to let automation run as far as
it reliably can and then surface only the genuinely human decisions, simply.

- **Producer**: any program (Orchid itself or an external tool such as docmgr)
  POSTs a work item to `POST /api/projects/{pid}/inbox`. An item carries a
  `source`, a `title`, optional markdown `body`, an optional `group_id` /
  `group_label` for clustering a batch, a list of `options` (the decision
  "buttons": `{id, label, detail}`), and an arbitrary `context` blob the producer
  needs handed back verbatim.
- **Surface**: items appear in a single unified web Inbox spanning every project
  (a top-level sidebar entry with a pending-count badge). Items are grouped by
  `group_label`; each item shows its options as buttons, with an "apply to all in
  group" shortcut for batches and a dismiss affordance. `GET /api/inbox` is the
  cross-project aggregate; `GET /api/projects/{pid}/inbox` is per-project. Both
  accept `status` and `source` filters.
- **Resolution**: the human picks an option; `POST .../inbox/{id}/resolve`
  records `{option_id, payload}` and stamps the item `resolved`. `dismiss` marks
  it `dismissed`. An option_id not offered by the item is rejected (400).
- **Contract is pull, not push**: Orchid records the chosen outcome but never
  executes it. The producer polls (`GET ...?status=resolved`) and acts on the
  decision itself — so an external tool stays a plain HTTP client with no inbound
  surface. A resolved decision is also the producer's cue to LEARN (e.g. persist
  the choice as a rule) so the same decision need not be asked again.

### Reference producer: docmgr ambiguous filing

docmgr (an automated Hazel replacement that sorts PDFs into a Documents tree)
infers a document's vendor with Claude, then matches it to a folder rule. When
two or more filing rules could legitimately claim a document (e.g. a shared-house
invoice tree vs a personal receipts tree) — an ambiguity an LLM cannot reliably
resolve — docmgr stops guessing and POSTs a grouped inbox item, one per
ambiguous document, with the candidate destinations as options. On a later run it
reads the resolved items, files each document into the chosen tree, and writes
the vendor into that rule's lookup so future documents from the same vendor sort
automatically.

## Real-time / event model

- An in-process pub/sub bus carries events with a per-topic monotonic `seq`. The
  WebSocket multiplexes topics: `sidebar` (auto), `session:<sid>`, `onboarding`,
  `collab:<id>`. Clients replay REST backlog then apply events past their `seq`
  watermark; a gap triggers a refetch. The watcher routes external transcript
  changes for Orchid-owned sessions only, suppressed while a driver is active.

## Constraints

- Single user, localhost-first; the public base URL is configurable so
  notification deep links resolve off-device.
- No secret material is stored in project state; Pushover credentials and the
  external base URL come from the environment.
- Autonomy tops out at a reviewable, verified change — never self-approval of a
  merge to the default branch, and never self-restart of the host/daemon without
  an explicit, scoped, detached ACL grant.
