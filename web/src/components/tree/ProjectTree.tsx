import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api, ApiError } from "../../api/client";
import type { AgentInfo, Project, SessionSummary } from "../../api/types";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";
import { AgentDot } from "../session/AgentPanel";
import { RelativeTime } from "../common/RelativeTime";
import { StatusDot } from "../common/StatusDot";

export function ProjectTree() {
  const { data: projects, isPending, isError, refetch } = useQuery({
    queryKey: ["projects"],
    queryFn: api.projects,
  });
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const select = useAppStore((s) => s.select);
  const focusComposer = useAppStore((s) => s.focusComposer);

  const toggle = (pid: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between px-3 pt-3 pb-2">
        <span className="text-[11px] font-medium tracking-wider text-zinc-500 uppercase">Projects</span>
        <button
          type="button"
          onClick={() => {
            select(null);
            focusComposer();
          }}
          className="rounded-md bg-violet-600 px-2 py-0.5 text-xs font-medium text-white transition-colors hover:bg-violet-500 focus-visible:ring-2 focus-visible:ring-violet-500/60 focus-visible:outline-none"
        >
          + New
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {isPending && <div className="px-2 py-2 text-xs text-zinc-600">Loading projects…</div>}
        {isError && (
          <div className="px-2 py-2 text-xs text-red-400/80">
            Couldn’t load projects.{" "}
            <button type="button" className="underline hover:text-red-300" onClick={() => void refetch()}>
              retry
            </button>
          </div>
        )}
        {projects?.length === 0 && (
          <div className="px-3 py-10 text-center text-xs leading-relaxed text-zinc-600">
            No projects yet — onboard one in the chat →
          </div>
        )}
        {projects?.map((p) => (
          <ProjectRow key={p.id} project={p} expanded={expanded.has(p.id)} onToggle={() => toggle(p.id)} />
        ))}
      </div>
    </div>
  );
}

