import { useEffect, useState } from "react";

function format(date: Date): string {
  const diff = Date.now() - date.getTime();
  if (diff < 45_000) return "just now";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${Math.max(1, minutes)}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** "3m ago"-style timestamp that re-renders every 30s. Renders nothing for null/bad input. */
export function RelativeTime({ iso }: { iso: string | null }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;

  return (
    <time dateTime={iso} title={date.toLocaleString()}>
      {format(date)}
    </time>
  );
}
