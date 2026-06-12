import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import { OnboardingChat } from "./components/onboarding/OnboardingChat";
import { NewSessionComposer } from "./components/session/NewSessionComposer";
import { SessionView } from "./components/session/SessionView";
import { ProjectTree } from "./components/tree/ProjectTree";
import { useAppStore } from "./state/stores";

export default function App() {
  const selected = useAppStore((s) => s.selected);
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
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-80 shrink-0 flex-col overflow-hidden border-r border-zinc-800">
          <ProjectTree />
        </aside>
        <main className="min-w-0 flex-1 overflow-hidden">
          {selected?.sid ? (
            <SessionView key={selected.sid} pid={selected.pid} sid={selected.sid} />
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