function ProjectRow({
  project,
  expanded,
  onToggle,
}: {
  project: Project;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const remove = useMutation({
    mutationFn: () => api.deleteProject(project.id),
    onSuccess: () => {
      setMenuOpen(false);
      setConfirming(false);
      queryClient.setQueryData<Project[]>(["projects"], (old) => old?.filter((p) => p.id !== project.id));
      queryClient.removeQueries({ queryKey: ["sessions", project.id] });
      const { selected, select } = useAppStore.getState();
      if (selected?.pid === project.id) select(null);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const closeMenu = () => {
    setMenuOpen(false);
    setConfirming(false);
    remove.reset();
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
        className={clsx(
          "group relative flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 select-none hover:bg-zinc-900 focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:outline-none",
          project.missing && "opacity-50",
        )}
        title={project.root}
      >
        <span
          className={clsx(
            "w-3 shrink-0 text-center text-[10px] text-zinc-600 transition-transform duration-150",
            expanded && "rotate-90",
          )}
        >
          ▶
        </span>
        <span className="truncate text-sm text-zinc-200">{project.name}</span>
        {project.missing && (
          <span title="Project folder is missing" className="shrink-0 text-xs text-amber-400">
            ⚠
          </span>
        )}
        <span className="ml-auto shrink-0 rounded-full bg-zinc-800 px-1.5 py-px text-[10px] tabular-nums text-zinc-400">
          {project.session_count}
        </span>
        <button
          type="button"
          title="New session"
          aria-label={`New session in ${project.name}`}
          onClick={(e) => {
            e.stopPropagation();
            closeMenu();
            useAppStore.getState().select({ pid: project.id, compose: true });
          }}
          className="shrink-0 rounded p-0.5 leading-none text-zinc-500 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-zinc-800 hover:text-violet-300 focus-visible:opacity-100"
        >
          +
        </button>
        <button
          type="button"
          aria-label={`Project menu for ${project.name}`}
          onClick={(e) => {
            e.stopPropagation();
            if (menuOpen) closeMenu();
            else setMenuOpen(true);
          }}
          className={clsx(
            "shrink-0 rounded p-0.5 leading-none text-zinc-500 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-zinc-800 hover:text-zinc-200 focus-visible:opacity-100",
            menuOpen && "opacity-100",
          )}
        >
          ⋯
        </button>

        {menuOpen && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={(e) => {
                e.stopPropagation();
                closeMenu();
              }}
            />
            <div
              className="absolute top-7 right-1 z-20 w-48 rounded-md border border-zinc-700 bg-zinc-900 p-1 shadow-xl shadow-black/50"
              onClick={(e) => e.stopPropagation()}
            >
              {confirming ? (
                <div className="px-2 py-1.5 text-xs">
                  <div className="mb-2 text-zinc-300">
                    Remove <span className="font-medium text-zinc-100">{project.name}</span>?
                  </div>
                  {remove.isError && (
                    <div className="mb-2 text-[11px] text-red-400">
                      {remove.error instanceof Error ? remove.error.message : "Failed to remove"}
                    </div>
                  )}
                  <div className="flex justify-end gap-1.5">
                    <button
                      type="button"
                      className="rounded px-2 py-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                      onClick={closeMenu}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      disabled={remove.isPending}
                      className="rounded bg-red-600/80 px-2 py-1 font-medium text-white hover:bg-red-500 disabled:opacity-50"
                      onClick={() => remove.mutate()}
                    >
                      {remove.isPending ? "Removing…" : "Remove"}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                    onClick={() => {
                      closeMenu();
                      useAppStore.getState().select({ pid: project.id, settings: true });
                    }}
                  >
                    Settings
                  </button>
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                    onClick={() => {
                      closeMenu();
                      useAppStore.getState().select({ pid: project.id, compose: true });
                    }}
                  >
                    New session
                  </button>
                  <div className="my-1 h-px bg-zinc-800" />
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1.5 text-left text-xs text-red-400 hover:bg-zinc-800 hover:text-red-300"
                    onClick={() => setConfirming(true)}
                  >
                    Remove
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </div>

      {expanded && <SessionList pid={project.id} />}
    </div>
  );
}

function SessionList({ pid }: { pid: string }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["sessions", pid],
    queryFn: () => api.sessions(pid),
  });
  const [showArchived, setShowArchived] = useState(false);

  const sessions = data ?? [];
  const archivedCount = sessions.filter((s) => s.archived).length;
  const visible = sessions
    .filter((s) => showArchived || !s.archived)
    .sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return timestamp(b) - timestamp(a);
    });

  return (
    <div className="mt-px mr-1 mb-1 ml-[15px] space-y-px border-l border-zinc-800/80 pl-1.5">
      {isPending && <div className="px-2 py-1.5 text-[11px] text-zinc-600">Loading sessions…</div>}
      {isError && <div className="px-2 py-1.5 text-[11px] text-red-400/80">Couldn’t load sessions</div>}
      {data && visible.length === 0 && (
        <div className="px-2 py-1.5 text-[11px] text-zinc-600">No sessions</div>
      )}
      {visible.map((s) => (
        <SessionRow key={s.id} pid={pid} session={s} />
      ))}
      {archivedCount > 0 && (
        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className="w-full rounded px-2 py-1 text-left text-[10px] text-zinc-600 hover:bg-zinc-900 hover:text-zinc-400 focus-visible:outline-none"
        >
          {showArchived ? "hide archived" : `show archived (${archivedCount})`}
        </button>
      )}
    </div>
  );
}

function SessionRow({ pid, session }: { pid: string; session: SessionSummary }) {
  const selected = useAppStore((s) => s.selected);
  const select = useAppStore((s) => s.select);
  const statuses = useAppStore((s) => s.sessionStatuses);
  const agents = useAppStore((s) => s.agents[session.id]);

  const [agentsExpanded, setAgentsExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);

  const isSelected = selected?.pid === pid && selected.sid === session.id;
  const liveStatus = statuses[session.id] ?? session.status;

  // Fetch the agent list when expanded (the selected session already streams it
  // live via its topic, so only fetch for non-selected rows). Result is mirrored
  // into the store via the effect below so the dots share one source of truth.
  const agentsQuery = useQuery({
    queryKey: ["session-agents", session.id],
    queryFn: () => api.sessionAgents(session.id),
    enabled: agentsExpanded && !isSelected,
    staleTime: 15_000,
  });
  useEffect(() => {
    if (agentsQuery.data && !isSelected) useAppStore.getState().setAgents(session.id, agentsQuery.data);
  }, [agentsQuery.data, agentsQuery.dataUpdatedAt, isSelected, session.id]);

  const agentList = agents ?? [];

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => select({ pid, sid: session.id })}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            select({ pid, sid: session.id });
          }
        }}
        className={clsx(
          "group/session relative flex cursor-pointer items-center gap-1.5 rounded-md py-1.5 pr-2 pl-1 select-none focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:outline-none",
          isSelected ? "bg-violet-500/10 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-300",
          session.archived && "opacity-60",
        )}
        title={session.title || session.id}
      >
        <button
          type="button"
          aria-label={agentsExpanded ? "Collapse agents" : "Expand agents"}
          onClick={(e) => {
            e.stopPropagation();
            setAgentsExpanded((v) => !v);
          }}
          className={clsx(
            "w-3 shrink-0 rounded text-center text-[9px] transition-transform duration-150 hover:text-zinc-300",
            agentList.length > 0 ? "text-zinc-500" : "text-zinc-700",
            agentsExpanded && "rotate-90",
          )}
        >
          ▶
        </button>
        <StatusDot status={liveStatus} />
        {session.pinned && (
          <span title="Pinned" className="shrink-0 text-[9px] text-violet-400/70">
            ★
          </span>
        )}
        {renaming ? (
          <RenameField
            sid={session.id}
            initial={session.title ?? ""}
            onDone={() => setRenaming(false)}
          />
        ) : (
          <span className="truncate text-[13px]">{session.title || `${session.id.slice(0, 8)}…`}</span>
        )}
        {session.archived && (
          <span title="Archived" className="shrink-0 text-[9px] text-zinc-600">
            ⊘
          </span>
        )}
        {!renaming && (
          <span className="ml-auto shrink-0 text-[10px] text-zinc-600 group-hover/session:hidden">
            <RelativeTime iso={session.updated_at} />
          </span>
        )}
        {!renaming && (
          <button
            type="button"
            aria-label={`Session menu for ${session.title || session.id}`}
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((v) => !v);
            }}
            className={clsx(
              "ml-auto hidden shrink-0 rounded p-0.5 leading-none text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 group-hover/session:block focus-visible:block",
              menuOpen && "!block",
            )}
          >
            ⋯
          </button>
        )}

        {menuOpen && (
          <SessionMenu
            pid={pid}
            session={session}
            onClose={() => setMenuOpen(false)}
            onRename={() => {
              setMenuOpen(false);
              setRenaming(true);
            }}
          />
        )}
      </div>

      {agentsExpanded && (
        <div className="mt-px mb-0.5 ml-[18px] space-y-px border-l border-zinc-800/60 pl-1.5">
          {agentList.map((a) => (
            <AgentRow key={a.agent_id} pid={pid} sid={session.id} agent={a} />
          ))}
          {agentList.length === 0 &&
            (agentsQuery.isPending && !isSelected ? (
              <div className="px-1.5 py-1 text-[10px] text-zinc-600">Loading agents…</div>
            ) : (
              <div className="px-1.5 py-1 text-[10px] text-zinc-600">No agents</div>
            ))}
        </div>
      )}
    </div>
  );
}

