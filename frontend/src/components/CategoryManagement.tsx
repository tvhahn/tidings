import { Pencil, Trash2 } from "lucide-react";
import { useState, useMemo } from "react";
import { CategoryPicker } from "@/components/CategoryPicker";
import { DemoSelfHostedModal } from "@/components/DemoSelfHostedModal";
import { IconPicker } from "@/components/IconPicker";
import {
  AddRowButton,
  DeleteRowButton,
  ListSearchInput,
  ShowAllToggle,
} from "@/components/settings/managedListPrimitives";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useManagedCategories,
  useAddCategory,
  useRenameCategory,
  useDeleteCategory,
  useUpdateCategoryGroup,
  useCategoryUsage,
  useCategoryIcons,
  useSetCategoryIcon,
  useClearCategoryIcon,
} from "@/hooks/useCategoryManagement";
import { isDemoMode } from "@/hooks/useDemoMode";
import { iconForCategory } from "@/lib/categoryIcons";
import type { CategoryWithGroup } from "@/types/api";

const COLLAPSED_LIMIT = 8;

export function CategoryManagement() {
  const { data, isLoading } = useManagedCategories();
  const { data: iconsData } = useCategoryIcons();
  const addMutation = useAddCategory();
  const renameMutation = useRenameCategory();
  const deleteMutation = useDeleteCategory();
  const groupMutation = useUpdateCategoryGroup();
  const setIconMutation = useSetCategoryIcon();
  const clearIconMutation = useClearCategoryIcon();

  const iconOverrides = iconsData?.icons ?? {};

  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [newName, setNewName] = useState("");
  const [newGroup, setNewGroup] = useState<string | null>(null);

  // Rename dialog
  const [renameTarget, setRenameTarget] = useState<CategoryWithGroup | null>(null);
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");

  // Delete dialog
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [reassignTo, setReassignTo] = useState<string | null>(null);

  const { data: usageData } = useCategoryUsage(deleteTarget);

  // Demo mode: every write affordance opens the self-hosted modal instead of
  // silently failing against the fixture backend.
  const demo = isDemoMode();
  const [demoGate, setDemoGate] = useState<string | null>(null);

  const categories = useMemo(() => data?.categories ?? [], [data?.categories]);
  const groups = data?.groups ?? [];

  const filtered = useMemo(() => {
    if (!search) return categories;
    const q = search.toLowerCase();
    return categories.filter(
      (c) => c.name.toLowerCase().includes(q) || (c.group && c.group.toLowerCase().includes(q))
    );
  }, [categories, search]);

  const handleAdd = () => {
    const name = newName.trim();
    if (!name) return;
    if (demo) {
      setDemoGate("Adding categories");
      return;
    }
    addMutation.mutate(
      { name, group: newGroup },
      {
        onSuccess: () => {
          setNewName("");
          setNewGroup(null);
        },
      }
    );
  };

  const openRenameDialog = (cat: CategoryWithGroup) => {
    if (demo) {
      setDemoGate("Renaming categories");
      return;
    }
    setRenameTarget(cat);
    setRenameValue(cat.name);
    setRenameDialogOpen(true);
  };

  const handleRename = () => {
    if (!renameTarget || !renameValue.trim()) return;
    renameMutation.mutate(
      { oldName: renameTarget.name, newName: renameValue.trim() },
      {
        onSuccess: () => {
          setRenameDialogOpen(false);
          setRenameTarget(null);
        },
      }
    );
  };

  const openDeleteDialog = (name: string) => {
    if (demo) {
      setDemoGate("Deleting categories");
      return;
    }
    setDeleteTarget(name);
    setReassignTo(null);
    setDeleteDialogOpen(true);
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate(
      { name: deleteTarget, reassignTo: reassignTo ?? undefined },
      {
        onSuccess: () => {
          setDeleteDialogOpen(false);
          setDeleteTarget(null);
          setReassignTo(null);
        },
      }
    );
  };

  const isSearching = search.length > 0;
  const showAll = isSearching || expanded;
  const visible = showAll ? filtered : filtered.slice(0, COLLAPSED_LIMIT);
  const hiddenCount = filtered.length - COLLAPSED_LIMIT;

  const isMiscellaneous = (name: string) => name.toLowerCase() === "miscellaneous";

  return (
    <section className="space-y-4">
      <SettingsSectionHeader
        title="Categories"
        infoHint={{
          label: "About Categories",
          content:
            "The full set of categories transactions can be assigned to, grouped by super-category (e.g. Housing, Transport). Renaming a category updates it everywhere it's already used.",
        }}
        count={data?.count}
        countLabel="categories"
        toolbar={
          <ListSearchInput
            id="settings-categories-search"
            value={search}
            onChange={setSearch}
            ariaLabel="Search categories"
            placeholder="Search categories…"
          />
        }
      />

      {/* Add form */}
      <div className="flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2">
        <Input
          id="settings-categories-new-name"
          placeholder="New category name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          className="h-8 flex-1 bg-background"
          onKeyDown={(e) => {
            if (e.key === "Enter") handleAdd();
          }}
        />
        <Select
          value={newGroup ?? "__none__"}
          onValueChange={(v) => setNewGroup(v === "__none__" ? null : v)}
        >
          <SelectTrigger className="h-8 w-40">
            <SelectValue placeholder="Group" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Ungrouped</SelectItem>
            {groups.map((g) => (
              <SelectItem key={g} value={g}>
                {g}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <AddRowButton
          onClick={handleAdd}
          disabled={!newName.trim() || addMutation.isPending}
          label="Add category"
        />
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}

      {!isLoading && filtered.length === 0 && (
        <p className="py-6 text-center text-muted-foreground">
          {search ? "No categories match your search" : "No categories configured"}
        </p>
      )}

      {!isLoading && visible.length > 0 && (
        <div className="space-y-2">
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14">Icon</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Group</TableHead>
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((c) => {
                  const currentIconName = iconOverrides[c.name.toLowerCase()] ?? null;
                  const resolvedIcon = iconForCategory(c.name, iconOverrides);
                  return (
                    <TableRow key={c.name}>
                      <TableCell>
                        <IconPicker
                          value={currentIconName}
                          trigger={resolvedIcon}
                          ariaLabel={`Change icon for ${c.name}`}
                          onChange={(iconName) => {
                            if (demo) {
                              setDemoGate("Category icons");
                              return;
                            }
                            if (iconName === null) {
                              clearIconMutation.mutate(c.name);
                            } else {
                              setIconMutation.mutate({ name: c.name, icon: iconName });
                            }
                          }}
                        />
                      </TableCell>
                      <TableCell>
                        <span className="font-medium text-sm">{c.name}</span>
                      </TableCell>
                      <TableCell>
                        <Select
                          value={c.group ?? "__none__"}
                          onValueChange={(v) => {
                            if (demo) {
                              setDemoGate("Category groups");
                              return;
                            }
                            groupMutation.mutate({
                              name: c.name,
                              group: v === "__none__" ? null : v,
                            });
                          }}
                        >
                          <SelectTrigger className="h-7 w-36 text-xs border-0 bg-transparent shadow-none hover:bg-muted/50 transition-colors px-2">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__none__">
                              <span className="text-muted-foreground">Ungrouped</span>
                            </SelectItem>
                            {groups.map((g) => (
                              <SelectItem key={g} value={g}>
                                {g}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => openRenameDialog(c)}
                            disabled={isMiscellaneous(c.name)}
                            className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-status-info/10 hover:text-status-info disabled:opacity-20 disabled:cursor-not-allowed"
                            title={
                              isMiscellaneous(c.name)
                                ? "Cannot rename Miscellaneous"
                                : "Rename category"
                            }
                            aria-label="Rename category"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <DeleteRowButton
                            onClick={() => openDeleteDialog(c.name)}
                            disabled={isMiscellaneous(c.name)}
                            label={
                              isMiscellaneous(c.name)
                                ? "Cannot delete Miscellaneous"
                                : "Delete category"
                            }
                            icon={Trash2}
                            size="sm"
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          {!isSearching && hiddenCount > 0 && (
            <ShowAllToggle
              expanded={expanded}
              onToggle={() => setExpanded(!expanded)}
              totalCount={filtered.length}
              entityPlural="categories"
            />
          )}
        </div>
      )}

      {/* Rename dialog */}
      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename category</DialogTitle>
            <DialogDescription>
              Renaming will update all transactions, overrides, and budget groups.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="text-sm text-muted-foreground">
              Current name:{" "}
              <span className="font-medium text-foreground">{renameTarget?.name}</span>
            </div>
            <Input
              id="settings-categories-rename"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder="New name"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRename();
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRenameDialogOpen(false)}
              disabled={renameMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleRename}
              disabled={
                renameMutation.isPending ||
                !renameValue.trim() ||
                renameValue.trim() === renameTarget?.name
              }
            >
              {renameMutation.isPending ? "Renaming..." : "Rename"}
            </Button>
          </DialogFooter>
          {renameMutation.isSuccess && renameMutation.data && (
            <p className="text-sm text-status-success">
              Renamed. Updated {renameMutation.data.transactions_updated} transaction
              {renameMutation.data.transactions_updated === 1 ? "" : "s"},{" "}
              {renameMutation.data.overrides_updated} override
              {renameMutation.data.overrides_updated === 1 ? "" : "s"}.
            </p>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete category</DialogTitle>
            <DialogDescription>
              This will remove &quot;{deleteTarget}&quot; from the category list.
            </DialogDescription>
          </DialogHeader>
          {usageData && usageData.transaction_count > 0 && (
            <div className="space-y-3">
              <p className="text-sm text-status-warning">
                This category has {usageData.transaction_count} transaction
                {usageData.transaction_count === 1 ? "" : "s"}. Choose a category to reassign them
                to:
              </p>
              <CategoryPicker value={reassignTo} onSelect={setReassignTo} />
            </div>
          )}
          {usageData && usageData.override_count > 0 && (
            <p className="text-sm text-muted-foreground">
              {usageData.override_count} override rule
              {usageData.override_count === 1 ? "" : "s"} will also be removed.
            </p>
          )}
          {usageData && usageData.in_budget && (
            <p className="text-sm text-muted-foreground">
              This category will be removed from budget targets
              {usageData.in_group ? ` and the "${usageData.in_group}" group` : ""}.
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={
                deleteMutation.isPending ||
                (usageData != null && usageData.transaction_count > 0 && !reassignTo)
              }
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DemoSelfHostedModal
        open={demoGate != null}
        onOpenChange={(open) => {
          if (!open) setDemoGate(null);
        }}
        featureName={demoGate ?? ""}
      />
    </section>
  );
}
