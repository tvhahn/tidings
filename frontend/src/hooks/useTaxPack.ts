import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useTaxPack(year: number) {
  return useQuery(queries.taxPack(year));
}
