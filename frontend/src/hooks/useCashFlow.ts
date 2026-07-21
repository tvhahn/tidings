import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { useSummary } from "@/hooks/useSummary";
import { buildCashFlowGraph, type CashFlowGraph } from "@/lib/cashFlow";

export function useCashFlow(month: string) {
  const summary = useSummary(month);
  const { groups } = useCategoryGroups();

  const graph: CashFlowGraph | null = summary.data
    ? buildCashFlowGraph(summary.data.current, groups)
    : null;

  return {
    graph,
    isPending: summary.isPending,
    isError: summary.isError,
    isPlaceholderData: summary.isPlaceholderData,
    error: summary.error,
  };
}
