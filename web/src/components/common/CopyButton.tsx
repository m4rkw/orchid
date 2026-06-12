import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";

export function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return; // clipboard unavailable (permissions / non-secure context)
    }
    setCopied(true);
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      title="Copy to clipboard"
      onClick={() => void copy()}
      className={clsx(
        "shrink-0 rounded-md border px-2 py-1 text-[11px] transition-colors",
        copied
          ? "border-emerald-500/50 text-emerald-400"
          : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200",
        className,
      )}
    >
      {copied ? "✓ copied" : "copy"}
    </button>
  );
}
