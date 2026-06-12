import { create } from "zustand";
import type {
  AgentInfo,
  NormalizedMessage,
  PermissionRequest,
  Project,
  SessionStatus,
  SessionSummary,
  WsEvent,
} from "../api/types";
import { queryClient } from "./queryClient";

export type Selection = { pid: string; sid?: string; compose?: boolean } | null;

/** Concatenated text-block content of a message ("" if it has none). */
export function messageText(message: NormalizedMessage): string {
  return message.blocks
    .filter((b) => b.type === "text")
    .map((b) => b.text ?? "")
    .join("\n")
    .trim();
}

const LOCAL_PREFIX = "local-";

/** True for client-generated rows (optimistic prompts, turn dividers). */
export function isLocalUuid(uuid: string): boolean {
  return uuid.startsWith(LOCAL_PREFIX);
}

function localUuid(): string {
  return `${LOCAL_PREFIX}${crypto.randomUUID()}`;
}

function turnDivider(payload: Record<string, unknown>): NormalizedMessage {
  const cost = typeof payload.total_cost_usd === "number" ? payload.total_cost_usd : undefined;
  const duration = typeof payload.duration_ms === "number" ? payload.duration_ms : undefined;
  const numTurns = typeof payload.num_turns === "number" ? payload.num_turns : undefined;
  const isError = payload.is_error === true;
  const parts = [isError ? "turn failed" : "turn done"];
  if (cost !== undefined) parts.push(`$${cost.toFixed(4)}`);
  if (duration !== undefined) parts.push(`${(duration / 1000).toFixed(1)}s`);
  if (numTurns !== undefined) parts.push(`${numTurns} ${numTurns === 1 ? "turn" : "turns"}`);
  return { uuid: localUuid(), role: "result", agent_id: null, blocks: [{ type: "text", text: parts.join(" · ") }] };
}

/** A permission card as kept in the store (payload + client-side lifecycle flag). */
export type PermissionCard = PermissionRequest & { expired: boolean };

/**
 * Live transcript state for one session.
 *
 * Until the REST backlog has been seeded, WS events queue in `pending`; the
 * seed then applies everything past the REST watermark in order. After seeding
 * every session-topic event advances `seq`; a gap drops back to the queueing
 * state and refetches the backlog.
 */
export type SessionBuffer = {
  seeded: boolean;
  /** Watermark: highest applied seq on topic `session:<sid>` (REST seed or WS). */
  seq: number;
  messages: NormalizedMessage[];
  /** uuid -> true for every message in `messages`. */
  seen: Record<string, true>;
  /** Events received before the backlog seed (applied, in order, on seed). */
  pending: WsEvent[];
  /** A turn is in flight (turn_started/turn_completed; optimistic on send). */
  running: boolean;
  lastError: string | null;
  lastTurn: { cost?: number; durationMs?: number } | null;
};

const emptyBuffer = (): SessionBuffer => ({
  seeded: false,
  seq: -1,
  messages: [],
  seen: {},
  pending: [],
  running: false,
  lastError: null,
  lastTurn: null,
});

const MAX_PENDING_EVENTS = 1000;

/**
 * Full (untruncated) messages fetched via GET /messages/{uuid}, kept across
 * reseeds so a backlog refetch doesn't re-truncate already-expanded messages.
 */
const fullMessageCache = new Map<string, NormalizedMessage>();

