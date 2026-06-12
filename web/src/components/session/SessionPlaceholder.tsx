import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useAppStore } from "../../state/stores";
import { CopyButton } from "../common/CopyButton";
import { StatusDot } from "../common/StatusDot";

export function SessionPlaceholder({ pid, sid }: { pid: string; sid: string }) {
  const { data } = useQuery({
    queryKey: ["sessions", pid],
    queryFn: () => api.sessions(pid),
  });
  const statusOverride = useAppStore((s) => s.sessionStatuses[sid]);

  const session = data?.find((s) => s.id === sid);
  const status = statusOverride ?? session?.status ?? "idle";
  const title = session?.title || `${sid.slice(0, 8)}…`;
  const resumeCommand = `claude --resume ${sid}`;

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-8">
      <div className="fade-up w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900/40 p-8 text-center shadow-xl shadow-black/30">
        <div className="flex items-center justify-center gap-2.5">
          <StatusDot status={status} />
          <h2 className="truncate text-base font-medium text-zinc-100">{title}</h2>
        </div>
        <div className="mt-1.5 font-mono text-[11px] break-all text-zinc-600">{sid}</div>

        <p className="mt-6 text-sm text-zinc-500">Session view arrives in M2.</p>

        <div className="mt-6 flex items-center gap-2 rounded-lg border border-zinc-800 bg-black/40 py-2 pr-2 pl-3">
          <code className="min-w-0 flex-1 truncate text-left font-mono text-xs text-zinc-300">{resumeCommand}</code>
          <CopyButton text={resumeCommand} />
        </div>
        <p className="mt-2 text-[11px] text-zinc-600">Run this in the project root to pick the session up in your terminal.</p>
      </div>
    </div>
  );
}
