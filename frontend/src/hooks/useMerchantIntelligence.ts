import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useMerchantIntelligence(month: string, months: number = 6) {
  return useQuery(queries.merchantIntelligence(month, months));
}
