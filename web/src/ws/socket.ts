import type { WsEvent } from "../api/types";

type EventHandler = (event: WsEvent) => void;
export type WsStatus = "connecting" | "open" | "closed";

const MIN_DELAY_MS = 500;
const MAX_DELAY_MS = 8_000;

/**
 * Singleton WebSocket manager.
 *
 * - Connects to ws(s)://<host>/ws (proxied to the backend in dev).
 * - Reconnects with capped exponential backoff (0.5s -> 8s).
 * - Re-sends every subscription and fires the registered resync callback on
 *   each (re)connect.
 * - Tracks per-topic seq; a gap (jump > 1) also triggers resync, and stale
 *   replays (seq <= last seen) are dropped.
 *
 * The "sidebar" topic is auto-subscribed server-side and is never sent in a
 * subscribe frame.
 */
class SocketManager {
  private ws: WebSocket | null = null;
  private handlers = new Set<EventHandler>();
  private topics = new Set<string>();
  private resync: (() => void) | null = null;
  private lastSeq = new Map<string, number>();
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private started = false;
  private status: WsStatus = "closed";
  private statusHandlers = new Set<() => void>();

  /** Idempotent; call once at app startup. */
  connect(): void {
    if (this.started) return;
    this.started = true;
    this.open();
  }

  /** useSyncExternalStore-compatible: subscribe to status changes. */
  subscribeStatus = (cb: () => void): (() => void) => {
    this.statusHandlers.add(cb);
    return () => {
      this.statusHandlers.delete(cb);
    };
  };

  getStatus = (): WsStatus => this.status;

  private setStatus(next: WsStatus): void {
    if (this.status === next) return;
    this.status = next;
    for (const cb of this.statusHandlers) cb();
  }

  /** Register a handler for every incoming WsEvent. Returns an unsubscribe fn. */
  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  /** Called on every (re)connect and on seq gaps; wire to query invalidation. */
  setResync(fn: () => void): void {
    this.resync = fn;
  }

  subscribe(topic: string): void {
    if (topic === "sidebar") return; // server auto-subscribes this topic
    if (this.topics.has(topic)) return;
    this.topics.add(topic);
    this.send({ type: "subscribe", topic });
  }

  unsubscribe(topic: string): void {
    if (!this.topics.delete(topic)) return;
    this.send({ type: "unsubscribe", topic });
  }

  private send(frame: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    }
  }

  private open(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    this.setStatus("connecting");

    ws.onopen = () => {
      this.attempt = 0;
      this.lastSeq.clear(); // seq is per-connection; never compare across connects
      this.setStatus("open");
      for (const topic of this.topics) {
        ws.send(JSON.stringify({ type: "subscribe", topic }));
      }
      this.resync?.();
    };

    ws.onmessage = (msg: MessageEvent) => {
      let event: WsEvent;
      try {
        event = JSON.parse(msg.data as string) as WsEvent;
      } catch {
        return;
      }
      if (typeof event.topic !== "string" || typeof event.seq !== "number") return;

      const prev = this.lastSeq.get(event.topic);
      if (prev !== undefined) {
        if (event.seq <= prev) return; // duplicate/replay
        if (event.seq > prev + 1) this.resync?.(); // missed events
      }
      this.lastSeq.set(event.topic, event.seq);

      for (const handler of this.handlers) handler(event);
    };

    ws.onclose = () => {
      if (this.ws === ws) {
        this.ws = null;
        this.setStatus("closed");
        this.scheduleReconnect();
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.timer !== null) return;
    const delay = Math.min(MAX_DELAY_MS, MIN_DELAY_MS * 2 ** this.attempt);
    this.attempt += 1;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.open();
    }, delay);
  }
}

export const socket = new SocketManager();
