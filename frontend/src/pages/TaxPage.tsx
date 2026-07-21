import { ChevronDown, ChevronRight, Download, Mail, Paperclip, Receipt, X } from "lucide-react";
import { useCallback, useState, type KeyboardEvent } from "react";
import { toast } from "sonner";
import { AttachmentCaptureDialog } from "@/components/AttachmentCaptureDialog";
import { AttachmentViewDialog } from "@/components/AttachmentViewDialog";
import { EmailPreviewDialog } from "@/components/EmailPreviewDialog";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { YearPicker } from "@/components/YearPicker";
import { useClearTaxOverride } from "@/hooks/useClearTaxOverride";
import { useSetTaxOverride } from "@/hooks/useSetTaxOverride";
import { useTaxPack } from "@/hooks/useTaxPack";
import { useTransactionAttachments } from "@/hooks/useTransactionAttachments";
import { downloadTaxPack } from "@/lib/api";
import { currentYear, formatCurrency } from "@/lib/format";
import type { TaxLineResponse, TaxPackTransaction } from "@/types/api";

// Verbatim from the spec (L12) — the one calm sentence the page carries.
const TAX_DISCLAIMER = "Tidings organizes your records; it doesn't give tax advice.";

function formatIsoDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// receipt | email | statement — rendered verbatim, sentence case.
function evidenceLabel(evidence: string): string {
  return evidence.charAt(0).toUpperCase() + evidence.slice(1);
}

function handleRowKey(cb: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      cb();
    }
  };
}

export function TaxPage() {
  const [year, setYear] = useState(currentYear());
  const { data, isLoading } = useTaxPack(year);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [attachTxId, setAttachTxId] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const toggle = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const onDownload = async () => {
    setDownloading(true);
    try {
      await downloadTaxPack(year);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Tax pack export failed.");
    } finally {
      setDownloading(false);
    }
  };

  const actions = (
    <>
      <YearPicker year={year} onChange={setYear} />
      <Button
        variant="outline"
        size="sm"
        onClick={onDownload}
        disabled={downloading || !data}
        className="gap-2"
      >
        <Download className="h-4 w-4" />
        Download tax pack
      </Button>
    </>
  );

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-9 w-32" />
        </div>
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-4">
        <PageHeader title="Tax receipts" actions={actions} />
        <p className="text-fg-muted">No claimable records for {year}.</p>
        <p className="text-xs text-fg-muted">{TAX_DISCLAIMER}</p>
      </div>
    );
  }

  const totalTransactions = data.lines.reduce((sum, l) => sum + l.transaction_count, 0);
  const totalReceipts = data.lines.reduce((sum, l) => sum + l.evidence_counts.receipt, 0);

  return (
    <div className="space-y-4">
      <PageHeader title="Tax receipts" actions={actions} />

      {/* Calm summary — the total of spending that falls in mapped claim lines,
          never framed as a deduction or refund. */}
      <div className="rounded-[14px] border border-border bg-card px-5 py-4 sm:px-6 sm:py-5">
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-fg-muted">
          Claimable categories · {year}
        </div>
        <div className="t-display mt-1.5 leading-none tabular-nums text-fg">
          {formatCurrency(data.grand_total)}
        </div>
        <div className="mt-2 text-[13px] text-fg-muted">
          {totalTransactions === 0
            ? `No transactions in a claim line yet for ${year}.`
            : `${totalTransactions} ${totalTransactions === 1 ? "transaction" : "transactions"} across ${data.lines.length} claim lines · ${totalReceipts} with receipts`}
        </div>
      </div>

      <div className="space-y-2">
        {data.lines.map((line) => (
          <TaxLine
            key={line.key}
            line={line}
            year={year}
            expanded={expanded.has(line.key)}
            onToggle={() => toggle(line.key)}
            onAttach={setAttachTxId}
          />
        ))}
      </div>

      <p className="pt-2 text-xs text-fg-muted">{TAX_DISCLAIMER}</p>

      <AttachmentCaptureDialog
        open={attachTxId !== null}
        onOpenChange={(open) => {
          if (!open) setAttachTxId(null);
        }}
        {...(attachTxId ? { txId: attachTxId } : {})}
      />
    </div>
  );
}

