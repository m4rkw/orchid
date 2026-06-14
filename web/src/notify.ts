/**
 * Desktop notifications (the default "Orchid needs you" channel) off the WS
 * events the store already receives. Fires only when the tab isn't focused, so
 * it surfaces blocked sessions / pending reviews without nagging while you watch.
 *
 * Browser notifications complement the optional server-side Pushover channel
 * (which fires regardless, even with no tab open).
 */

let permissionRequested = false;

/** Ask once, on a user gesture (Safari/Chrome require a gesture for the prompt). */
export function armNotificationPermission(): void {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "default") return;
  const ask = () => {
    if (permissionRequested) return;
    permissionRequested = true;
    void Notification.requestPermission().catch(() => {});
    window.removeEventListener("pointerdown", ask);
  };
  window.addEventListener("pointerdown", ask, { once: true });
}

export type NotifyOptions = {
  title: string;
  body: string;
  /** Dedup tag — a repeat with the same tag replaces the prior popup. */
  tag?: string;
  /** Invoked when the user clicks the notification. */
  onClick?: () => void;
};

export function notify({ title, body, tag, onClick }: NotifyOptions): void {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  // Only when the user isn't already looking at Orchid.
  if (document.visibilityState === "visible") return;
  try {
    const n = new Notification(title, { body, tag });
    n.onclick = () => {
      window.focus();
      onClick?.();
      n.close();
    };
  } catch {
    // Some browsers throw for non-persistent notifications; ignore.
  }
}
