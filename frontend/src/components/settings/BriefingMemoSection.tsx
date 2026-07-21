import { useEffect, useState } from "react";
import { toast } from "sonner";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { cn } from "@/lib/utils";

const MEMO_MAX_LENGTH = 2000;
// Start nudging the counter into view once the memo is within this many
// characters of the cap, so the limit never arrives as a surprise.
const COUNTER_VISIBLE_FROM = MEMO_MAX_LENGTH - 200;

const PLACEHOLDER =
  "Household of four. Saving for a renovation through fall. Property taxes and home insurance are annual, both due around May.";

export function BriefingMemoSection() {
  const { data: config } = useConfig();
  const updateConfig = useUpdateConfig();

  const savedMemo = config?.insights_user_memo ?? "";
  const [draft, setDraft] = useState(savedMemo);

  // Re-sync the draft whenever the persisted value changes (initial load, or a
  // refetch after saving). While the user is editing, `savedMemo` is stable, so
  // this doesn't clobber in-progress edits.
  useEffect(() => {
    setDraft(savedMemo);
  }, [savedMemo]);

  const isDirty = draft !== savedMemo;
  const disabled = updateConfig.isPending;
  const nearLimit = draft.length >= COUNTER_VISIBLE_FROM;

  const handleSave = () => {
    if (!isDirty || disabled) return;
    // An empty draft clears the memo back to no context (stored as null).
    const next = draft.trim().length > 0 ? draft : null;
    updateConfig.mutate(
      { insights_user_memo: next },
      { onSuccess: () => toast.success("Briefing memo saved") }
    );
  };

  return (
    <section className="space-y-3">
      <SettingsSectionHeader
        title="Briefing memo"
        infoHint={{
          label: "About the briefing memo",
          content:
            "This memo is added to every monthly briefing as standing context, so the writeup already knows the facts that don't change month to month.",
        }}
      />
      <p className="text-sm text-muted-foreground">
        Standing context for your monthly briefing. Household facts, known annual bills, goals —
        whatever the briefing should already know.
      </p>

      <Textarea
        aria-label="Briefing memo"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        maxLength={MEMO_MAX_LENGTH}
        disabled={disabled}
        rows={5}
        placeholder={PLACEHOLDER}
      />

      <div className="flex items-center justify-between gap-3">
        <span
          className={cn(
            "text-xs tabular-nums text-muted-foreground",
            nearLimit ? "visible" : "invisible"
          )}
          aria-hidden={!nearLimit}
        >
          {draft.length.toLocaleString()} / {MEMO_MAX_LENGTH.toLocaleString()}
        </span>
        <Button type="button" size="sm" onClick={handleSave} disabled={!isDirty || disabled}>
          Save memo
        </Button>
      </div>
    </section>
  );
}
