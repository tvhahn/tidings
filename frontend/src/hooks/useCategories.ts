import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queryConfigs";

export function useCategories() {
  return useQuery(queries.categories());
}
