import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import { OnboardingChat } from "./components/onboarding/OnboardingChat";
import { ProjectSettings } from "./components/project/ProjectSettings";
import { NewSessionComposer } from "./components/session/NewSessionComposer";
import { SessionView } from "./components/session/SessionView";
import { ProjectTree } from "./components/tree/ProjectTree";
import { useAppStore } from "./state/stores";
import { useWsStatus } from "./ws/useWsStatus";

export default function App() {
  const selected = useAppStore((s) => s.selected);
  const ws = useWsStatus();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 60_000,
    retry: false,
  });

  return (
    <div className="flex h-screen flex-col bg-ink-950 text-zinc-200">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-800 px-4">
        <div className="flex items-center gap-2 select-none">
          <span className="text-lg leading-none text-violet-400">⚘</span>
          <span className="bg-gradient-to-r from-violet-300 to-fuchsia-300 bg-clip-text text-sm font-semibold tracking-wide text-transparent">
            Orchid
          </span>
        </div>
        <div className="flex items-center gap-3">
          <WsIndicator status={ws} />
          <div
            className="text-[11px] text-zinc-600"
            title={
              health.data
                ? `orchid ${health.data.version} · sdk ${health.data.sdk_version} · config ${health.data.config_dir} · home ${health.data.orchid_home}`
                : undefined
            }
          >
            {health.data ? (
              <>claude {health.data.claude_cli_version}</>
            ) : health.isError ? (
              <span className="text-amber-500/80">backend offline</span>
            ) : (
              "…"
            )}
          </div>
        </div>
      </header>

      {ws !== "open" && (
        <div className="shrink-0 border-b border-amber-500/30 bg-amber-500/10 px-4 py-1.5 text-center text-[11px] text-amber-300">
          {ws === "connecting" ? "Connecting to Orchid…" : "Live connection lost"} — sessions and the
          onboarding chat won't update until the WebSocket reconnects. If you're behind a proxy, it must
          support WebSockets (HTTP/1.1); otherwise reach Orchid directly on its port.
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-80 shrink-0 flex-col overflow-hidden border-r border-zinc-800">
          <ProjectTree />
        </aside>
        <main className="min-w-0 flex-1 overflow-hidden">
          {selected?.sid ? (
            <SessionView key={selected.sid} pid={selected.pid} sid={selected.sid} />
          ) : selected?.settings ? (
            <ProjectSettings key={`settings-${selected.pid}`} pid={selected.pid} />
          ) : selected?.compose ? (
            <NewSessionComposer key={selected.pid} pid={selected.pid} />
          ) : (
            <OnboardingChat />
          )}
        </main>
      </div>
    </div>
  );
}

function WsIndicator({ status }: { status: "connecting" | "open" | "closed" }) {
  const meta = {
    open: { color: "bg-emerald-500", label: "live", title: "Live updates connected" },
    connecting: { color: "bg-amber-400 animate-pulse", label: "connecting", title: "Connecting…" },
    closed: { color: "bg-red-500", label: "offline", title: "Live connection lost — reconnecting" },
  }[status];
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-zinc-500" title={meta.title}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.color}`} />
      {meta.label}
    </span>
  );
}
