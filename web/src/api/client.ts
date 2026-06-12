import type {
  AgentInfo,
  Health,
  MessagesResponse,
  NormalizedMessage,
  Project,
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
};
