import { Pencil } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CategoryManagement } from "@/components/CategoryManagement";
import { GroupEditorDialog } from "@/components/GroupEditorDialog";
import { PageHeader } from "@/components/PageHeader";
import { AutoIgnoreRulesSection } from "@/components/settings/AutoIgnoreRulesSection";
import { CategoryRulesSection } from "@/components/settings/CategoryRulesSection";
import { MerchantAliasSection } from "@/components/settings/MerchantAliasSection";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "categories", label: "Categories" },
  { id: "rules", label: "Rules" },
  { id: "ignore", label: "Auto-ignore" },
  { id: "aliases", label: "Aliases" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function isTabId(value: string | null): value is TabId {
  return TABS.some((t) => t.id === value);
}

export function CategorizePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: TabId = isTabId(tabParam) ? tabParam : "categories";
  const [groupsDialogOpen, setGroupsDialogOpen] = useState(false);

  const setTab = (next: TabId) => {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === "categories") {
          p.delete("tab");
        } else {
          p.set("tab", next);
        }
        return p;
      },
      { replace: true }
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Categorize"
        subtitle="Categories, rules, and merchant aliases."
        actions={
          tab === "categories" ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setGroupsDialogOpen(true)}
              className="gap-1.5"
            >
              <Pencil className="h-3.5 w-3.5" />
              Manage groups
            </Button>
          ) : null
        }
      />

      <div role="tablist" aria-label="Categorize sections" className="flex gap-1 border-b">
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.id)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "border-primary text-foreground"
                  : "border-transparent text-fg-secondary hover:text-foreground"
              )}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      <div role="tabpanel">
        {tab === "categories" ? <CategoryManagement /> : null}
        {tab === "rules" ? <CategoryRulesSection /> : null}
        {tab === "ignore" ? <AutoIgnoreRulesSection /> : null}
        {tab === "aliases" ? <MerchantAliasSection /> : null}
      </div>

      <GroupEditorDialog open={groupsDialogOpen} onOpenChange={setGroupsDialogOpen} />
    </div>
  );
}
