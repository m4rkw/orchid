import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "../../api/client";
import type { CollabMessage } from "../../api/types";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";
import { socket } from "../../ws/socket";

const MAX_COMPOSER_HEIGHT_PX = 144;

export function CollaborationView({ cid }: { cid: string }) {
  const ensureCollab = useAppStore((s) => s.ensureCollab);
  const seedCollab = useAppStore((s) => s.seedCollab);
  const buf = useAppStore((s) => s.collabBuffers[cid]);

  const { data: collab } = useQuery({
    queryKey: ["collab", cid],
    queryFn: () => api.collaboration(cid),
    refetchInterval: 30_000,
  });

  useEffect(() => {
    ensureCollab(cid);
  }, [cid, ensureCollab]);

  useEffect(() => {
    if (collab?.messages) {
      seedCollab(cid, collab.messages);
    }
  }, [cid, collab, seedCollab]);

  useEffect(() => {
    const topic = `collab:${cid}`;
    socket.subscribe(topic);
    return () => socket.unsubscribe(topic);
  }, [cid]);

  const messages = buf?.messages ?? collab?.messages ?? [];
  const responding = buf?.responding ?? false;
  const respondingLabel = buf?.respondingLabel ?? null;
  const isActive = collab?.state === "active";
  const autoContinue = collab?.auto_continue ?? true;

  return (
    <div className="flex h-full flex-col">
      <Header cid={cid} title={collab?.title} participants={collab?.participants} state={collab?.state} />
      <MessageList messages={messages} responding={responding} respondingLabel={respondingLabel} />
      {isActive && (
        <Composer
          cid={cid}
          responding={responding}
          autoContinue={autoContinue}
        />
      )}
      {collab?.state === "completed" && (
        <div className="shrink-0 border-t border-zinc-800 px-4 py-3 text-center text-sm text-zinc-500">
          Collaboration ended
        </div>
      )}
    </div>
  );
}

function Header({
  cid,
  title,
  participants,
  state,
}: {
  cid: string;
  title?: string;
  participants?: Array<{ project_id: string; label: string }>;
  state?: string;
}) {
  const endCollab = useMutation({
    mutationFn: () => api.endCollab(cid),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["collab", cid] });
      void queryClient.invalidateQueries({ queryKey: ["collaborations"] });
    },
  });

  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-zinc-800 px-4 py-2.5">
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-sm font-medium text-zinc-200">
          {title ?? "Collaboration"}
        </h2>
        {participants && (
          <div className="mt-0.5 flex flex-wrap gap-1.5">
            {participants.map((p) => (
              <span
                key={p.project_id}
                className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400"
              >
                {p.label}
              </span>
            ))}
          </div>
        )}
      </div>
      {state === "active" && (
        <button
          type="button"
          onClick={() => endCollab.mutate()}
          disabled={endCollab.isPending}
          className="shrink-0 rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:border-red-500/50 hover:text-red-400 disabled:opacity-50"
        >
          End
        </button>
      )}
    </div>
  );
}

function MessageList({
  messages,
  responding,
  respondingLabel,
}: {
  messages: CollabMessage[];
  responding: boolean;
  respondingLabel: string | null;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, responding]);

  const colorFor = (sender: string): string => {
    if (sender === "user") return "text-violet-300";
    const colors = ["text-sky-300", "text-emerald-300", "text-amber-300", "text-rose-300", "text-cyan-300"];
    let hash = 0;
    for (let i = 0; i < sender.length; i++) hash = (hash * 31 + sender.charCodeAt(i)) | 0;
    return colors[Math.abs(hash) % colors.length];
  };

  return (
    <div ref={containerRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
      <div className="mx-auto max-w-3xl space-y-4">
        {messages.map((m) => (
          <div key={m.id}>
            <div className="mb-1 flex items-center gap-2">
              <span className={clsx("text-xs font-medium", colorFor(m.sender))}>
                {m.sender_label}
              </span>
              <span className="text-[10px] text-zinc-600">
                {formatTime(m.timestamp)}
              </span>
            </div>
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
              {m.content}
            </div>
          </div>
        ))}
        {responding && (
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span className="size-3 animate-spin rounded-full border border-zinc-600 border-t-zinc-300" />
            {respondingLabel ? `${respondingLabel} is responding…` : "Agent responding…"}
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function Composer({
  cid,
  responding,
  autoContinue,
}: {
  cid: string;
  responding: boolean;
  autoContinue: boolean;
}) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_COMPOSER_HEIGHT_PX)}px`;
  }, [value]);

  const sendMsg = useMutation({
    mutationFn: (text: string) => api.sendCollabMessage(cid, text),
    onSuccess: () => {
      setValue("");
      void queryClient.invalidateQueries({ queryKey: ["collab", cid] });
    },
  });

  const toggleAuto = useMutation({
    mutationFn: (v: boolean) => api.setCollabAutoContinue(cid, v),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["collab", cid] }),
  });

  const resumeRelay = useMutation({
    mutationFn: () => api.continueCollab(cid),
  });

  const send = () => {
    const text = value.trim();
    if (!text || sendMsg.isPending) return;
    sendMsg.mutate(text);
  };

  return (
    <div className="shrink-0 border-t border-zinc-800 p-4 pt-3">
      <div
        className={clsx(
          "mx-auto flex max-w-3xl items-end gap-2 rounded-xl border bg-ink-900 px-3 py-2 transition-colors",
          responding ? "border-violet-500/40" : "border-zinc-700 focus-within:border-violet-500/60",
        )}
      >
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          disabled={sendMsg.isPending}
          placeholder="Send a message to the collaboration…"
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
          disabled={sendMsg.isPending || value.trim() === ""}
          className="mb-px shrink-0 rounded-lg bg-violet-600 px-3 py-1 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </div>
      <div className="mx-auto mt-2 flex max-w-3xl items-center justify-between px-1">
        <label className="flex items-center gap-2 text-[11px] text-zinc-500">
          <input
            type="checkbox"
            checked={autoContinue}
            onChange={(e) => toggleAuto.mutate(e.target.checked)}
            className="accent-violet-500"
          />
          Auto-continue
        </label>
        {!responding && !autoContinue && (
          <button
            type="button"
            onClick={() => resumeRelay.mutate()}
            disabled={resumeRelay.isPending}
            className="rounded border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400 hover:border-violet-500/50 hover:text-violet-300 disabled:opacity-50"
          >
            Continue
          </button>
        )}
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}
