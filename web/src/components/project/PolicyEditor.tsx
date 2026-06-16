import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { GateConfig, GateMode, Policy, PolicyProfile } from "../../api/types";
import { queryClient } from "../../state/queryClient";

const PROFILES: { key: PolicyProfile; label: string; desc: string; color: string }[] = [
  { key: "permissive", label: "Permissive", desc: "Auto-ship. Minimal gates.", color: "amber" },
  { key: "balanced", label: "Balanced", desc: "Quality gates + agent review.", color: "blue" },
  { key: "strict", label: "Strict", desc: "Human approves everything.", color: "emerald" },
];

const GATE_LABELS: Record<string, string> = {
  tests_pass: "Tests pass",
  spec_compliance: "Spec compliance",
  diff_budget: "Diff budget",
  no_new_deps: "No new deps",
  sensitive_files: "Sensitive files",
  acceptance_criteria: "Acceptance criteria",
};

const GATE_MODES: GateMode[] = ["required", "optional", "skip"];

const MODE_COLORS: Record<GateMode, string> = {
  required: "text-emerald-400",
  optional: "text-amber-400",
  skip: "text-zinc-500",
};

export function PolicyEditor({ pid }: { pid: string }) {
  const policy = useQuery({
    queryKey: ["policy", pid],
    queryFn: () => api.projectPolicy(pid),
  });

  const [profile, setProfile] = useState<PolicyProfile>("balanced");
  const [planApproval, setPlanApproval] = useState<"auto" | "human">("auto");
  const [reviewStrategy, setReviewStrategy] = useState<"agent" | "human" | "self">("agent");
  const [mergeApproval, setMergeApproval] = useState<"auto" | "human">("auto");
  const [gates, setGates] = useState<Record<string, GateConfig>>({});
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (policy.data && !initialized) {
      setProfile(policy.data.profile);
      setPlanApproval(policy.data.plan_approval);
      setReviewStrategy(policy.data.review_strategy);
      setMergeApproval(policy.data.merge_approval);
      setGates(policy.data.gates);
      setInitialized(true);
    }
  }, [policy.data, initialized]);

  const save = useMutation({
    mutationFn: (p: Partial<Policy>) => api.putProjectPolicy(pid, p),
    onSuccess: (updated) => {
      queryClient.setQueryData(["policy", pid], updated);
      setProfile(updated.profile);
    },
  });

  const selectProfile = (key: PolicyProfile) => {
    setProfile(key);
    save.mutate({ profile: key });
    setInitialized(false);
  };

  const updateField = (field: string, value: string) => {
    const patch: Partial<Policy> = {};
    if (field === "plan_approval") {
      setPlanApproval(value as "auto" | "human");
      patch.plan_approval = value as "auto" | "human";
    } else if (field === "review_strategy") {
      setReviewStrategy(value as "agent" | "human" | "self");
      patch.review_strategy = value as "agent" | "human" | "self";
    } else if (field === "merge_approval") {
      setMergeApproval(value as "auto" | "human");
      patch.merge_approval = value as "auto" | "human";
    }
    setProfile("custom");
    save.mutate(patch);
  };

  const updateGate = (name: string, mode: GateMode) => {
    const updated = { ...gates, [name]: { ...gates[name], mode } };
    setGates(updated);
    setProfile("custom");
    save.mutate({ gates: { [name]: { ...gates[name], mode } } });
  };

  const updateGateConfig = (name: string, key: string, value: string | number | string[]) => {
    const updated = { ...gates, [name]: { ...gates[name], [key]: value } };
    setGates(updated);
    setProfile("custom");
    save.mutate({ gates: { [name]: { ...gates[name], [key]: value } } });
  };

  if (policy.isLoading) {
    return <div className="py-4 text-sm text-zinc-500">Loading policy...</div>;
  }

  return (
    <div>
      <h2 className="text-base font-medium text-zinc-100">Autonomy policy</h2>
      <p className="mt-1 text-xs text-zinc-500">
        Controls how much human involvement is needed at each workflow stage.
      </p>

      {/* Profile selector */}
      <div className="mt-4 flex gap-2">
        {PROFILES.map((p) => (
          <button
            key={p.key}
            onClick={() => selectProfile(p.key)}
            className={`flex-1 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
              profile === p.key
                ? `border-${p.color}-500/50 bg-${p.color}-500/10 text-${p.color}-300`
                : "border-zinc-700 bg-zinc-900/40 text-zinc-400 hover:border-zinc-600"
            }`}
          >
            <div className="font-medium">{p.label}</div>
            <div className="mt-0.5 text-[10px] opacity-70">{p.desc}</div>
          </button>
        ))}
      </div>
      {profile === "custom" && (
        <div className="mt-2 text-[10px] text-violet-400/70">Custom policy (modified from preset)</div>
      )}

      {/* Pipeline controls */}
      <div className="mt-5 space-y-3">
        <h3 className="text-xs font-medium text-zinc-400">Pipeline</h3>
        <div className="grid grid-cols-3 gap-3">
          <label className="block">
            <span className="mb-1 block text-[10px] text-zinc-500">Plan approval</span>
            <select
              value={planApproval}
              onChange={(e) => updateField("plan_approval", e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-ink-900 px-2 py-1 text-xs text-zinc-200 outline-none focus:border-violet-500/60"
            >
              <option value="auto">Auto</option>
              <option value="human">Human</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[10px] text-zinc-500">Review strategy</span>
            <select
              value={reviewStrategy}
              onChange={(e) => updateField("review_strategy", e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-ink-900 px-2 py-1 text-xs text-zinc-200 outline-none focus:border-violet-500/60"
            >
              <option value="self">Self</option>
              <option value="agent">Agent</option>
              <option value="human">Human</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[10px] text-zinc-500">Merge approval</span>
            <select
              value={mergeApproval}
              onChange={(e) => updateField("merge_approval", e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-ink-900 px-2 py-1 text-xs text-zinc-200 outline-none focus:border-violet-500/60"
            >
              <option value="auto">Auto</option>
              <option value="human">Human</option>
            </select>
          </label>
        </div>
      </div>

      {/* Quality gates */}
      <div className="mt-5 space-y-2">
        <h3 className="text-xs font-medium text-zinc-400">Quality gates</h3>
        <div className="space-y-1.5">
          {Object.entries(gates).map(([name, cfg]) => (
            <div key={name} className="rounded-md border border-zinc-800 bg-zinc-900/30 px-3 py-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-zinc-300">{GATE_LABELS[name] ?? name}</span>
                <div className="flex gap-1">
                  {GATE_MODES.map((m) => (
                    <button
                      key={m}
                      onClick={() => updateGate(name, m)}
                      className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                        cfg.mode === m
                          ? `${MODE_COLORS[m]} bg-zinc-800`
                          : "text-zinc-600 hover:text-zinc-400"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>
              {name === "diff_budget" && cfg.mode !== "skip" && (
                <label className="mt-1.5 flex items-center gap-2 text-[10px] text-zinc-500">
                  Max lines:
                  <input
                    type="number"
                    value={cfg.max_lines ?? 500}
                    onChange={(e) => updateGateConfig(name, "max_lines", parseInt(e.target.value) || 500)}
                    className="w-20 rounded border border-zinc-700 bg-ink-900 px-2 py-0.5 text-xs text-zinc-300 outline-none"
                  />
                </label>
              )}
              {name === "sensitive_files" && cfg.mode !== "skip" && (
                <label className="mt-1.5 block text-[10px] text-zinc-500">
                  Patterns (one per line):
                  <textarea
                    value={(cfg.patterns ?? []).join("\n")}
                    onChange={(e) => updateGateConfig(name, "patterns", e.target.value.split("\n").filter(Boolean))}
                    rows={2}
                    className="mt-0.5 w-full rounded border border-zinc-700 bg-ink-900 px-2 py-1 font-mono text-xs text-zinc-300 outline-none"
                    placeholder="*.env&#10;*.pem"
                  />
                </label>
              )}
              {name === "acceptance_criteria" && cfg.mode !== "skip" && (
                <label className="mt-1.5 block text-[10px] text-zinc-500">
                  Criteria:
                  <textarea
                    value={cfg.criteria ?? ""}
                    onChange={(e) => updateGateConfig(name, "criteria", e.target.value)}
                    rows={3}
                    className="mt-0.5 w-full rounded border border-zinc-700 bg-ink-900 px-2 py-1 text-xs text-zinc-300 outline-none"
                    placeholder="The API must remain backwards-compatible..."
                  />
                </label>
              )}
            </div>
          ))}
        </div>
      </div>

      {save.isError && (
        <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {save.error instanceof Error ? save.error.message : "Failed to save"}
        </div>
      )}
      {save.isSuccess && !save.isPending && (
        <div className="mt-2 text-[10px] text-violet-300/60">Saved</div>
      )}
    </div>
  );
}