function AgentRow({ pid, sid, agent }: { pid: string; sid: string; agent: AgentInfo }) {
  const select = useAppStore((s) => s.select);
  const selected = useAppStore((s) => s.selected);
  const isActive = selected?.sid === sid && selected.drillAgentId === agent.agent_id;

  return (
    <button
      type="button"
      onClick={() => select({ pid, sid, drillAgentId: agent.agent_id })}
      title={agent.agent_id}
      className={clsx(
        "flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:outline-none",
        isActive ? "bg-violet-500/10 text-zinc-200" : "text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300",
      )}
    >
      <AgentDot status={agent.status} />
      <span className="truncate font-mono text-[11px]">{agent.agent_id.slice(0, 8)}</span>
      {agent.agent_type && (
        <span className="shrink-0 truncate text-[10px] text-zinc-600">{agent.agent_type}</span>
      )}
      <span className="ml-auto shrink-0 rounded-full bg-zinc-800 px-1.5 py-px text-[10px] tabular-nums text-zinc-400">
        {agent.message_count}
      </span>
    </button>
  );
}

function RenameField({ sid, initial, onDone }: { sid: string; initial: string; onDone: () => void }) {
  const [value, setValue] = useState(initial);
  const rename = useMutation({
    mutationFn: (title: string) => api.renameSession(sid, title),
    // session_upserted updates the cache; nothing more to do on success.
    onSuccess: onDone,
  });

  const submit = () => {
    const title = value.trim();
    if (!title || rename.isPending) return;
    if (title === initial.trim()) {
      onDone();
      return;
    }
    rename.mutate(title);
  };

  return (
    <input
      autoFocus
      value={value}
      disabled={rename.isPending}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => setValue(e.target.value)}
      onBlur={onDone}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          submit();
        } else if (e.key === "Escape") {
          e.preventDefault();
          onDone();
        }
      }}
      className="min-w-0 flex-1 rounded border border-violet-500/40 bg-ink-900 px-1 py-0.5 text-[13px] text-zinc-100 outline-none focus:border-violet-500/70 disabled:opacity-50"
    />
  );
}

