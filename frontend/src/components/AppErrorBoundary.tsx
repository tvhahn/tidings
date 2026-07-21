import { RefreshCw } from "lucide-react";
import { Component, type ReactNode } from "react";

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  hasError: boolean;
  message: string | null;
}

/**
 * Real-mode catch-all. Without it, an uncaught render error unmounts the
 * entire React tree to a white screen with no recovery path — demo mode had
 * a boundary (DemoErrorBoundary, which carries demo copy and a GitHub CTA)
 * while the actual product did not. A hard reload is the reliable recovery
 * for render errors; resetting state usually re-crashes on the same render.
 */
export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  constructor(props: AppErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, message: null };
  }

  static getDerivedStateFromError(err: unknown): AppErrorBoundaryState {
    const message = err instanceof Error ? err.message : String(err);
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown): void {
    console.error("[app] error boundary caught", error);
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="mx-auto mt-12 max-w-md rounded-xl border bg-card p-6 text-center">
        <h2 className="text-base font-semibold">This view hit an error.</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Your data is unaffected. Reloading usually clears it.
        </p>
        {this.state.message ? (
          <p className="mt-2 break-words text-xs text-muted-foreground/70">{this.state.message}</p>
        ) : null}
        <div className="mt-4 flex items-center justify-center">
          <button
            onClick={this.handleReload}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent/50"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Reload page
          </button>
        </div>
      </div>
    );
  }
}
