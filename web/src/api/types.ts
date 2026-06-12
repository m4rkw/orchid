export type Project = {
  id: string;
  name: string;
  root: string;
  session_count: number;
  missing: boolean;
};

/** Per-project defaults. `null` model means "inherit". Not returned by GET /api/projects. */
export type ProjectSettings = {
  model?: string | null;
  permission_mode?: PermissionMode;
};

export type PermissionMode = "acceptEdits" | "default" | "plan" | "bypassPermissions";

/** Body of PATCH /api/projects/{pid}. */
export type ProjectUpdate = {
  name?: string;
  settings?: ProjectSettings;
};

export type SessionStatus = "idle" | "running" | "external";

export type SessionSummary = {
  id: string;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
  status: SessionStatus;
  message_count: number;
  pinned: boolean;
  archived: boolean;
  created_by: "orchid" | "external";
};

export type SessionDetail = SessionSummary & {
  project_id: string;
  handoff_command: string;
};

export type AgentStatus = "running" | "done";

export type AgentInfo = {
  agent_id: string;
  message_count: number;
  status: AgentStatus;
  /** Set from the `agent_started` event when known; absent from the REST list. */
  agent_type?: string;
};

/** Payload of a `permission_request` WS event. */
export type PermissionRequest = {
  request_id: string;
  tool_name: string;
  input_preview: string;
  display_name?: string;
  description?: string;
  expires_at: string;
};

/** Response of GET /api/sessions/{sid}/messages; `seq` is the WS replay watermark. */
export type MessagesResponse = {
  messages: NormalizedMessage[];
  seq: number;
};

/** 202 response of POST /api/sessions/{sid}/prompt. */
export type PromptAccepted = {
  state: string;
  queue_len: number;
};

/** 201 response of POST /api/sessions/{sid}/fork. */
export type ForkResponse = {
  session_id: string;
};

export type Block = {
  type: "text" | "thinking" | "tool_use" | "tool_result";
  text?: string;
  id?: string;
  name?: string;
  input_preview?: string;
  tool_use_id?: string;
  content_preview?: string;
  is_error?: boolean;
  truncated?: boolean;
};

export type NormalizedMessage = {
  uuid: string;
  role: "user" | "assistant" | "system" | "result";
  agent_id: string | null;
  blocks: Block[];
};

export type WsEvent = {
  topic: string;
  seq: number;
  type: string;
  payload: Record<string, unknown>;
};

/** Payload of a `session_removed` WS event (topic `sidebar`). */
export type SessionRemovedEvent = {
  project_id: string;
  session_id: string;
};

/** Payload of a `project_updated` WS event (topic `sidebar`). */
export type ProjectUpdatedEvent = {
  project: Project;
};

/** Payload of `agent_started` / `agent_stopped` WS events (topic `session:<sid>`). */
export type AgentLifecycleEvent = {
  agent_id: string;
  agent_type?: string;
};

/** Response shape of GET /api/health. */
export type Health = {
  version: string;
  claude_cli_version: string;
  sdk_version: string;
  config_dir: string;
  orchid_home: string;
};
