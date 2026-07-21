import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import App from "./App.tsx";
import "./index.css";

const ONE_DAY_MS = 1000 * 60 * 60 * 24;

// Query-key prefixes that are safe to paint from a cold localStorage cache.
// New query types default to *not* persisted until added here (allowlist).
// Journal-class queries are intentionally excluded — they mutate daily and a
// day-old persisted snapshot misleads (showed April 28 data on April 30 in
// production). Loader flash on cold-load is the right tradeoff there.
const PERSIST_KEY_PREFIXES = new Set([
  "summary",
  "trend",
  "categories",
  "categoryGroups",
  "insights-list",
  "insights-content",
]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      // gcTime must exceed maxAge below so the persister can rehydrate entries
      // that haven't been accessed in memory this session.
      gcTime: ONE_DAY_MS,
      // Note: React Query v5 already tracks accessed props by default (the old
      // `notifyOnChangeProps: 'tracked'` was removed), so consumers only
      // re-render on fields they actually read — no extra config needed.
    },
  },
});

const persister = createSyncStoragePersister({
  storage: window.localStorage,
  key: "rq-cache-v1",
});

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Root element #root not found");
createRoot(rootEl).render(
  <StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister,
        maxAge: ONE_DAY_MS,
        // Bump manually whenever a persisted response shape changes so stale
        // caches from older deploys are discarded on next load.
        // v4: category list now comes from storage (the user's custom set),
        // not the bundled seed — discard persisted seed-default categories.
        buster: "v4",
        dehydrateOptions: {
          shouldDehydrateQuery: (query) => {
            const first = query.queryKey[0];
            return typeof first === "string" && PERSIST_KEY_PREFIXES.has(first);
          },
        },
      }}
    >
      <BrowserRouter
        basename={import.meta.env.PROD && import.meta.env.MODE === "demo" ? "/demo" : "/"}
      >
        <App />
        <Toaster />
      </BrowserRouter>
    </PersistQueryClientProvider>
  </StrictMode>
);
