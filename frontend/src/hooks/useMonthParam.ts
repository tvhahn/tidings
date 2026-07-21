import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { currentMonth } from "@/lib/format";

export function useMonthParam() {
  const [searchParams, setSearchParams] = useSearchParams();
  const month = searchParams.get("month") || currentMonth();

  const setMonth = useCallback(
    (next: string) => {
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.set("month", next);
          return p;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  return [month, setMonth] as const;
}
