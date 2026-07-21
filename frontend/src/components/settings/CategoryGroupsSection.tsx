import { Layers, Pencil } from "lucide-react";
import { useState } from "react";
import { GroupEditorDialog } from "@/components/GroupEditorDialog";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Button } from "@/components/ui/button";
import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { useChartTone } from "@/hooks/useChartTone";
import { getGroupColor } from "@/lib/categoryGroups";

export function CategoryGroupsSection() {
  const { groups, isLoading } = useCategoryGroups();
  const tone = useChartTone();
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <section className="space-y-4">
      <SettingsSectionHeader
        title="Category Groups"
        infoHint={{
          label: "About Category Groups",
          content:
            "Buckets that organize categories for the Summary chart, Sankey cash flow, and budget table — e.g. Food & Dining, Transport. Renaming or reordering a group updates all visualizations.",
        }}
        count={groups.length}
        countLabel="groups"
        toolbar={
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDialogOpen(true)}
            className="gap-1.5"
          >
            <Pencil className="h-3.5 w-3.5" />
            Manage groups
          </Button>
        }
      />

      {groups.length === 0 ? (
        <button
          onClick={() => setDialogOpen(true)}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed bg-muted/30 px-4 py-6 text-sm text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        >
          <Layers className="h-4 w-4" />
          No groups yet — create your first
        </button>
      ) : (
        <div
          className={`flex flex-wrap gap-2 ${isLoading ? "opacity-60" : ""}`}
          aria-label="Category group list"
        >
          {groups.map((g) => (
            <div
              key={g.name}
              className="inline-flex items-center gap-2 rounded-full border bg-muted/30 px-3 py-1 text-sm"
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ backgroundColor: getGroupColor(g.name, groups, tone) }}
                aria-hidden="true"
              />
              <span className="font-medium">{g.name}</span>
              <span className="text-xs text-muted-foreground">{g.categories.length}</span>
            </div>
          ))}
        </div>
      )}

      <GroupEditorDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </section>
  );
}
