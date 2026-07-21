import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { NAV_TABS, TAX_HREF, sectionOf, type NavTab } from "@/config/navTabs";
import { useTaxTrackingEnabled } from "@/hooks/useTaxTrackingEnabled";
import { cn } from "@/lib/utils";
import { useNavPreferences } from "@/stores/navPreferences";

function SortableRow({
  tab,
  hidden,
  onToggle,
}: {
  tab: NavTab;
  hidden: boolean;
  onToggle: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: tab.href,
  });
  const Icon = tab.icon;
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex items-center gap-3 rounded-lg border border-border/50 bg-card px-3 py-2.5",
        isDragging && "opacity-60 ring-1 ring-ring",
        hidden && "opacity-60"
      )}
    >
      <button
        type="button"
        aria-label={`Drag ${tab.label}`}
        className="-m-2 inline-flex h-11 w-11 touch-none items-center justify-center text-muted-foreground hover:text-foreground cursor-grab active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
      <span className="flex-1 text-sm">{tab.label}</span>
      <Switch checked={!hidden} onCheckedChange={onToggle} aria-label={`Show ${tab.label} tab`} />
    </div>
  );
}

export function TabCustomizationSection() {
  const tabOrder = useNavPreferences((s) => s.tabOrder);
  const hiddenTabs = useNavPreferences((s) => s.hiddenTabs);
  const setOrder = useNavPreferences((s) => s.setOrder);
  const toggleHidden = useNavPreferences((s) => s.toggleHidden);
  const reset = useNavPreferences((s) => s.reset);
  const taxEnabled = useTaxTrackingEnabled();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const byHref = new Map(NAV_TABS.map((t) => [t.href, t]));
  const hiddenSet = new Set(hiddenTabs);

  // Drop the Tax receipts row when the feature is off — it can't be shown or
  // reordered while disabled (Settings → Features owns that switch).
  const visibleHrefs = tabOrder.filter((h) => taxEnabled || h !== TAX_HREF);
  const mainHrefs = visibleHrefs.filter((h) => sectionOf(h) === "main");
  const workspaceHrefs = visibleHrefs.filter((h) => sectionOf(h) === "workspace");

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    if (sectionOf(String(active.id)) !== sectionOf(String(over.id))) return;
    const oldIdx = tabOrder.indexOf(String(active.id));
    const newIdx = tabOrder.indexOf(String(over.id));
    if (oldIdx < 0 || newIdx < 0) return;
    setOrder(arrayMove(tabOrder, oldIdx, newIdx));
  };

  const renderRow = (href: string) => {
    const tab = byHref.get(href);
    if (!tab) return null;
    return (
      <SortableRow
        key={href}
        tab={tab}
        hidden={hiddenSet.has(href)}
        onToggle={() => toggleHidden(href)}
      />
    );
  };

  return (
    <section className="space-y-4">
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="space-y-0.5">
          <p className="text-sm font-medium">Navigation tabs</p>
          <p className="text-xs text-fg-secondary">
            Drag to reorder within a section. Toggle to hide tabs you don&apos;t use — hidden tabs
            remain reachable by direct URL.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={reset} className="self-start sm:self-auto">
          Reset to default
        </Button>
      </div>

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={mainHrefs} strategy={verticalListSortingStrategy}>
          <div className="space-y-2">{mainHrefs.map(renderRow)}</div>
        </SortableContext>

        {workspaceHrefs.length > 0 ? (
          <>
            <p className="mt-4 px-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              Workspace
            </p>
            <SortableContext items={workspaceHrefs} strategy={verticalListSortingStrategy}>
              <div className="space-y-2">{workspaceHrefs.map(renderRow)}</div>
            </SortableContext>
          </>
        ) : null}
      </DndContext>
    </section>
  );
}
