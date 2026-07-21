import { useCallback, useEffect, useState } from "react";
import { LoginGate } from "@/components/LoginGate";
import { Skeleton } from "@/components/ui/skeleton";
import { useDemoMode } from "@/hooks/useDemoMode";
import { AUTH_REQUIRED_EVENT, AUTH_STATE_CHANGED_EVENT, fetchHealth } from "@/lib/api";

type GateState =
  | { kind: "loading" }
  | { kind: "open"; authRequired: false }
  | { kind: "open"; authRequired: true }
  | { kind: "locked" }; // password set + no valid session → render LoginGate

/**
 * Gates render on /health.auth_required + the cookie state.
 *
 * - TOFU (auth_required=false): render children. SetupBanner appears via
 *   the `tofu` flag exposed to the wrapper.
 * - auth_required=true + valid cookie: render children.
 * - auth_required=true + no/invalid cookie: render LoginGate.
 *
 * Listens for `tidings:auth-required` (dispatched by `lib/api.fetchJSON` on
 * any 401) so a mid-session expiry kicks the user back to the gate.
 */
export function AuthBoundary({
  children,
}: {
  children: (ctx: { tofu: boolean }) => React.ReactNode;
}) {
  const demo = useDemoMode();
  const [state, setState] = useState<GateState>({ kind: "loading" });

  const probe = useCallback(async () => {
    if (demo) {
      // The static demo bundle has no real backend; pretend we're signed in.
      setState({ kind: "open", authRequired: false });
      return;
    }
    try {
      const health = await fetchHealth();
      if (!health.auth_required) {
        setState({ kind: "open", authRequired: false });
        return;
      }
      // Try a cheap protected request; if it 200s, we have a valid cookie.
      const res = await fetch("/api/v1/categories", { credentials: "same-origin" });
      if (res.ok) {
        setState({ kind: "open", authRequired: true });
      } else if (res.status === 401) {
        setState({ kind: "locked" });
      } else {
        // Any other status — treat as transient, allow render and let the
        // page itself surface the error.
        setState({ kind: "open", authRequired: true });
      }
    } catch {
      // Backend unreachable — fall through and let the page handle it.
      setState({ kind: "open", authRequired: false });
    }
  }, [demo]);

  useEffect(() => {
    void probe();
  }, [probe]);

  useEffect(() => {
    const onAuthRequired = () => {
      setState((prev) => (prev.kind === "open" && prev.authRequired ? { kind: "locked" } : prev));
    };
    const onAuthStateChanged = () => {
      void probe();
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    window.addEventListener(AUTH_STATE_CHANGED_EVENT, onAuthStateChanged);
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
      window.removeEventListener(AUTH_STATE_CHANGED_EVENT, onAuthStateChanged);
    };
  }, [probe]);

  if (state.kind === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="w-full max-w-sm space-y-3">
          <Skeleton className="h-8 w-32 mx-auto" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      </div>
    );
  }

  if (state.kind === "locked") {
    return <LoginGate onSignedIn={() => void probe()} />;
  }

  return <>{children({ tofu: !state.authRequired && !demo })}</>;
}
