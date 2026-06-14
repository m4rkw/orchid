import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { armNotificationPermission } from "./notify";
import { queryClient } from "./state/queryClient";
import { useAppStore } from "./state/stores";
import { socket } from "./ws/socket";
import "./index.css";

// Deep links from notifications: ?project=<pid>&session=<sid> or &review=<rid>.
// Apply the selection, then strip the query so a refresh doesn't re-trigger it.
(function applyDeepLink() {
  const q = new URLSearchParams(window.location.search);
  const pid = q.get("project");
  if (!pid) return;
  const sid = q.get("session");
  const reviewId = q.get("review");
  if (sid) useAppStore.getState().select({ pid, sid });
  else if (reviewId) useAppStore.getState().select({ pid, reviews: true, reviewId });
  else useAppStore.getState().select({ pid });
  window.history.replaceState(null, "", window.location.pathname);
})();

// Desktop notifications: request permission on the first user gesture.
armNotificationPermission();

// Wire the socket once at startup (outside React, so StrictMode double-effects
// can't double-subscribe). "sidebar" is auto-subscribed server-side; we keep
// "onboarding" subscribed for the app's lifetime so no events are missed while
// a session is selected.
socket.onEvent((event) => useAppStore.getState().apply(event));
socket.setResync(() => void queryClient.invalidateQueries());
socket.subscribe("onboarding");
socket.connect();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
