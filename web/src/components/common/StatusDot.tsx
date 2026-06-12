import { clsx } from "clsx";
import type { SessionStatus } from "../../api/types";

export function StatusDot({ status, className }: { status: SessionStatus; className?: string }) {
  return (
    <span
      aria-label={status}
      title={status}
      className={clsx(
        "inline-block size-2 shrink-0 rounded-full",
        status === "running" && "animate-pulse bg-violet-400 shadow-[0_0_6px] shadow-violet-400/60",
        status === "external" && "bg-amber-400",
        status === "idle" && "bg-zinc-500",
        className,
      )}
    />
  );
}
