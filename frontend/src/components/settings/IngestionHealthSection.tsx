import { useQuery } from "@tanstack/react-query";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { useCoverage } from "@/hooks/useCoverage";
import { queries } from "@/lib/queryConfigs";
import { cn } from "@/lib/utils";
import type { CoverageInstitution, CoverageStatus, HealthStatus } from "@/types/api";

/** Render the modeled cadence status as an observational word (never an alarm). */
function statusLabel(status: CoverageStatus): string {
  return status === "irregular" ? "no steady cadence" : status;
}

/** Active reads plainly; quieter states dim rather than raising an alarm. */
function statusToneClass(status: CoverageStatus): string {
  return status === "active" ? "text-fg-secondary" : "text-muted-foreground";
}

function lastAlertLabel(days: number | null): string | null {
  if (days == null) return null;
  if (days === 0) return "last alert today";
  return `last alert ${days} ${days === 1 ? "day" : "days"} ago`;
}

function InstitutionRow({ inst }: { inst: CoverageInstitution }) {
  const lastAlert = lastAlertLabel(inst.days_since_last_seen);
  const meta: string[] = [];
  if (lastAlert) meta.push(lastAlert);
  if (inst.threshold_gap_days != null) meta.push(`typical gap ≤ ${inst.threshold_gap_days} days`);

  const isQuiet = inst.status === "quiet";

  return (
    <div className="rounded-lg border border-border/50 px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium">{inst.institution}</p>
        <span className={cn("shrink-0 text-xs", statusToneClass(inst.status))}>
          {statusLabel(inst.status)}
        </span>
      </div>
      {meta.length > 0 && (
        <p className="mt-1 text-xs text-muted-foreground tabular-nums">{meta.join(" · ")}</p>
      )}
      {isQuiet && inst.days_since_last_seen != null && inst.threshold_gap_days != null && (
        <div className="mt-2 space-y-1 text-xs text-muted-foreground">
          <p>
            quiet for {inst.days_since_last_seen} days — you usually see a gap of no more than{" "}
            {inst.threshold_gap_days}
          </p>
          <p>A statement import can fill the gap.</p>
        </div>
      )}
    </div>
  );
}

export function IngestionHealthSection() {
  const { data: coverage, isLoading } = useCoverage();
  const { data: health } = useQuery<HealthStatus>(queries.health());

  const institutions = coverage?.institutions ?? [];
  const capture = coverage?.capture ?? null;
  const quarantined = health?.parse_failures_7d ?? 0;

  return (
    <section className="space-y-4">
      <SettingsSectionHeader
        title="Ingestion coverage"
        infoHint={{
          label: "About ingestion coverage",
          content:
            "How often each bank's alert emails arrive, modeled over the past year. An institution reads quiet when it hasn't sent an alert in longer than its usual gap — a statement import fills whatever the emails missed.",
        }}
        count={institutions.length > 0 ? institutions.length : undefined}
        countLabel="institutions"
      />

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      )}

      {!isLoading && institutions.length === 0 && (
        <p className="py-6 text-center text-muted-foreground">No alert history yet.</p>
      )}

      {institutions.length > 0 && (
        <div className="space-y-2">
          {institutions.map((inst) => (
            <InstitutionRow key={inst.institution} inst={inst} />
          ))}
        </div>
      )}

      {quarantined > 0 && (
        <p className="text-xs text-muted-foreground">
          {quarantined} {quarantined === 1 ? "email" : "emails"} quarantined in the last 7 days.
        </p>
      )}

      {capture && (
        <div className="space-y-1.5 rounded-lg border border-border/50 bg-muted/20 px-4 py-3">
          <p className="text-sm text-fg-secondary">
            Alerts caught {capture.overall.caught} of {capture.overall.total} statement transactions
            in the months you've imported.
          </p>
          {capture.by_institution.length > 0 && (
            <ul className="space-y-0.5 text-xs text-muted-foreground tabular-nums">
              {capture.by_institution.map((row) => (
                <li key={row.institution} className="flex items-baseline justify-between gap-3">
                  <span>{row.institution}</span>
                  <span>
                    {row.caught} of {row.total}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
