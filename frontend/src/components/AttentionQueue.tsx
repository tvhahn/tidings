import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { TransactionCard } from "@/components/TransactionCard";
import { TransactionTable } from "@/components/TransactionTable";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { useAttentionQueue } from "@/hooks/useAttentionQueue";
import { useMarkReviewed } from "@/hooks/useMarkReviewed";
import { DEFAULT_SORT } from "@/lib/sort";
import type { SortConfig } from "@/lib/sort";
import type { Transaction } from "@/types/api";

interface AttentionQueueProps {
  month: string;
  onEmailPreview?: (txn: Transaction) => void;
}

export function AttentionQueue({ month, onEmailPreview }: AttentionQueueProps) {
  const [open, setOpen] = useState(false);
  const [sort, setSort] = useState<SortConfig>(DEFAULT_SORT);
  const { data, isLoading } = useAttentionQueue(month);
  const reviewMutation = useMarkReviewed();

  const handleConfirm = (txn: Transaction) => {
    reviewMutation.mutate({
      forwardedTo: txn.forwarded_to,
      dateFileName: txn.date_file_name,
    });
  };

  const count = data?.count ?? 0;

  if (isLoading) {
    return <Skeleton className="h-12 w-full" />;
  }

  if (count === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="group flex w-full items-center gap-3 rounded-[14px] border border-border bg-card px-5 py-3 text-left transition-colors hover:bg-surface-muted">
        <span className="text-[10.5px] font-medium uppercase tracking-[0.08em] text-fg-muted">
          Notice
        </span>
        <span className="text-[13px] font-medium text-fg">
          {count} transaction{count === 1 ? "" : "s"} need a category
        </span>
        {open ? (
          <ChevronDown className="ml-auto h-4 w-4 text-fg-muted" />
        ) : (
          <ChevronRight className="ml-auto h-4 w-4 text-fg-muted" />
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2">
        <div className="hidden md:block">
          <TransactionTable
            transactions={data?.transactions ?? []}
            sort={sort}
            onSortChange={setSort}
            onConfirm={handleConfirm}
            onEmailPreview={onEmailPreview}
            showHeader={false}
          />
        </div>
        <div className="space-y-3 md:hidden">
          {(data?.transactions ?? []).map((txn) => (
            <TransactionCard
              key={`${txn.forwarded_to}|${txn.date_file_name}`}
              transaction={txn}
              onConfirm={handleConfirm}
              onEmailPreview={onEmailPreview}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
