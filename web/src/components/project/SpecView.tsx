import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api, ApiError } from "../../api/client";
import { useAppStore } from "../../state/stores";
import { Markdown } from "../common/Markdown";

export function SpecView({ pid }: { pid: string }) {
  const select = useAppStore((s) => s.select);
  const queryClient = useQueryClient();
  const spec = useQuery({
    queryKey: ["spec", pid],
    queryFn: () => api.projectSpec(pid),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });

  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState(false);
  const [draft, setDraft] = useState("");
  const [title, setTitle] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const startEditing = useCallback(() => {
    setDraft(spec.data?.content ?? "");
    setTitle(spec.data?.title ?? "Specification");
    setEditing(true);
    setPreview(false);
  }, [spec.data]);

  const startNew = useCallback(() => {
    setDraft("");
    setTitle("Specification");
    setEditing(true);
    setPreview(false);
  }, []);

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [editing]);

  const save = useMutation({
    mutationFn: () => api.putProjectSpec(pid, draft, title),
    onSuccess: (data) => {
      queryClient.setQueryData(["spec", pid], data);
      setEditing(false);
    },
  });

  const hasSpec = spec.data && !spec.isError;
  const is404 = spec.error instanceof ApiError && spec.error.status === 404;

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="mx-auto w-full max-w-2xl">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-medium text-zinc-100">Specification</h2>
          <div className="flex items-center gap-2">
            {hasSpec && !editing && (
              <button
                type="button"
                onClick={startEditing}
                className="rounded-md px-2 py-1 text-xs text-zinc-400 transition-colors hover:bg-zinc-900 hover:text-zinc-200"
              >
                Edit
              </button>
            )}
            <button
              type="button"
              onClick={() => select(null)}
              className="rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-300"
            >
              Close
            </button>
          </div>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
          The canonical reference for what this project should do. Agents verify their work against
          it and update it when behaviour changes.
        </p>

        {spec.isPending && <div className="mt-6 text-xs text-zinc-600">Loading…</div>}

        {is404 && !editing && (
          <div className="mt-10 text-center">
            <p className="text-xs leading-relaxed text-zinc-600">
              No specification yet. Create one to give agents a canonical reference.
            </p>
            <button
              type="button"
              onClick={startNew}
              className="mt-3 rounded-md bg-violet-600 px-3 py-1.5 text-xs text-white hover:bg-violet-500"
            >
              Create spec
            </button>
          </div>
        )}

        {editing ? (
          <div className="mt-5 space-y-3">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Specification title"
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 outline-none focus:border-violet-500"
            />
            <div className="flex gap-1 border-b border-zinc-800 pb-1">
              <button
                type="button"
                onClick={() => setPreview(false)}
                className={clsx(
                  "rounded-t px-2 py-1 text-xs",
                  !preview ? "bg-zinc-800 text-zinc-200" : "text-zinc-500 hover:text-zinc-300",
                )}
              >
                Write
              </button>
              <button
                type="button"
                onClick={() => setPreview(true)}
                className={clsx(
                  "rounded-t px-2 py-1 text-xs",
                  preview ? "bg-zinc-800 text-zinc-200" : "text-zinc-500 hover:text-zinc-300",
                )}
              >
                Preview
              </button>
            </div>
            {preview ? (
              <div className="min-h-[20rem] rounded-md border border-zinc-700 bg-zinc-900 p-4">
                {draft.trim() ? (
                  <Markdown>{draft}</Markdown>
                ) : (
                  <p className="text-xs text-zinc-600">Nothing to preview</p>
                )}
              </div>
            ) : (
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Write your specification in markdown…"
                rows={24}
                className="w-full resize-y rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-xs leading-relaxed text-zinc-200 outline-none focus:border-violet-500"
              />
            )}
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="rounded-md px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => save.mutate()}
                disabled={save.isPending || !draft.trim()}
                className={clsx(
                  "rounded-md px-3 py-1.5 text-xs text-white",
                  save.isPending ? "bg-violet-700 opacity-60" : "bg-violet-600 hover:bg-violet-500",
                )}
              >
                {save.isPending ? "Saving…" : "Save"}
              </button>
            </div>
            {save.isError && (
              <p className="text-xs text-red-400">
                {save.error instanceof Error ? save.error.message : "Failed to save"}
              </p>
            )}
          </div>
        ) : hasSpec ? (
          <div className="mt-5 fade-up rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
            <div className="flex items-center gap-2">
              <h3 className="min-w-0 truncate text-sm font-medium text-zinc-100">
                {spec.data!.title}
              </h3>
              <span className="shrink-0 rounded-full bg-violet-500/15 px-1.5 py-px text-[10px] text-violet-300">
                v{spec.data!.version}
              </span>
            </div>
            <div className="mt-4">
              <Markdown>{spec.data!.content}</Markdown>
            </div>
            {spec.data!.updated_at && (
              <div className="mt-4 text-[10px] text-zinc-600">
                Updated {new Date(spec.data!.updated_at).toLocaleString()}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
