import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { RoleTemplate } from "../../api/types";
import { queryClient } from "../../state/queryClient";

/**
 * Per-project agent roles. The orchestrator is the session you drive; the
 * subagents (worker/reviewer/verifier) are the ones it delegates to. The four
 * "infra" roles are intentionally covered by Orchid/the model and shown for
 * context only — toggling them would have no runtime effect, so they're read-only.
 */
export function AgentRoles({ pid }: { pid: string }) {
  const roles = useQuery({ queryKey: ["agents", pid], queryFn: () => api.projectAgents(pid) });
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  const save = useMutation({
    mutationFn: (next: RoleTemplate[]) => api.setProjectAgents(pid, next),
    onSuccess: (updated) => {
      queryClient.setQueryData<RoleTemplate[]>(["agents", pid], updated);
      setOverrides({});
    },
  });

  const data = roles.data;
  const enabledOf = (r: RoleTemplate) => overrides[r.slug] ?? r.enabled;
  const dirty = !!data && data.some((r) => r.slug in overrides && overrides[r.slug] !== r.enabled);

  const submit = () => {
    if (!data) return;
    save.mutate(data.map((r) => ({ ...r, enabled: enabledOf(r) })));
  };

  const orchestrator = data?.find((r) => r.kind === "orchestrator");
  const subagents = data?.filter((r) => r.kind === "subagent") ?? [];
  const infra = data?.filter((r) => r.kind === "infra") ?? [];

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-zinc-100">Agent roles</h3>
        {dirty && (
          <button
            type="button"
            onClick={submit}
            disabled={save.isPending}
            className="rounded-md bg-violet-600 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-40"
          >
            {save.isPending ? "Saving…" : "Save roles"}
          </button>
        )}
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
        The orchestrator session decomposes a goal, keeps the plan on disk, and delegates to the
        enabled subagents. Start it from a project’s ⋯ menu → “Start orchestrator”.
      </p>

      {roles.isPending && <div className="mt-3 text-xs text-zinc-600">Loading roles…</div>}
      {roles.isError && <div className="mt-3 text-xs text-red-400/80">Couldn’t load roles.</div>}

      {data && (
        <div className="mt-3 space-y-1.5">
          {orchestrator && (
            <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-violet-200">{orchestrator.name}</span>
                <span className="rounded-full bg-violet-500/20 px-1.5 py-px text-[10px] text-violet-300">always on</span>
              </div>
              <p className="mt-0.5 text-[11px] text-zinc-400">{orchestrator.summary}</p>
            </div>
          )}

          {subagents.map((r) => (
            <label
              key={r.slug}
              className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-zinc-800 px-3 py-2 hover:border-zinc-700"
            >
              <input
                type="checkbox"
                checked={enabledOf(r)}
                onChange={(e) => setOverrides((o) => ({ ...o, [r.slug]: e.target.checked }))}
                className="mt-0.5 h-3.5 w-3.5 accent-violet-500"
              />
              <span className="min-w-0">
                <span className="text-xs font-medium text-zinc-200">{r.name}</span>
                <span className="block text-[11px] leading-relaxed text-zinc-500">{r.summary}</span>
              </span>
            </label>
          ))}

          {infra.length > 0 && (
            <details className="rounded-lg border border-zinc-800/60 px-3 py-2">
              <summary className="cursor-pointer text-[11px] text-zinc-500 select-none">
                {infra.length} roles already covered by Orchid / the model
              </summary>
              <ul className="mt-2 space-y-2">
                {infra.map((r) => (
                  <li key={r.slug} className="text-[11px] leading-relaxed">
                    <span className="text-zinc-400">{r.name}</span>
                    <span className="block text-zinc-600">{r.note}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {save.isError && (
        <div className="mt-2 text-[11px] text-red-400">
          {save.error instanceof Error ? save.error.message : "Failed to save roles"}
        </div>
      )}
    </div>
  );
}
