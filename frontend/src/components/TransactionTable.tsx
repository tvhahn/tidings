import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ArrowUp,
  ArrowDown,
  ChevronsUpDown,
  CheckCircle2,
  EyeOff,
  FileText,
  Mail,
  Sparkles,
  Trash2,
} from "lucide-react";
import { createContext, memo, useContext, useRef, useState } from "react";
import { toast } from "sonner";
import { CategoryPicker } from "@/components/CategoryPicker";
import { CommentPopover } from "@/components/CommentPopover";
import { RowAttachmentAction } from "@/components/RowAttachmentAction";
import { TaxFlagMenu } from "@/components/TaxFlagMenu";
import { TransactionEditPopover } from "@/components/TransactionEditPopover";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useIgnoreTransaction } from "@/hooks/useIgnoreTransaction";
import { useSoftDelete } from "@/hooks/useSoftDelete";
import { useUpdateCategory } from "@/hooks/useUpdateCategory";
import { formatCurrency, formatDate, titleCase } from "@/lib/format";
import type { SortConfig, SortColumn } from "@/lib/sort";
import { cn } from "@/lib/utils";
import { useEditedTransactions, makeKey } from "@/stores/editedTransactions";
import { usePreferences } from "@/stores/preferences";
import type { Transaction } from "@/types/api";

interface SelectionMode {
  /** Stable txn keys (`${forwarded_to}|${date_file_name}`). */
  selected: Set<string>;
  /** Toggle a single row's selection state. */
  onToggle: (key: string) => void;
  /** Toggle "select all currently visible". */
  onToggleAll: () => void;
}

interface TransactionTableProps {
  transactions: Transaction[];
  sort: SortConfig;
  onSortChange: (sort: SortConfig) => void;
  onConfirm?: ((txn: Transaction) => void) | undefined;
  onEmailPreview?: ((txn: Transaction) => void) | undefined;
  showHeader?: boolean | undefined;
  /** Empty-state copy shown when there are zero transactions. Defaults to
   *  the calm Tidings phrasing. */
  emptyMessage?: string | undefined;
  /** When provided, renders a leading checkbox column for bulk-categorize. */
  selectionMode?: SelectionMode | undefined;
  /** Virtualize rows via @tanstack/react-virtual. Use on pages that can render
   *  thousands of rows (e.g. the Transactions range view). Leave off for small monthly views —
   *  virtualization adds a scroll container and is pure overhead at <300 rows. */
  virtualize?: boolean | undefined;
}

/** True once a row has been hovered/focused — gates mounting its action cluster. */
const RowRevealContext = createContext(false);

interface CategoryCellProps {
  txn: Transaction;
  edited: boolean;
  onCategoryChange: (category: string) => void;
  onConfirm?: (() => void) | undefined;
  onToggleIgnore: () => void;
  onDelete: () => void;
  onEmailPreview?: (() => void) | undefined;
}

/**
 * The category picker plus its hover-action cluster. The cluster is lazy-mounted
 * on first row hover/focus (via RowRevealContext) so a month change renders
 * fresh rows without the ~dozen Radix nodes each — the bulk of the table's DOM.
 * Once mounted, group-hover still governs visibility, so behavior is unchanged.
 */
// Every cluster action renders as a 20px square (p-0.5 padding + h-4 w-4 icon)
// separated by gap-0.5 (2px). Keep in sync with the button/trigger classes
// below and in CommentPopover/TransactionEditPopover.
const CLUSTER_BUTTON_PX = 20;
const CLUSTER_GAP_PX = 2;

