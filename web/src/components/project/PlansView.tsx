import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api } from "../../api/client";
import type { Plan, PlanStep, PlanStepStatus } from "../../api/types";
import { useAppStore } from "../../state/stores";

const STEP_DOT: Record<PlanStepStatus, string> = {
  pending: "bg-zinc-600",
  in_progress: "bg-violet-400 animate-pulse",
  done: "bg-emerald-500",
  blocked: "bg-amber-500",
};

/**
 * Read-only view of a project's persisted plans (.orchid/plans/*.json), kept
 * live by the `plan_upserted` WS event. You drive a plan from the orchestrator
 * session — e.g. prompt it "implement step stp_xxxx" — and it updates here.
 */
export function PlansView({ pid }: { pid: string }) {
  const select = useAppStore((s) => s.select);
  const plans = useQuery({ queryKey: ["plans", pid], queryFn: () => api.projectPlans(pid) });

  return (
    <div className="h-full overflow-y-auto p-8">
      <div className="mx-auto w-full max-w-2xl">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-medium text-zinc-100">Plans</h2>
          <button
            type="button"
            onClick={() => select(null)}
            className="rounded-md px-2 py-1 text-xs text-zinc-500 transition-colors hover:bg-zinc-900 hover:text-zinc-300"
          >
            Close
          </button>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
          Persisted by the orchestrator so they survive its context window. Drive one from the
          orchestrator session — prompt it, e.g. <code className="text-zinc-400">implement step stp_…</code>.
        </p>

        {plans.isPending && <div className="mt-6 text-xs text-zinc-600">Loading plans…</div>}
        {plans.isError && <div className="mt-6 text-xs text-red-400/80">Couldn’t load plans.</div>}
        {plans.data?.length === 0 && (
          <div className="mt-10 text-center text-xs leading-relaxed text-zinc-600">
            No plans yet. Start the orchestrator with a goal and it will draft one.
          </div>
        )}

        <div className="mt-5 space-y-4">
          {plans.data?.map((plan) => (
            <PlanCard key={plan.id} plan={plan} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PlanCard({ plan }: { plan: Plan }) {
  const done = plan.steps.filter((s) => s.status === "done").length;
  return (
    <div className="fade-up rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-center gap-2">
        <h3 className="min-w-0 truncate text-sm font-medium text-zinc-100">{plan.title}</h3>
        <span
          className={clsx(
            "shrink-0 rounded-full px-1.5 py-px text-[10px]",
            plan.status === "done"
              ? "bg-emerald-500/15 text-emerald-300"
              : plan.status === "abandoned"
                ? "bg-zinc-700/50 text-zinc-400"
                : "bg-violet-500/15 text-violet-300",
          )}
        >
          {plan.status}
        </span>
        <span className="ml-auto shrink-0 text-[10px] tabular-nums text-zinc-500">
          {done}/{plan.steps.length} steps
        </span>
      </div>
      {plan.goal && <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{plan.goal}</p>}

      <ol className="mt-3 space-y-1.5">
        {plan.steps.map((step) => (
          <StepRow key={step.id} step={step} />
        ))}
      </ol>
      <div className="mt-2 font-mono text-[10px] text-zinc-700">{plan.id}</div>
    </div>
  );
}

function StepRow({ step }: { step: PlanStep }) {
  return (
    <li className="flex items-start gap-2">
      <span className={clsx("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", STEP_DOT[step.status])} />
      <span className="min-w-0">
        <span
          className={clsx(
            "text-xs",
            step.status === "done" ? "text-zinc-500 line-through" : "text-zinc-200",
          )}
        >
          {step.title}
        </span>
        {step.roles.length > 0 && (
          <span className="ml-1.5 text-[10px] text-zinc-600">({step.roles.join(", ")})</span>
        )}
        {step.notes && <span className="block text-[10px] text-zinc-600">{step.notes}</span>}
        <span className="ml-0 font-mono text-[9px] text-zinc-700">{step.id}</span>
      </span>
    </li>
  );
}
