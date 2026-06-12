import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { api } from "../../api/client";
import { useAppStore } from "../../state/stores";
import { useWsStatus } from "../../ws/useWsStatus";
import { MessageList } from "../common/MessageList";

const MAX_COMPOSER_HEIGHT_PX = 144; // ~6 lines at 24px line-height

export function OnboardingChat() {
  const messages = useAppStore((s) => s.onboarding.messages);
  const running = useAppStore((s) => s.onboarding.running);
  const lastError = useAppStore((s) => s.onboarding.lastError);
  const composerFocusKey = useAppStore((s) => s.composerFocusKey);
  const appendOnboardingUser = useAppStore((s) => s.appendOnboardingUser);
  const setOnboardingError = useAppStore((s) => s.setOnboardingError);
  const loadOnboarding = useAppStore((s) => s.loadOnboarding);
  const resetOnboarding = useAppStore((s) => s.resetOnboarding);

  const ws = useWsStatus();
  const wsOpen = ws === "open";
  // Without the live socket we can't observe a turn finishing, so "running" is
  // meaningless: don't lock the composer on it. Show the offline state instead.
  const blocked = running && wsOpen;

  // Recover history + the true running state whenever the socket (re)connects —
  // this clears a spinner left stuck by a missed turn_completed and restores the
  // chat after a reload.
  useEffect(() => {
    if (ws !== "open") return;
    let cancelled = false;
    void api
      .onboardingMessages()
      .then((res) => {
        if (!cancelled) loadOnboarding(res.messages, res.running);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [ws, loadOnboarding]);

  const [value, setValue] = useState("");
  const [resetting, setResetting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottom = useRef(true);

  // Stick-to-bottom: follow new messages unless the user has scrolled up.
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  useEffect(() => {
    if (stickToBottom.current) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    }
  }, [messages, blocked]);

  // Auto-grow the composer up to ~6 lines.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_COMPOSER_HEIGHT_PX)}px`;
  }, [value]);

  // Focus requests ("+ New" button) and re-focus when a turn finishes.
  useEffect(() => {
    textareaRef.current?.focus();
  }, [composerFocusKey]);
  useEffect(() => {
    if (!blocked) textareaRef.current?.focus();
  }, [blocked]);

  const send = async () => {
    const text = value.trim();
    if (!text || blocked || !wsOpen) return;
    setValue("");
    appendOnboardingUser(text); // optimistic; also flips running on
    try {
      await api.onboardingPrompt(text);
    } catch (err) {
      setOnboardingError(err instanceof Error ? err.message : "Failed to send prompt");
    }
  };

  const reset = async () => {
    setResetting(true);
    try {
      await api.onboardingReset();
      resetOnboarding();
    } catch (err) {
      setOnboardingError(err instanceof Error ? err.message : "Failed to reset");
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-zinc-800 px-4">
        <div className="flex items-baseline gap-2">
          <h1 className="text-sm font-medium text-zinc-200">Onboarding</h1>
          <span className="text-[11px] text-zinc-600">register projects by chatting with Claude</span>
        </div>
        <button
          type="button"
          disabled={resetting}
          onClick={() => void reset()}
          className="rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-red-400 disabled:opacity-50"
        >
          {resetting ? "Resetting…" : "Reset"}
        </button>
      </div>

      <div ref={scrollRef} onScroll={handleScroll} className="min-h-0 flex-1 overflow-y-auto">
        {messages.length === 0 ? <EmptyHero /> : <MessageList messages={messages} running={blocked} />}
      </div>

      <div className="shrink-0 border-t border-zinc-800 p-4 pt-3">
        {lastError && (
          <div className="mx-auto mb-2 flex max-w-3xl items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            <span className="shrink-0 font-medium">Error:</span>
            <span className="min-w-0 break-words">{lastError}</span>
            <button
              type="button"
              aria-label="Dismiss error"
              className="ml-auto shrink-0 text-red-400/70 hover:text-red-300"
              onClick={() => setOnboardingError(null)}
            >
              ✕
            </button>
          </div>
        )}
        <div
          className={clsx(
            "relative mx-auto flex max-w-3xl items-end gap-2 rounded-xl border bg-ink-900 px-3 py-2 transition-colors",
            blocked ? "border-violet-500/40" : "border-zinc-700 focus-within:border-violet-500/60",
            !wsOpen && "border-amber-500/40",
          )}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            disabled={blocked || !wsOpen}
            placeholder={blocked || !wsOpen ? "" : "Ask Claude to onboard a project…"}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            className="max-h-36 min-h-6 w-full resize-none bg-transparent text-sm leading-6 text-zinc-100 outline-none placeholder:text-zinc-600 disabled:opacity-50"
          />
          {!wsOpen ? (
            <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-amber-300/80">
              Live connection offline — reconnect to chat
            </div>
          ) : (
            blocked && (
              <div className="pointer-events-none absolute inset-y-0 left-3 flex animate-pulse items-center text-sm text-violet-300/80">
                Claude is working…
              </div>
            )
          )}
          <button
            type="button"
            onClick={() => void send()}
            disabled={blocked || !wsOpen || value.trim() === ""}
            className="mb-px shrink-0 rounded-lg bg-violet-600 px-3 py-1 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-violet-600"
          >
            Send
          </button>
        </div>
        <div className="mx-auto mt-1.5 max-w-3xl px-1 text-[10px] text-zinc-600">
          Enter to send · Shift+Enter for newline
        </div>
      </div>
    </div>
  );
}

function EmptyHero() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
      <div className="text-4xl text-violet-400/80">⚘</div>
      <div className="font-medium text-zinc-300">Onboard a project</div>
      <p className="max-w-sm text-sm leading-relaxed text-zinc-500">
        Ask Claude to register a folder as a project — try{" "}
        <span className="rounded bg-zinc-800/70 px-1.5 py-0.5 font-mono text-xs text-zinc-300">
          onboard ~/code/my-app
        </span>
      </p>
    </div>
  );
}
