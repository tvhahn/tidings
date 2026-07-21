import { AlertTriangle, Combine } from "lucide-react";
import { useState } from "react";
import { CategoryPicker } from "@/components/CategoryPicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useConsolidateOverrides, useOverrideDuplicates } from "@/hooks/useOverrides";
import type { OverrideDuplicateGroup } from "@/types/api";

/**
 * Surfaces overrides that share a normalized merchant key so the user can
 * consolidate them down to a single rule. Unanimous groups (every member
 * agrees on category) support one-click consolidation; ambiguous groups
 * require picking a canonical category first.
 */
export function OverrideDuplicatesBanner() {
  const { data } = useOverrideDuplicates();
  const [open, setOpen] = useState(false);

  const groups = data?.groups ?? [];
  if (groups.length === 0) return null;

  const unanimous = groups.filter((g) => g.unanimous_category !== null);
  const ambiguous = groups.filter((g) => g.unanimous_category === null);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-3 rounded-xl border border-status-warning/30 bg-status-warning/[0.03] px-4 py-3 text-left text-sm transition-colors hover:bg-status-warning/[0.06]"
      >
        <Combine className="h-4 w-4 shrink-0 text-status-warning" />
        <div className="flex-1 min-w-0">
          <div className="font-medium">
            {groups.length === 1
              ? "1 duplicate group detected"
              : `${groups.length} duplicate groups detected`}
          </div>
          <div className="text-xs text-muted-foreground">
            {unanimous.length > 0 && `${unanimous.length} ready to consolidate`}
            {unanimous.length > 0 && ambiguous.length > 0 && " · "}
            {ambiguous.length > 0 && `${ambiguous.length} need review`}
          </div>
        </div>
        <span className="shrink-0 text-xs font-medium text-status-warning underline-offset-2 hover:underline">
          Review
        </span>
      </button>

      <DuplicatesDialog open={open} onOpenChange={setOpen} groups={groups} />
    </>
  );
}

function DuplicatesDialog({
  open,
  onOpenChange,
  groups,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: OverrideDuplicateGroup[];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Review duplicate rules</DialogTitle>
          <DialogDescription>
            Rules that share a normalized merchant key. Consolidating collapses them into a single
            rule so future variants match automatically.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {groups.map((g) => (
            <DuplicateGroupCard key={g.normalized_key} group={g} />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function DuplicateGroupCard({ group }: { group: OverrideDuplicateGroup }) {
  const consolidate = useConsolidateOverrides();
  const isAmbiguous = group.unanimous_category === null;

  const [canonicalCompany, setCanonicalCompany] = useState(() =>
    group.normalized_key.toUpperCase()
  );
  const [pickedCategory, setPickedCategory] = useState<string | null>(group.unanimous_category);

  const disabled = !canonicalCompany.trim() || !pickedCategory || consolidate.isPending;

  const handleConsolidate = () => {
    if (!pickedCategory) return;
    consolidate.mutate({
      normalized_key: group.normalized_key,
      canonical_company: canonicalCompany.trim(),
      category: pickedCategory,
      members: group.members.map((m) => m.company),
    });
  };

  return (
    <div className="rounded-lg border border-border/50 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isAmbiguous && <AlertTriangle className="h-4 w-4 shrink-0 text-status-warning" />}
          <code className="truncate text-sm font-semibold">{group.normalized_key}</code>
          <Badge variant="secondary" className="shrink-0 text-xs">
            {group.members.length}
          </Badge>
        </div>
      </div>

      <ul className="mb-3 space-y-1 text-sm">
        {group.members.map((m) => (
          <li key={m.company} className="flex items-center justify-between gap-2">
            <span className="truncate">{m.company}</span>
            <Badge
              variant={isAmbiguous ? "outline" : "secondary"}
              className="shrink-0 text-xs font-normal"
            >
              {m.category}
            </Badge>
          </li>
        ))}
      </ul>

      {isAmbiguous && (
        <p className="mb-2 text-xs text-muted-foreground">
          Members disagree on category. Pick the canonical category before consolidating.
        </p>
      )}

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-xs text-muted-foreground">Canonical rule:</span>
          <Input
            id="settings-duplicates-canonical"
            value={canonicalCompany}
            onChange={(e) => setCanonicalCompany(e.target.value)}
            className="h-8 flex-1"
            placeholder="Canonical company name"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-xs text-muted-foreground">Category:</span>
          <CategoryPicker
            value={pickedCategory}
            onSelect={setPickedCategory}
            placeholder={isAmbiguous ? "Select canonical…" : "Category"}
          />
          <Button
            type="button"
            onClick={handleConsolidate}
            disabled={disabled}
            size="sm"
            className="ml-auto"
          >
            {consolidate.isPending ? "Consolidating…" : "Consolidate"}
          </Button>
        </div>
        {consolidate.isError && (
          <p className="text-xs text-status-danger">
            {consolidate.error instanceof Error
              ? consolidate.error.message
              : "Consolidation failed"}
          </p>
        )}
      </div>
    </div>
  );
}