type AppState = {
  selected: Selection;
  onboarding: {
    messages: NormalizedMessage[];
    running: boolean;
    lastError: string | null;
  };
  sessionStatuses: Record<string, SessionStatus>;
  queueLens: Record<string, number>;
  sessionBuffers: Record<string, SessionBuffer>;
  agents: Record<string, AgentInfo[]>;
  permissions: Record<string, PermissionCard[]>;
  /** Bumped to ask the onboarding composer to grab focus. */
  composerFocusKey: number;

  select: (selected: Selection) => void;
  focusComposer: () => void;
  appendOnboardingUser: (text: string) => void;
  setOnboardingError: (message: string | null) => void;
  resetOnboarding: () => void;

  /** Make sure a buffer exists for sid (call before subscribing to its topic). */
  ensureSession: (sid: string) => void;
  /** Seed/replace the transcript from GET /messages, then drain queued WS events. */
  seedSession: (sid: string, messages: NormalizedMessage[], seq: number) => void;
  /** Drop live state (watermark, queue) on deselect; keeps messages as a cache. */
  clearSessionLive: (sid: string) => void;
  appendSessionUser: (sid: string, text: string) => void;
  setSessionError: (sid: string, message: string | null) => void;
  setSessionRunning: (sid: string, running: boolean) => void;
  /** Swap in the untruncated version of a message (and remember it across reseeds). */
  markMessageFull: (sid: string, message: NormalizedMessage) => void;
  setQueueLen: (sid: string, queueLen: number) => void;
  setAgents: (sid: string, agents: AgentInfo[]) => void;
  resolvePermission: (sid: string, requestId: string) => void;
  expirePermission: (sid: string, requestId: string) => void;

  /** Single reducer for every WsEvent coming off the socket. */
  apply: (event: WsEvent) => void;
};

/** Pure transcript-event application (message/turn/error) used live and on seed-drain. */
function applyToBuffer(buf: SessionBuffer, event: WsEvent): SessionBuffer {
  const { type, payload } = event;
  switch (type) {
    case "message": {
      const message = payload.message as NormalizedMessage;
      if (!message || typeof message.uuid !== "string") return buf;
      if (buf.seen[message.uuid]) return buf;
      const canonical = fullMessageCache.get(message.uuid) ?? message;
      // If the server echoes a prompt we appended optimistically, swap the
      // optimistic copy for the canonical one instead of duplicating.
      if (canonical.role === "user") {
        const incoming = messageText(canonical);
        if (incoming) {
          const idx = buf.messages.findIndex(
            (m) => m.role === "user" && m.uuid.startsWith(LOCAL_PREFIX) && messageText(m) === incoming,
          );
          if (idx !== -1) {
            const next = buf.messages.slice();
            next[idx] = canonical;
            const seen = { ...buf.seen, [canonical.uuid]: true as const };
            delete seen[buf.messages[idx].uuid];
            return { ...buf, messages: next, seen };
          }
        }
      }
      return {
        ...buf,
        messages: [...buf.messages, canonical],
        seen: { ...buf.seen, [canonical.uuid]: true },
      };
    }
    case "turn_started":
      return { ...buf, running: true, lastError: null };
    case "turn_completed": {
      const cost = typeof payload.total_cost_usd === "number" ? payload.total_cost_usd : undefined;
      const durationMs = typeof payload.duration_ms === "number" ? payload.duration_ms : undefined;
      const divider = turnDivider(payload);
      return {
        ...buf,
        running: false,
        lastTurn: { cost, durationMs },
        messages: [...buf.messages, divider],
        seen: { ...buf.seen, [divider.uuid]: true },
      };
    }
    case "error": {
      const message = typeof payload.message === "string" ? payload.message : "Unknown session error";
      return { ...buf, running: false, lastError: message };
    }
    default:
      return buf;
  }
}

function upsertAgent(list: AgentInfo[] | undefined, agentId: string, patch: Partial<AgentInfo>): AgentInfo[] {
  const agents = list ?? [];
  const idx = agents.findIndex((a) => a.agent_id === agentId);
  if (idx === -1) {
    return [...agents, { agent_id: agentId, message_count: 0, status: "running", ...patch }];
  }
  const next = agents.slice();
  next[idx] = { ...next[idx], ...patch };
  return next;
}

