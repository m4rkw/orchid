import { useState } from "react";
import { clsx } from "clsx";
import type { Block, NormalizedMessage } from "../../api/types";
import { messageText } from "../../state/stores";
import { Markdown } from "./Markdown";

/** Fetches the untruncated version of the enclosing message (parent swaps it in). */
export type ShowFullFn = () => Promise<void> | void;

export function MessageRow({
  message,
  onShowFull,
  animate = true,
}: {
  message: NormalizedMessage;
  /** Provided where GET /messages/{uuid} exists; enables "show full" on truncated blocks. */
  onShowFull?: ShowFullFn;
  /** Disable the entry animation (virtualized lists re-mount rows on scroll). */
  animate?: boolean;
}) {
  switch (message.role) {
    case "user": {
      const toolResults = message.blocks.filter((b) => b.type === "tool_result");
      // Tool results come back as user-role messages; render them as chips, not a prompt bubble.
      if (toolResults.length > 0 && !messageText(message)) {
        return (
          <div className={clsx(animate && "fade-up", "flex max-w-[85%] flex-col gap-1.5")}>
            {toolResults.map((b, i) => (
              <ToolResultChip key={b.tool_use_id ?? i} block={b} onShowFull={onShowFull} />
            ))}
          </div>
        );
      }
      return (
        <div
          className={clsx(
            animate && "fade-up",
            "ml-auto max-w-[80%] rounded-2xl rounded-br-sm border border-violet-500/30 bg-violet-600/15 px-3.5 py-2 text-sm break-words whitespace-pre-wrap text-zinc-100",
          )}
        >
          {messageText(message)}
        </div>
      );
    }
    case "assistant":
      return <AssistantMessage message={message} onShowFull={onShowFull} animate={animate} />;
    case "system":
      return (
        <div className={clsx(animate && "fade-up", "mx-auto max-w-[85%] text-center text-xs text-zinc-500 italic")}>
          {messageText(message) || "system"}
        </div>
      );
    case "result":
      return <ResultDivider text={messageText(message) || "turn done"} animate={animate} />;
  }
}

function AssistantMessage({
  message,
  onShowFull,
  animate,
}: {
  message: NormalizedMessage;
  onShowFull?: ShowFullFn;
  animate: boolean;
}) {
  const blocks = message.blocks.filter((b) => b.type !== "text" || (b.text ?? "").trim() !== "");
  if (blocks.length === 0) return null;
  return (
    <div className={clsx(animate && "fade-up", "max-w-[88%]")}>
      {message.agent_id && (
        <div className="mb-1 pl-1 font-mono text-[10px] text-zinc-600">agent {message.agent_id.slice(0, 8)}</div>
      )}
      <div className="flex flex-col gap-2 rounded-2xl rounded-bl-sm border border-zinc-800 bg-transparent px-3.5 py-2.5">
        {blocks.map((b, i) => (
          <BlockView key={b.id ?? b.tool_use_id ?? i} block={b} onShowFull={onShowFull} />
        ))}
      </div>
    </div>
  );
}

export function BlockView({ block, onShowFull }: { block: Block; onShowFull?: ShowFullFn }) {
  switch (block.type) {
    case "text":
      return (
        <div>
          <Markdown>{block.text ?? ""}</Markdown>
          {block.truncated && onShowFull && (
            <div className="mt-1">
              <ShowFullButton onShowFull={onShowFull} />
            </div>
          )}
        </div>
      );
    case "thinking":
      return <ThinkingBlock block={block} onShowFull={onShowFull} />;
    case "tool_use":
      return <ToolUseChip block={block} onShowFull={onShowFull} />;
    case "tool_result":
      return <ToolResultChip block={block} onShowFull={onShowFull} />;
  }
}

function ShowFullButton({ onShowFull }: { onShowFull: ShowFullFn }) {
  const [loading, setLoading] = useState(false);
  return (
    <button
      type="button"
      disabled={loading}
      onClick={(e) => {
        // Inside <summary> elements: don't toggle the chip when expanding.
        e.preventDefault();
        e.stopPropagation();
        if (loading) return;
        setLoading(true);
        void Promise.resolve(onShowFull()).finally(() => setLoading(false));
      }}
      className="shrink-0 rounded border border-violet-500/30 px-1.5 py-px text-[10px] text-violet-400 transition-colors hover:border-violet-400/60 hover:text-violet-300 disabled:opacity-50"
    >
      {loading ? "loading…" : "show full"}
    </button>
  );
}

function ThinkingBlock({ block, onShowFull }: { block: Block; onShowFull?: ShowFullFn }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-zinc-500 italic select-none hover:text-zinc-400">thinking…</summary>
      <div className="mt-1.5 border-l border-zinc-800 pl-3 leading-relaxed break-words whitespace-pre-wrap text-zinc-500 italic">
        {block.text ?? ""}
      </div>
      {block.truncated && onShowFull && (
        <div className="mt-1 pl-3">
          <ShowFullButton onShowFull={onShowFull} />
        </div>
      )}
    </details>
  );
}

function ToolUseChip({ block, onShowFull }: { block: Block; onShowFull?: ShowFullFn }) {
  return (
    <details className="group rounded-lg border border-zinc-800 bg-zinc-900/60 text-xs">
      <summary className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5 text-zinc-400 select-none hover:text-zinc-200">
        <span className="text-violet-400/80">⚙</span>
        <span className="truncate font-mono">{block.name ?? "tool"}</span>
        {block.truncated && onShowFull && <ShowFullButton onShowFull={onShowFull} />}
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

function ToolResultChip({ block, onShowFull }: { block: Block; onShowFull?: ShowFullFn }) {
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
        {block.truncated && onShowFull && <ShowFullButton onShowFull={onShowFull} />}
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

export function ResultDivider({ text, animate = true }: { text: string; animate?: boolean }) {
  return (
    <div className={clsx(animate && "fade-up", "my-0.5 flex items-center gap-3 text-[11px] text-zinc-500")}>
      <div className="h-px flex-1 bg-zinc-800" />
      <span className="shrink-0">{text}</span>
      <div className="h-px flex-1 bg-zinc-800" />
    </div>
  );
}

/** The pulsing caret shown while Claude is working. */
export function RunningCursor() {
  return (
    <div className="animate-pulse pl-1 font-mono text-sm text-violet-400/80" aria-label="Claude is working">
      ▍
    </div>
  );
}
