import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useTransactionDetail(forwardedTo: string, dateFileName: string, enabled: boolean) {
  return useQuery({ ...queries.transactionDetail(forwardedTo, dateFileName), enabled });
}
