import { create } from "zustand";
import type { NormalizedMessage, Project, SessionStatus, SessionSummary, WsEvent } from "../api/types";
import { queryClient } from "./queryClient";

export type Selection = { pid?: string; sid?: string } | null;

/** Concatenated text-block content of a message ("" if it has none). */
export function messageText(message: NormalizedMessage): string {
  return message.blocks
    .filter((b) => b.type === "text")
    .map((b) => b.text ?? "")
    .join("\n")
    .trim();
}

const LOCAL_PREFIX = "local-";

function localUuid(): string {
  return `${LOCAL_PREFIX}${crypto.randomUUID()}`;
}

type AppState = {
  selected: Selection;
  onboarding: {
    messages: NormalizedMessage[];
    running: boolean;
    lastError: string | null;
  };
  sessionStatuses: Record<string, SessionStatus>;
  /** Bumped to ask the onboarding composer to grab focus. */
  composerFocusKey: number;

  select: (selected: Selection) => void;
  focusComposer: () => void;
  appendOnboardingUser: (text: string) => void;
  setOnboardingError: (message: string | null) => void;
  resetOnboarding: () => void;
  /** Single reducer for every WsEvent coming off the socket. */
  apply: (event: WsEvent) => void;
};

export const useAppStore = create<AppState>()((set, get) => ({
  selected: null,
  onboarding: { messages: [], running: false, lastError: null },
  sessionStatuses: {},
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