function TaxLine({
  line,
  year,
  expanded,
  onToggle,
  onAttach,
}: {
  line: TaxLineResponse;
  year: number;
  expanded: boolean;
  onToggle: () => void;
  onAttach: (txId: string) => void;
}) {
  const coverage =
    line.transaction_count > 0
      ? `${line.evidence_counts.receipt} of ${line.transaction_count} with receipts`
      : null;

  return (
    <div className="rounded-xl border border-border/60 bg-card">
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-xl"
        onClick={onToggle}
        onKeyDown={handleRowKey(onToggle)}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
      >
        <span className="text-fg-muted">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-fg">{line.label}</div>
        </div>
        <div className="text-right">
          <div className="text-sm font-semibold tabular-nums text-fg">
            {formatCurrency(line.total)}
          </div>
          <div className="text-xs text-fg-muted">
            {coverage ?? `${line.transaction_count} transactions`}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-border/60 px-4 py-3">
          {line.note && <p className="mb-3 text-xs text-fg-muted">{line.note}</p>}
          {line.transactions.length === 0 ? (
            <p className="text-sm text-fg-muted">No claimable transactions for {year}.</p>
          ) : (
            <ul className="divide-y divide-border/50">
              {line.transactions.map((tx) => (
                <TaxTransactionRow key={tx.tx_id} tx={tx} onAttach={onAttach} />
              ))}
            </ul>
          )}

          {line.excluded_transactions.length > 0 && (
            <div className="mt-4 border-t border-border/50 pt-3">
              <div className="mb-1 text-xs font-medium text-fg-muted">Removed</div>
              <ul className="divide-y divide-border/40">
                {line.excluded_transactions.map((tx) => (
                  <ExcludedTransactionRow key={tx.tx_id} tx={tx} />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TaxTransactionRow({
  tx,
  onAttach,
}: {
  tx: TaxPackTransaction;
  onAttach: (txId: string) => void;
}) {
  const setOverride = useSetTaxOverride();
  const clearOverride = useClearTaxOverride();

  const [emailOpen, setEmailOpen] = useState(false);
  const [receiptsOpen, setReceiptsOpen] = useState(false);
  // Lazily fetch attachments only once the row engages the receipt view — no
  // bulk per-row sweep across the line.
  const [engaged, setEngaged] = useState(false);
  const { data: attachmentsData } = useTransactionAttachments(tx.tx_id, engaged);
  const attachments = attachmentsData?.attachments ?? [];
  const hasReceipt = tx.evidence === "receipt";

  const handleRemove = () => {
    // Excluding a manually-added item would orphan its include override, so
    // fully un-flag manual items instead of stacking an exclude on top.
    const callbacks = {
      onSuccess: () => toast("Removed from tax pack"),
      onError: (err: unknown) =>
        toast(err instanceof Error ? err.message : "Couldn't remove from tax pack"),
    };
    if (tx.manual) clearOverride.mutate(tx.tx_id, callbacks);
    else setOverride.mutate({ txId: tx.tx_id, mode: "exclude" }, callbacks);
  };

  return (
    <li className="flex items-center gap-3 py-2">
      <span className="w-24 shrink-0 text-xs tabular-nums text-fg-muted">
        {formatIsoDate(tx.date)}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-fg">{tx.company}</span>
      <Badge variant="secondary" className="shrink-0 font-normal">
        {evidenceLabel(tx.evidence)}
      </Badge>
      <span className="w-20 shrink-0 text-right text-sm font-medium tabular-nums text-fg">
        {formatCurrency(tx.amount)}
      </span>
      <div className="flex shrink-0 items-center gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="View original email"
              onClick={() => setEmailOpen(true)}
              className="rounded p-1 text-fg-muted transition-colors hover:bg-muted hover:text-fg"
            >
              <Mail className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent>View original email</TooltipContent>
        </Tooltip>
        {hasReceipt && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label="View receipts"
                onClick={() => {
                  setEngaged(true);
                  setReceiptsOpen(true);
                }}
                className="rounded p-1 text-fg-muted transition-colors hover:bg-muted hover:text-fg"
              >
                <Receipt className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent>View receipts</TooltipContent>
          </Tooltip>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="Attach a receipt"
              onClick={() => onAttach(tx.tx_id)}
              className="rounded p-1 text-fg-muted transition-colors hover:bg-muted hover:text-fg"
            >
              <Paperclip className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Attach a receipt</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="Remove from tax pack"
              onClick={handleRemove}
              className="rounded p-1 text-fg-muted transition-colors hover:bg-status-danger/10 hover:text-status-danger"
            >
              <X className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Remove from tax pack</TooltipContent>
        </Tooltip>
      </div>

      <EmailPreviewDialog
        transaction={{ forwarded_to: tx.forwarded_to, date_file_name: tx.date_file_name }}
        open={emailOpen}
        onOpenChange={setEmailOpen}
      />
      <AttachmentViewDialog
        attachments={attachments}
        open={receiptsOpen}
        onOpenChange={setReceiptsOpen}
        onAttachAnother={() => {
          setReceiptsOpen(false);
          onAttach(tx.tx_id);
        }}
      />
    </li>
  );
}

function ExcludedTransactionRow({ tx }: { tx: TaxPackTransaction }) {
  const clearOverride = useClearTaxOverride();

  const handleRestore = () => {
    clearOverride.mutate(tx.tx_id, {
      onSuccess: () => toast("Restored to tax pack"),
      onError: (err) => toast(err instanceof Error ? err.message : "Couldn't restore to tax pack"),
    });
  };

  return (
    <li className="flex items-center gap-3 py-2 opacity-60">
      <span className="w-24 shrink-0 text-xs tabular-nums text-fg-muted">
        {formatIsoDate(tx.date)}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-fg">{tx.company}</span>
      <span className="w-20 shrink-0 text-right text-sm font-medium tabular-nums text-fg">
        {formatCurrency(tx.amount)}
      </span>
      <Button variant="ghost" size="sm" onClick={handleRestore} className="shrink-0 text-xs">
        Restore
      </Button>
    </li>
  );
}
