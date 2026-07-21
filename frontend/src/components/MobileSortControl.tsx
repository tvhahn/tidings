import { ArrowUpDown } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SortConfig, SortColumn, SortDirection } from "@/lib/sort";

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "date-desc", label: "Date: Newest first" },
  { value: "date-asc", label: "Date: Oldest first" },
  { value: "amount-desc", label: "Amount: High to low" },
  { value: "amount-asc", label: "Amount: Low to high" },
  { value: "company-asc", label: "Company: A to Z" },
  { value: "company-desc", label: "Company: Z to A" },
  { value: "category-asc", label: "Category: A to Z" },
  { value: "category-desc", label: "Category: Z to A" },
  { value: "institution-asc", label: "Institution: A to Z" },
  { value: "institution-desc", label: "Institution: Z to A" },
  { value: "type-asc", label: "Type: A to Z" },
  { value: "type-desc", label: "Type: Z to A" },
];

interface MobileSortControlProps {
  sort: SortConfig;
  onSortChange: (sort: SortConfig) => void;
}

export function MobileSortControl({ sort, onSortChange }: MobileSortControlProps) {
  const value = `${sort.column}-${sort.direction}`;

  return (
    <div className="md:hidden flex items-center gap-2">
      <ArrowUpDown className="h-4 w-4 text-muted-foreground shrink-0" />
      <Select
        value={value}
        onValueChange={(v) => {
          const [column, direction] = v.split("-") as [SortColumn, SortDirection];
          onSortChange({ column, direction });
        }}
      >
        <SelectTrigger className="h-8 text-xs w-[200px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SORT_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value} className="text-xs">
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