function SessionMenu({
  pid,
  session,
  onClose,
  onRename,
}: {
  pid: string;
  session: SessionSummary;
  onClose: () => void;
  onRename: () => void;
}) {
  const select = useAppStore((s) => s.select);
  /** null = not confirming; false = first ask; true = retry with ?force=true. */
  const [confirmDelete, setConfirmDelete] = useState(false);

  const pin = useMutation({
    mutationFn: (value: boolean) => api.pinSession(session.id, value),
  });
  const archive = useMutation({
    mutationFn: (value: boolean) => api.archiveSession(session.id, value),
  });
  const fork = useMutation({
    mutationFn: () => api.forkSession(session.id),
    onSuccess: ({ session_id }) => {
      onClose();
      // the new session arrives via session_upserted; select it now.
      select({ pid, sid: session_id });
    },
  });
  const del = useMutation({
    mutationFn: (force?: boolean) => api.deleteSession(session.id, force),
    onSuccess: () => {
      // session_removed normally beats us; remove locally in case it doesn't.
      useAppStore.getState().removeSession(pid, session.id);
      onClose();
    },
  });

  const deleteErr = del.error instanceof ApiError ? del.error : null;
  const isRunning = deleteErr?.status === 409 && deleteErr.code === "SESSION_RUNNING";
  const isExternal = deleteErr?.status === 409 && deleteErr.code === "EXTERNAL_ACTIVITY";

  return (
    <>
      <div
        className="fixed inset-0 z-10"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
      />
      <div
        className="absolute top-7 right-1 z-20 w-44 rounded-md border border-zinc-700 bg-zinc-900 p-1 shadow-xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        {confirmDelete ? (
          <div className="px-2 py-1.5 text-xs">
            <div className="mb-2 text-zinc-300">Delete this session?</div>
            {isRunning && <div className="mb-2 text-[11px] text-red-400">Can’t delete a running session</div>}
            {isExternal && (
              <div className="mb-2 text-[11px] text-amber-400">This session looks active in a terminal.</div>
            )}
            {deleteErr && !isRunning && !isExternal && (
              <div className="mb-2 text-[11px] text-red-400">{deleteErr.message}</div>
            )}
            <div className="flex justify-end gap-1.5">
              <button
                type="button"
                className="rounded px-2 py-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                onClick={() => {
                  setConfirmDelete(false);
                  del.reset();
                }}
              >
                Cancel
              </button>
              {isExternal ? (
                <button
                  type="button"
                  disabled={del.isPending}
                  className="rounded bg-amber-500/80 px-2 py-1 font-medium text-white hover:bg-amber-500 disabled:opacity-50"
                  onClick={() => del.mutate(true)}
                >
                  {del.isPending ? "Deleting…" : "Delete anyway"}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={del.isPending || isRunning}
                  className="rounded bg-red-600/80 px-2 py-1 font-medium text-white hover:bg-red-500 disabled:opacity-50"
                  onClick={() => del.mutate(undefined)}
                >
                  {del.isPending ? "Deleting…" : "Delete"}
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            <MenuItem label="Rename" onClick={onRename} />
            <MenuItem
              label={session.pinned ? "Unpin" : "Pin"}
              disabled={pin.isPending}
              onClick={() => {
                pin.mutate(!session.pinned);
                onClose();
              }}
            />
            <MenuItem
              label={session.archived ? "Unarchive" : "Archive"}
              disabled={archive.isPending}
              onClick={() => {
                archive.mutate(!session.archived);
                onClose();
              }}
            />
            <MenuItem label={fork.isPending ? "Forking…" : "Fork"} disabled={fork.isPending} onClick={() => fork.mutate()} />
            {fork.isError && (
              <div className="px-2 py-1 text-[11px] text-red-400">
                {fork.error instanceof Error ? fork.error.message : "Fork failed"}
              </div>
            )}
            <div className="my-1 h-px bg-zinc-800" />
            <button
              type="button"
              className="w-full rounded px-2 py-1.5 text-left text-xs text-red-400 hover:bg-zinc-800 hover:text-red-300"
              onClick={() => setConfirmDelete(true)}
            >
              Delete
            </button>
          </>
        )}
      </div>
    </>
  );
}

function MenuItem({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      className="w-full rounded px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function timestamp(s: SessionSummary): number {
  if (!s.updated_at) return 0;
  const t = Date.parse(s.updated_at);
  return Number.isNaN(t) ? 0 : t;
}
