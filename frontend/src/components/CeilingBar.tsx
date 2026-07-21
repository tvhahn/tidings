import { useState } from "react";
import { Input } from "@/components/ui/input";

interface CeilingBarProps {
  ceiling: number;
  allocated: number;
  onCeilingChange: (value: string) => void;
  ceilingRaw: string;
}

export function CeilingBar({ ceiling, allocated, onCeilingChange, ceilingRaw }: CeilingBarProps) {
  const [editing, setEditing] = useState(false);

  const unallocated = ceiling - allocated;
  const pct = ceiling > 0 ? Math.min((allocated / ceiling) * 100, 100) : 0;

  let barColor = "bg-status-success";
  if (ceiling > 0 && allocated > ceiling) {
    barColor = "bg-status-danger";
  } else if (ceiling > 0 && pct >= 95) {
    barColor = "bg-status-warning";
  }

  return (
    <div className="space-y-2 rounded-lg border p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Annual Ceiling:</span>
          {editing ? (
            <Input
              type="number"
              value={ceilingRaw}
              onChange={(e) => onCeilingChange(e.target.value)}
              onBlur={() => setEditing(false)}
              onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
              className="h-7 w-32 text-sm"
              // eslint-disable-next-line jsx-a11y/no-autofocus -- inline edit control shown on click; focus preserves typing flow
              autoFocus
            />
          ) : (
            <button
              onClick={() => setEditing(true)}
              className="text-sm font-semibold hover:underline"
            >
              ${ceiling.toLocaleString()}
            </button>
          )}
        </div>
        <span className="text-sm text-muted-foreground">
          ${Math.abs(unallocated).toLocaleString()} {unallocated >= 0 ? "unallocated" : "over"}
        </span>
      </div>
      {ceiling > 0 && (
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground w-24 text-right">
            ${allocated.toLocaleString()}
          </span>
          <div className="flex-1 h-3 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${barColor}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground w-24">${ceiling.toLocaleString()}</span>
        </div>
      )}
    </div>
  );
}
