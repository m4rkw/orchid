import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "../../api/client";
import type { AgentInfo, NormalizedMessage } from "../../api/types";
import { queryClient } from "../../state/queryClient";
import { MessageList } from "../common/MessageList";

export function AgentDot({ status }: { status: AgentInfo["status"] }) {
  return (
    <span
      aria-label={status}
      title={status}
      className={clsx(
        "inline-block size-2 shrink-0 rounded-full",
        status === "running" ? "animate-pulse bg-violet-400 shadow-[0_0_6px] shadow-violet-400/60" : "bg-zinc-500",
      )}
    />
  );
}

/** Right-edge column listing the session's sub-agents; click a row to drill in. */
export function AgentPanel({ agents, onSelect }: { agents: AgentInfo[]; onSelect: (aid: string) => void }) {
  return (
    <div className="flex w-60 shrink-0 flex-col border-l border-zinc-800">
      <div className="shrink-0 px-3 pt-3 pb-2 text-[11px] font-medium tracking-wider text-zinc-500 uppercase">
        Agents
      </div>
      <div className="min-h-0 flex-1 space-y-px overflow-y-auto px-2 pb-3">
        {agents.length === 0 && <div className="px-2 py-1.5 text-[11px] text-zinc-600">No agents</div>}
        {agents.map((a) => (
          <button
            key={a.agent_id}
            type="button"
            onClick={() => onSelect(a.agent_id)}
            title={a.agent_id}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:outline-none"
          >
            <AgentDot status={a.status} />
            <span className="truncate font-mono text-xs">{a.agent_id.slice(0, 8)}</span>
            <span className="ml-auto shrink-0 rounded-full bg-zinc-800 px-1.5 py-px text-[10px] tabular-nums text-zinc-400">
              {a.message_count}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Slide-over panel showing one agent's transcript (fetched on open). */
export function AgentDrillIn({
  sid,
  agent,
  onClose,
}: {
  sid: string;
  agent: AgentInfo;
  onClose: () => void;
}) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["agent-messages", sid, agent.agent_id],
    queryFn: () => api.agentMessages(sid, agent.agent_id),
    refetchOnMount: "always",
    staleTime: 0,
  });

  // "show full" swaps the untruncated message into this query's cache.
  const showFull = async (uuid: string) => {
    const full = await api.sessionMessage(sid, uuid);
    queryClient.setQueryData<{ messages: NormalizedMessage[] }>(["agent-messages", sid, agent.agent_id], (old) =>
      old ? { messages: old.messages.map((m) => (m.uuid === uuid ? full : m)) } : old,
    );
  };

  return (
    <div className="absolute inset-0 z-20 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="fade-up flex h-full w-full max-w-2xl flex-col border-l border-zinc-800 bg-ink-950 shadow-2xl shadow-black/60"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex h-11 shrink-0 items-center gap-2.5 border-b border-zinc-800 px-4">
          <AgentDot status={agent.status} />
          <span className="font-mono text-sm text-zinc-200">agent {agent.agent_id.slice(0, 8)}</span>
          <span className="text-[11px] text-zinc-600">
            {agent.message_count} {agent.message_count === 1 ? "message" : "messages"} · {agent.status}
          </span>
          <button
            type="button"
            aria-label="Close agent view"
            onClick={onClose}
            className="ml-auto rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-200"
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isPending && <div className="px-4 py-6 text-center text-xs text-zinc-600">Loading agent messages…</div>}
          {isError && (
            <div className="px-4 py-6 text-center text-xs text-red-400/80">
              Couldn’t load agent messages.{" "}
              <button type="button" className="underline hover:text-red-300" onClick={() => void refetch()}>
                retry
              </button>
            </div>
          )}
          {data && data.messages.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-zinc-600">No messages yet</div>
          )}
          {data && data.messages.length > 0 && (
            <MessageList messages={data.messages} running={agent.status === "running"} onShowFull={showFull} />
          )}
        </div>
      </div>
    </div>
  );
}
