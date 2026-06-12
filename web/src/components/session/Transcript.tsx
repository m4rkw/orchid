import { useEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { NormalizedMessage } from "../../api/types";
import type { PermissionCard as PermissionCardData } from "../../state/stores";
import { MessageRow, RunningCursor } from "../common/MessageBlock";
import { PermissionCard } from "./PermissionCard";

/**
 * Virtualized session transcript with stick-to-bottom. Permission cards, the
 * running caret and the inline error banner render below the virtual list
 * (inside the same scroll element) so they always sit at the tail.
 */
export function Transcript({
  sid,
  messages,
  running,
  lastError,
  permissions,
  loading,
  onShowFull,
  onDismissError,
}: {
  sid: string;
  messages: NormalizedMessage[];
  running: boolean;
  lastError: string | null;
  permissions: PermissionCardData[];
  /** Backlog request still in flight and nothing cached yet. */
  loading: boolean;
  onShowFull: (uuid: string) => Promise<void>;
  onDismissError: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 72,
    overscan: 8,
    getItemKey: (i) => messages[i].uuid,
  });
  const totalSize = virtualizer.getTotalSize();

  // Stick-to-bottom: follow the tail unless the user has scrolled up. Runs on
  // every content/measurement change so it keeps up while row heights settle.
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  useEffect(() => {
    if (!stickToBottom.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, totalSize, running, lastError, permissions.length]);

  // New session selected in the same mounted view: snap back to the tail.
  useEffect(() => {
    stickToBottom.current = true;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [sid]);

  const items = virtualizer.getVirtualItems();
  const hasTail = running || lastError !== null || permissions.length > 0;

  return (
    <div ref={scrollRef} onScroll={handleScroll} className="min-h-0 flex-1 overflow-y-auto">
      {loading && messages.length === 0 ? (
        <div className="px-4 py-8 text-center text-xs text-zinc-600">Loading messages…</div>
      ) : messages.length === 0 && !hasTail ? (
        <div className="px-4 py-8 text-center text-xs text-zinc-600">No messages yet</div>
      ) : (
        <div className="relative mx-0 mt-4" style={{ height: totalSize }}>
          {items.map((vi) => {
            const message = messages[vi.index];
            return (
              <div
                key={vi.key}
                data-index={vi.index}
                ref={virtualizer.measureElement}
                className="absolute top-0 left-0 w-full"
                style={{ transform: `translateY(${vi.start}px)` }}
              >
                <div className="mx-auto flex max-w-3xl flex-col px-4 pb-3">
                  <MessageRow message={message} animate={false} onShowFull={() => onShowFull(message.uuid)} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {hasTail && (
        <div className="mx-auto flex max-w-3xl flex-col gap-3 px-4 pb-5">
          {permissions.map((card) => (
            <PermissionCard key={card.request_id} sid={sid} card={card} />
          ))}
          {lastError && (
            <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              <span className="shrink-0 font-medium">Error:</span>
              <span className="min-w-0 break-words">{lastError}</span>
              <button
                type="button"
                aria-label="Dismiss error"
                className="ml-auto shrink-0 text-red-400/70 hover:text-red-300"
                onClick={onDismissError}
              >
                ✕
              </button>
            </div>
          )}
          {running && <RunningCursor />}
        </div>
      )}
    </div>
  );
}
