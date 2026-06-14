import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api, ApiError } from "../../api/client";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";

const MAX_COMPOSER_HEIGHT_PX = 144;

/** Full-pane new-session view: empty transcript + composer. First send creates the session. */
export function NewSessionComposer({ pid }: { pid: string }) {
  const select = useAppStore((s) => s.select);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const project = projects.data?.find((p) => p.id === pid);

  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => textareaRef.current?.focus(), []);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_COMPOSER_HEIGHT_PX)}px`;
  }, [value]);

  const create = useMutation({
    mutationFn: (text: string) => api.createSession(pid, text),
    onSuccess: ({ session_id }) => {
      void queryClient.invalidateQueries({ queryKey: ["sessions", pid] });
      select({ pid, sid: session_id });
    },
  });

  const send = () => {
    const text = value.trim();
    if (!text || create.isPending) return;
    create.mutate(text);
  };

  const isTimeout = create.error instanceof ApiError && create.error.status === 504;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center border-b border-zinc-800 px-4">
        <h2 className="text-sm font-medium text-zinc-200">New session</h2>
        <span className="ml-2 min-w-0 truncate text-xs text-zinc-500" title={project?.root}>
          in {project?.name ?? pid}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 items-center justify-center">
        <p className="text-sm text-zinc-600">Type a prompt below to start</p>
      </div>

      <div className="shrink-0 border-t border-zinc-800 p-4 pt-3">
        {create.isError && (
          <div className="mx-auto mb-2 flex max-w-3xl items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            <span className="shrink-0 font-medium">Error:</span>
            <span className="min-w-0 break-words">
              {isTimeout
                ? "Timed out waiting for the session to start. It may still come up — or retry."
                : create.error instanceof Error
                  ? create.error.message
                  : "Failed to start session"}
            </span>
            <button
              type="button"
              aria-label="Dismiss error"
              className="ml-auto shrink-0 text-red-400/70 hover:text-red-300"
              onClick={() => create.reset()}
            >
              ✕
            </button>
          </div>
        )}
        <div
          className={clsx(
            "mx-auto flex max-w-3xl items-end gap-2 rounded-xl border bg-ink-900 px-3 py-2 transition-colors",
            create.isPending ? "border-violet-500/40" : "border-zinc-700 focus-within:border-violet-500/60",
          )}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            disabled={create.isPending}
            placeholder="What should Orchid do in this project?"
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send();
              }
            }}
            className="max-h-36 min-h-6 w-full resize-none bg-transparent text-base leading-6 text-zinc-100 outline-none placeholder:text-zinc-600 disabled:opacity-50 md:text-sm"
          />
          <button
            type="button"
            onClick={send}
            disabled={create.isPending || value.trim() === ""}
            className="mb-px shrink-0 rounded-lg bg-violet-600 px-3 py-1 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-violet-600"
          >
            Send
          </button>
        </div>
        <div className="mx-auto mt-1.5 max-w-3xl px-1 text-[10px] text-zinc-600">
          {create.isPending ? (
            <span className="flex items-center gap-2 text-violet-300/80">
              <span className="size-3 animate-spin rounded-full border border-violet-400/30 border-t-violet-300" />
              Starting session… (can take up to 30s)
            </span>
          ) : (
            "Enter to send · Shift+Enter for newline"
          )}
        </div>
      </div>
    </div>
  );
}
