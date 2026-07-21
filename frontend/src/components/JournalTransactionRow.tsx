import { CheckCircle2, EyeOff, Mail, MoreHorizontal, Trash2 } from "lucide-react";
import { memo, useState } from "react";
import { toast } from "sonner";
import { CategoryPicker } from "@/components/CategoryPicker";
import { CommentPopover } from "@/components/CommentPopover";
import { EmailPreviewDialog } from "@/components/EmailPreviewDialog";
import { EnrichmentBadges } from "@/components/EnrichmentBadges";
import { IconSlot } from "@/components/IconSlot";
import { RowAttachmentAction } from "@/components/RowAttachmentAction";
import { TaxFlagMenu } from "@/components/TaxFlagMenu";
import { TransactionEditPopover } from "@/components/TransactionEditPopover";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCategoryIcons } from "@/hooks/useCategoryManagement";
import { useIgnoreTransaction } from "@/hooks/useIgnoreTransaction";
import { useMarkReviewed } from "@/hooks/useMarkReviewed";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useSoftDelete } from "@/hooks/useSoftDelete";
import { useUpdateCategory } from "@/hooks/useUpdateCategory";
import { iconForCategory } from "@/lib/categoryIcons";
import { formatCurrency, titleCase } from "@/lib/format";
import { cleanMerchantName } from "@/lib/merchantDisplay";
import { cn } from "@/lib/utils";
import { makeKey, useEditedTransactions } from "@/stores/editedTransactions";
import type { Transaction } from "@/types/api";

/** Provenance tooltip for a cleaned merchant name — shows the raw parsed
 *  string. Styled as a light popover card (bg-popover + border + shadow, like
 *  PopoverContent) rather than the default inverse-video tooltip: this is a
 *  small data readout, not an action label. */
function MerchantProvenanceTooltip({ company }: { company: string | null }) {
  return (
    <TooltipContent className="max-w-xs rounded-lg border border-border bg-popover px-3 py-2 text-popover-foreground shadow-md">
      <div className="font-mono text-xs break-all text-fg-2">{company}</div>
      <div className="mt-1 text-[11px] text-fg-muted">as parsed from the email</div>
    </TooltipContent>
  );
}

interface Props {
  transaction: Transaction;
  /** First transaction of the first day on /journal. Keeps this row's action
   *  cluster mounted at rest and tags the Mail icon, category pill, and note
   *  with `data-tour` anchors so the demo tour can spotlight them. */
  anchorsDemoTour?: boolean | undefined;
}

