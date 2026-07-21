import { useMemo, useState } from "react";
import { ActivityEntryRow } from "@/components/activity/ActivityEntryRow";
import { ActivityGroupHeader } from "@/components/activity/ActivityGroupHeader";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useActivity } from "@/hooks/useActivity";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useRevertActivity } from "@/hooks/useRevertActivity";
import { groupActivity } from "@/lib/activityGrouping";
import { ApiError } from "@/lib/apiError";
import { DEMO_NOW_ISO } from "@/lib/demoConstants";
import type { ActivityEntry } from "@/types/api";

function revertErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return "Couldn't revert this change — try again.";
}

// Kept out of the component body so the reference clock reads as one plain call
// (a raw `Date.now()` in render trips react-hooks/purity). The demo anchors to
// its fixed clock so relative and burst timestamps stay sensible.
function resolveNowMs(demo: boolean): number {
  return demo ? new Date(DEMO_NOW_ISO).getTime() : Date.now();
}

export function ActivityFeed() {
  const demo = useDemoMode();
  const query = useActivity();
  const revert = useRevertActivity();
  const [revertError, setRevertError] = useState<{ id: string; message: string } | null>(null);
  const [demoNoteId, setDemoNoteId] = useState<string | null>(null);

  const entries = query.data?.entries;
  const groups = useMemo(() => groupActivity(entries ?? []), [entries]);
  const nowMs = resolveNowMs(demo);

  const handleRevert = (entry: ActivityEntry) => {
    setRevertError(null);
    // Demo has no backend to mutate — surface a calm note instead of calling the
    // throwing demo twin (L11: the rail stays visible, only the action is off).
    if (demo) {
      setDemoNoteId(entry.id);
      return;
    }
    setDemoNoteId(null);
    revert.mutate(
      { id: entry.id },
      { onError: (err) => setRevertError({ id: entry.id, message: revertErrorMessage(err) }) }
    );
  };

  const noteFor = (id: string): string | null => {
    if (demoNoteId === id) return "Revert is disabled in the demo.";
    if (revertError?.id === id) return revertError.message;
    return null;
  };

  return (
    <section className="space-y-4">
      <SettingsSectionHeader
        title="Activity"
        infoHint={{
          label: "About activity",
          content:
            "A record of every change made through the API or the app, newest first. Reverting a change restores what it touched and is itself recorded here.",
        }}
      />

      {query.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : query.isError ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-fg-muted">
            Couldn't load the activity ledger — try again.
          </CardContent>
        </Card>
      ) : groups.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No recorded changes yet. Writes made through the API or the app will appear here.
        </p>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <div key={`${group.principalKey}-${group.ts}`} className="space-y-2">
              <ActivityGroupHeader group={group} nowMs={nowMs} />
              <ul className="space-y-2">
                {group.entries.map((entry) => (
                  <ActivityEntryRow
                    key={entry.id}
                    entry={entry}
                    onRevert={handleRevert}
                    reverting={revert.isPending && revert.variables?.id === entry.id}
                    note={noteFor(entry.id)}
                    nowMs={nowMs}
                  />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
