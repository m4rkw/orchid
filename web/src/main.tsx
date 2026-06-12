import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { queryClient } from "./state/queryClient";
import { useAppStore } from "./state/stores";
import { socket } from "./ws/socket";
import "./index.css";

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
