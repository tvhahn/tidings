import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useAttentionQueue(month: string) {
  return useQuery(queries.attention(month));
}
