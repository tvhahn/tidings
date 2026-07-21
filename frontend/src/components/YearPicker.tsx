import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

interface YearPickerProps {
  year: number;
  onChange: (year: number) => void;
}

export function YearPicker({ year, onChange }: YearPickerProps) {
  return (
    <div className="flex items-center gap-1">
      <Button variant="ghost" size="icon" onClick={() => onChange(year - 1)}>
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <span className="min-w-[80px] inline-flex items-center justify-center rounded-full border border-border/60 px-3 py-1 text-sm font-medium">
        {year}
      </span>
      <Button variant="ghost" size="icon" onClick={() => onChange(year + 1)}>
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
