export type ProjectIntent = "adhoc" | "goal";
export type ReviewMode = "manual" | "autonomous";

export type ProjectType = "application" | "meta";

export type Project = {
  id: string;
  name: string;
  root: string;
  session_count: number;
  missing: boolean;
  intent: ProjectIntent | null;
  goal: string | null;
  review_mode: ReviewMode | null;
  project_type: ProjectType | null;
  children: string[];
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
  intent?: ProjectIntent | null;
  goal?: string | null;
  review_mode?: ReviewMode | null;
  project_type?: ProjectType | null;
  children?: string[];
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
  role: string | null;
};

export type SessionDetail = SessionSummary & {
  project_id: string;
  handoff_command: string;
  /** Cumulative cost across this session's Orchid-driven turns (null until a turn completes). */
  cost_usd: number | null;
  turns: number;
};

/** Response of GET /api/projects/{pid}/usage — rolled-up cost across the project's sessions. */
export type ProjectUsage = {
  total_cost_usd: number;
  turns: number;
  sessions: number;
};

/** orchestrator = the session you drive; subagent = materialized via `agents=`;
 *  infra = covered by Orchid/the model, shipped off-by-default for visibility. */
export type RoleKind = "orchestrator" | "subagent" | "infra";

export type RoleTemplate = {
  slug: string;
  name: string;
  summary: string;
  kind: RoleKind;
  enabled: boolean;
  prompt: string;
  model: string | null;
  tools: string[] | null;
  disallowed_tools: string[] | null;
  note: string | null;
};

export type PlanStepStatus = "pending" | "in_progress" | "done" | "blocked";

export type PlanStep = {
  id: string;
  title: string;
  status: PlanStepStatus;
  roles: string[];
  notes: string | null;
};

export type Plan = {
  id: string;
  title: string;
  goal: string;
  status: "active" | "done" | "abandoned";
  steps: PlanStep[];
  created_at: string | null;
  updated_at: string | null;
};

/** Payload of a `plan_upserted` WS event (topic `sidebar`). */
export type PlanUpsertedEvent = {
  project_id: string;
  plan: Plan;
};

export type AgentStatus = "running" | "done";

export type AgentInfo = {
  agent_id: string;
  message_count: number;
  status: AgentStatus;
  /** Set from the `agent_started` event when known; absent from the REST list. */
  agent_type?: string;
};

/** Payload of a `choice_prompt` WS event (topic `onboarding`): a fixed-answer question the
 *  console agent wants rendered as one-click quick replies. */
export type ChoicePrompt = {
  id: string;
  question: string;
  options: string[];
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

/** Collaboration types. */

export type CollabParticipant = {
  project_id: string;
  label: string;
  session_id?: string | null;
};

export type CollabMessage = {
  id: string;
  sender: string;
  sender_label: string;
  content: string;
  timestamp: string;
};

export type CollabSummary = {
  id: string;
  title: string;
  participants: CollabParticipant[];
  message_count: number;
  state: "active" | "completed";
  auto_continue: boolean;
  created_at: string;
  updated_at: string;
};

export type CollabDetail = CollabSummary & {
  messages: CollabMessage[];
};

/** Response shape of GET /api/health. */
export type Health = {
  version: string;
  claude_cli_version: string;
  sdk_version: string;
  config_dir: string;
  orchid_home: string;
};

export type GitCommit = {
  hash: string;
  short_hash: string;
  message: string;
  author: string;
  date: string;
  refs: string;
};

export type Spec = {
  version: number;
  title: string;
  content: string;
  status: "active" | "archived";
  created_at: string | null;
  updated_at: string | null;
};

export type SpecUpdatedEvent = {
  project_id: string;
  spec: Spec;
};

export type PolicyProfile = "permissive" | "balanced" | "strict" | "custom";
export type GateMode = "required" | "optional" | "skip";

export type GateConfig = {
  mode: GateMode;
  max_lines?: number;
  patterns?: string[];
  criteria?: string;
};

export type Policy = {
  version: number;
  profile: PolicyProfile;
  plan_approval: "auto" | "human";
  review_strategy: "agent" | "human" | "self";
  merge_approval: "auto" | "human";
  gates: Record<string, GateConfig>;
  updated_at: string | null;
};

export type ReviewStatus = "pending" | "approved" | "changes_requested" | "merged";

export type ReviewRequest = {
  id: string;
  project_id: string;
  branch: string;
  summary: string;
  status: ReviewStatus;
  reviewer_notes: string | null;
  created_at: string | null;
  /** Observed checks the submitter ran (verifier output). Null = no evidence attached. */
  verification: string | null;
  /** Computed server-side on the single-review GET only (absent from the list response). */
  touches_tests?: boolean;
  files_changed?: number;
};
