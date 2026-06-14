import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { api, ApiError } from "../../api/client";
import { useAppStore, type PermissionCard as PermissionCardData } from "../../state/stores";

/** Inline approval card for a `permission_request` WS event. */
export function PermissionCard({ sid, card }: { sid: string; card: PermissionCardData }) {
  const resolvePermission = useAppStore((s) => s.resolvePermission);
  const expirePermission = useAppStore((s) => s.expirePermission);
  const [pending, setPending] = useState<"allow" | "deny" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Enter key accepts the permission request.
  useEffect(() => {
    if (card.expired) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && pending === null) {
        e.preventDefault();
        void respond("allow");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  // Auto-dim when expires_at passes.
  useEffect(() => {
    if (card.expired) return;
    const ms = Date.parse(card.expires_at) - Date.now();
    if (Number.isNaN(ms)) return;
    if (ms <= 0) {
      expirePermission(sid, card.request_id);
      return;
    }
    const timer = setTimeout(() => expirePermission(sid, card.request_id), ms);
    return () => clearTimeout(timer);
  }, [card.expired, card.expires_at, card.request_id, sid, expirePermission]);

  const respond = async (behavior: "allow" | "deny") => {
    setPending(behavior);
    setError(null);
    try {
      await api.respondPermission(card.request_id, behavior);
      resolvePermission(sid, card.request_id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 410) {
        expirePermission(sid, card.request_id); // already gone server-side: dim it
      } else {
        setError(err instanceof Error ? err.message : "Failed to respond");
      }
    } finally {
      setPending(null);
    }
  };

  return (
    <div
      className={clsx(
        "fade-up rounded-xl border p-3",
        card.expired ? "border-zinc-800 opacity-50" : "border-violet-500/40 bg-violet-500/5",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-violet-400">⚿</span>
        <span className="text-sm font-medium text-zinc-100">{card.display_name || card.tool_name}</span>
        <span className="font-mono text-[10px] text-zinc-600">{card.tool_name}</span>
        {card.expired && (
          <span className="ml-auto rounded-full bg-zinc-800 px-2 py-px text-[10px] text-zinc-400">expired</span>
        )}
      </div>
      {card.description && <p className="mt-1.5 text-xs leading-relaxed text-zinc-400">{card.description}</p>}
      {card.input_preview && (
        <details className="group mt-2 rounded-lg border border-zinc-800 bg-zinc-900/60 text-xs">
          <summary className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5 text-zinc-500 select-none hover:text-zinc-300">
            <span>input</span>
            <span className="ml-auto text-[9px] text-zinc-600 transition-transform group-open:rotate-90">▶</span>
          </summary>
          <pre className="mx-2 mb-2 overflow-x-auto rounded-md bg-black/40 p-2 font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap text-zinc-300">
            {card.input_preview}
          </pre>
        </details>
      )}
      {error && <div className="mt-2 text-[11px] text-red-400">{error}</div>}
      {!card.expired && (
        <div className="mt-2.5 flex gap-2">
          <button
            type="button"
            disabled={pending !== null}
            onClick={() => void respond("allow")}
            className="rounded-lg bg-violet-600 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-violet-500 disabled:opacity-50"
          >
            {pending === "allow" ? "Allowing…" : "Allow"}
          </button>
          <button
            type="button"
            disabled={pending !== null}
            onClick={() => void respond("deny")}
            className="rounded-lg border border-zinc-700 px-3 py-1 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100 disabled:opacity-50"
          >
            {pending === "deny" ? "Denying…" : "Deny"}
          </button>
        </div>
      )}
    </div>
  );
}
