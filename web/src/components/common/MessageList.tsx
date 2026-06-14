import type { NormalizedMessage } from "../../api/types";
import { MessageRow, RunningCursor } from "./MessageBlock";

/**
 * Plain (non-virtualized) transcript: onboarding chat and agent drill-ins.
 * The session transcript uses the virtualized variant in components/session.
 */
export function MessageList({
  messages,
  running = false,
  onShowFull,
}: {
  messages: NormalizedMessage[];
  /** Append the "Orchid is working" indicator. */
  running?: boolean;
  /** Per-message fetch of the untruncated version; enables "show full" affordances. */
  onShowFull?: (uuid: string) => Promise<void> | void;
}) {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3 px-4 py-5">
      {messages.map((m) => (
        <MessageRow key={m.uuid} message={m} onShowFull={onShowFull ? () => onShowFull(m.uuid) : undefined} />
      ))}
      {running && <RunningCursor />}
    </div>
  );
}
