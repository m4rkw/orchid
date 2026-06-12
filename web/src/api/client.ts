import type {
  AgentInfo,
  ForkResponse,
  Health,
  MessagesResponse,
  NormalizedMessage,
  Project,
  ProjectUpdate,
  PromptAccepted,
  SessionDetail,
  SessionSummary,
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

  onboardingPrompt: (prompt: string) =>
    request<Record<string, never>>("/api/onboarding/prompt", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),

  onboardingReset: () =>
    request<Record<string, never>>("/api/onboarding/reset", { method: "POST" }),

  onboardingMessages: () =>
    request<{ messages: NormalizedMessage[]; running: boolean }>("/api/onboarding/messages"),
};
