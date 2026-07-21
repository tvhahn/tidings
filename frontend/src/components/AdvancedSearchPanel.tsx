import { ChevronDown, Download, Loader2, Search } from "lucide-react";
import { useState } from "react";
import { MonthPickerInput } from "@/components/MonthPickerInput";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { downloadExport } from "@/lib/api";
import type { Filters } from "@/lib/filters";
import { cn } from "@/lib/utils";
import type { SearchParams } from "@/types/api";

const TYPES = ["purchase", "withdrawal", "e-transfer", "preauth", "deposit"];

/**
 * Draft state for the range controls the panel owns directly. Category,
 * institution, and free-text search stay in the page's FilterBar and fold into
 * the committed query via the `filters` prop.
 */
export interface RangeDraft {
  from: string;
  to: string;
  type: string;
  min: string;
  max: string;
  includeIgnored: boolean;
  includeTrash: boolean;
}

interface AdvancedSearchPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** True when the page is showing cross-month range results. */
  rangeMode: boolean;
  /** FilterBar state — its category/institution/search fold into the commit. */
  filters: Filters;
  /** Range controls hydrated from the URL (or defaults in month mode). */
  initialDraft: RangeDraft;
  /** Commit the snapshot to the URL (enters range mode + triggers the fetch). */
  onCommit: (params: SearchParams) => void;
  /** Params for the current mode's CSV export, or null if none apply. */
  exportParams: SearchParams | null;
  /** Clear the range and return to the anchor month (range mode only). */
  onBackToMonth: () => void;
}

export function AdvancedSearchPanel({
  open,
  onOpenChange,
  rangeMode,
  filters,
  initialDraft,
  onCommit,
  exportParams,
  onBackToMonth,
}: AdvancedSearchPanelProps) {
  const [draft, setDraft] = useState<RangeDraft>(initialDraft);
  const [exporting, setExporting] = useState(false);

  const update = <K extends keyof RangeDraft>(key: K, value: RangeDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const handleSearch = () => {
    const params: SearchParams = { from: draft.from, to: draft.to };
    const q = filters.search.trim();
    if (q) params.q = q;
    if (filters.category !== "all") params.category = filters.category;
    if (filters.institution !== "all") params.institution = filters.institution;
    if (draft.type !== "all") params.type = draft.type;
    if (draft.min) {
      const n = Number(draft.min);
      if (Number.isFinite(n)) params.min_amount = n;
    }
    if (draft.max) {
      const n = Number(draft.max);
      if (Number.isFinite(n)) params.max_amount = n;
    }
    if (draft.includeIgnored) params.include_ignored = true;
    if (draft.includeTrash) params.include_deleted = true;
    onCommit(params);
  };

  const handleExport = async () => {
    if (!exportParams) return;
    setExporting(true);
    try {
      await downloadExport(exportParams);
    } finally {
      setExporting(false);
    }
  };

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-1.5 text-sm font-medium text-fg-muted transition-colors hover:text-fg"
        >
          <ChevronDown
            className={cn("h-4 w-4 transition-transform", open && "rotate-180")}
            aria-hidden
          />
          Advanced search
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="mt-3 space-y-4 rounded-[14px] border border-border bg-card px-5 pb-5 pt-5 sm:pt-6">
          {/* Month range */}
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label htmlFor="adv-from" className="text-xs font-medium text-muted-foreground">
                From
              </label>
              <MonthPickerInput
                id="adv-from"
                value={draft.from}
                onChange={(v) => update("from", v)}
                className="w-[180px]"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="adv-to" className="text-xs font-medium text-muted-foreground">
                To
              </label>
              <MonthPickerInput
                id="adv-to"
                value={draft.to}
                onChange={(v) => update("to", v)}
                className="w-[180px]"
              />
            </div>
          </div>

          {/* Type + amount range */}
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label htmlFor="adv-type" className="text-xs font-medium text-muted-foreground">
                Type
              </label>
              <Select value={draft.type} onValueChange={(v) => update("type", v)}>
                <SelectTrigger id="adv-type" className="w-[160px]">
                  <SelectValue placeholder="All types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All types</SelectItem>
                  {TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label htmlFor="adv-min" className="text-xs font-medium text-muted-foreground">
                Min $
              </label>
              <Input
                id="adv-min"
                type="number"
                inputMode="decimal"
                placeholder="0"
                value={draft.min}
                onChange={(e) => update("min", e.target.value)}
                className="w-[100px]"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="adv-max" className="text-xs font-medium text-muted-foreground">
                Max $
              </label>
              <Input
                id="adv-max"
                type="number"
                inputMode="decimal"
                placeholder="no max"
                value={draft.max}
                onChange={(e) => update("max", e.target.value)}
                className="w-[100px]"
              />
            </div>
          </div>

          {/* Visibility toggles */}
          <div className="flex flex-wrap items-center gap-6">
            <label htmlFor="adv-ignored" className="flex items-center gap-2 text-sm text-fg">
              <Switch
                id="adv-ignored"
                checked={draft.includeIgnored}
                onCheckedChange={(v) => update("includeIgnored", v)}
              />
              Include ignored
            </label>
            <label htmlFor="adv-trash" className="flex items-center gap-2 text-sm text-fg">
              <Switch
                id="adv-trash"
                checked={draft.includeTrash}
                onCheckedChange={(v) => update("includeTrash", v)}
              />
              Include trash
            </label>
          </div>

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Button onClick={handleSearch} className="gap-1.5">
              <Search className="h-4 w-4" />
              Search this range
            </Button>
            <Button
              variant="outline"
              onClick={handleExport}
              disabled={exporting || !exportParams}
              className="gap-1.5"
            >
              {exporting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              Export CSV
            </Button>
            {rangeMode && (
              <Button variant="ghost" onClick={onBackToMonth} className="text-fg-muted">
                Back to this month
              </Button>
            )}
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
