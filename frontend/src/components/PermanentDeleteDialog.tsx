import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatCurrency, formatDate } from "@/lib/format";
import type { Transaction } from "@/types/api";

interface PermanentDeleteDialogProps {
  transaction: Transaction | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  isPending: boolean;
}

export function PermanentDeleteDialog({
  transaction,
  open,
  onOpenChange,
  onConfirm,
  isPending,
}: PermanentDeleteDialogProps) {
  if (!transaction) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Permanently delete transaction?</DialogTitle>
          <DialogDescription>
            This action cannot be undone. The transaction will be permanently removed.
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-md border p-3 text-sm space-y-1">
          <div className="font-medium">{transaction.company || "Unknown"}</div>
          <div className="text-muted-foreground">{formatDate(transaction.date)}</div>
          <div className="font-mono">{formatCurrency(transaction.amount)}</div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={isPending}>
            {isPending ? "Deleting..." : "Delete Forever"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
