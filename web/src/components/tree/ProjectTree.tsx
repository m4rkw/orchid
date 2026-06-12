import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "../../api/client";
import type { Project, SessionSummary } from "../../api/types";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";
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
                <button
                  type="button"
                  className="w-full rounded px-2 py-1.5 text-left text-xs text-red-400 hover:bg-zinc-800 hover:text-red-300"
                  onClick={() => setConfirming(true)}
                >
                  Remove
                </button>
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
  const selected = useAppStore((s) => s.selected);
  const select = useAppStore((s) => s.select);
  const statuses = useAppStore((s) => s.sessionStatuses);

  const visible = (data ?? [])
    .filter((s) => !s.archived)
    .sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return timestamp(b) - timestamp(a);
    });

  return (
    <div className="mt-px mr-1 mb-1 ml-[15px] space-y-px border-l border-zinc-800/80 pl-1.5">
      {isPending && <div className="px-2 py-1.5 text-[11px] text-zinc-600">Loading sessions…</div>}
      {isError && <div className="px-2 py-1.5 text-[11px] text-red-400/80">Couldn’t load sessions</div>}
      {data && visible.length === 0 && <div className="px-2 py-1.5 text-[11px] text-zinc-600">No sessions</div>}
      {visible.map((s) => {
        const isSelected = selected?.pid === pid && selected.sid === s.id;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => select({ pid, sid: s.id })}
            className={clsx(
              "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:outline-none",
              isSelected ? "bg-violet-500/10 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-300",
            )}
          >
            <StatusDot status={statuses[s.id] ?? s.status} />
            {s.pinned && (
              <span title="Pinned" className="shrink-0 text-[9px] text-violet-400/70">
                ★
              </span>
            )}
            <span className="truncate text-[13px]">{s.title || `${s.id.slice(0, 8)}…`}</span>
            <span className="ml-auto shrink-0 text-[10px] text-zinc-600">
              <RelativeTime iso={s.updated_at} />
            </span>
          </button>
        );
      })}
    </div>
  );
}

function timestamp(s: SessionSummary): number {
  if (!s.updated_at) return 0;
  const t = Date.parse(s.updated_at);
  return Number.isNaN(t) ? 0 : t;
}
