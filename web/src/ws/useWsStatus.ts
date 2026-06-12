import { useSyncExternalStore } from "react";
import { socket, type WsStatus } from "./socket";

/** Live WebSocket connection state, for connection indicators. */
export function useWsStatus(): WsStatus {
  return useSyncExternalStore(socket.subscribeStatus, socket.getStatus, () => "connecting");
}