export const useAppStore = create<AppState>()((set, get) => ({
  selected: null,
  onboarding: { messages: [], running: false, lastError: null },
  sessionStatuses: {},
  queueLens: {},
  sessionBuffers: {},
  agents: {},
  permissions: {},
  composerFocusKey: 0,

  select: (selected) => set({ selected }),

  focusComposer: () => set((s) => ({ composerFocusKey: s.composerFocusKey + 1 })),

  appendOnboardingUser: (text) =>
    set((s) => ({
      onboarding: {
        ...s.onboarding,
        running: true, // optimistic; confirmed by turn_started
        lastError: null,
        messages: [
          ...s.onboarding.messages,
          { uuid: localUuid(), role: "user", agent_id: null, blocks: [{ type: "text", text }] },
        ],
      },
    })),

  setOnboardingError: (message) =>
    set((s) => ({
      onboarding: {
        ...s.onboarding,
        lastError: message,
        // an error ends the run; clearing the error leaves the run state alone
        running: message === null ? s.onboarding.running : false,
      },
    })),

  resetOnboarding: () => set({ onboarding: { messages: [], running: false, lastError: null } }),

  ensureSession: (sid) =>
    set((s) => (s.sessionBuffers[sid] ? s : { sessionBuffers: { ...s.sessionBuffers, [sid]: emptyBuffer() } })),

  seedSession: (sid, messages, seq) =>
    set((s) => {
      const prev = s.sessionBuffers[sid] ?? emptyBuffer();
      // A stale snapshot (older than what we've already applied live) is ignored.
      if (prev.seeded && seq < prev.seq) return s;
      const canonical = messages.map((m) => fullMessageCache.get(m.uuid) ?? m);
      const seen: Record<string, true> = {};
      for (const m of canonical) seen[m.uuid] = true;
      let buf: SessionBuffer = {
        ...prev,
        seeded: true,
        seq,
        messages: canonical,
        seen,
        pending: [],
      };
      // Drain events that arrived while the backlog was in flight.
      for (const event of prev.pending) {
        if (event.seq <= buf.seq) continue;
        buf = { ...applyToBuffer(buf, event), seq: event.seq };
      }
      return { sessionBuffers: { ...s.sessionBuffers, [sid]: buf } };
    }),

  clearSessionLive: (sid) =>
    set((s) => {
      const prev = s.sessionBuffers[sid];
      if (!prev) return s;
      return {
        sessionBuffers: {
          ...s.sessionBuffers,
          [sid]: { ...prev, seeded: false, seq: -1, pending: [], running: false },
        },
      };
    }),

  appendSessionUser: (sid, text) =>
    set((s) => {
      const prev = s.sessionBuffers[sid] ?? emptyBuffer();
      const msg: NormalizedMessage = {
        uuid: localUuid(),
        role: "user",
        agent_id: null,
        blocks: [{ type: "text", text }],
      };
      return {
        sessionBuffers: {
          ...s.sessionBuffers,
          [sid]: {
            ...prev,
            lastError: null,
            messages: [...prev.messages, msg],
            seen: { ...prev.seen, [msg.uuid]: true },
          },
        },
      };
    }),

  setSessionError: (sid, message) =>
    set((s) => {
      const prev = s.sessionBuffers[sid] ?? emptyBuffer();
      return { sessionBuffers: { ...s.sessionBuffers, [sid]: { ...prev, lastError: message } } };
    }),

  setSessionRunning: (sid, running) =>
    set((s) => {
      const prev = s.sessionBuffers[sid] ?? emptyBuffer();
      return { sessionBuffers: { ...s.sessionBuffers, [sid]: { ...prev, running } } };
    }),

  markMessageFull: (sid, message) => {
    fullMessageCache.set(message.uuid, message);
    set((s) => {
      const prev = s.sessionBuffers[sid];
      if (!prev) return s;
      const idx = prev.messages.findIndex((m) => m.uuid === message.uuid);
      if (idx === -1) return s;
      const next = prev.messages.slice();
      next[idx] = message;
      return { sessionBuffers: { ...s.sessionBuffers, [sid]: { ...prev, messages: next } } };
    });
  },

  setQueueLen: (sid, queueLen) => set((s) => ({ queueLens: { ...s.queueLens, [sid]: queueLen } })),

  setAgents: (sid, agents) => set((s) => ({ agents: { ...s.agents, [sid]: agents } })),

  resolvePermission: (sid, requestId) =>
    set((s) => ({
      permissions: {
        ...s.permissions,
        [sid]: (s.permissions[sid] ?? []).filter((p) => p.request_id !== requestId),
      },
    })),

  expirePermission: (sid, requestId) =>
    set((s) => ({
      permissions: {
        ...s.permissions,
        [sid]: (s.permissions[sid] ?? []).map((p) => (p.request_id === requestId ? { ...p, expired: true } : p)),
      },
    })),

  apply: (event) => {
    const { topic, type, payload } = event;

    if (topic === "sidebar") {
      switch (type) {
        case "project_added": {
          const project = payload.project as Project;
          const cached = queryClient.getQueryData<Project[]>(["projects"]);
          if (cached) {
            queryClient.setQueryData<Project[]>(
              ["projects"],
              cached.some((p) => p.id === project.id)
                ? cached.map((p) => (p.id === project.id ? project : p))
                : [...cached, project],
            );
          } else {
            void queryClient.invalidateQueries({ queryKey: ["projects"] });
          }
          break;
        }
        case "project_removed": {
          const pid = payload.project_id as string;
          queryClient.setQueryData<Project[]>(["projects"], (old) => old?.filter((p) => p.id !== pid));
          queryClient.removeQueries({ queryKey: ["sessions", pid] });
          if (get().selected?.pid === pid) set({ selected: null });
          break;
        }
        case "session_upserted": {
          const pid = payload.project_id as string;
          const session = payload.session as SessionSummary;
          set((s) => ({ sessionStatuses: { ...s.sessionStatuses, [session.id]: session.status } }));
          const cached = queryClient.getQueryData<SessionSummary[]>(["sessions", pid]);
          if (cached) {
            const idx = cached.findIndex((x) => x.id === session.id);
            if (idx === -1) {
              queryClient.setQueryData<SessionSummary[]>(["sessions", pid], [session, ...cached]);
              // a brand-new session bumps the project's badge
              queryClient.setQueryData<Project[]>(["projects"], (old) =>
                old?.map((p) => (p.id === pid ? { ...p, session_count: p.session_count + 1 } : p)),
              );
            } else {
              const next = cached.slice();
              next[idx] = session;
              queryClient.setQueryData<SessionSummary[]>(["sessions", pid], next);
            }
          } else {
            void queryClient.invalidateQueries({ queryKey: ["sessions", pid] });
          }
          break;
        }
        case "session_status": {
          const sid = payload.session_id as string;
          const status = payload.status as SessionStatus;
          const queueLen = typeof payload.queue_len === "number" ? payload.queue_len : 0;
          set((s) => ({
            sessionStatuses: { ...s.sessionStatuses, [sid]: status },
            queueLens: { ...s.queueLens, [sid]: queueLen },
          }));
          break;
        }
      }
      return;
    }

    if (topic.startsWith("session:")) {
      const sid = topic.slice("session:".length);
      const buf = get().sessionBuffers[sid];
      if (!buf) return; // not tracked (never selected); nothing to update

      // Backlog not loaded yet: queue everything, the seed drains it in order.
      if (!buf.seeded) {
        if (buf.pending.length >= MAX_PENDING_EVENTS) return;
        set((s) => ({
          sessionBuffers: { ...s.sessionBuffers, [sid]: { ...buf, pending: [...buf.pending, event] } },
        }));
        return;
      }

      if (event.seq <= buf.seq) return; // replayed/duplicate
      if (event.seq > buf.seq + 1) {
        // Gap: drop back to queueing and refetch the backlog.
        set((s) => ({
          sessionBuffers: {
            ...s.sessionBuffers,
            [sid]: { ...buf, seeded: false, pending: [event] },
          },
        }));
        void queryClient.invalidateQueries({ queryKey: ["session-messages", sid] });
        return;
      }

      // In-order event: transcript bits first, then the keyed side tables.
      set((s) => {
        const cur = s.sessionBuffers[sid];
        if (!cur) return s;
        return { sessionBuffers: { ...s.sessionBuffers, [sid]: { ...applyToBuffer(cur, event), seq: event.seq } } };
      });

      switch (type) {
        case "message": {
          const message = payload.message as NormalizedMessage;
          if (message?.agent_id) {
            set((s) => ({
              agents: {
                ...s.agents,
                [sid]: upsertAgent(s.agents[sid], message.agent_id as string, {}).map((a) =>
                  a.agent_id === message.agent_id ? { ...a, message_count: a.message_count + 1 } : a,
                ),
              },
            }));
          }
          break;
        }
        case "agent_started": {
          const agentId = payload.agent_id as string;
          set((s) => ({
            agents: { ...s.agents, [sid]: upsertAgent(s.agents[sid], agentId, { status: "running" }) },
          }));
          break;
        }
        case "agent_stopped": {
          const agentId = payload.agent_id as string;
          set((s) => ({
            agents: { ...s.agents, [sid]: upsertAgent(s.agents[sid], agentId, { status: "done" }) },
          }));
          void queryClient.invalidateQueries({ queryKey: ["agent-messages", sid, agentId] });
          void queryClient.invalidateQueries({ queryKey: ["session-agents", sid] });
          break;
        }
        case "permission_request": {
          const card = payload as unknown as PermissionRequest;
          if (typeof card.request_id !== "string") break;
          set((s) => {
            const cards = s.permissions[sid] ?? [];
            if (cards.some((p) => p.request_id === card.request_id)) return s;
            return { permissions: { ...s.permissions, [sid]: [...cards, { ...card, expired: false }] } };
          });
          break;
        }
      }
      return;
    }

    if (topic === "onboarding") {
      switch (type) {
        case "message": {
          const message = payload.message as NormalizedMessage;
          set((s) => {
            const msgs = s.onboarding.messages;
            if (msgs.some((m) => m.uuid === message.uuid)) return s; // replay
            // If the server echoes the prompt we already appended optimistically,
            // swap the optimistic copy for the canonical one instead of duplicating.
            if (message.role === "user") {
              const incoming = messageText(message);
              if (incoming) {
                const idx = msgs.findIndex(
                  (m) => m.role === "user" && m.uuid.startsWith(LOCAL_PREFIX) && messageText(m) === incoming,
                );
                if (idx !== -1) {
                  const next = msgs.slice();
                  next[idx] = message;
                  return { onboarding: { ...s.onboarding, messages: next } };
                }
              }
            }
            return { onboarding: { ...s.onboarding, messages: [...msgs, message] } };
          });
          break;
        }
        case "turn_started":
          set((s) => ({ onboarding: { ...s.onboarding, running: true, lastError: null } }));
          break;
        case "turn_completed": {
          const cost = typeof payload.total_cost_usd === "number" ? payload.total_cost_usd : undefined;
          const duration = typeof payload.duration_ms === "number" ? payload.duration_ms : undefined;
          const parts = ["turn done"];
          if (cost !== undefined) parts.push(`$${cost.toFixed(4)}`);
          if (duration !== undefined) parts.push(`${(duration / 1000).toFixed(1)}s`);
          const divider: NormalizedMessage = {
            uuid: localUuid(),
            role: "result",
            agent_id: null,
            blocks: [{ type: "text", text: parts.join(" · ") }],
          };
          set((s) => ({
            onboarding: { ...s.onboarding, running: false, messages: [...s.onboarding.messages, divider] },
          }));
          break;
        }
        case "project_registered":
          void queryClient.invalidateQueries({ queryKey: ["projects"] });
          break;
        case "error": {
          const message = typeof payload.message === "string" ? payload.message : "Unknown onboarding error";
          set((s) => ({ onboarding: { ...s.onboarding, running: false, lastError: message } }));
          break;
        }
      }
    }
  },
}));
