import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { api, ApiError } from "../../api/client";
import type { SessionDetail } from "../../api/types";
import { isLocalUuid, isProjectSel, useAppStore } from "../../state/stores";
import { queryClient } from "../../state/queryClient";
import { socket } from "../../ws/socket";
import { CopyButton } from "../common/CopyButton";
import { StatusDot } from "../common/StatusDot";
import { AgentDrillIn, AgentPanel } from "./AgentPanel";
import { Transcript } from "./Transcript";

const MAX_COMPOSER_HEIGHT_PX = 144; // ~6 lines at 24px line-height

export function SessionView({ pid, sid }: { pid: string; sid: string }) {
  const ensureSession = useAppStore((s) => s.ensureSession);
  const seedSession = useAppStore((s) => s.seedSession);
  const clearSessionLive = useAppStore((s) => s.clearSessionLive);
  const setAgents = useAppStore((s) => s.setAgents);
  const seedPermissions = useAppStore((s) => s.seedPermissions);
  const setSessionError = useAppStore((s) => s.setSessionError);
  const buffer = useAppStore((s) => s.sessionBuffers[sid]);
  const statusOverride = useAppStore((s) => s.sessionStatuses[sid]);
  const queueLen = useAppStore((s) => s.queueLens[sid] ?? 0);
  const agents = useAppStore((s) => s.agents[sid]);
  const permissions = useAppStore((s) => s.permissions[sid]);
  const selectedDrillAgentId = useAppStore((s) => (isProjectSel(s.selected) && s.selected.sid === sid ? s.selected.drillAgentId : undefined));

  // Track the live topic for the lifetime of the selection.
  useEffect(() => {
    ensureSession(sid);
    socket.subscribe(`session:${sid}`);
    return () => {
      socket.unsubscribe(`session:${sid}`);
      clearSessionLive(sid);
      queryClient.removeQueries({ queryKey: ["session-messages", sid] });
    };
  }, [sid, ensureSession, clearSessionLive]);

  const detail = useQuery({
    queryKey: ["session", sid],
    queryFn: () => api.session(sid),
  });

  // Backlog: refetch on every (re)select; the seq watermark comes with it.
  const messagesQuery = useQuery({
    queryKey: ["session-messages", sid],
    queryFn: () => api.sessionMessages(sid),
    staleTime: 0,
    refetchOnMount: "always",
  });
  useEffect(() => {
    if (messagesQuery.data) {
      seedSession(sid, messagesQuery.data.messages, messagesQuery.data.seq);
    }
    // dataUpdatedAt: reseed even when a refetch returns structurally-equal data.
  }, [messagesQuery.data, messagesQuery.dataUpdatedAt, sid, seedSession]);

  const agentsQuery = useQuery({
    queryKey: ["session-agents", sid],
    queryFn: () => api.sessionAgents(sid),
    staleTime: 0,
    refetchOnMount: "always",
  });
  useEffect(() => {
    if (agentsQuery.data) setAgents(sid, agentsQuery.data);
  }, [agentsQuery.data, agentsQuery.dataUpdatedAt, sid, setAgents]);

  const permsQuery = useQuery({
    queryKey: ["session-permissions", sid],
    queryFn: () => api.sessionPermissions(sid),
    staleTime: 0,
    refetchOnMount: "always",
  });
  useEffect(() => {
    if (permsQuery.data?.length) {
      seedPermissions(sid, permsQuery.data.map((p) => ({ ...p, expired: false })));
    }
  }, [permsQuery.data, permsQuery.dataUpdatedAt, sid, seedPermissions]);

  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const project = projects.data?.find((p) => p.id === (detail.data?.project_id ?? pid));

  const status = statusOverride ?? detail.data?.status ?? "idle";
  const running = status === "running" || buffer?.running === true;
  const messages = buffer?.messages ?? [];
  const messageCount = useMemo(() => messages.filter((m) => !isLocalUuid(m.uuid)).length, [messages]);
  const lastTurnCost = buffer?.lastTurn?.cost;
  const title = detail.data?.title || `${sid.slice(0, 8)}…`;

  // Default the 240px agents panel open only on wide screens; on phones/small
  // tablets (< lg) it would squash the transcript, so start hidden there. The
  // header "agents N" button still toggles it. Lazy init: evaluated once on mount.
  const [agentsOpen, setAgentsOpen] = useState(
    () => typeof window === "undefined" || window.innerWidth >= 1024);
  const [verbose, setVerbose] = useState(false);
  const [drillAgentId, setDrillAgentId] = useState<string | null>(null);
  const drillAgent = drillAgentId === null ? null : (agents ?? []).find((a) => a.agent_id === drillAgentId) ?? null;
  useEffect(() => setDrillAgentId(null), [sid]);
  // Opening an agent from the LEFT TREE flows through the selection; mirror it here.
  useEffect(() => {
    if (selectedDrillAgentId) setDrillAgentId(selectedDrillAgentId);
  }, [selectedDrillAgentId]);
  const closeDrill = () => {
    setDrillAgentId(null);
    const { selected, select } = useAppStore.getState();
    // Clear the selection's drill marker so re-clicking the same agent re-opens.
    if (isProjectSel(selected) && selected.sid === sid && selected.drillAgentId) {
      select({ ...selected, drillAgentId: undefined });
    }
  };

  const [interruptError, setInterruptError] = useState<string | null>(null);
  const interrupt = async () => {
    setInterruptError(null);
    try {
      await api.interrupt(sid);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) return; // nothing to interrupt
      setInterruptError(err instanceof Error ? err.message : "Failed to interrupt");
    }
  };

  const allowAll = () => {
    const store = useAppStore.getState();
    const cards = permissions ?? [];
    for (const card of cards) {
      if (!card.expired) {
        void api.respondPermission(card.request_id, "allow").catch(() => {});
        store.resolvePermission(sid, card.request_id);
      }
    }
    store.setAutoApprove(sid, true);
  };

  const showFull = async (uuid: string) => {
    if (isLocalUuid(uuid)) return;
    const full = await api.sessionMessage(sid, uuid);
    useAppStore.getState().markMessageFull(sid, full);
  };

  const [headerRenaming, setHeaderRenaming] = useState(false);
  useEffect(() => setHeaderRenaming(false), [sid]);

  return (
    <div className="relative flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center gap-2.5 border-b border-zinc-800 px-4">
        <StatusDot status={status} />
        {headerRenaming ? (
          <HeaderRenameField sid={sid} initial={detail.data?.title ?? ""} onDone={() => setHeaderRenaming(false)} />
        ) : (
          <h1
            className="min-w-0 cursor-text truncate text-sm font-medium text-zinc-200 hover:text-zinc-100"
            title={sid}
            onDoubleClick={() => setHeaderRenaming(true)}
          >
            {detail.data?.pinned && <span className="mr-1 text-[11px] text-violet-400/70">★</span>}
            {title}
          </h1>
        )}
        <span className="hidden min-w-0 truncate text-[11px] text-zinc-600 sm:inline">
          {project ? `${project.name} · ` : ""}
          {messageCount} {messageCount === 1 ? "message" : "messages"}
          {lastTurnCost !== undefined && ` · last turn $${lastTurnCost.toFixed(4)}`}
        </span>
        {queueLen > 0 && (
          <span className="shrink-0 rounded-full bg-violet-500/15 px-2 py-px text-[10px] font-medium text-violet-300">
            queued: {queueLen}
          </span>
        )}
        {detail.data?.created_by === "external" && (
          <span
            className="shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-px text-[10px] font-medium text-amber-300/90"
            title="This session was created in a terminal. Viewing is safe; sending a prompt from the web could conflict with the terminal, so you'll be asked to take over first."
          >
            terminal
          </span>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {interruptError && <span className="text-[10px] text-red-400">{interruptError}</span>}
          {status === "running" && (
            <button
              type="button"
              onClick={() => void interrupt()}
              className="rounded-md bg-violet-600 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-violet-500 focus-visible:ring-2 focus-visible:ring-violet-500/60 focus-visible:outline-none"
            >
              ■ Interrupt
            </button>
          )}
          <button
            type="button"
            onClick={() => setVerbose((v) => !v)}
            className={clsx(
              "rounded-md border px-2 py-1 text-xs transition-colors",
              verbose
                ? "border-violet-500/40 text-violet-300"
                : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200",
            )}
          >
            verbose
          </button>
          {(agents?.length ?? 0) > 0 && (
            <button
              type="button"
              onClick={() => setAgentsOpen((v) => !v)}
              className={clsx(
                "rounded-md border px-2 py-1 text-xs transition-colors",
                agentsOpen
                  ? "border-violet-500/40 text-violet-300"
                  : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200",
              )}
            >
              agents {agents!.length}
            </button>
          )}
          {detail.data && (
            <SessionHeaderMenu
              pid={detail.data.project_id ?? pid}
              session={detail.data}
              onRename={() => setHeaderRenaming(true)}
            />
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <Transcript
            sid={sid}
            messages={messages}
            running={running}
            lastError={buffer?.lastError ?? null}
            permissions={permissions ?? []}
            loading={messagesQuery.isPending && messages.length === 0}
            verbose={verbose}
            onShowFull={showFull}
            onDismissError={() => setSessionError(sid, null)}
            onAllowAll={allowAll}
          />
          {messagesQuery.isError && (
            <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-1 text-[11px] text-red-400/80">
              Couldn’t load messages.{" "}
              <button type="button" className="underline hover:text-red-300" onClick={() => void messagesQuery.refetch()}>
                retry
              </button>
            </div>
          )}
          {detail.data && status !== "running" && (
            <div className="mx-auto flex w-full max-w-3xl shrink-0 items-center gap-2 px-4 pb-1 text-[11px] text-zinc-600">
              <span className="shrink-0">handoff:</span>
              <code className="min-w-0 truncate font-mono text-zinc-500" title={detail.data.handoff_command}>
                {detail.data.handoff_command}
              </code>
              <CopyButton text={detail.data.handoff_command} className="border-0 px-1 py-0.5" />
            </div>
          )}
          <Composer sid={sid} running={running} queueLen={queueLen} onInterrupt={() => void interrupt()} />
        </div>
        {agentsOpen && (agents?.length ?? 0) > 0 && (
          <AgentPanel agents={agents!} onSelect={(aid) => setDrillAgentId(aid)} />
        )}
      </div>

      {drillAgent && <AgentDrillIn sid={sid} agent={drillAgent} onClose={closeDrill} />}
    </div>
  );
}

function Composer({
  sid,
  running,
  queueLen,
  onInterrupt,
}: {
  sid: string;
  running: boolean;
  queueLen: number;
  onInterrupt: () => void;
}) {
  const appendSessionUser = useAppStore((s) => s.appendSessionUser);
  const setQueueLen = useAppStore((s) => s.setQueueLen);

  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  /** Prompt rejected with 409 EXTERNAL_ACTIVITY, awaiting "Send anyway". */
  const [externalPrompt, setExternalPrompt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow the composer up to ~6 lines.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_COMPOSER_HEIGHT_PX)}px`;
  }, [value]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, [sid]);

  const send = async (text: string, force: boolean) => {
    if (!text || sending) return;
    setSending(true);
    setError(null);
    try {
      const res = await api.sendPrompt(sid, text, force || undefined);
      appendSessionUser(sid, text); // optimistic; swapped for the WS echo
      setQueueLen(sid, res.queue_len);
      setExternalPrompt(null);
      setValue((v) => (v.trim() === text ? "" : v));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "EXTERNAL_ACTIVITY") {
        setExternalPrompt(text);
      } else {
        setError(err instanceof Error ? err.message : "Failed to send prompt");
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="shrink-0 border-t border-zinc-800 p-4 pt-3">
      {externalPrompt !== null && (
        <div className="mx-auto mb-2 flex max-w-3xl items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <span className="min-w-0">
            This session is owned by a terminal — driving it from the web at the same time can corrupt
            it. Take over only if no terminal has it open.
          </span>
          <button
            type="button"
            disabled={sending}
            onClick={() => void send(externalPrompt, true)}
            className="ml-auto shrink-0 rounded-md bg-amber-500/20 px-2 py-1 font-medium text-amber-100 transition-colors hover:bg-amber-500/30 disabled:opacity-50"
          >
            Send anyway
          </button>
          <button
            type="button"
            aria-label="Dismiss warning"
            className="shrink-0 text-amber-300/70 hover:text-amber-200"
            onClick={() => setExternalPrompt(null)}
          >
            ✕
          </button>
        </div>
      )}
      {error && (
        <div className="mx-auto mb-2 flex max-w-3xl items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <span className="shrink-0 font-medium">Error:</span>
          <span className="min-w-0 break-words">{error}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            className="ml-auto shrink-0 text-red-400/70 hover:text-red-300"
            onClick={() => setError(null)}
          >
            ✕
          </button>
        </div>
      )}
      <div
        className={clsx(
          "mx-auto flex max-w-3xl items-end gap-2 rounded-xl border bg-ink-900 px-3 py-2 transition-colors",
          running ? "border-violet-500/40" : "border-zinc-700 focus-within:border-violet-500/60",
        )}
      >
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          placeholder={running ? "Orchid is working — Enter queues your prompt…" : "Send a prompt…"}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send(value.trim(), false);
            } else if (e.key === "Escape" && running) {
              e.preventDefault();
              onInterrupt();
            }
          }}
          className="max-h-36 min-h-6 w-full resize-none bg-transparent text-base leading-6 text-zinc-100 outline-none placeholder:text-zinc-600 md:text-sm"
        />
        {running && (
          <button
            type="button"
            title="Interrupt (Esc)"
            aria-label="Interrupt"
            onClick={onInterrupt}
            className="mb-px shrink-0 rounded-lg border border-violet-500/40 px-2.5 py-1 text-sm text-violet-300 transition-colors hover:bg-violet-500/15"
          >
            ■
          </button>
        )}
        <button
          type="button"
          onClick={() => void send(value.trim(), false)}
          disabled={sending || value.trim() === ""}
          className="mb-px shrink-0 rounded-lg bg-violet-600 px-3 py-1 text-sm font-medium text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-violet-600"
        >
          Send
        </button>
      </div>
      <div className="mx-auto mt-1.5 flex max-w-3xl items-center px-1 text-[10px] text-zinc-600">
        <span>
          Enter to send · Shift+Enter for newline
          {running && " · Esc to interrupt · sends while running are queued"}
        </span>
        {queueLen > 0 && <span className="ml-auto text-violet-400/80">queued: {queueLen}</span>}
      </div>
    </div>
  );
}

/** Inline title editor in the SessionView header. */
function HeaderRenameField({ sid, initial, onDone }: { sid: string; initial: string; onDone: () => void }) {
  const [value, setValue] = useState(initial);
  const rename = useMutation({
    mutationFn: (title: string) => api.renameSession(sid, title),
    onSuccess: onDone, // session_upserted refreshes the cache
  });

  const submit = () => {
    const title = value.trim();
    if (!title || rename.isPending) return;
    if (title === initial.trim()) {
      onDone();
      return;
    }
    rename.mutate(title);
  };

  return (
    <input
      autoFocus
      value={value}
      disabled={rename.isPending}
      onChange={(e) => setValue(e.target.value)}
      onBlur={onDone}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          submit();
        } else if (e.key === "Escape") {
          e.preventDefault();
          onDone();
        }
      }}
      className="min-w-0 flex-1 rounded border border-violet-500/40 bg-ink-900 px-2 py-0.5 text-sm font-medium text-zinc-100 outline-none focus:border-violet-500/70 disabled:opacity-50"
    />
  );
}

/** ⋯ menu in the SessionView header: pin / archive / fork / delete (rename via header title). */
function SessionHeaderMenu({
  pid,
  session,
  onRename,
}: {
  pid: string;
  session: SessionDetail;
  onRename: () => void;
}) {
  const select = useAppStore((s) => s.select);
  const [open, setOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const close = () => {
    setOpen(false);
    setConfirmDelete(false);
  };

  const pin = useMutation({ mutationFn: (value: boolean) => api.pinSession(session.id, value) });
  const archive = useMutation({ mutationFn: (value: boolean) => api.archiveSession(session.id, value) });
  const fork = useMutation({
    mutationFn: () => api.forkSession(session.id),
    onSuccess: ({ session_id }) => {
      close();
      select({ pid, sid: session_id });
    },
  });
  const del = useMutation({
    mutationFn: (force?: boolean) => api.deleteSession(session.id, force),
    onSuccess: () => {
      useAppStore.getState().removeSession(pid, session.id);
    },
  });

  const deleteErr = del.error instanceof ApiError ? del.error : null;
  const isRunning = deleteErr?.status === 409 && deleteErr.code === "SESSION_RUNNING";
  const isExternal = deleteErr?.status === 409 && deleteErr.code === "EXTERNAL_ACTIVITY";

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Session menu"
        onClick={() => (open ? close() : setOpen(true))}
        className={clsx(
          "rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200",
          open && "border-zinc-500 text-zinc-200",
        )}
      >
        ⋯
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={close} />
          <div className="absolute top-8 right-0 z-20 w-44 rounded-md border border-zinc-700 bg-zinc-900 p-1 shadow-xl shadow-black/50">
            {confirmDelete ? (
              <div className="px-2 py-1.5 text-xs">
                <div className="mb-2 text-zinc-300">Delete this session?</div>
                {isRunning && <div className="mb-2 text-[11px] text-red-400">Can’t delete a running session</div>}
                {isExternal && (
                  <div className="mb-2 text-[11px] text-amber-400">This session looks active in a terminal.</div>
                )}
                {deleteErr && !isRunning && !isExternal && (
                  <div className="mb-2 text-[11px] text-red-400">{deleteErr.message}</div>
                )}
                <div className="flex justify-end gap-1.5">
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                    onClick={() => {
                      setConfirmDelete(false);
                      del.reset();
                    }}
                  >
                    Cancel
                  </button>
                  {isExternal ? (
                    <button
                      type="button"
                      disabled={del.isPending}
                      className="rounded bg-amber-500/80 px-2 py-1 font-medium text-white hover:bg-amber-500 disabled:opacity-50"
                      onClick={() => del.mutate(true)}
                    >
                      {del.isPending ? "Deleting…" : "Delete anyway"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={del.isPending || isRunning}
                      className="rounded bg-red-600/80 px-2 py-1 font-medium text-white hover:bg-red-500 disabled:opacity-50"
                      onClick={() => del.mutate(undefined)}
                    >
                      {del.isPending ? "Deleting…" : "Delete"}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <>
                <HeaderMenuItem
                  label="Rename"
                  onClick={() => {
                    close();
                    onRename();
                  }}
                />
                <HeaderMenuItem
                  label={session.pinned ? "Unpin" : "Pin"}
                  disabled={pin.isPending}
                  onClick={() => {
                    pin.mutate(!session.pinned);
                    close();
                  }}
                />
                <HeaderMenuItem
                  label={session.archived ? "Unarchive" : "Archive"}
                  disabled={archive.isPending}
                  onClick={() => {
                    archive.mutate(!session.archived);
                    close();
                  }}
                />
                <HeaderMenuItem
                  label={fork.isPending ? "Forking…" : "Fork"}
                  disabled={fork.isPending}
                  onClick={() => fork.mutate()}
                />
                {fork.isError && (
                  <div className="px-2 py-1 text-[11px] text-red-400">
                    {fork.error instanceof Error ? fork.error.message : "Fork failed"}
                  </div>
                )}
                <div className="my-1 h-px bg-zinc-800" />
                <button
                  type="button"
                  className="w-full rounded px-2 py-1.5 text-left text-xs text-red-400 hover:bg-zinc-800 hover:text-red-300"
                  onClick={() => setConfirmDelete(true)}
                >
                  Delete
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function HeaderMenuItem({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      className="w-full rounded px-2 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
      onClick={onClick}
    >
      {label}
    </button>
  );
}
