import { Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { CategoryPicker } from "@/components/CategoryPicker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAddTransaction } from "@/hooks/useAddTransaction";
import { isDemoMode } from "@/hooks/useDemoMode";
import { useResolveParseFailure } from "@/hooks/useResolveParseFailure";
import { DEMO_TODAY } from "@/lib/demoConstants";
import type { TransactionType } from "@/types/api";

interface ResolveFailureContext {
  /** Quarantined row id this entry resolves. */
  id: string;
  /** Bank detected for the unreadable email; prefilled onto the transaction. */
  institution: string | null;
  /** Raw email body, shown read-only so the user can transcribe the values. */
  emailBody: string;
  /** The email body is still being fetched. Show a loading state rather than the
   *  "nothing stored" fallback, which would otherwise flash on the common path
   *  (open the dialog before the detail request returns). */
  emailLoading?: boolean;
}

interface AddTransactionDialogProps {
  /** Controlled open state. When provided, the default "Add" trigger button is
   *  not rendered and the caller drives open/close — the "Needs review"
   *  deep-link uses this. Omit for the standalone trigger-button variant. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** When set, the dialog records a hand-entered transaction for an email the
   *  parsers couldn't read and resolves the row in one call. It prefills the
   *  detected institution, shows the email body read-only, and requires a
   *  category: a hand-typed row carries no extraction audit, so it never reaches
   *  the review queue — an omitted category would become a permanent silent
   *  miscellaneous with no follow-up. */
  resolveFailure?: ResolveFailureContext;
}

export function AddTransactionDialog({
  open,
  onOpenChange,
  resolveFailure,
}: AddTransactionDialogProps = {}) {
  const isControlled = open !== undefined;
  const [internalOpen, setInternalOpen] = useState(false);
  const dialogOpen = isControlled ? open : internalOpen;
  const setOpen = (next: boolean) => {
    if (isControlled) onOpenChange?.(next);
    else setInternalOpen(next);
  };

  const isResolve = !!resolveFailure;

  // Demo entries default to the demo world's "today", not the visitor's.
  const [date, setDate] = useState(() =>
    isDemoMode() ? DEMO_TODAY : new Date().toISOString().split("T")[0]
  );
  const [amount, setAmount] = useState("");
  const [company, setCompany] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [transactionType, setTransactionType] = useState<TransactionType>("purchase");

  const addMutation = useAddTransaction();
  const resolveMutation = useResolveParseFailure();
  const mutation = isResolve ? resolveMutation : addMutation;

  const reset = () => {
    setAmount("");
    setCompany("");
    setCategory(null);
    setTransactionType("purchase");
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const amt = parseFloat(amount);
    if (!amt || !company.trim() || !date) return;
    // Resolve requires a category — see the resolveFailure prop comment.
    if (isResolve && !category) return;

    const onSuccess = () => {
      setOpen(false);
      reset();
    };

    if (resolveFailure) {
      resolveMutation.mutate(
        {
          id: resolveFailure.id,
          body: {
            date,
            amount: amt,
            company: company.trim(),
            // Required at submit (button gated on it), so this is never null in
            // practice — `?? null` only satisfies the optional-field type.
            category: category ?? null,
            transaction_type: transactionType,
            institution: resolveFailure.institution,
          },
        },
        { onSuccess }
      );
    } else {
      addMutation.mutate(
        {
          date,
          amount: amt,
          company: company.trim(),
          category: category || undefined,
          transaction_type: transactionType,
        },
        { onSuccess }
      );
    }
  };

  const submitDisabled =
    mutation.isPending || !amount || !company.trim() || (isResolve && !category);

  return (
    <Dialog open={dialogOpen} onOpenChange={setOpen}>
      {!isControlled && (
        <DialogTrigger asChild>
          <button
            className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-accent transition-colors"
            title="Add transaction"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </DialogTrigger>
      )}
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isResolve ? "Enter this transaction" : "Add Transaction"}</DialogTitle>
          {isResolve && (
            <DialogDescription>
              This email couldn't be read — add the details to keep it in your records.
            </DialogDescription>
          )}
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {resolveFailure && (
            <div className="space-y-1.5">
              <span className="text-sm font-medium">Email</span>
              {resolveFailure.emailLoading ? (
                <div className="flex items-center gap-2 rounded-md border border-border bg-surface-muted/50 p-3 text-xs text-fg-muted">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading email…
                </div>
              ) : (
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-surface-muted/50 p-3 font-mono text-xs text-fg-secondary">
                  {resolveFailure.emailBody || "No email body was stored."}
                </pre>
              )}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="add-txn-date" className="text-sm font-medium">
                Date
              </label>
              <Input
                id="add-txn-date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="add-txn-amount" className="text-sm font-medium">
                Amount
              </label>
              <Input
                id="add-txn-amount"
                type="number"
                step="0.01"
                min="0.01"
                placeholder="0.00"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="add-txn-company" className="text-sm font-medium">
              Company
            </label>
            <Input
              id="add-txn-company"
              placeholder="Merchant name"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              required
            />
          </div>
          {isResolve ? (
            // A hand-typed row has no attention-queue safety net, so the category
            // is a prominent, required full-width field — not a tucked-away
            // "optional" slot beside the type.
            <>
              <div className="space-y-1.5">
                <label htmlFor="add-txn-category" className="text-sm font-medium">
                  Category
                </label>
                <CategoryPicker value={category} onSelect={setCategory} />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="add-txn-type" className="text-sm font-medium">
                  Type
                </label>
                <select
                  id="add-txn-type"
                  value={transactionType}
                  onChange={(e) => setTransactionType(e.target.value as TransactionType)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                >
                  <option value="purchase">Purchase</option>
                  <option value="withdrawal">Withdrawal</option>
                  <option value="e-transfer">E-Transfer</option>
                  <option value="deposit">Deposit</option>
                </select>
              </div>
            </>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="add-txn-category" className="text-sm font-medium">
                  Category
                </label>
                <CategoryPicker value={category} onSelect={setCategory} />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="add-txn-type" className="text-sm font-medium">
                  Type
                </label>
                <select
                  id="add-txn-type"
                  value={transactionType}
                  onChange={(e) => setTransactionType(e.target.value as TransactionType)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                >
                  <option value="purchase">Purchase</option>
                  <option value="withdrawal">Withdrawal</option>
                  <option value="e-transfer">E-Transfer</option>
                  <option value="deposit">Deposit</option>
                </select>
              </div>
            </div>
          )}
          {/* The resolve variant surfaces errors through the hook's toast (calm,
           *  specific copy), so don't also render the raw backend message inline
           *  — two conflicting strings at once. The add variant has no toast, so
           *  it keeps the inline message. */}
          {!isResolve && mutation.isError && (
            <p className="text-sm text-destructive">{(mutation.error as Error).message}</p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-lg border px-4 py-2 text-sm hover:bg-accent transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitDisabled}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {isResolve
                ? mutation.isPending
                  ? "Adding…"
                  : "Add transaction"
                : mutation.isPending
                  ? "Adding..."
                  : "Add Transaction"}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
