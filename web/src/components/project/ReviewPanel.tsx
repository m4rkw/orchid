import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "../../api/client";
import type { ReviewRequest } from "../../api/types";
import { queryClient } from "../../state/queryClient";
import { useAppStore } from "../../state/stores";
import { Markdown } from "../common/Markdown";
import { RelativeTime } from "../common/RelativeTime";

export function ReviewPanel({ pid }: { pid: string }) {
  const reviews = useQuery({
    queryKey: ["reviews", pid],
    queryFn: () => api.projectReviews(pid),
  });
  const initialReviewId = useAppStore((s) => (s.selected && "reviewId" in s.selected ? s.selected.reviewId : null) ?? null);
  const [selectedId, setSelectedId] = useState<string | null>(initialReviewId);

  const data = reviews.data ?? [];
  const pending = data.filter((r) => r.status === "pending");
  const resolved = data.filter((r) => r.status !== "pending");

  // Auto-select: if nothing is selected and reviews loaded, pick the first pending (or first overall)
  useEffect(() => {
    if (selectedId || !reviews.data) return;
    const first = pending[0] ?? data[0];
    if (first) setSelectedId(first.id);
  }, [reviews.data, selectedId, pending, data]);

  const selected = data.find((r) => r.id === selectedId);

  const select = useAppStore((s) => s.select);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center gap-3 border-b border-zinc-800 px-4">
        <button
          type="button"
          onClick={() => select({ pid })}
          className="text-xs text-zinc-500 hover:text-zinc-300"
        >
          &larr; Dashboard
        </button>
        <h1 className="text-sm font-medium text-zinc-200">Reviews</h1>
        {pending.length > 0 && (
          <span className="rounded-full bg-amber-500/20 px-1.5 py-px text-[10px] font-medium text-amber-300">
            {pending.length} pending
          </span>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        {/* List */}
        <div className="w-64 shrink-0 overflow-y-auto border-r border-zinc-800 p-2">
          {pending.length > 0 && (
            <>
              <div className="px-2 py-1 text-[10px] font-medium tracking-wider text-amber-400 uppercase">
                Pending ({pending.length})
              </div>
              {pending.map((r) => (
                <ReviewListItem
                  key={r.id}
                  review={r}
                  active={selectedId === r.id}
                  onClick={() => setSelectedId(r.id)}
                />
              ))}
            </>
          )}
          {resolved.length > 0 && (
            <>
              <div className="mt-2 px-2 py-1 text-[10px] font-medium tracking-wider text-zinc-600 uppercase">
                Resolved ({resolved.length})
              </div>
              {resolved.map((r) => (
                <ReviewListItem
                  key={r.id}
                  review={r}
                  active={selectedId === r.id}
                  onClick={() => setSelectedId(r.id)}
                />
              ))}
            </>
          )}
          {data.length === 0 && (
            <div className="px-2 py-6 text-center text-[11px] text-zinc-600">No reviews yet</div>
          )}
        </div>

        {/* Detail */}
        <div className="min-w-0 flex-1 overflow-y-auto">
          {selected ? (
            <ReviewDetail pid={pid} review={selected} />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-zinc-600">
              Select a review
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ReviewListItem({
  review,
  active,
  onClick,
}: {
  review: ReviewRequest;
  active: boolean;
  onClick: () => void;
}) {
  const statusColor = {
    pending: "bg-amber-400",
    approved: "bg-emerald-500",
    changes_requested: "bg-red-400",
    merged: "bg-violet-500",
  }[review.status];

  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs",
        active ? "bg-violet-500/10 text-zinc-200" : "text-zinc-400 hover:bg-zinc-900",
      )}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusColor}`} />
      <span className="min-w-0 flex-1 truncate">{review.branch}</span>
    </button>
  );
}

function ReviewDetail({ pid, review }: { pid: string; review: ReviewRequest }) {
  const select = useAppStore((s) => s.select);
  const diff = useQuery({
    queryKey: ["review-diff", pid, review.id],
    queryFn: () => api.reviewDiff(pid, review.id),
  });
  // The single-review GET enriches with verification + the server-computed
  // touches_tests / files_changed flags (the list response omits those).
  const full = useQuery({
    queryKey: ["review", pid, review.id],
    queryFn: () => api.projectReview(pid, review.id),
  });
  const detail = full.data ?? review;
  const [notes, setNotes] = useState("");

  const verify = useMutation({
    mutationFn: () => api.verifyReview(pid, review.id),
    onSuccess: (data) => queryClient.setQueryData(["review", pid, review.id], data),
  });

  const approve = useMutation({
    mutationFn: () => api.approveReview(pid, review.id, notes || undefined),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["reviews", pid] });
      void queryClient.invalidateQueries({ queryKey: ["activity", pid] });
      select({ pid });
    },
  });

  const reject = useMutation({
    mutationFn: () => api.rejectReview(pid, review.id, notes || undefined),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["reviews", pid] });
    },
  });

  const isPending = review.status === "pending";

  return (
    <div className="p-4">
      <div className="mb-4">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium text-zinc-200">{review.branch}</h2>
          <span
            className={clsx(
              "rounded-full px-2 py-0.5 text-[10px] font-medium",
              review.status === "pending" && "bg-amber-500/20 text-amber-300",
              review.status === "merged" && "bg-violet-500/20 text-violet-300",
              review.status === "changes_requested" && "bg-red-500/20 text-red-300",
            )}
          >
            {review.status.replace("_", " ")}
          </span>
          {detail.pr_url && (
            <a
              href={detail.pr_url}
              target="_blank"
              rel="noreferrer"
              className="shrink-0 rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] text-violet-300 hover:bg-violet-500/25"
            >
              PR{detail.pr_number ? ` #${detail.pr_number}` : ""} ↗
            </a>
          )}
        </div>
        <div className="mt-2 text-xs leading-relaxed text-zinc-400">
          <Markdown>{review.summary}</Markdown>
        </div>
        {review.created_at && (
          <span className="text-[10px] text-zinc-600">
            <RelativeTime iso={review.created_at} />
          </span>
        )}
      </div>

      {review.reviewer_notes && (
        <div className="mb-4 rounded border border-zinc-800 bg-zinc-900/50 px-3 py-2 text-xs text-zinc-300">
          <div className="mb-1 text-[10px] text-zinc-500">Reviewer notes</div>
          {review.reviewer_notes}
        </div>
      )}

      {/* Verification — observed evidence: CI checks and/or attached/run output. */}
      <div className="mb-4">
        <div className="mb-1 flex items-center gap-2 text-[10px] font-medium tracking-wider text-zinc-500 uppercase">
          Verification
          {detail.touches_tests && (
            <span className="rounded-full bg-amber-500/20 px-1.5 py-px text-[9px] font-medium text-amber-300 normal-case">
              ⚠ modifies tests — confirm not weakened
            </span>
          )}
          <button
            type="button"
            onClick={() => verify.mutate()}
            disabled={verify.isPending}
            className="ml-auto rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] normal-case text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
          >
            {verify.isPending ? "Running…" : "Run checks"}
          </button>
        </div>
        {detail.ci && (
          <div
            className={clsx(
              "mb-2 rounded border px-3 py-2 text-xs",
              detail.ci.state === "passed" && "border-emerald-500/30 bg-emerald-500/5 text-emerald-300",
              detail.ci.state === "failed" && "border-red-500/30 bg-red-500/5 text-red-300",
              detail.ci.state === "pending" && "border-amber-500/30 bg-amber-500/5 text-amber-300",
            )}
          >
            <div className="font-medium">
              CI: {detail.ci.passed} passed · {detail.ci.failed} failed · {detail.ci.pending} pending
            </div>
            <div className="mt-1 font-mono text-[11px] leading-5 whitespace-pre-wrap">
              {detail.ci.lines.join("\n")}
            </div>
          </div>
        )}
        {detail.verification ? (
          <pre className="max-h-48 overflow-auto rounded border border-zinc-800 bg-ink-950 px-3 py-2 font-mono text-[11px] leading-5 whitespace-pre-wrap text-zinc-300">
            {detail.verification}
          </pre>
        ) : !detail.ci ? (
          <div className="rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-300">
            ⚠ No verification evidence — run the checks (or attach test output). Correctness unconfirmed.
          </div>
        ) : null}
        {verify.isError && (
          <p className="mt-1 text-xs text-red-400">
            {verify.error instanceof Error ? verify.error.message : "Failed to run checks"}
          </p>
        )}
      </div>

      {/* Diff viewer */}
      <div className="mb-4">
        <div className="mb-1 text-[10px] font-medium tracking-wider text-zinc-500 uppercase">
          Diff
          {typeof detail.files_changed === "number" && detail.files_changed > 0 && (
            <span className="ml-2 normal-case text-zinc-600">({detail.files_changed} files)</span>
          )}
        </div>
        {diff.isPending ? (
          <div className="py-4 text-center text-xs text-zinc-600">Loading diff…</div>
        ) : diff.data?.diff ? (
          <DiffView diff={diff.data.diff} />
        ) : (
          <div className="py-4 text-center text-xs text-zinc-600">No diff available</div>
        )}
      </div>

      {/* Actions */}
      {isPending && (
        <div className="space-y-2">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes (optional)"
            rows={2}
            className="w-full resize-none rounded border border-zinc-700 bg-ink-900 px-3 py-2 text-xs text-zinc-100 outline-none focus:border-violet-500/60"
          />
          {(approve.isError || reject.isError) && (
            <div className="text-xs text-red-400">
              {approve.error instanceof Error ? approve.error.message : reject.error instanceof Error ? reject.error.message : "Action failed"}
            </div>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={approve.isPending || reject.isPending}
              onClick={() => approve.mutate()}
              className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {approve.isPending ? "Merging…" : "Approve & Merge"}
            </button>
            <button
              type="button"
              disabled={approve.isPending || reject.isPending}
              onClick={() => reject.mutate()}
              className="rounded bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700 disabled:opacity-50"
            >
              {reject.isPending ? "Rejecting…" : "Request Changes"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <pre className="max-h-[60vh] overflow-auto rounded border border-zinc-800 bg-ink-950 font-mono text-[11px] leading-5">
      {lines.map((line, i) => {
        let cls = "text-zinc-400";
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "text-emerald-400/90 bg-emerald-500/5";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "text-red-400/90 bg-red-500/5";
        else if (line.startsWith("@@")) cls = "text-violet-400/80";
        else if (line.startsWith("diff ") || line.startsWith("index ")) cls = "text-zinc-600";
        return (
          <div key={i} className={clsx("px-3", cls)}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
