import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TableCell, TableRow } from "@/components/ui/table";
import type { CategoryFormEntry } from "@/lib/budgetCalc";
import { formatCurrencyRounded } from "@/lib/format";

interface BudgetEditRowProps {
  entry: CategoryFormEntry;
  avg3: number | null;
  avg12: number | null;
  suggestedMonthly: number | null;
  currentMonthSpent: number | null;
  ytdSpent: number | null;
  showSpending: boolean;
  onUpdate: (key: string, patch: Partial<CategoryFormEntry>) => void;
  onRemove: (key: string) => void;
}

const formatNum = formatCurrencyRounded;

function deltaLabel(target: number, avg: number | null): string | null {
  if (avg == null || avg === 0 || target === 0) return null;
  const monthly = target / 12;
  const pctDiff = ((monthly - avg) / avg) * 100;
  if (Math.abs(pctDiff) < 20) return null;
  const sign = pctDiff > 0 ? "\u2191" : "\u2193";
  return `${sign}${Math.abs(Math.round(pctDiff))}%`;
}

export function BudgetEditRow({
  entry,
  avg3,
  avg12,
  suggestedMonthly,
  currentMonthSpent,
  ytdSpent,
  showSpending,
  onUpdate,
  onRemove,
}: BudgetEditRowProps) {
  const monthly = Math.round((entry.target / 12) * 100) / 100;
  const annual = entry.target;
  const delta = deltaLabel(entry.target, avg3);

  const handleUpdate = (patch: Partial<CategoryFormEntry>) => {
    onUpdate(entry.key, patch);
  };

  const fillFromAvg = (avg: number | null) => {
    if (avg == null) return;
    handleUpdate({
      inputMode: "monthly",
      displayAmount: String(Math.round(avg)),
    });
  };

  return (
    <TableRow className="group">
      {/* Category */}
      <TableCell className="font-medium capitalize">{entry.key}</TableCell>

      {/* 3mo Avg */}
      <TableCell className="text-right">
        <button
          onClick={() => fillFromAvg(avg3)}
          className="text-muted-foreground hover:text-foreground hover:underline cursor-pointer"
          title="Click to use as target"
        >
          {formatNum(avg3)}
        </button>
      </TableCell>

      {/* 12mo Avg */}
      <TableCell className="text-right">
        <button
          onClick={() => fillFromAvg(avg12)}
          className="text-muted-foreground hover:text-foreground hover:underline cursor-pointer"
          title="Click to use as target"
        >
          {formatNum(avg12)}
        </button>
      </TableCell>

      {/* This Month (conditional) */}
      {showSpending && (
        <TableCell className="text-right text-muted-foreground">
          {formatNum(currentMonthSpent)}
        </TableCell>
      )}

      {/* YTD (conditional) */}
      {showSpending && (
        <TableCell className="text-right text-muted-foreground">{formatNum(ytdSpent)}</TableCell>
      )}

      {/* Monthly Target */}
      <TableCell className="text-right">
        {entry.inputMode === "monthly" ? (
          <div className="flex items-center justify-end gap-1">
            <span className="text-muted-foreground text-xs">$</span>
            <Input
              type="number"
              value={entry.displayAmount}
              onChange={(e) => handleUpdate({ displayAmount: e.target.value })}
              placeholder={
                suggestedMonthly != null ? String(Math.round(suggestedMonthly)) : undefined
              }
              className="h-7 w-20 text-right text-sm"
              min="0"
            />
            {delta && (
              <span className="text-xs text-muted-foreground ml-1 whitespace-nowrap">{delta}</span>
            )}
          </div>
        ) : (
          <button
            onClick={() => handleUpdate({ inputMode: "monthly" })}
            className="text-sm text-muted-foreground hover:text-foreground hover:underline cursor-pointer"
          >
            {formatNum(monthly)}
          </button>
        )}
      </TableCell>

      {/* Annual Target */}
      <TableCell className="text-right">
        {entry.inputMode === "yearly" ? (
          <div className="flex items-center justify-end gap-1">
            <span className="text-muted-foreground text-xs">$</span>
            <Input
              type="number"
              value={entry.displayAmount}
              onChange={(e) => handleUpdate({ displayAmount: e.target.value })}
              className="h-7 w-24 text-right text-sm"
              min="0"
            />
          </div>
        ) : (
          <button
            onClick={() => handleUpdate({ inputMode: "yearly" })}
            className="text-sm text-muted-foreground hover:text-foreground hover:underline cursor-pointer"
          >
            {formatNum(annual)}
          </button>
        )}
      </TableCell>

      {/* Type */}
      <TableCell>
        <Select
          value={entry.categoryType}
          onValueChange={(v) => handleUpdate({ categoryType: v as "fixed" | "variable" | "lumpy" })}
        >
          <SelectTrigger className="h-7 w-[110px] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fixed">Fixed</SelectItem>
            <SelectItem value="variable">Variable</SelectItem>
            <SelectItem value="lumpy">Lumpy</SelectItem>
          </SelectContent>
        </Select>
      </TableCell>

      {/* Remove */}
      <TableCell>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={() => onRemove(entry.key)}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </TableCell>
    </TableRow>
  );
}
