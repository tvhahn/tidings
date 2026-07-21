import { ArrowUp, ArrowDown, Pencil, Trash2, Plus, Check, X, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
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
import { useCategoryGroups, useUpdateGroups } from "@/hooks/useCategoryGroups";
import { useManagedCategories } from "@/hooks/useCategoryManagement";
import { useChartTone } from "@/hooks/useChartTone";
import { getGroupColor, getPaletteColorByIndex } from "@/lib/categoryGroups";

interface GroupEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface EditableGroup {
  name: string;
  categories: string[];
}

export function GroupEditorDialog({ open, onOpenChange }: GroupEditorDialogProps) {
  const { groups: serverGroups, version } = useCategoryGroups();
  const updateMutation = useUpdateGroups();
  const { data: managedData } = useManagedCategories();
  const tone = useChartTone();

  const [groups, setGroups] = useState<EditableGroup[]>([]);
  const [newGroupName, setNewGroupName] = useState("");
  const [renamingIndex, setRenamingIndex] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // All known categories from the management API
  const allCategories = managedData?.categories?.map((c) => c.name) ?? [];

  // Reset local state when dialog opens
  useEffect(() => {
    if (open) {
      setGroups(serverGroups.map((g) => ({ name: g.name, categories: [...g.categories] })));
      setNewGroupName("");
      setRenamingIndex(null);
    }
  }, [open, serverGroups]);

  // Compute ungrouped categories
  const assignedSet = new Set(groups.flatMap((g) => g.categories.map((c) => c.toLowerCase())));
  const ungrouped = allCategories.filter((c) => !assignedSet.has(c.toLowerCase()));

  const hasChanges =
    JSON.stringify(groups) !==
    JSON.stringify(serverGroups.map((g) => ({ name: g.name, categories: [...g.categories] })));

  // ---- Group CRUD ----

  const addGroup = () => {
    const name = newGroupName.trim();
    if (!name) return;
    if (groups.some((g) => g.name.toLowerCase() === name.toLowerCase())) {
      toast.error("A group with that name already exists");
      return;
    }
    setGroups([...groups, { name, categories: [] }]);
    setNewGroupName("");
  };

  const moveGroup = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= groups.length) return;
    const next = [...groups];
    const at = next[index];
    const to = next[target];
    if (!at || !to) return;
    next[index] = to;
    next[target] = at;
    setGroups(next);
  };

  const startRename = (index: number) => {
    setRenamingIndex(index);
    const current = groups[index];
    if (current) setRenameValue(current.name);
  };

  const confirmRename = () => {
    if (renamingIndex === null) return;
    const name = renameValue.trim();
    if (!name) return;
    if (groups.some((g, i) => i !== renamingIndex && g.name.toLowerCase() === name.toLowerCase())) {
      toast.error("A group with that name already exists");
      return;
    }
    setGroups(groups.map((g, i) => (i === renamingIndex ? { ...g, name } : g)));
    setRenamingIndex(null);
  };

  const deleteGroup = (index: number) => {
    setGroups(groups.filter((_, i) => i !== index));
    // Categories become ungrouped automatically
  };

  // ---- Category assignment ----

  const moveCategory = (category: string, fromGroup: string | null, toGroup: string | null) => {
    setGroups(
      groups.map((g) => {
        let cats = g.categories;
        // Remove from old group
        if (fromGroup && g.name === fromGroup) {
          cats = cats.filter((c) => c.toLowerCase() !== category.toLowerCase());
        }
        // Add to new group
        if (toGroup && g.name === toGroup) {
          cats = [...cats, category.toLowerCase()];
        }
        return { ...g, categories: cats };
      })
    );
  };

  // ---- Save ----

  const handleSave = () => {
    updateMutation.mutate(
      {
        groups: groups.map((g) => ({ name: g.name, categories: g.categories })),
        version: version || null,
      },
      {
        onSuccess: () => {
          toast.success("Groups saved");
          onOpenChange(false);
        },
        onError: (err) => {
          const status = (err as Error & { status?: number }).status;
          if (status === 409) {
            toast.error("Groups were modified elsewhere. Please close and reopen to refresh.");
          } else {
            toast.error("Failed to save groups");
          }
        },
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Category Groups</DialogTitle>
          <DialogDescription>
            Organize spending categories into groups for Summary charts and tables.
          </DialogDescription>
        </DialogHeader>

        {/* Group list */}
        <div className="space-y-1.5">
          {groups.map((group, index) => (
            <div
              key={`${group.name}-${index}`}
              className="flex items-center gap-2 rounded-md border px-3 py-2"
            >
              <span
                className="h-3 w-3 shrink-0 rounded-sm"
                style={{ backgroundColor: getGroupColor(group.name, groups, tone) }}
              />
              {renamingIndex === index ? (
                <div className="flex flex-1 items-center gap-1">
                  <Input
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") confirmRename();
                      if (e.key === "Escape") setRenamingIndex(null);
                    }}
                    className="h-7 text-sm"
                    // eslint-disable-next-line jsx-a11y/no-autofocus -- inline rename input shown on click; focus preserves typing flow
                    autoFocus
                  />
                  <button
                    onClick={confirmRename}
                    className="rounded p-0.5 text-status-success hover:bg-status-success/10"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setRenamingIndex(null)}
                    className="rounded p-0.5 text-muted-foreground hover:bg-muted"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <span className="flex-1 text-sm font-medium">{group.name}</span>
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                    {group.categories.length}
                  </Badge>
                </>
              )}

              {renamingIndex !== index && (
                <div className="flex items-center gap-0.5">
                  <button
                    onClick={() => moveGroup(index, -1)}
                    disabled={index === 0}
                    className="rounded p-0.5 text-muted-foreground/40 hover:text-foreground hover:bg-muted transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
                    title="Move up"
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => moveGroup(index, 1)}
                    disabled={index === groups.length - 1}
                    className="rounded p-0.5 text-muted-foreground/40 hover:text-foreground hover:bg-muted transition-colors disabled:opacity-20 disabled:cursor-not-allowed"
                    title="Move down"
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => startRename(index)}
                    className="rounded p-0.5 text-muted-foreground/40 hover:text-status-info hover:bg-status-info/10 transition-colors"
                    title="Rename group"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => deleteGroup(index)}
                    className="rounded p-0.5 text-muted-foreground/40 hover:text-status-danger hover:bg-status-danger/10 transition-colors"
                    title="Delete group"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
          ))}

          {/* Add group row */}
          <div className="flex items-center gap-2 rounded-md border border-dashed px-3 py-2">
            <span
              className="h-3 w-3 shrink-0 rounded-sm"
              style={{
                backgroundColor: getPaletteColorByIndex(groups.length, tone),
                opacity: 0.4,
              }}
            />
            <Input
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              placeholder="New group name"
              className="h-7 flex-1 text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter") addGroup();
              }}
            />
            <button
              onClick={addGroup}
              disabled={!newGroupName.trim()}
              className="rounded p-0.5 text-muted-foreground hover:text-status-success hover:bg-status-success/10 transition-colors disabled:opacity-30"
              title="Add group"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Category assignments */}
        <div className="space-y-2 pt-2">
          <h4 className="text-sm font-medium text-muted-foreground">Category Assignments</h4>
          <div className="max-h-[240px] overflow-y-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-background border-b">
                <tr>
                  <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">
                    Category
                  </th>
                  <th className="text-left px-3 py-1.5 font-medium text-muted-foreground">Group</th>
                </tr>
              </thead>
              <tbody>
                {/* Show grouped categories first, then ungrouped */}
                {groups.flatMap((g) =>
                  g.categories.map((cat) => (
                    <CategoryRow
                      key={cat}
                      category={cat}
                      currentGroup={g.name}
                      groups={groups}
                      onMove={moveCategory}
                    />
                  ))
                )}
                {ungrouped.map((cat) => (
                  <CategoryRow
                    key={cat}
                    category={cat}
                    currentGroup={null}
                    groups={groups}
                    onMove={moveCategory}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={updateMutation.isPending || !hasChanges}>
            {updateMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving...
              </>
            ) : (
              "Save"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---- Internal row component ----

function CategoryRow({
  category,
  currentGroup,
  groups,
  onMove,
}: {
  category: string;
  currentGroup: string | null;
  groups: EditableGroup[];
  onMove: (category: string, from: string | null, to: string | null) => void;
}) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="px-3 py-1.5 capitalize">{category}</td>
      <td className="px-3 py-1.5">
        <Select
          value={currentGroup ?? "__ungrouped__"}
          onValueChange={(v) => {
            const newGroup = v === "__ungrouped__" ? null : v;
            onMove(category, currentGroup, newGroup);
          }}
        >
          <SelectTrigger className="h-7 w-40 text-xs border-0 bg-transparent shadow-none hover:bg-muted/50 transition-colors px-2">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__ungrouped__">
              <span className="text-muted-foreground">Ungrouped</span>
            </SelectItem>
            {groups.map((g) => (
              <SelectItem key={g.name} value={g.name}>
                {g.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
    </tr>
  );
}
