import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api, ApiError } from "../../api/client";
import type { GitCommit, Plan, ReviewRequest, SessionSummary } from "../../api/types";
import { useAppStore } from "../../state/stores";
import { RelativeTime } from "../common/RelativeTime";

export function ProjectDashboard({ pid }: { pid: string }) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const project = projects.data?.find((p) => p.id === pid);
  const plans = useQuery({ queryKey: ["plans", pid], queryFn: () => api.projectPlans(pid) });
  const activity = useQuery({ queryKey: ["activity", pid], queryFn: () => api.projectActivity(pid) });
  const reviews = useQuery({ queryKey: ["reviews", pid], queryFn: () => api.projectReviews(pid) });
  const sessions = useQuery({ queryKey: ["sessions", pid], queryFn: () => api.sessions(pid) });
  const usage = useQuery({ queryKey: ["usage", pid], queryFn: () => api.projectUsage(pid) });
  const spec = useQuery({
    queryKey: ["spec", pid],
    queryFn: () => api.projectSpec(pid),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
  const policyQ = useQuery({
    queryKey: ["policy", pid],
    queryFn: () => api.projectPolicy(pid),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
  const select = useAppStore((s) => s.select);
  const statuses = useAppStore((s) => s.sessionStatuses);

  const pendingReviews = reviews.data?.filter((r) => r.status === "pending") ?? [];
  const runningSessions = (sessions.data ?? []).filter(
    (s) => (statuses[s.id] ?? s.status) === "running",
  );

  const progress = useMemo(() => {
    if (!plans.data) return null;
    const active = plans.data.filter((p) => p.status === "active");
    if (active.length === 0) return null;
    const total = active.reduce((n, p) => n + p.steps.length, 0);
    const done = active.reduce(
      (n, p) => n + p.steps.filter((s) => s.status === "done").length,
      0,
    );
    return total > 0 ? { done, total, pct: Math.round((done / total) * 100) } : null;
  }, [plans.data]);

  if (!project) return null;

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-zinc-800 px-4">
        <h1 className="text-sm font-medium text-zinc-200">{project.name}</h1>
        <div className="flex items-center gap-2">
          {usage.data && usage.data.turns > 0 && (
            <span
              className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] tabular-nums text-zinc-400"
              title={`${usage.data.turns} turns across ${usage.data.sessions} session${usage.data.sessions !== 1 ? "s" : ""}`}
            >
              ${usage.data.total_cost_usd.toFixed(2)}
            </span>
          )}
          {policyQ.data ? (
            <span
              className={clsx(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                policyQ.data.profile === "permissive" && "bg-amber-500/20 text-amber-300",
                policyQ.data.profile === "balanced" && "bg-blue-500/20 text-blue-300",
                policyQ.data.profile === "strict" && "bg-emerald-500/20 text-emerald-300",
                policyQ.data.profile === "custom" && "bg-violet-500/20 text-violet-300",
              )}
            >
              {policyQ.data.profile}
            </span>
          ) : project.review_mode ? (
            <span
              className={clsx(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                project.review_mode === "autonomous"
                  ? "bg-violet-500/20 text-violet-300"
                  : "bg-zinc-800 text-zinc-400",
              )}
            >
              {project.review_mode}
            </span>
          ) : null}
          {project.intent && (
            <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400">
              {project.intent === "goal" ? "goal-oriented" : "ad-hoc"}
            </span>
          )}
        </div>
      </div>

      <div className="mx-auto w-full max-w-3xl space-y-4 p-6">
        {/* Goal */}
        {project.goal && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
            <div className="mb-1 text-[11px] font-medium tracking-wider text-zinc-500 uppercase">
              Goal
            </div>
            <p className="text-sm leading-relaxed text-zinc-200">{project.goal}</p>
            {progress && (
              <div className="mt-3">
                <div className="mb-1 flex justify-between text-[11px] text-zinc-500">
                  <span>Progress</span>
                  <span>
                    {progress.done}/{progress.total} steps ({progress.pct}%)
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className="h-full rounded-full bg-violet-500 transition-all"
                    style={{ width: `${progress.pct}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Quick actions */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => select({ pid, compose: true })}
            className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
          >
            New session
          </button>
          <button
            type="button"
            onClick={() => select({ pid, plans: true })}
            className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
          >
            Plans
          </button>
          <button
            type="button"
            onClick={() => select({ pid, architecture: true })}
            className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
          >
            Architecture
          </button>
          <button
            type="button"
            onClick={() => select({ pid, spec: true })}
            className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
          >
            Spec
          </button>
          <button
            type="button"
            onClick={() => select({ pid, settings: true })}
            className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
          >
            Settings
          </button>
        </div>

        {/* Pending reviews */}
        {pendingReviews.length > 0 && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
            <div className="mb-2 text-[11px] font-medium tracking-wider text-amber-400 uppercase">
              Pending reviews ({pendingReviews.length})
            </div>
            <div className="space-y-2">
              {pendingReviews.map((r) => (
                <ReviewRow key={r.id} pid={pid} review={r} />
              ))}
            </div>
          </div>
        )}

        {/* Running sessions */}
        {runningSessions.length > 0 && (
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
            <div className="mb-2 text-[11px] font-medium tracking-wider text-emerald-400 uppercase">
              Active sessions ({runningSessions.length})
            </div>
            <div className="space-y-1">
              {runningSessions.map((s) => (
                <ActiveSessionRow key={s.id} pid={pid} session={s} />
              ))}
            </div>
          </div>
        )}

        {/* Plans overview */}
        {plans.data && plans.data.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
            <div className="mb-2 text-[11px] font-medium tracking-wider text-zinc-500 uppercase">
              Plans
            </div>
            <div className="space-y-2">
              {plans.data.map((p) => (
                <PlanRow key={p.id} plan={p} />
              ))}
            </div>
          </div>
        )}

        {/* Spec */}
        {spec.data && (
          <button
            type="button"
            onClick={() => select({ pid, spec: true })}
            className="w-full rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 text-left transition-colors hover:border-zinc-700"
          >
            <div className="flex items-center gap-2">
              <div className="text-[11px] font-medium tracking-wider text-zinc-500 uppercase">
                Specification
              </div>
              <span className="rounded-full bg-violet-500/15 px-1.5 py-px text-[10px] text-violet-300">
                v{spec.data.version}
              </span>
            </div>
            <p className="mt-1 truncate text-xs text-zinc-400">{spec.data.title}</p>
          </button>
        )}

        {/* Recent activity (changelog) */}
        {activity.data && activity.data.length > 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
            <div className="mb-2 text-[11px] font-medium tracking-wider text-zinc-500 uppercase">
              Recent activity
            </div>
            <div className="space-y-1">
              {activity.data.slice(0, 20).map((c) => (
                <CommitRow key={c.hash} commit={c} />
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!project.goal && (!plans.data || plans.data.length === 0) && (!activity.data || activity.data.length === 0) && (
          <div className="py-12 text-center text-sm text-zinc-600">
            Start a session or set a project goal to get going.
          </div>
        )}
      </div>
    </div>
  );
}

function PlanRow({ plan }: { plan: Plan }) {
  const done = plan.steps.filter((s) => s.status === "done").length;
  const total = plan.steps.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="flex items-center gap-3">
      <span
        className={clsx(
          "h-2 w-2 shrink-0 rounded-full",
          plan.status === "done" ? "bg-emerald-500" : plan.status === "active" ? "bg-violet-500" : "bg-zinc-600",
        )}
      />
      <span className="min-w-0 flex-1 truncate text-xs text-zinc-300">{plan.title}</span>
      {total > 0 && (
        <>
          <div className="h-1 w-16 overflow-hidden rounded-full bg-zinc-800">
            <div
              className="h-full rounded-full bg-violet-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="shrink-0 text-[10px] tabular-nums text-zinc-500">
            {done}/{total}
          </span>
        </>
      )}
    </div>
  );
}

function ReviewRow({ pid, review }: { pid: string; review: ReviewRequest }) {
  const select = useAppStore((s) => s.select);
  return (
    <button
      type="button"
      onClick={() => select({ pid, reviews: true, reviewId: review.id })}
      className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-amber-500/10"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
      <span className="min-w-0 flex-1 truncate text-zinc-300">{review.branch}</span>
      <span className="shrink-0 text-[10px] text-zinc-500">
        {review.created_at && <RelativeTime iso={review.created_at} />}
      </span>
    </button>
  );
}

function ActiveSessionRow({ pid, session: s }: { pid: string; session: SessionSummary }) {
  const select = useAppStore((s) => s.select);
  const agents = useAppStore((st) => st.agents[s.id]);
  const agentCount = agents?.length ?? 0;

  return (
    <button
      type="button"
      onClick={() => select({ pid, sid: s.id })}
      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-emerald-500/10"
    >
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
      <span className="min-w-0 flex-1 truncate">
        {s.title || `${s.id.slice(0, 8)}…`}
      </span>
      {s.role === "orchestrator" && (
        <span className="shrink-0 rounded-full bg-violet-500/20 px-1.5 py-px text-[10px] text-violet-300">
          orchestrator
        </span>
      )}
      {agentCount > 0 && (
        <span className="shrink-0 text-[10px] text-zinc-500">
          {agentCount} agent{agentCount !== 1 ? "s" : ""}
        </span>
      )}
    </button>
  );
}

function CommitRow({ commit }: { commit: GitCommit }) {
  return (
    <div className="flex items-start gap-2 py-0.5">
      <code className="shrink-0 text-[11px] text-violet-400/70">{commit.short_hash}</code>
      <span className="min-w-0 flex-1 truncate text-xs text-zinc-400">{commit.message}</span>
      <span className="shrink-0 text-[10px] text-zinc-600">
        <RelativeTime iso={commit.date} />
      </span>
    </div>
  );
}
