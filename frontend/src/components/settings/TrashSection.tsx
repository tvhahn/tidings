import { RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { MonthPicker } from "@/components/MonthPicker";
import { PermanentDeleteDialog } from "@/components/PermanentDeleteDialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePermanentDelete } from "@/hooks/usePermanentDelete";
import { useRestoreTransaction } from "@/hooks/useRestoreTransaction";
import { useTrash } from "@/hooks/useTrash";
import { formatCurrency, formatDate, currentMonth } from "@/lib/format";
import type { Transaction } from "@/types/api";

export function TrashSection() {
  const [month, setMonth] = useState(() => currentMonth());
  const { data: trashData, isLoading: trashLoading } = useTrash(month);
  const restoreMutation = useRestoreTransaction();
  const permanentDeleteMutation = usePermanentDelete();

  const [deleteTarget, setDeleteTarget] = useState<Transaction | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const trashItems = trashData?.transactions ?? [];

  const handlePermanentDelete = () => {
    if (!deleteTarget) return;
    permanentDeleteMutation.mutate(
      {
        forwardedTo: deleteTarget.forwarded_to,
        dateFileName: deleteTarget.date_file_name,
      },
      {
        onSuccess: () => {
          setDeleteDialogOpen(false);
          setDeleteTarget(null);
        },
      }
    );
  };

  return (
    <>
      <section className="space-y-4">
        <div className="flex justify-end">
          <MonthPicker month={month} onChange={setMonth} />
        </div>

        {trashLoading && (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        )}

        {!trashLoading && trashItems.length === 0 && (
          <p className="py-8 text-center text-muted-foreground">No deleted transactions</p>
        )}

        {!trashLoading && trashItems.length > 0 && (
          <div className="rounded-xl border border-border/50">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trashItems.map((txn) => (
                  <TableRow key={`${txn.forwarded_to}|${txn.date_file_name}`}>
                    <TableCell>
                      <span className="text-muted-foreground whitespace-nowrap text-xs">
                        {formatDate(txn.date)}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="font-medium">{txn.company || "—"}</span>
                    </TableCell>
                    <TableCell>
                      <span className="text-right block whitespace-nowrap font-mono text-sm">
                        {formatCurrency(txn.amount)}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-muted-foreground text-xs">{txn.category || "—"}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() =>
                            restoreMutation.mutate({
                              forwardedTo: txn.forwarded_to,
                              dateFileName: txn.date_file_name,
                            })
                          }
                          className="rounded p-0.5 text-muted-foreground hover:text-status-success hover:bg-status-success/10 transition-colors"
                          title="Restore transaction"
                        >
                          <RotateCcw className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            setDeleteTarget(txn);
                            setDeleteDialogOpen(true);
                          }}
                          className="rounded p-0.5 text-muted-foreground hover:text-status-danger hover:bg-status-danger/10 transition-colors"
                          title="Permanently delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <PermanentDeleteDialog
        transaction={deleteTarget}
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onConfirm={handlePermanentDelete}
        isPending={permanentDeleteMutation.isPending}
      />
    </>
  );
}
