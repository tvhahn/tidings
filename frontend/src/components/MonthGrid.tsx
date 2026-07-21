import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { currentMonth, MONTH_SHORT, parseYearMonth } from "@/lib/format";

interface MonthGridProps {
  selectedMonth: string; // "YYYY-MM"
  onSelect: (month: string) => void;
}

export function MonthGrid({ selectedMonth, onSelect }: MonthGridProps) {
  const [selectedYear, selectedMonthNum] = parseYearMonth(selectedMonth);
  const [pickerYear, setPickerYear] = useState(selectedYear);

  const now = currentMonth();
  const [nowYear, nowMonth] = parseYearMonth(now);

  const isFuture = (yr: number, mo: number) => yr > nowYear || (yr === nowYear && mo > nowMonth);

  return (
    <>
      {/* Year navigation */}
      <div className="flex items-center justify-between mb-2">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setPickerYear((y) => y - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm font-semibold">{pickerYear}</span>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setPickerYear((y) => y + 1)}
          disabled={pickerYear >= nowYear}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {/* Month grid (3 cols x 4 rows) */}
      <div className="grid grid-cols-3 gap-1">
        {MONTH_SHORT.map((name, i) => {
          const mo = i + 1;
          const isSelected = pickerYear === selectedYear && mo === selectedMonthNum;
          const future = isFuture(pickerYear, mo);

          return (
            <Button
              key={name}
              variant={isSelected ? "default" : "ghost"}
              size="sm"
              className="h-8 text-xs"
              disabled={future}
              onClick={() => {
                const newMonth = `${pickerYear}-${String(mo).padStart(2, "0")}`;
                onSelect(newMonth);
              }}
            >
              {name}
            </Button>
          );
        })}
      </div>
    </>
  );
}
