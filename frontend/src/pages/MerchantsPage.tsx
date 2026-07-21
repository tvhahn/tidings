import { MerchantAlerts } from "@/components/merchants/MerchantAlerts";
import { MerchantSummaryCards } from "@/components/merchants/MerchantSummaryCards";
import { RecurringMerchantsList } from "@/components/merchants/RecurringMerchantsList";
import { MonthPicker } from "@/components/MonthPicker";
import { PageHeader } from "@/components/PageHeader";
import { useMerchantIntelligence } from "@/hooks/useMerchantIntelligence";
import { useMonthParam } from "@/hooks/useMonthParam";

export function MerchantsPage() {
  const [month, setMonth] = useMonthParam();
  const { data, isLoading, error } = useMerchantIntelligence(month, 6);

  return (
    <div className="space-y-4">
      <PageHeader title="Merchants" actions={<MonthPicker month={month} onChange={setMonth} />} />

      {isLoading && (
        <div className="rounded-[14px] border border-border bg-card px-5 py-6">
          <div className="flex items-center gap-3 text-fg-muted">
            <span className="flex gap-1" aria-hidden>
              <span className="h-2 w-2 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
              <span className="h-2 w-2 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
              <span className="h-2 w-2 rounded-full bg-current animate-bounce" />
            </span>
            <span className="text-sm">Reading the last six months</span>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-[14px] border border-status-danger-calm/30 bg-status-danger-calm/[0.025] px-5 py-5">
          <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-fg-muted">
            Notice
          </p>
          <p className="mt-1.5 text-[13px] text-status-danger-calm-text">
            Could not load merchant intelligence right now.
          </p>
        </div>
      )}

      {data && (
        <>
          <MerchantSummaryCards summary={data.summary} />
          <RecurringMerchantsList
            merchants={data.merchants}
            month={data.month}
            monthsAnalyzed={data.months_analyzed}
          />
          <MerchantAlerts
            summary={data.summary}
            merchants={data.merchants}
            month={data.month}
            monthsAnalyzed={data.months_analyzed}
          />
        </>
      )}
    </div>
  );
}
