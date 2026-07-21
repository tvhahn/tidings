import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useTrash(month: string) {
  return useQuery(queries.trash(month));
}