function JournalTransactionRowImpl({ transaction: txn, anchorsDemoTour }: Props) {
  const { amount, company, category, context } = txn;
  const updateCategory = useUpdateCategory();
  const ignoreMutation = useIgnoreTransaction();
  const deleteMutation = useSoftDelete();
  const reviewMutation = useMarkReviewed();
  const isEdited = useEditedTransactions((s) => s.isEdited);
  const undo = useEditedTransactions((s) => s.undo);
  const key = makeKey(txn.forwarded_to, txn.date_file_name);
  const needsAttention = txn.category?.toLowerCase() === "miscellaneous" && !txn.category_audit;

  const [emailOpen, setEmailOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Render one layout at a time behind a JS breakpoint instead of shipping both
  // `hidden lg:flex` + `lg:hidden` trees — halves nodes/row. (1024px ≈ the lg
  // breakpoint the fixed-width desktop columns need.)
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  // Lazy-mount the desktop hover cluster on first hover/focus so a month change
  // renders fresh (un-hovered) rows without the ~dozen Radix nodes each. Once
  // mounted it keeps its group-hover visibility, so behavior is unchanged. The
  // first demo row starts revealed so its data-tour anchor exists at load.
  const [revealed, setRevealed] = useState(!!anchorsDemoTour);
  const reveal = () => setRevealed(true);

  const { data: iconsData } = useCategoryIcons();
  const categoryIcon = iconForCategory(category, iconsData?.icons);

  // Display-layer merchant cleanup: rows show a tidied name; hovering reveals
  // the raw parsed string. Stored data is never touched. `titleCase` is applied
  // on top of the cleaned string (cleanMerchantName never title-cases).
  const cleaned = company ? cleanMerchantName(company) : null;
  const merchantLabel = cleaned ? titleCase(cleaned) : null;
  const merchantWasCleaned =
    !!company && !!cleaned && cleaned.trim().toLowerCase() !== company.trim().toLowerCase();

  const handleCategoryChange = (newCategory: string) => {
    const oldCategory = category || "miscellaneous";
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

  const handleConfirm = () =>
    reviewMutation.mutate({ forwardedTo: txn.forwarded_to, dateFileName: txn.date_file_name });
  const handleIgnoreToggle = () =>
    ignoreMutation.mutate({
      forwardedTo: txn.forwarded_to,
      dateFileName: txn.date_file_name,
      ignored: !txn.ignored,
    });
  const handleDelete = () =>
    deleteMutation.mutate({ forwardedTo: txn.forwarded_to, dateFileName: txn.date_file_name });
  const openEmail = () => {
    setMenuOpen(false);
    setEmailOpen(true);
  };

  // Tour anchor for the "notes" step. Pin it to the first row's *visible*
  // marginalia note (rendered below, seeded in the demo fixture) — never the
  // hover-cluster icon, which is opacity-0 at rest and would spotlight an
  // invisible target. Gating on anchorsDemoTour keeps it on the one
  // always-mounted row so the spotlight is deterministic.
  const commentTourAnchor = anchorsDemoTour && txn.comment ? "comment-action" : undefined;
  const mailTourAnchor = anchorsDemoTour ? "email-origin" : undefined;
  const categoryTourAnchor = anchorsDemoTour ? "category-pill" : undefined;

  // One shared cluster of action icons. On desktop it lives before the amount
  // and only appears on row hover/focus; on mobile it's the payload of the
  // kebab popover. Keeping a single definition means the two surfaces never
  // drift.
  const renderCluster = () => (
    <>
      {needsAttention && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              aria-label="Confirm category"
              onClick={handleConfirm}
              className="rounded p-0.5 text-muted-foreground hover:text-status-success hover:bg-status-success/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
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
            onClick={handleIgnoreToggle}
            className={cn(
              "rounded p-0.5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong",
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
      <RowAttachmentAction txn={txn} />
      <TransactionEditPopover
        forwardedTo={txn.forwarded_to}
        dateFileName={txn.date_file_name}
        company={txn.company}
        amount={txn.amount}
        transactionType={txn.transaction_type}
      />
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            aria-label="View original email"
            onClick={openEmail}
            data-tour={mailTourAnchor}
            className="rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
          >
            <Mail className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent>View original email</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            aria-label="Delete transaction"
            onClick={handleDelete}
            className="rounded p-0.5 text-muted-foreground hover:text-status-danger hover:bg-status-danger/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Delete transaction</TooltipContent>
      </Tooltip>
      <TaxFlagMenu txn={txn} />
    </>
  );

  const amountSpan = (
    <span
      className={cn("font-semibold tabular-nums text-sm shrink-0", txn.ignored && "line-through")}
    >
      {formatCurrency(amount)}
    </span>
  );

  const categoryPicker = (
    <CategoryPicker
      variant="inline"
      value={titleCase(category)}
      onSelect={handleCategoryChange}
      edited={isEdited(key)}
      tourAnchor={categoryTourAnchor}
      merchant={company}
    />
  );

  return (
    <div
      className={cn("group py-3 px-1", txn.ignored && "opacity-50")}
      onMouseEnter={isDesktop ? reveal : undefined}
      onFocusCapture={isDesktop ? reveal : undefined}
    >
      {isDesktop ? (
        /* Desktop: single-line ledger row — icon, merchant, category, chips, hover cluster, amount.
           Fixed-width columns need ~1024px to coexist with the merchant name; below that the
           two-line mobile layout renders instead (one layout at a time, not both CSS-hidden). */
        <div className="flex items-center gap-3 min-w-0">
          <IconSlot icon={categoryIcon} />
          {/* Always render the merchant slot so the category column lines up even
              on rows with no company — with a muted fallback so the row never
              shows a nameless blank cell. */}
          {merchantWasCleaned ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className={cn(
                    "text-sm truncate shrink-0 w-56",
                    company ? "font-medium" : "font-normal text-fg-muted"
                  )}
                >
                  {merchantLabel ?? "Unknown merchant"}
                </span>
              </TooltipTrigger>
              <MerchantProvenanceTooltip company={company} />
            </Tooltip>
          ) : (
            <span
              className={cn(
                "text-sm truncate shrink-0 w-56",
                company ? "font-medium" : "font-normal text-fg-muted"
              )}
            >
              {merchantLabel ?? "Unknown merchant"}
            </span>
          )}
          <div className="shrink-0 w-48">{categoryPicker}</div>
          <EnrichmentBadges context={context} category={category} />
          <div className="flex-1" />
          {/* Lazy-mounted on first hover/focus (see `revealed`); group-hover still
              governs visibility so un-hovered rows carry none of these nodes.
              pointer-coarse: Tailwind gates group-hover behind (hover: hover),
              so touch devices wide enough for this layout (iPad landscape)
              would otherwise get invisible-but-tappable buttons — including
              Delete. Show the cluster at rest there instead. */}
          {revealed && (
            <div className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100 [.tour-active_&]:opacity-100 transition-opacity">
              {renderCluster()}
            </div>
          )}
          {amountSpan}
        </div>
      ) : (
        /* Mobile / small-desktop: two lines — line 1: icon, merchant, amount, kebab; line 2: chips */
        <div>
          <div className="flex items-center gap-2 min-w-0">
            <IconSlot icon={categoryIcon} />
            {merchantWasCleaned ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span
                    className={cn(
                      "text-sm truncate flex-1 min-w-0",
                      company ? "font-medium" : "font-normal text-fg-muted"
                    )}
                  >
                    {merchantLabel ?? "Unknown merchant"}
                  </span>
                </TooltipTrigger>
                <MerchantProvenanceTooltip company={company} />
              </Tooltip>
            ) : (
              <span
                className={cn(
                  "text-sm truncate flex-1 min-w-0",
                  company ? "font-medium" : "font-normal text-fg-muted"
                )}
              >
                {merchantLabel ?? "Unknown merchant"}
              </span>
            )}
            {amountSpan}
            <Popover open={menuOpen} onOpenChange={setMenuOpen}>
              <PopoverTrigger asChild>
                <button
                  aria-label="Transaction actions"
                  className="shrink-0 rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-border-strong"
                >
                  <MoreHorizontal className="h-4 w-4" />
                </button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-auto p-1.5">
                <div className="flex items-center gap-0.5">{renderCluster()}</div>
              </PopoverContent>
            </Popover>
          </div>
          <div className="mt-1.5 flex items-center flex-wrap gap-x-2 gap-y-1 pl-10">
            {categoryPicker}
            <EnrichmentBadges context={context} category={category} />
          </div>
        </div>
      )}

      {/* Marginalia: when a note exists, render it inline under the row
          so users can read it at rest. Clicking the line opens the same
          popover as the hover-cluster icon. */}
      {txn.comment && (
        <div className="mt-1 pl-10">
          <CommentPopover
            forwardedTo={txn.forwarded_to}
            dateFileName={txn.date_file_name}
            comment={txn.comment}
            variant="marginalia"
            tourAnchor={commentTourAnchor}
          />
        </div>
      )}

      <EmailPreviewDialog transaction={txn} open={emailOpen} onOpenChange={setEmailOpen} />
    </div>
  );
}

export const JournalTransactionRow = memo(JournalTransactionRowImpl);
