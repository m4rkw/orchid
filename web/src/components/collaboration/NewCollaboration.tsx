import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "../../api/client";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";

export function NewCollaboration() {
  const select = useAppStore((s) => s.select);
  const { data: projects, isPending } = useQuery({
    queryKey: ["collab-eligible"],
    queryFn: api.collabEligibleProjects,
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());

  const create = useMutation({
    mutationFn: () => api.createCollaboration([...selected]),
    onSuccess: (collab) => {
      void queryClient.invalidateQueries({ queryKey: ["collaborations"] });
      select({ collab: collab.id });
    },
  });

  const toggle = (pid: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center border-b border-zinc-800 px-4">
        <h2 className="text-sm font-medium text-zinc-200">New collaboration</h2>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-lg space-y-6">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-zinc-400">
              Select projects to collaborate (2+)
            </label>
            <div className="space-y-1">
              {projects?.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => toggle(p.id)}
                  className={clsx(
                    "flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                    selected.has(p.id)
                      ? "border-violet-500/50 bg-violet-500/10 text-zinc-100"
                      : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200",
                  )}
                >
                  <span
                    className={clsx(
                      "flex size-4 shrink-0 items-center justify-center rounded border text-[10px]",
                      selected.has(p.id)
                        ? "border-violet-500 bg-violet-500 text-white"
                        : "border-zinc-600",
                    )}
                  >
                    {selected.has(p.id) && "✓"}
                  </span>
                  <span className="truncate">{p.name}</span>
                  <span className="ml-auto shrink-0 text-[10px] text-zinc-600">
                    {p.session_count} sessions
                  </span>
                </button>
              ))}
              {isPending && (
                <div className="py-4 text-center text-xs text-zinc-600">Loading…</div>
              )}
              {!isPending && (!projects || projects.length === 0) && (
                <div className="py-4 text-center text-xs text-zinc-600">
                  No projects with active sessions — start a session in a project first
                </div>
              )}
            </div>
          </div>

          {create.isError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {create.error instanceof Error ? create.error.message : "Failed to create collaboration"}
            </div>
          )}

          <button
            type="button"
            onClick={() => create.mutate()}
            disabled={selected.size < 2 || create.isPending}
            className="w-full rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {create.isPending ? "Starting…" : "Start"}
          </button>
        </div>
      </div>
    </div>
  );
}