function CategoryCell({
  txn,
  edited,
  onCategoryChange,
  onConfirm,
  onToggleIgnore,
  onDelete,
  onEmailPreview,
}: CategoryCellProps) {
  const revealed = useContext(RowRevealContext);
  const needsAttention = txn.category?.toLowerCase() === "miscellaneous" && !txn.category_audit;
  // Reserve the cluster's exact footprint BEFORE the buttons mount. Mounting
  // the cluster mid-gesture (first row hover) must not change the cell's
  // content width: when it did, the table's auto layout reallocated column
  // widths between a click's mousedown and mouseup, sliding the pill out from
  // under the pointer — mousedown hit the pill, mouseup hit a cluster button,
  // and the click was dispatched to their common ancestor, so "Edit category"
  // clicks on a fresh row were swallowed. The container always renders at
  // final width; only the buttons are reveal-gated.
  const actionCount = 6 + (onConfirm && needsAttention ? 1 : 0) + (onEmailPreview ? 1 : 0);
  const clusterWidth = actionCount * CLUSTER_BUTTON_PX + (actionCount - 1) * CLUSTER_GAP_PX;
  return (
    <div className="flex items-center gap-1.5">
      <CategoryPicker
        variant="inline"
        value={txn.category ? titleCase(txn.category) : null}
        onSelect={onCategoryChange}
        edited={edited}
        needsAttention={needsAttention}
        merchant={txn.company}
      />
      <div
        style={{ width: clusterWidth }}
        className="ml-auto flex shrink-0 items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity"
      >
        {revealed && (
          <>
            {onConfirm && needsAttention && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    aria-label="Confirm category"
                    onClick={onConfirm}
                    className="rounded p-0.5 text-muted-foreground/50 hover:text-status-success hover:bg-status-success/10 transition-colors"
                  >
                    <CheckCircle2 className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>Confirm category</TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  aria-label={txn.ignored ? "Restore transaction" : "Ignore transaction"}
                  onClick={onToggleIgnore}
                  className={cn(
                    "rounded p-0.5 transition-colors",
                    txn.ignored
                      ? "text-muted-foreground hover:text-foreground"
                      : "text-muted-foreground/50 hover:text-status-warning hover:bg-status-warning/10"
                  )}
                >
                  <EyeOff className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>
                {txn.ignored ? "Restore transaction" : "Ignore transaction"}
              </TooltipContent>
            </Tooltip>
            <CommentPopover
              forwardedTo={txn.forwarded_to}
              dateFileName={txn.date_file_name}
              comment={txn.comment}
            />
            <RowAttachmentAction txn={txn} />
            <TransactionEditPopover
              forwardedTo={txn.forwarded_to}
              dateFileName={txn.date_file_name}
              company={txn.company}
              amount={txn.amount}
              transactionType={txn.transaction_type}
            />
            {onEmailPreview && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    aria-label="View original email"
                    onClick={onEmailPreview}
                    className="rounded p-0.5 text-muted-foreground/50 hover:text-foreground hover:bg-muted transition-colors"
                  >
                    <Mail className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>View original email</TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  aria-label="Delete transaction"
                  onClick={onDelete}
                  className="rounded p-0.5 text-muted-foreground/50 hover:text-status-danger hover:bg-status-danger/10 transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>Delete transaction</TooltipContent>
            </Tooltip>
            <TaxFlagMenu txn={txn} />
          </>
        )}
      </div>
    </div>
  );
}

/**
 * One table row. Holds the reveal flag so hovering/focusing anywhere in the row
 * mounts its action cluster (see CategoryCell). Keyed by the stable txn id
 * (getRowId), so a month change remounts rows and resets reveal to false.
 */
function TxnRow({ row }: { row: Row<Transaction> }) {
  const [revealed, setRevealed] = useState(false);
  const reveal = () => setRevealed(true);
  return (
    <RowRevealContext.Provider value={revealed}>
      <TableRow
        className={cn("group", row.original.ignored && "opacity-40")}
        onMouseEnter={reveal}
        onFocusCapture={reveal}
      >
        {row.getVisibleCells().map((cell) => (
          <TableCell key={cell.id}>
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </TableCell>
        ))}
      </TableRow>
    </RowRevealContext.Provider>
  );
}

function TransactionTableImpl({
  transactions,
  sort,
  onSortChange,
  onConfirm,
  onEmailPreview,
  showHeader = true,
  emptyMessage = "No transactions match.",
  selectionMode,
  virtualize = false,
}: TransactionTableProps) {
  const updateCategory = useUpdateCategory();
  const ignoreMutation = useIgnoreTransaction();
  const deleteMutation = useSoftDelete();
  const isEdited = useEditedTransactions((s) => s.isEdited);
  const undo = useEditedTransactions((s) => s.undo);
  const dateFormat = usePreferences((s) => s.dateFormat);

  const handleCategoryChange = (txn: Transaction, newCategory: string) => {
    const oldCategory = txn.category || "miscellaneous";
    if (newCategory.toLowerCase() === oldCategory.toLowerCase()) return;

    updateCategory.mutate(
      {
        forwardedTo: txn.forwarded_to,
        dateFileName: txn.date_file_name,
        category: newCategory,
        oldCategory,
      },
      {
        onSuccess: () => {
          toast(`Category updated to ${newCategory}`, {
            action: {
              label: "Undo",
              onClick: () => {
                const old = undo(makeKey(txn.forwarded_to, txn.date_file_name));
                if (old) {
                  updateCategory.mutate({
                    forwardedTo: txn.forwarded_to,
                    dateFileName: txn.date_file_name,
                    category: old,
                    oldCategory: newCategory.toLowerCase(),
                  });
                }
              },
            },
          });
        },
      }
    );
  };

  const handleHeaderClick = (column: SortColumn) => {
    if (sort.column === column) {
      onSortChange({ column, direction: sort.direction === "asc" ? "desc" : "asc" });
    } else {
      onSortChange({ column, direction: "asc" });
    }
  };

  const SortIcon = ({ column }: { column: SortColumn }) => {
    if (sort.column !== column)
      return <ChevronsUpDown className="h-3.5 w-3.5 text-muted-foreground/40" />;
    if (sort.direction === "asc") return <ArrowUp className="h-3.5 w-3.5" />;
    return <ArrowDown className="h-3.5 w-3.5" />;
  };

  const sortHeader = (label: string, column: SortColumn, align?: "right") => () => (
    <button
      onClick={() => handleHeaderClick(column)}
      className={cn(
        "flex items-center gap-1 hover:text-foreground transition-colors -ml-1 px-1 py-0.5 rounded",
        align === "right" && "ml-auto",
        sort.column === column ? "text-foreground" : "text-muted-foreground"
      )}
    >
      {label}
      <SortIcon column={column} />
    </button>
  );

  const allKeys = transactions.map((t) => makeKey(t.forwarded_to, t.date_file_name));
  const allSelected =
    selectionMode != null &&
    allKeys.length > 0 &&
    allKeys.every((k) => selectionMode.selected.has(k));
  const someSelected =
    selectionMode != null && !allSelected && allKeys.some((k) => selectionMode.selected.has(k));

  const selectionColumn: ColumnDef<Transaction> = {
    id: "select",
    header: () => (
      <input
        type="checkbox"
        aria-label={allSelected ? "Deselect all" : "Select all"}
        checked={allSelected}
        ref={(el) => {
          if (el) el.indeterminate = someSelected;
        }}
        onChange={() => selectionMode?.onToggleAll()}
        className="h-4 w-4 cursor-pointer accent-brand"
      />
    ),
    cell: ({ row }) => {
      const key = makeKey(row.original.forwarded_to, row.original.date_file_name);
      const checked = selectionMode?.selected.has(key) ?? false;
      return (
        <input
          type="checkbox"
          aria-label={checked ? "Deselect transaction" : "Select transaction"}
          checked={checked}
          onChange={() => selectionMode?.onToggle(key)}
          className="h-4 w-4 cursor-pointer accent-brand"
        />
      );
    },
  };

  const baseColumns: ColumnDef<Transaction>[] = [
    {
      accessorKey: "date",
      header: sortHeader("Date", "date"),
      cell: ({ row }) => (
        <span className="text-muted-foreground whitespace-nowrap text-xs">
          {formatDate(row.original.date, dateFormat)}
        </span>
      ),
    },
    {
      accessorKey: "company",
      header: sortHeader("Merchant", "company"),
      cell: ({ row }) => (
        <div>
          <span className="font-medium">
            {row.original.company ? (
              titleCase(row.original.company)
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
            {row.original.statement_source && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <FileText className="inline h-3.5 w-3.5 text-muted-foreground ml-1" />
                </TooltipTrigger>
                <TooltipContent>From statement</TooltipContent>
              </Tooltip>
            )}
            {row.original.extraction_audit && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Sparkles className="inline h-3.5 w-3.5 text-muted-foreground ml-1" />
                </TooltipTrigger>
                <TooltipContent>Recovered by AI</TooltipContent>
              </Tooltip>
            )}
          </span>
          {row.original.comment && (
            <p className="text-xs text-muted-foreground truncate max-w-[200px]">
              {row.original.comment}
            </p>
          )}
        </div>
      ),
    },
    {
      accessorKey: "amount",
      header: sortHeader("Amount", "amount", "right"),
      cell: ({ row }) => (
        <span
          className={cn(
            "text-right block whitespace-nowrap tabular-nums text-sm font-semibold",
            row.original.ignored && "line-through"
          )}
        >
          {formatCurrency(row.original.amount)}
        </span>
      ),
    },
    {
      accessorKey: "category",
      header: sortHeader("Category", "category"),
      cell: ({ row }) => {
        const txn = row.original;
        return (
          <CategoryCell
            txn={txn}
            edited={isEdited(makeKey(txn.forwarded_to, txn.date_file_name))}
            onCategoryChange={(cat) => handleCategoryChange(txn, cat)}
            onConfirm={onConfirm ? () => onConfirm(txn) : undefined}
            onToggleIgnore={() =>
              ignoreMutation.mutate({
                forwardedTo: txn.forwarded_to,
                dateFileName: txn.date_file_name,
                ignored: !txn.ignored,
              })
            }
            onDelete={() =>
              deleteMutation.mutate({
                forwardedTo: txn.forwarded_to,
                dateFileName: txn.date_file_name,
              })
            }
            onEmailPreview={onEmailPreview ? () => onEmailPreview(txn) : undefined}
          />
        );
      },
    },
    {
      accessorKey: "institution",
      header: sortHeader("Institution", "institution"),
      cell: ({ row }) => (
        <span className="text-muted-foreground text-xs">{row.original.institution || "—"}</span>
      ),
    },
    {
      accessorKey: "transaction_type",
      header: sortHeader("Type", "type"),
      cell: ({ row }) => (
        <span className="text-muted-foreground text-xs">
          {row.original.transaction_type || "—"}
        </span>
      ),
    },
  ];

  const columns = selectionMode ? [selectionColumn, ...baseColumns] : baseColumns;

  // TanStack Table returns unmemoizable functions by design; React Compiler's skip is expected here.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: transactions,
    columns,
    getCoreRowModel: getCoreRowModel(),
    // Identity by txn key (not row index) so a month change remounts rows —
    // resetting each row's lazy-reveal state (see TxnRow) instead of carrying a
    // previous month's revealed cluster into the same position.
    getRowId: (t) => makeKey(t.forwarded_to, t.date_file_name),
  });

  const rows = table.getRowModel().rows;
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 48,
    overscan: 8,
  });

  const renderRows = () => {
    if (!rows.length) {
      return (
        <TableRow>
          <TableCell colSpan={columns.length} className="h-24 text-center text-fg-muted">
            {emptyMessage}
          </TableCell>
        </TableRow>
      );
    }
    if (!virtualize) {
      return rows.map((row) => <TxnRow key={row.id} row={row} />);
    }

    const virtualRows = virtualizer.getVirtualItems();
    const totalSize = virtualizer.getTotalSize();
    const paddingTop = virtualRows[0]?.start ?? 0;
    const paddingBottom = totalSize - (virtualRows[virtualRows.length - 1]?.end ?? 0);

    return (
      <>
        {paddingTop > 0 && (
          <tr aria-hidden="true">
            <td colSpan={columns.length} style={{ height: paddingTop, padding: 0, border: 0 }} />
          </tr>
        )}
        {virtualRows.map((vr) => {
          const row = rows[vr.index];
          if (!row) return null;
          return <TxnRow key={row.id} row={row} />;
        })}
        {paddingBottom > 0 && (
          <tr aria-hidden="true">
            <td colSpan={columns.length} style={{ height: paddingBottom, padding: 0, border: 0 }} />
          </tr>
        )}
      </>
    );
  };

  const containerClass = virtualize
    ? "rounded-xl border border-border/50 max-h-[70vh] overflow-auto"
    : "rounded-xl border border-border/50";

  return (
    <div ref={scrollRef} className={containerClass}>
      <Table>
        {showHeader && (
          <TableHeader className={virtualize ? "sticky top-0 z-10 bg-background" : undefined}>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
        )}
        <TableBody>{renderRows()}</TableBody>
      </Table>
    </div>
  );
}

// Memoized so a page's *urgent* render (e.g. the Transactions two-state month
// flip) can skip the whole table when its props are unchanged. Only pays off
// when callers pass referentially stable props (see TransactionsPage).
export const TransactionTable = memo(TransactionTableImpl);
