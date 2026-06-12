import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";

/** Right-pane form for starting a fresh session in a project. */
export function NewSessionComposer({ pid }: { pid: string }) {
  const select = useAppStore((s) => s.select);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const project = projects.data?.find((p) => p.id === pid);

  const [prompt, setPrompt] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => textareaRef.current?.focus(), []);

  const create = useMutation({
    mutationFn: (text: string) => api.createSession(pid, text),
    onSuccess: ({ session_id }) => {
      // session_upserted usually beats us; invalidate in case it didn't.
      void queryClient.invalidateQueries({ queryKey: ["sessions", pid] });
      select({ pid, sid: session_id });
    },
  });

  const start = () => {
    const text = prompt.trim();
    if (!text || create.isPending) return;
    create.mutate(text);
  };

  const isTimeout = create.error instanceof ApiError && create.error.status === 504;

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-8">
      <div className="fade-up w-full max-w-xl rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 shadow-xl shadow-black/30">
        <div className="flex items-baseline gap-2">
          <h2 className="text-base font-medium text-zinc-100">New session</h2>
          <span className="min-w-0 truncate text-xs text-zinc-500" title={project?.root}>
            in {project?.name ?? pid}
          </span>
        </div>

        <textarea
          ref={textareaRef}
          rows={6}
          value={prompt}
          disabled={create.isPending}
          placeholder="What should Claude do in this project?"
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              start();
            }
          }}
          className="mt-4 w-full resize-y rounded-xl border border-zinc-700 bg-ink-900 px-3 py-2.5 text-sm leading-6 text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-violet-500/60 disabled:opacity-50"
        />

        {create.isError && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            <span className="min-w-0 break-words">
              {isTimeout
                ? "Timed out waiting for the session to start. It may still come up — or retry."
                : create.error instanceof Error
                  ? create.error.message
                  : "Failed to start session"}
            </span>
            <button
              type="button"
              className="ml-auto shrink-0 rounded-md bg-red-500/20 px-2 py-1 font-medium text-red-200 transition-colors hover:bg-red-500/30"
              onClick={start}
            >
              Retry
            </button>
          </div>
        )}

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={start}
            disabled={create.isPending || prompt.trim() === ""}
            className="rounded-lg bg-violet-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-violet-600"
          >
            Start session
          </button>
          {create.isPending && (
            <span className="flex items-center gap-2 text-xs text-violet-300/80">
              <span className="size-3 animate-spin rounded-full border border-violet-400/30 border-t-violet-300" />
              starting session… (can take up to 30s)
            </span>
          )}
          {!create.isPending && (
            <button
              type="button"
              onClick={() => select(null)}
              className="ml-auto rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-300"
            >
              Cancel
            </button>
          )}
        </div>
        <div className="mt-2 text-[10px] text-zinc-600">⌘/Ctrl+Enter to start</div>
      </div>
    </div>
  );
}
