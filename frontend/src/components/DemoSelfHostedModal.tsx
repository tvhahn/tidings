import { ExternalLink } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { REPO_URL, SETUP_ANCHOR } from "@/lib/demoConstants";

interface DemoSelfHostedModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  featureName: string;
  description?: string;
}

export function DemoSelfHostedModal({
  open,
  onOpenChange,
  featureName,
  description,
}: DemoSelfHostedModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{featureName} is a self-hosted feature</DialogTitle>
          <DialogDescription>
            {description ??
              "This action writes to your local database, reads your email, or calls an AI provider. The live demo is read-only for anything that would touch real data."}
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2 flex flex-col gap-2 text-sm">
          <a
            href={SETUP_ANCHOR}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 font-medium text-brand hover:underline"
          >
            Self-hosted setup guide
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 text-muted-foreground hover:underline"
          >
            View on GitHub
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Inline variant used as a full-page replacement (e.g. Statements page). */
export function DemoSelfHostedInline({
  featureName,
  description,
}: {
  featureName: string;
  description?: string;
}) {
  return (
    <div className="mx-auto max-w-lg rounded-xl border bg-card p-8 text-center shadow-sm">
      <h2 className="text-lg font-semibold">{featureName} is a self-hosted feature</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        {description ??
          "This feature writes to your local database or calls external providers (PDF parsing, AI, email)."}
      </p>
      <div className="mt-5 flex flex-col items-center gap-2 text-sm">
        <a
          href={SETUP_ANCHOR}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-2 font-medium text-brand-foreground hover:opacity-90"
        >
          Self-hosted setup guide
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </a>
        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 text-muted-foreground hover:underline"
        >
          View on GitHub
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </a>
      </div>
    </div>
  );
}
