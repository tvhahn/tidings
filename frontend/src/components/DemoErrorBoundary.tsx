import { ExternalLink, RefreshCw } from "lucide-react";
import { Component, type ReactNode } from "react";
import { REPO_URL } from "@/lib/demoConstants";

interface DemoErrorBoundaryProps {
  children: ReactNode;
}

interface DemoErrorBoundaryState {
  hasError: boolean;
  message: string | null;
}

export class DemoErrorBoundary extends Component<DemoErrorBoundaryProps, DemoErrorBoundaryState> {
  constructor(props: DemoErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, message: null };
  }

  static getDerivedStateFromError(err: unknown): DemoErrorBoundaryState {
    const message = err instanceof Error ? err.message : String(err);
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown): void {
    console.warn("[demo] page error boundary caught", error);
  }

  handleReload = (): void => {
    this.setState({ hasError: false, message: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="mx-auto mt-12 max-w-md rounded-xl border bg-card p-6 text-center">
        <h2 className="text-base font-semibold">Demo data didn&rsquo;t load.</h2>
        {this.state.message ? (
          <p className="mt-1 text-xs text-muted-foreground">{this.state.message}</p>
        ) : null}
        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            onClick={this.handleReload}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent/50"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Reload
          </button>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            View on GitHub
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        </div>
      </div>
    );
  }
}
