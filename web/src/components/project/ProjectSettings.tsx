import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { PermissionMode, Project, ProjectUpdate } from "../../api/types";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";
import { AgentRoles } from "./AgentRoles";
import { PolicyEditor } from "./PolicyEditor";

const MODEL_PRESETS = ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"] as const;
const PERMISSION_MODES: PermissionMode[] = ["acceptEdits", "default", "plan", "bypassPermissions"];

const INHERIT = "__inherit__";

/**
 * Right-pane project settings form.
 *
 * GET /api/projects does NOT return `settings`, so the model / permission-mode
 * fields can't be pre-populated — they start at their defaults (inherit /
 * acceptEdits) and only take effect once saved.
 */
export function ProjectSettings({ pid }: { pid: string }) {
  const select = useAppStore((s) => s.select);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const project = projects.data?.find((p) => p.id === pid);

  const [name, setName] = useState(project?.name ?? "");
  /** Either INHERIT, a preset id, or free-text. */
  const [model, setModel] = useState<string>(INHERIT);
  const [customModel, setCustomModel] = useState("");
  const [permissionMode, setPermissionMode] = useState<PermissionMode>("acceptEdits");
  // Once the projects query resolves, adopt the real name (only if untouched).
  const [nameTouched, setNameTouched] = useState(false);
  const effectiveName = nameTouched ? name : (project?.name ?? "");

  const save = useMutation({
    mutationFn: (patch: ProjectUpdate) => api.updateProject(pid, patch),
    onSuccess: (updated: Project) => {
      // project_updated normally beats us; patch the cache directly too.
      queryClient.setQueryData<Project[]>(["projects"], (old) =>
        old?.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)),
      );
    },
  });

  const submit = () => {
    if (save.isPending) return;
    const trimmedName = effectiveName.trim();
    const modelValue =
      model === INHERIT ? null : model === "__custom__" ? customModel.trim() || null : model;
    const patch: ProjectUpdate = {
      ...(trimmedName && trimmedName !== project?.name ? { name: trimmedName } : {}),
      settings: { model: modelValue, permission_mode: permissionMode },
    };
    save.mutate(patch);
  };

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="mx-auto w-full max-w-xl space-y-4">
      <div className="fade-up rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 shadow-xl shadow-black/30">
        <div className="flex items-baseline gap-2">
          <h2 className="text-base font-medium text-zinc-100">Project settings</h2>
          <span className="min-w-0 truncate text-xs text-zinc-500" title={project?.root}>
            {project?.root}
          </span>
        </div>

        <div className="mt-5 space-y-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-zinc-400">Name</span>
            <input
              value={effectiveName}
              onChange={(e) => {
                setNameTouched(true);
                setName(e.target.value);
              }}
              className="w-full rounded-lg border border-zinc-700 bg-ink-900 px-3 py-1.5 text-sm text-zinc-100 outline-none focus:border-violet-500/60"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-zinc-400">Default model</span>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-ink-900 px-3 py-1.5 text-sm text-zinc-100 outline-none focus:border-violet-500/60"
            >
              <option value={INHERIT}>inherit (default)</option>
              {MODEL_PRESETS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
              <option value="__custom__">custom…</option>
            </select>
            {model === "__custom__" && (
              <input
                autoFocus
                value={customModel}
                placeholder="model id"
                onChange={(e) => setCustomModel(e.target.value)}
                className="mt-2 w-full rounded-lg border border-zinc-700 bg-ink-900 px-3 py-1.5 font-mono text-sm text-zinc-100 outline-none focus:border-violet-500/60"
              />
            )}
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-zinc-400">Default permission mode</span>
            <select
              value={permissionMode}
              onChange={(e) => setPermissionMode(e.target.value as PermissionMode)}
              className="w-full rounded-lg border border-zinc-700 bg-ink-900 px-3 py-1.5 text-sm text-zinc-100 outline-none focus:border-violet-500/60"
            >
              {PERMISSION_MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
        </div>

        <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
          Current model / permission mode aren’t returned by the API, so these start at their defaults
          (inherit / acceptEdits). Saving overwrites them.
        </p>

        {save.isError && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            <span className="min-w-0 break-words">
              {save.error instanceof Error ? save.error.message : "Failed to save settings"}
            </span>
          </div>
        )}

        <div className="mt-5 flex items-center gap-3">
          <button
            type="button"
            onClick={submit}
            disabled={save.isPending || !effectiveName.trim()}
            className="rounded-lg bg-violet-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-violet-600"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {save.isSuccess && !save.isPending && (
            <span className="text-xs text-violet-300/80">Saved</span>
          )}
          <button
            type="button"
            onClick={() => select(null)}
            className="ml-auto rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-300"
          >
            Close
          </button>
        </div>
      </div>

      <div className="fade-up rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 shadow-xl shadow-black/30">
        <PolicyEditor pid={pid} />
      </div>

      <div className="fade-up rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 shadow-xl shadow-black/30">
        <AgentRoles pid={pid} />
      </div>
      </div>
    </div>
  );
}
