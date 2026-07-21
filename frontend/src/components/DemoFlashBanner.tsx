import { ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { REPO_URL } from "@/lib/demoConstants";
import { readAndClearDemoFlash } from "@/lib/demoFlash";

export function DemoFlashBanner() {
  const [message, setMessage] = useState<string | null>(null);
  const location = useLocation();

  useEffect(() => {
    const raw = readAndClearDemoFlash();
    if (raw) {
      setMessage(raw);
    }
  }, [location.key]);

  // Clear on next navigation after display
  useEffect(() => {
    if (!message) return;
    const handle = window.setTimeout(() => setMessage(null), 8000);
    return () => window.clearTimeout(handle);
  }, [message]);

  if (!message) return null;

  return (
    <div className="flex items-center justify-center gap-3 bg-brand/10 px-4 py-2 text-sm">
      <span>{message}</span>
      <a
        href={REPO_URL}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1 font-medium underline hover:no-underline"
      >
        View on GitHub
        <ExternalLink className="h-3.5 w-3.5" aria-hidden />
      </a>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => setMessage(null)}
        className="ml-2 inline-flex h-5 w-5 items-center justify-center rounded hover:bg-accent/50"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
