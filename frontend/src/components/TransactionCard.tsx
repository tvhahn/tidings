import {
  CheckCircle2,
  EyeOff,
  FileText,
  Mail,
  MoreHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { createElement, memo, useState } from "react";
import { toast } from "sonner";
import { CategoryPicker } from "@/components/CategoryPicker";
import { CommentPopover } from "@/components/CommentPopover";
import { RowAttachmentAction } from "@/components/RowAttachmentAction";
import { TaxFlagMenu } from "@/components/TaxFlagMenu";
import { TransactionEditPopover } from "@/components/TransactionEditPopover";
import { Card, CardContent } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { useCategoryIcons } from "@/hooks/useCategoryManagement";
import { useIgnoreTransaction } from "@/hooks/useIgnoreTransaction";
import { useSoftDelete } from "@/hooks/useSoftDelete";
import { useUpdateCategory } from "@/hooks/useUpdateCategory";
import { iconForCategory } from "@/lib/categoryIcons";
import { formatCurrency, formatDate, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEditedTransactions, makeKey } from "@/stores/editedTransactions";
import { usePreferences } from "@/stores/preferences";
import type { Transaction } from "@/types/api";

interface TransactionCardProps {
  transaction: Transaction;
  onConfirm?: ((txn: Transaction) => void) | undefined;
  onEmailPreview?: ((txn: Transaction) => void) | undefined;
}

function TransactionCardImpl({
  transaction: txn,
  onConfirm,
  onEmailPreview,
}: TransactionCardProps) {
  const updateCategory = useUpdateCategory();
  const ignoreMutation = useIgnoreTransaction();
  const deleteMutation = useSoftDelete();
  const isEdited = useEditedTransactions((s) => s.isEdited);
  const undo = useEditedTransactions((s) => s.undo);
  const dateFormat = usePreferences((s) => s.dateFormat);
  const key = makeKey(txn.forwarded_to, txn.date_file_name);
  const needsAttention = txn.category?.toLowerCase() === "miscellaneous" && !txn.category_audit;
  const [menuOpen, setMenuOpen] = useState(false);

  const { data: iconsData } = useCategoryIcons();
  const categoryIcon = iconForCategory(txn.category, iconsData?.icons);
  const categoryIconEl = createElement(categoryIcon, {
    className: "h-4 w-4",
    "aria-hidden": true,
  });

  const handleCategoryChange = (newCategory: string) => {
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
                const old = undo(key);
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

  const actionCluster = (
    <>
      {onConfirm && needsAttention && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              aria-label="Confirm category"
              onClick={() => {
                setMenuOpen(false);
                onConfirm(txn);
              }}
              className="rounded p-1 text-muted-foreground hover:text-status-success hover:bg-status-success/10 transition-colors"
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
            onClick={() => {
              setMenuOpen(false);
              ignoreMutation.mutate({
                forwardedTo: txn.forwarded_to,
                dateFileName: txn.date_file_name,
                ignored: !txn.ignored,
              });
            }}
            className={cn(
              "rounded p-1 transition-colors",
              txn.ignored
                ? "text-muted-foreground hover:text-foreground"
                : "text-muted-foreground hover:text-status-warning hover:bg-status-warning/10"
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
      <RowAttachmentAction txn={txn} size="md" onActivate={() => setMenuOpen(false)} />
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
              onClick={() => {
                setMenuOpen(false);
                onEmailPreview(txn);
              }}
              className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
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
            onClick={() => {
              setMenuOpen(false);
              deleteMutation.mutate({
                forwardedTo: txn.forwarded_to,
                dateFileName: txn.date_file_name,
              });
            }}
            className="rounded p-1 text-muted-foreground hover:text-status-danger hover:bg-status-danger/10 transition-colors"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Delete transaction</TooltipContent>
      </Tooltip>
      <TaxFlagMenu txn={txn} size="md" />
    </>
  );

  const meta = [txn.institution, txn.transaction_type].filter(Boolean).join(" · ");

  return (
    <Card className={cn("cv-auto-row border-border/50", txn.ignored && "opacity-40")}>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 min-w-0">
          <span className="shrink-0 flex h-8 w-8 items-center justify-center rounded-full bg-muted text-muted-foreground">
            {categoryIconEl}
          </span>
          <span className="font-medium text-sm truncate flex-1 min-w-0">
            {txn.company ? (
              titleCase(txn.company)
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
            {txn.statement_source && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <FileText className="inline h-3.5 w-3.5 text-muted-foreground ml-1" />
                </TooltipTrigger>
                <TooltipContent>From statement</TooltipContent>
              </Tooltip>
            )}
            {txn.extraction_audit && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Sparkles className="inline h-3.5 w-3.5 text-muted-foreground ml-1" />
                </TooltipTrigger>
                <TooltipContent>Recovered by AI</TooltipContent>
              </Tooltip>
            )}
          </span>
          <span
            className={cn(
              "shrink-0 font-semibold tabular-nums text-sm",
              txn.ignored && "line-through"
            )}
          >
            {formatCurrency(txn.amount)}
          </span>
          <Popover open={menuOpen} onOpenChange={setMenuOpen}>
            <PopoverTrigger asChild>
              <button
                aria-label="Transaction actions"
                className="shrink-0 rounded p-1 text-muted-foreground/60 hover:text-foreground hover:bg-muted transition-colors"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto p-1.5">
              <div className="flex items-center gap-0.5">{actionCluster}</div>
            </PopoverContent>
          </Popover>
        </div>
        <div className="mt-1.5 flex items-center flex-wrap gap-x-2 gap-y-1 pl-10">
          <span className="text-xs text-muted-foreground tabular-nums">
            {formatDate(txn.date, dateFormat)}
          </span>
          <CategoryPicker
            variant="inline"
            value={txn.category ? titleCase(txn.category) : null}
            onSelect={handleCategoryChange}
            edited={isEdited(key)}
            needsAttention={needsAttention}
            merchant={txn.company}
          />
          {meta && <span className="text-xs text-muted-foreground">{meta}</span>}
        </div>
        {txn.comment && (
          <p className="mt-1 pl-10 text-xs text-muted-foreground line-clamp-1">{txn.comment}</p>
        )}
      </CardContent>
    </Card>
  );
}

export const TransactionCard = memo(TransactionCardImpl);
