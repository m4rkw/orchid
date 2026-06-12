import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { api } from "../../api/client";
import type { Block, NormalizedMessage } from "../../api/types";
import { messageText, useAppStore } from "../../state/stores";
import { Markdown } from "../common/Markdown";

const MAX_COMPOSER_HEIGHT_PX = 144; // ~6 lines at 24px line-height

export function OnboardingChat() {
  const messages = useAppStore((s) => s.onboarding.messages);
  const running = useAppStore((s) => s.onboarding.running);
  const lastError = useAppStore((s) => s.onboarding.lastError);
  const composerFocusKey = useAppStore((s) => s.composerFocusKey);
  const appendOnboardingUser = useAppStore((s) => s.appendOnboardingUser);
  const setOnboardingError = useAppStore((s) => s.setOnboardingError);
  const resetOnboarding = useAppStore((s) => s.resetOnboarding);

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
  }, [messages, running]);

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
    if (!running) textareaRef.current?.focus();
  }, [running]);

  const send = async () => {
    const text = value.trim();
    if (!text || running) return;
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
        {messages.length === 0 ? (
          <EmptyHero />
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-3 px-4 py-5">
            {messages.map((m) => (
              <MessageRow key={m.uuid} message={m} />
            ))}
            {running && (
              <div className="animate-pulse pl-1 font-mono text-sm text-violet-400/80" aria-label="Claude is working">
                ▍
              </div>
            )}
          </div>
        )}
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
            running ? "border-violet-500/40" : "border-zinc-700 focus-within:border-violet-500/60",
          )}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            disabled={running}
            placeholder={running ? "" : "Ask Claude to onboard a project…"}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            className="max-h-36 min-h-6 w-full resize-none bg-transparent text-sm leading-6 text-zinc-100 outline-none placeholder:text-zinc-600 disabled:opacity-50"
          />
          {running && (
            <div className="pointer-events-none absolute inset-y-0 left-3 flex animate-pulse items-center text-sm text-violet-300/80">
              Claude is working…
            </div>
          )}
          <button
            type="button"
            onClick={() => void send()}
            disabled={running || value.trim() === ""}
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

function MessageRow({ message }: { message: NormalizedMessage }) {
  switch (message.role) {
    case "user": {
      const toolResults = message.blocks.filter((b) => b.type === "tool_result");
      // Tool results come back as user-role messages; render them as chips, not a prompt bubble.
      if (toolResults.length > 0 && !messageText(message)) {
        return (
          <div className="fade-up flex max-w-[85%] flex-col gap-1.5">
            {toolResults.map((b, i) => (
              <ToolResultChip key={b.tool_use_id ?? i} block={b} />
            ))}
          </div>
        );
      }
      return (
        <div className="fade-up ml-auto max-w-[80%] rounded-2xl rounded-br-sm border border-violet-500/30 bg-violet-600/15 px-3.5 py-2 text-sm break-words whitespace-pre-wrap text-zinc-100">
          {messageText(message)}
        </div>
      );
    }
    case "assistant":
      return <AssistantMessage message={message} />;
    case "system":
      return (
        <div className="fade-up mx-auto max-w-[85%] text-center text-xs text-zinc-500 italic">
          {messageText(message) || "system"}
        </div>
      );
    case "result":
      return <ResultDivider text={messageText(message) || "turn done"} />;
  }
}

function AssistantMessage({ message }: { message: NormalizedMessage }) {
  const blocks = message.blocks.filter((b) => b.type !== "text" || (b.text ?? "").trim() !== "");
  if (blocks.length === 0) return null;
  return (
    <div className="fade-up max-w-[88%]">
      {message.agent_id && (
        <div className="mb-1 pl-1 font-mono text-[10px] text-zinc-600">agent {message.agent_id.slice(0, 8)}</div>
      )}
      <div className="flex flex-col gap-2 rounded-2xl rounded-bl-sm border border-zinc-800 bg-transparent px-3.5 py-2.5">
        {blocks.map((b, i) => (
          <BlockView key={b.id ?? b.tool_use_id ?? i} block={b} />
        ))}
      </div>
    </div>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "text":
      return <Markdown>{block.text ?? ""}</Markdown>;
    case "thinking":
      return <ThinkingBlock block={block} />;
    case "tool_use":
      return <ToolUseChip block={block} />;
    case "tool_result":
      return <ToolResultChip block={block} />;
  }
}

function ThinkingBlock({ block }: { block: Block }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-zinc-500 italic select-none hover:text-zinc-400">thinking…</summary>
      <div className="mt-1.5 border-l border-zinc-800 pl-3 leading-relaxed break-words whitespace-pre-wrap text-zinc-500 italic">
        {block.text ?? ""}
      </div>
    </details>
  );
}

function ToolUseChip({ block }: { block: Block }) {
  return (
    <details className="group rounded-lg border border-zinc-800 bg-zinc-900/60 text-xs">
      <summary className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5 text-zinc-400 select-none hover:text-zinc-200">
        <span className="text-violet-400/80">⚙</span>
        <span className="truncate font-mono">{block.name ?? "tool"}</span>
        <span className="ml-auto text-[9px] text-zinc-600 transition-transform group-open:rotate-90">▶</span>
      </summary>
      {block.input_preview ? (
        <pre className="mx-2 mb-2 overflow-x-auto rounded-md bg-black/40 p-2 font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap text-zinc-300">
          {block.input_preview}
          {block.truncated && <span className="text-zinc-600"> …(truncated)</span>}
        </pre>
      ) : (
        <div className="px-2.5 pb-2 text-zinc-600">no input preview</div>
      )}
    </details>
  );
}

function ToolResultChip({ block }: { block: Block }) {
  const isError = block.is_error === true;
  return (
    <details
      className={clsx(
        "group rounded-lg border text-xs",
        isError ? "border-red-500/30 bg-red-500/5" : "border-zinc-800 bg-zinc-900/40",
      )}
    >
      <summary
        className={clsx(
          "flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5 select-none",
          isError ? "text-red-400 hover:text-red-300" : "text-zinc-500 hover:text-zinc-300",
        )}
      >
        <span>{isError ? "✗" : "⤷"}</span>
        <span>{isError ? "error result" : "result"}</span>
        {block.truncated && <span className="text-[10px] text-zinc-600">(truncated)</span>}
        <span className="ml-auto text-[9px] text-zinc-600 transition-transform group-open:rotate-90">▶</span>
      </summary>
      <pre
        className={clsx(
          "mx-2 mb-2 overflow-x-auto rounded-md bg-black/40 p-2 font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap",
          isError ? "text-red-300/90" : "text-zinc-400",
        )}
      >
        {block.content_preview ?? ""}
      </pre>
    </details>
  );
}

function ResultDivider({ text }: { text: string }) {
  return (
    <div className="fade-up my-0.5 flex items-center gap-3 text-[11px] text-zinc-500">
      <div className="h-px flex-1 bg-zinc-800" />
      <span className="shrink-0">{text}</span>
      <div className="h-px flex-1 bg-zinc-800" />
    </div>
  );
}
