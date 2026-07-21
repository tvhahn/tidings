import { ChevronDown, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { RowState, RowStates } from "@/lib/statementReviewRows";

/** One column in a review table. `render` produces the cell's inner content;
 *  the shell owns the `<TableCell>`/`<TableHead>` wrappers and their classes. */
export interface ReviewColumn<Item> {
  header: string;
  headerClassName?: string;
  cellClassName?: string;
  render: (item: Item, state: RowState) => ReactNode;
}

interface CollapsibleConfig {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  badge?: ReactNode;
}

interface ReviewSectionProps<Item extends { index: number }> {
  title: string;
  count: number;
  items: Item[];
  states: RowStates;
  columns: ReviewColumn<Item>[];
  rowClassName?: (item: Item, state: RowState) => string;
  /** Collapsible shell (Previously Imported, Matched). Mutually exclusive with `bulk`. */
  collapsible?: CollapsibleConfig;
  /** Header-right bulk controls (Ambiguous, Suspected Duplicates, New). */
  bulk?: ReactNode;
}

/** Generic reconciliation section: Card + optional Collapsible shell wrapping a
 *  table whose columns are supplied as data. Replaces the five near-identical
 *  Table blocks the StatementReview component used to inline. Per-section quirks
 *  (extra columns, row highlighting, bulk controls, collapsibility) live in the
 *  props, not in copies of the markup. */
export function ReviewSection<Item extends { index: number }>({
  title,
  count,
  items,
  states,
  columns,
  rowClassName,
  collapsible,
  bulk,
}: ReviewSectionProps<Item>) {
  if (items.length === 0) return null;

  const body = (
    <CardContent className="p-0">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col, i) => (
              <TableHead key={i} className={col.headerClassName}>
                {col.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => {
            const state = states[item.index];
            if (!state) return null;
            return (
              <TableRow key={item.index} className={rowClassName?.(item, state) ?? ""}>
                {columns.map((col, i) => (
                  <TableCell key={i} className={col.cellClassName}>
                    {col.render(item, state)}
                  </TableCell>
                ))}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </CardContent>
  );

  if (collapsible) {
    return (
      <Collapsible open={collapsible.open} onOpenChange={collapsible.onOpenChange}>
        <Card className="border-border/50">
          <CollapsibleTrigger asChild>
            <CardHeader className="cursor-pointer py-3 px-4">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                {collapsible.open ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                {title} ({count}){collapsible.badge}
              </CardTitle>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>{body}</CollapsibleContent>
        </Card>
      </Collapsible>
    );
  }

  return (
    <Card className="border-border/50">
      <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-medium">
          {title} ({count})
        </CardTitle>
        {bulk}
      </CardHeader>
      {body}
    </Card>
  );
}
