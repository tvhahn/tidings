import { ExternalLink } from "lucide-react";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { useDemoMode } from "@/hooks/useDemoMode";
import { REPO_URL, SETUP_ANCHOR } from "@/lib/demoConstants";
import { useDemoTour } from "@/stores/demoTour";

export function DemoBanner() {
  const staticDemo = useDemoMode();
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();
  const openTour = useDemoTour((s) => s.open);
  const tourDismissed = useDemoTour((s) => s.dismissedForever);

  if (staticDemo) {
    return (
      <div className="flex items-center gap-x-3 gap-y-1 flex-wrap bg-status-warning-muted border-b border-status-warning/30 px-4 py-2 text-sm text-status-warning-accent">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium">Demo mode</span>
          <span className="opacity-80 truncate">— your changes don&rsquo;t persist.</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <button
            type="button"
            onClick={openTour}
            className={`inline-flex items-center gap-1 rounded-full border border-status-warning/40 px-2.5 py-0.5 text-xs font-medium transition-colors hover:bg-status-warning/15 ${
              tourDismissed ? "opacity-70" : ""
            }`}
          >
            {tourDismissed ? "Tour" : "Take a tour"}
          </button>
          <a
            href={SETUP_ANCHOR}
            target="_blank"
            rel="noreferrer noopener"
            data-tour="self-host-cta"
            className="inline-flex items-center gap-1 font-semibold underline underline-offset-2 hover:no-underline"
          >
            Self-host this
            <span aria-hidden>&rarr;</span>
          </a>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 opacity-90 underline underline-offset-2 hover:no-underline"
          >
            GitHub
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
          <a
            href="/"
            className="inline-flex items-center gap-1 opacity-90 underline underline-offset-2 hover:no-underline"
          >
            Back to gettidings.com
          </a>
        </div>
      </div>
    );
  }

  if (!config?.demo_mode) return null;

  return (
    <div className="bg-status-warning-muted border-b border-status-warning/30 px-4 py-2 text-center text-sm text-status-warning-accent">
      <span className="font-medium">Demo Mode</span> — showing sample data.{" "}
      <button
        onClick={() => updateConfig.mutate({ demo_mode: false })}
        className="underline hover:no-underline font-medium"
        disabled={updateConfig.isPending}
      >
        Exit Demo
      </button>
    </div>
  );
}
