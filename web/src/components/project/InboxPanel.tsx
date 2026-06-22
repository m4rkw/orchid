import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "../../api/client";
import type { InboxItem, InboxOption } from "../../api/types";
import { queryClient } from "../../state/queryClient";
import { isInboxSel, useAppStore } from "../../state/stores";
import { Markdown } from "../common/Markdown";
import { RelativeTime } from "../common/RelativeTime";

/** Group label fallback chain: explicit group_label → source. */
function groupLabelFor(item: InboxItem): string {
  return item.group_label ?? item.source;
}

function groupKeyFor(item: InboxItem): string {
  return item.group_id ?? `${item.project_id}:${groupLabelFor(item)}`;
}

/** True when every item in the group exposes the same set of option ids. */
function sharedOptions(items: InboxItem[]): InboxOption[] {
  if (items.length === 0) return [];
  const first = items[0].options;
  const sig = (opts: InboxOption[]) => opts.map((o) => o.id).sort().join("|");
  const target = sig(first);
  return items.every((it) => sig(it.options) === target) ? first : [];
}

export function InboxPanel() {
  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: () => api.inboxAll("pending"),
  });
  const focusedId = useAppStore((s) => (isInboxSel(s.selected) ? s.selected.inboxId : null) ?? null);

  const items = inbox.data ?? [];

  // Group items, preserving newest-first order: first appearance defines order.
  const groups: { key: string; label: string; items: InboxItem[] }[] = [];
  const index = new Map<string, number>();
  for (const item of items) {
    const key = groupKeyFor(item);
    let i = index.get(key);
    if (i === undefined) {
      i = groups.length;
      index.set(key, i);
      groups.push({ key, label: groupLabelFor(item), items: [] });
    }
    groups[i].items.push(item);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center gap-3 border-b border-zinc-800 px-4">
        <h1 className="text-sm font-medium text-zinc-200">Inbox</h1>
        {items.length > 0 && (
          <span className="rounded-full bg-amber-500/20 px-1.5 py-px text-[10px] font-medium text-amber-300">
            {items.length} pending
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {inbox.isPending ? (
          <div className="py-10 text-center text-xs text-zinc-600">Loading inbox…</div>
        ) : items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-zinc-600">
            <span className="text-2xl text-emerald-500/70">✓</span>
            <p className="mt-2 text-sm">Inbox zero</p>
            <p className="mt-1 text-[11px] text-zinc-700">Nothing needs your input right now.</p>
          </div>
        ) : (
          <div className="space-y-4 p-4">
            {groups.map((g) => (
              <InboxGroup key={g.key} label={g.label} items={g.items} focusedId={focusedId} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function InboxGroup({
  label,
  items,
  focusedId,
}: {
  label: string;
  items: InboxItem[];
  focusedId: string | null;
}) {
  const shared = sharedOptions(items);
  const canBatch = items.length > 1 && shared.length > 0;

  const applyAll = useMutation({
    mutationFn: async (optionId: string) => {
      for (const it of items) {
        await api.resolveInboxItem(it.project_id, it.id, optionId);
      }
    },
    // onSettled, not onSuccess: a mid-batch failure still resolves earlier items
    // server-side, so refetch regardless to reconcile the list.
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["inbox"] }),
  });

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-800 bg-ink-900/40">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-2">
        <span className="text-[11px] font-medium tracking-wider text-zinc-400 uppercase">{label}</span>
        <span className="rounded-full bg-zinc-800 px-1.5 py-px text-[10px] tabular-nums text-zinc-400">
          {items.length}
        </span>
        {canBatch && (
          <div className="ml-auto flex items-center gap-1">
            <span className="text-[10px] text-zinc-600">apply to all:</span>
            {shared.map((opt) => (
              <button
                key={opt.id}
                type="button"
                title={opt.detail ?? undefined}
                disabled={applyAll.isPending}
                onClick={() => applyAll.mutate(opt.id)}
                className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="divide-y divide-zinc-800/70">
        {items.map((item) => (
          <InboxRow key={item.id} item={item} focused={focusedId === item.id} />
        ))}
      </div>
    </div>
  );
}

/** A free-text inbox item (kind === "input"): type a value, press Enter. */
function InboxInput({ item, disabled }: { item: InboxItem; disabled: boolean }) {
  const [value, setValue] = useState("");
  const submit = useMutation({
    mutationFn: (v: string) =>
      api.resolveInboxItem(item.project_id, item.id, "submit", { value: v }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["inbox"] }),
  });
  const busy = disabled || submit.isPending;
  const trimmed = value.trim();
  return (
    <form
      className="mt-2 flex gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (trimmed) submit.mutate(trimmed);
      }}
    >
      <input
        autoFocus
        type="text"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Type a value and press Enter…"
        className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-amber-500/50 focus:outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={busy || !trimmed}
        className="shrink-0 rounded bg-zinc-800 px-2.5 py-1 text-xs text-zinc-200 hover:bg-zinc-700 disabled:opacity-50"
      >
        {submit.isPending ? "Saving…" : "Save"}
      </button>
      {submit.isError && (
        <p className="mt-1 text-[11px] text-red-400">
          {submit.error instanceof Error ? submit.error.message : "Failed"}
        </p>
      )}
    </form>
  );
}

function InboxRow({ item, focused }: { item: InboxItem; focused: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focused]);

  const resolve = useMutation({
    mutationFn: (optionId: string) => api.resolveInboxItem(item.project_id, item.id, optionId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["inbox"] }),
  });

  const dismiss = useMutation({
    mutationFn: () => api.dismissInboxItem(item.project_id, item.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["inbox"] }),
  });

  const busy = resolve.isPending || dismiss.isPending;

  return (
    <div
      ref={ref}
      className={clsx(
        "px-3 py-3 transition-colors",
        focused ? "bg-amber-500/5 ring-1 ring-inset ring-amber-500/30" : "",
      )}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm text-zinc-200">{item.title}</div>
          {item.body && (
            <div className="mt-1 text-xs leading-relaxed text-zinc-400">
              <Markdown>{item.body}</Markdown>
            </div>
          )}
          <div className="mt-1 text-[10px] text-zinc-600">
            <RelativeTime iso={item.created_at} />
          </div>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => dismiss.mutate()}
          className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 disabled:opacity-50"
        >
          {dismiss.isPending ? "Dismissing…" : "Dismiss"}
        </button>
      </div>

      {item.kind === "input" && <InboxInput item={item} disabled={busy} />}

      {item.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.options.map((opt) => (
            <button
              key={opt.id}
              type="button"
              title={opt.detail ?? undefined}
              disabled={busy}
              onClick={() => resolve.mutate(opt.id)}
              className="rounded bg-zinc-800 px-2.5 py-1 text-left text-xs text-zinc-200 hover:bg-zinc-700 disabled:opacity-50"
            >
              <span className="font-medium">{opt.label}</span>
              {opt.detail && <span className="ml-1 text-[10px] text-zinc-500">{opt.detail}</span>}
            </button>
          ))}
        </div>
      )}

      {(resolve.isError || dismiss.isError) && (
        <p className="mt-1 text-[11px] text-red-400">
          {resolve.error instanceof Error
            ? resolve.error.message
            : dismiss.error instanceof Error
              ? dismiss.error.message
              : "Action failed"}
        </p>
      )}
    </div>
  );
}
