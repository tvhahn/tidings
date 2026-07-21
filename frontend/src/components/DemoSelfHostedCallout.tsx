import { ExternalLink, Github } from "lucide-react";
import { REPO_URL, SETUP_ANCHOR } from "@/lib/demoConstants";

export function DemoSelfHostedCallout() {
  return (
    <section className="mt-8 rounded-xl border bg-card p-6">
      {/* Brand rust lives in the rule (the page-title signature), not the button. */}
      <div className="mb-3 h-[2px] w-8 rounded-[2px] bg-brand" aria-hidden />
      <h2 className="text-base font-semibold">
        This is what the dashboard looks like running on your own machine.
      </h2>
      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
        It takes about 5 minutes to set up: one Gmail forwarding rule, one App Password, optionally
        an OpenAI key for AI categorization. Your data never leaves your machine.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <a
          href={SETUP_ANCHOR}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Self-hosted setup guide
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </a>
        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent/50"
        >
          <Github className="h-3.5 w-3.5" aria-hidden />
          View on GitHub
        </a>
      </div>
    </section>
  );
}
