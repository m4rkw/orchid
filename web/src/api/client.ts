import type {
  AgentInfo,
  CollabDetail,
  CollabMessage,
  CollabSummary,
  ForkResponse,
  GitCommit,
  Health,
  MessagesResponse,
  NormalizedMessage,
  Plan,
  Policy,
  Project,
  PermissionRequest,
  ProjectUpdate,
  ProjectUsage,
  PromptAccepted,
  InboxItem,
  InboxStatus,
  ReviewRequest,
  RoleTemplate,
  SessionDetail,
  SessionSummary,
  Architecture,
  Spec,
} from "./types";

/** Normalized API error: carries HTTP status plus the backend's {error:{code,message}} body when present. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (err) {
    throw new ApiError(0, "network_error", err instanceof Error ? err.message : "Network request failed");
  }

  if (!res.ok) {
    let code = "http_error";
    let message = `HTTP ${res.status} ${res.statusText}`.trim();
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } };
      if (body && typeof body === "object" && body.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      }
    } catch {
      // non-JSON error body; keep the generic HTTP message
    }
    throw new ApiError(res.status, code, message);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  projects: () => request<Project[]>("/api/projects"),

  addProject: (path: string, name?: string) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(name === undefined ? { path } : { path, name }),
    }),

  deleteProject: (id: string) =>
    request<void>(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),

  updateProject: (id: string, patch: ProjectUpdate) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  sessions: (pid: string) =>
    request<SessionSummary[]>(`/api/projects/${encodeURIComponent(pid)}/sessions`),

  projectAgents: (pid: string) =>
    request<RoleTemplate[]>(`/api/projects/${encodeURIComponent(pid)}/agents`),

  setProjectAgents: (pid: string, roles: RoleTemplate[]) =>
    request<RoleTemplate[]>(`/api/projects/${encodeURIComponent(pid)}/agents`, {
      method: "PUT",
      body: JSON.stringify({ roles }),
    }),

  projectPlans: (pid: string) =>
    request<Plan[]>(`/api/projects/${encodeURIComponent(pid)}/plans`),

  projectPlan: (pid: string, planId: string) =>
    request<Plan>(`/api/projects/${encodeURIComponent(pid)}/plans/${encodeURIComponent(planId)}`),

  createSession: (pid: string, prompt: string) =>
    request<{ session_id: string }>(`/api/projects/${encodeURIComponent(pid)}/sessions`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),

  session: (sid: string) => request<SessionDetail>(`/api/sessions/${encodeURIComponent(sid)}`),

  sessionMessages: (sid: string) =>
    request<MessagesResponse>(`/api/sessions/${encodeURIComponent(sid)}/messages`),

  sessionMessage: (sid: string, uuid: string) =>
    request<NormalizedMessage>(
      `/api/sessions/${encodeURIComponent(sid)}/messages/${encodeURIComponent(uuid)}`,
    ),

  sessionAgents: (sid: string) =>
    request<AgentInfo[]>(`/api/sessions/${encodeURIComponent(sid)}/agents`),

  sessionPermissions: (sid: string) =>
    request<PermissionRequest[]>(`/api/sessions/${encodeURIComponent(sid)}/permissions`),

  renameSession: (sid: string, title: string) =>
    request<Record<string, never>>(`/api/sessions/${encodeURIComponent(sid)}/rename`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),

  pinSession: (sid: string, value: boolean) =>
    request<Record<string, never>>(`/api/sessions/${encodeURIComponent(sid)}/pin`, {
      method: "POST",
      body: JSON.stringify({ value }),
    }),

  archiveSession: (sid: string, value: boolean) =>
    request<Record<string, never>>(`/api/sessions/${encodeURIComponent(sid)}/archive`, {
      method: "POST",
      body: JSON.stringify({ value }),
    }),

  forkSession: (sid: string, title?: string) =>
    request<ForkResponse>(`/api/sessions/${encodeURIComponent(sid)}/fork`, {
      method: "POST",
      body: JSON.stringify(title === undefined ? {} : { title }),
    }),

  deleteSession: (sid: string, force?: boolean) =>
    request<void>(
      `/api/sessions/${encodeURIComponent(sid)}${force ? "?force=true" : ""}`,
      { method: "DELETE" },
    ),

  agentMessages: (sid: string, aid: string) =>
    request<{ messages: NormalizedMessage[] }>(
      `/api/sessions/${encodeURIComponent(sid)}/agents/${encodeURIComponent(aid)}/messages`,
    ),

  sendPrompt: (sid: string, prompt: string, force?: boolean) =>
    request<PromptAccepted>(`/api/sessions/${encodeURIComponent(sid)}/prompt`, {
      method: "POST",
      body: JSON.stringify(force === undefined ? { prompt } : { prompt, force }),
    }),

  interrupt: (sid: string) =>
    request<Record<string, never>>(`/api/sessions/${encodeURIComponent(sid)}/interrupt`, {
      method: "POST",
    }),

  respondPermission: (requestId: string, behavior: "allow" | "deny") =>
    request<Record<string, never>>(`/api/permissions/${encodeURIComponent(requestId)}`, {
      method: "POST",
      body: JSON.stringify({ behavior }),
    }),

  projectActivity: (pid: string, limit?: number) =>
    request<GitCommit[]>(
      `/api/projects/${encodeURIComponent(pid)}/activity${limit ? `?limit=${limit}` : ""}`,
    ),

  projectUsage: (pid: string) =>
    request<ProjectUsage>(`/api/projects/${encodeURIComponent(pid)}/usage`),

  projectSpec: (pid: string) =>
    request<Spec>(`/api/projects/${encodeURIComponent(pid)}/spec`),

  putProjectSpec: (pid: string, content: string, title?: string) =>
    request<Spec>(`/api/projects/${encodeURIComponent(pid)}/spec`, {
      method: "PUT",
      body: JSON.stringify(title !== undefined ? { content, title } : { content }),
    }),

  projectArchitecture: (pid: string) =>
    request<Architecture>(`/api/projects/${encodeURIComponent(pid)}/architecture`),

  putProjectArchitecture: (pid: string, content: string, title?: string) =>
    request<Architecture>(`/api/projects/${encodeURIComponent(pid)}/architecture`, {
      method: "PUT",
      body: JSON.stringify(title !== undefined ? { content, title } : { content }),
    }),

  projectReviews: (pid: string) =>
    request<ReviewRequest[]>(`/api/projects/${encodeURIComponent(pid)}/reviews`),

  projectReview: (pid: string, rid: string) =>
    request<ReviewRequest>(
      `/api/projects/${encodeURIComponent(pid)}/reviews/${encodeURIComponent(rid)}`,
    ),

  verifyReview: (pid: string, rid: string) =>
    request<ReviewRequest>(
      `/api/projects/${encodeURIComponent(pid)}/reviews/${encodeURIComponent(rid)}/verify`,
      { method: "POST" },
    ),

  reviewDiff: (pid: string, rid: string) =>
    request<{ diff: string }>(
      `/api/projects/${encodeURIComponent(pid)}/reviews/${encodeURIComponent(rid)}/diff`,
    ),

  approveReview: (pid: string, rid: string, notes?: string) =>
    request<ReviewRequest>(
      `/api/projects/${encodeURIComponent(pid)}/reviews/${encodeURIComponent(rid)}/approve`,
      { method: "POST", body: JSON.stringify({ notes: notes ?? null }) },
    ),

  projectPolicy: (pid: string) =>
    request<Policy>(`/api/projects/${encodeURIComponent(pid)}/policy`),

  putProjectPolicy: (pid: string, policy: Partial<Policy>) =>
    request<Policy>(`/api/projects/${encodeURIComponent(pid)}/policy`, {
      method: "PUT",
      body: JSON.stringify(policy),
    }),

  rejectReview: (pid: string, rid: string, notes?: string) =>
    request<ReviewRequest>(
      `/api/projects/${encodeURIComponent(pid)}/reviews/${encodeURIComponent(rid)}/reject`,
      { method: "POST", body: JSON.stringify({ notes: notes ?? null }) },
    ),

  // -- inbox -----------------------------------------------------------------

  inboxAll: (status?: InboxStatus, source?: string) => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if (source) q.set("source", source);
    const qs = q.toString();
    return request<InboxItem[]>(`/api/inbox${qs ? `?${qs}` : ""}`);
  },

  resolveInboxItem: (pid: string, id: string, optionId: string, payload?: Record<string, unknown>) =>
    request<InboxItem>(
      `/api/projects/${encodeURIComponent(pid)}/inbox/${encodeURIComponent(id)}/resolve`,
      { method: "POST", body: JSON.stringify(payload !== undefined ? { option_id: optionId, payload } : { option_id: optionId }) },
    ),

  dismissInboxItem: (pid: string, id: string) =>
    request<InboxItem>(
      `/api/projects/${encodeURIComponent(pid)}/inbox/${encodeURIComponent(id)}/dismiss`,
      { method: "POST" },
    ),

  onboardingPrompt: (prompt: string) =>
    request<Record<string, never>>("/api/onboarding/prompt", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),

  onboardingReset: () =>
    request<Record<string, never>>("/api/onboarding/reset", { method: "POST" }),

  onboardingMessages: () =>
    request<{ messages: NormalizedMessage[]; running: boolean }>("/api/onboarding/messages"),

  // -- collaborations --------------------------------------------------------

  collaborations: () => request<CollabSummary[]>("/api/collaborations"),

  collabEligibleProjects: () =>
    request<Array<{ id: string; name: string; session_count: number }>>("/api/collaborations/eligible-projects"),

  collaboration: (cid: string) =>
    request<CollabDetail>(`/api/collaborations/${encodeURIComponent(cid)}`),

  createCollaboration: (projectIds: string[]) =>
    request<CollabDetail>("/api/collaborations", {
      method: "POST",
      body: JSON.stringify({ project_ids: projectIds }),
    }),

  sendCollabMessage: (cid: string, message: string) =>
    request<CollabMessage>(`/api/collaborations/${encodeURIComponent(cid)}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  continueCollab: (cid: string, targetIndex?: number) =>
    request<{ status: string }>(
      `/api/collaborations/${encodeURIComponent(cid)}/continue`,
      {
        method: "POST",
        body: JSON.stringify(targetIndex !== undefined ? { target_index: targetIndex } : {}),
      },
    ),

  setCollabAutoContinue: (cid: string, value: boolean) =>
    request<{ status: string }>(
      `/api/collaborations/${encodeURIComponent(cid)}/auto-continue`,
      { method: "POST", body: JSON.stringify({ value }) },
    ),

  endCollab: (cid: string) =>
    request<CollabDetail>(`/api/collaborations/${encodeURIComponent(cid)}/end`, {
      method: "POST",
    }),

  deleteCollab: (cid: string) =>
    request<void>(`/api/collaborations/${encodeURIComponent(cid)}`, {
      method: "DELETE",
    }),
};
