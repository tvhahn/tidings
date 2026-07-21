import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { MonthGrid } from "@/components/MonthGrid";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatMonthLabelLong } from "@/lib/format";
import { cn } from "@/lib/utils";

interface MonthPickerInputProps {
  value: string; // "YYYY-MM"
  onChange: (month: string) => void;
  className?: string;
  id?: string;
}

export function MonthPickerInput({ value, onChange, className, id }: MonthPickerInputProps) {
  const [open, setOpen] = useState(false);

  const handleSelect = (month: string) => {
    onChange(month);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={id}
          className={cn(
            "flex h-9 items-center justify-between gap-2 whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring",
            className
          )}
        >
          <span>{formatMonthLabelLong(value)}</span>
          <ChevronDown className="h-4 w-4 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3" align="start">
        <MonthGrid key={String(open)} selectedMonth={value} onSelect={handleSelect} />
      </PopoverContent>
    </Popover>
  );
}
