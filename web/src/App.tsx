import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "./api/client";
import { CollaborationView } from "./components/collaboration/CollaborationView";
import { NewCollaboration } from "./components/collaboration/NewCollaboration";
import { ConsoleChat } from "./components/console/ConsoleChat";
import { ProjectDashboard } from "./components/project/ProjectDashboard";
import { PlansView } from "./components/project/PlansView";
import { ProjectSettings } from "./components/project/ProjectSettings";
import { ReviewPanel } from "./components/project/ReviewPanel";
import { InboxPanel } from "./components/project/InboxPanel";
import { SpecView } from "./components/project/SpecView";
import { ArchitectureView } from "./components/project/ArchitectureView";
import { NewSessionComposer } from "./components/session/NewSessionComposer";
import { SessionView } from "./components/session/SessionView";
import { ProjectTree } from "./components/tree/ProjectTree";
import { isCollabSel, isInboxSel, isNewCollabSel, isProjectSel, useAppStore } from "./state/stores";
import { useWsStatus } from "./ws/useWsStatus";

export default function App() {
  const selected = useAppStore((s) => s.selected);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const ws = useWsStatus();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 60_000,
    retry: false,
  });

  useEffect(() => setSidebarOpen(false), [selected]);

  return (
    <div className="flex h-screen flex-col bg-ink-950 text-zinc-200">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-800 px-4">
        <div className="flex items-center gap-2 select-none">
          <button
            type="button"
            aria-label="Toggle sidebar"
            className="rounded p-1 text-zinc-400 hover:text-zinc-200 md:hidden"
            onClick={() => setSidebarOpen((v) => !v)}
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
              <path fillRule="evenodd" d="M2 4.75A.75.75 0 0 1 2.75 4h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 4.75ZM2 10a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 10Zm0 5.25a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1-.75-.75Z" clipRule="evenodd" />
            </svg>
          </button>
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

      <div className="relative flex min-h-0 flex-1">
        {sidebarOpen && (
          <div className="absolute inset-0 z-20 bg-black/50 md:hidden" onClick={() => setSidebarOpen(false)} />
        )}
        <aside
          className={clsx(
            "flex shrink-0 flex-col overflow-hidden border-r border-zinc-800 bg-ink-950",
            "absolute inset-y-0 left-0 z-30 w-80 max-w-[85vw] transition-transform duration-200 ease-in-out",
            sidebarOpen ? "translate-x-0" : "-translate-x-full",
            "md:relative md:z-auto md:max-w-none md:translate-x-0 md:transition-none",
          )}
        >
          <ProjectTree />
        </aside>
        <main className="min-w-0 flex-1 overflow-hidden">
          {isInboxSel(selected) ? (
            <InboxPanel />
          ) : isCollabSel(selected) ? (
            <CollaborationView key={selected.collab} cid={selected.collab} />
          ) : isNewCollabSel(selected) ? (
            <NewCollaboration />
          ) : isProjectSel(selected) && selected.sid ? (
            <SessionView key={selected.sid} pid={selected.pid} sid={selected.sid} />
          ) : isProjectSel(selected) && selected.settings ? (
            <ProjectSettings key={`settings-${selected.pid}`} pid={selected.pid} />
          ) : isProjectSel(selected) && selected.plans ? (
            <PlansView key={`plans-${selected.pid}`} pid={selected.pid} />
          ) : isProjectSel(selected) && selected.reviews ? (
            <ReviewPanel key={`reviews-${selected.pid}-${selected.reviewId ?? ""}`} pid={selected.pid} />
          ) : isProjectSel(selected) && selected.architecture ? (
            <ArchitectureView key={`arch-${selected.pid}`} pid={selected.pid} />
          ) : isProjectSel(selected) && selected.spec ? (
            <SpecView key={`spec-${selected.pid}`} pid={selected.pid} />
          ) : isProjectSel(selected) && selected.compose ? (
            <NewSessionComposer key={selected.pid} pid={selected.pid} />
          ) : isProjectSel(selected) ? (
            <ProjectDashboard key={`dash-${selected.pid}`} pid={selected.pid} />
          ) : (
            <ConsoleChat />
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
