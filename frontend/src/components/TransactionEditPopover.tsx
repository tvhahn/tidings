import { Pencil } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useUpdateTransactionFields } from "@/hooks/useUpdateTransactionFields";

const TRANSACTION_TYPES = ["purchase", "withdrawal", "preauth", "e-transfer", "deposit"] as const;

interface TransactionEditPopoverProps {
  forwardedTo: string;
  dateFileName: string;
  company: string | null;
  amount: number | null;
  transactionType: string | null;
}

export function TransactionEditPopover({
  forwardedTo,
  dateFileName,
  company,
  amount,
  transactionType,
}: TransactionEditPopoverProps) {
  const [open, setOpen] = useState(false);
  const [draftCompany, setDraftCompany] = useState(company ?? "");
  const [draftAmount, setDraftAmount] = useState(amount?.toString() ?? "");
  const [draftType, setDraftType] = useState(transactionType ?? "");
  const companyRef = useRef<HTMLInputElement>(null);
  const mutation = useUpdateTransactionFields();

  useEffect(() => {
    if (open) {
      setDraftCompany(company ?? "");
      setDraftAmount(amount?.toString() ?? "");
      setDraftType(transactionType ?? "");
      requestAnimationFrame(() => companyRef.current?.focus());
    }
  }, [open, company, amount, transactionType]);

  const isDirty =
    draftCompany !== (company ?? "") ||
    draftAmount !== (amount?.toString() ?? "") ||
    draftType !== (transactionType ?? "");

  const handleSave = () => {
    const fields: { company?: string; amount?: number; transaction_type?: string } = {};

    const trimmedCompany = draftCompany.trim();
    if (trimmedCompany && trimmedCompany !== (company ?? "")) {
      fields.company = trimmedCompany;
    }

    const parsedAmount = parseFloat(draftAmount);
    if (!isNaN(parsedAmount) && parsedAmount > 0 && parsedAmount !== amount) {
      fields.amount = parsedAmount;
    }

    if (draftType && draftType !== (transactionType ?? "")) {
      fields.transaction_type = draftType;
    }

    if (Object.keys(fields).length === 0) return;

    mutation.mutate({ forwardedTo, dateFileName, fields });
    setOpen(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (isDirty) handleSave();
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <button
              aria-label="Edit details"
              className="rounded p-0.5 text-muted-foreground transition-colors hover:text-status-info hover:bg-status-info/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
            >
              <Pencil className="h-4 w-4" />
            </button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>Edit details</TooltipContent>
      </Tooltip>
      <PopoverContent className="w-72 p-3" align="start" onKeyDown={handleKeyDown}>
        <div className="space-y-3">
          <div>
            <label htmlFor="txn-edit-company" className="text-xs font-medium text-muted-foreground">
              Company
            </label>
            <Input
              id="txn-edit-company"
              ref={companyRef}
              value={draftCompany}
              onChange={(e) => setDraftCompany(e.target.value)}
              placeholder="Company name"
              className="mt-1 h-8 text-sm"
            />
          </div>
          <div>
            <label htmlFor="txn-edit-amount" className="text-xs font-medium text-muted-foreground">
              Amount
            </label>
            <div className="relative mt-1">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                $
              </span>
              <Input
                id="txn-edit-amount"
                type="number"
                step="0.01"
                min="0.01"
                value={draftAmount}
                onChange={(e) => setDraftAmount(e.target.value)}
                placeholder="0.00"
                className="h-8 pl-7 text-sm"
              />
            </div>
          </div>
          <div>
            <label htmlFor="txn-edit-type" className="text-xs font-medium text-muted-foreground">
              Type
            </label>
            <Select value={draftType} onValueChange={setDraftType}>
              <SelectTrigger className="mt-1 h-8 text-sm">
                <SelectValue placeholder="Select type" />
              </SelectTrigger>
              <SelectContent>
                {TRANSACTION_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Ctrl+Enter to save</span>
          <Button size="sm" onClick={handleSave} disabled={!isDirty}>
            Save
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
