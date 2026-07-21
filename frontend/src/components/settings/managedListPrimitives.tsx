import { ChevronDown, ChevronUp, Plus, Search, X } from "lucide-react";
import * as React from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type ListSearchInputProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  className?: string;
};

export function ListSearchInput({
  id,
  value,
  onChange,
  ariaLabel,
  placeholder = "Search…",
  className,
}: ListSearchInputProps) {
  return (
    <div className={cn("relative w-full sm:w-64", className)}>
      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className="pl-9 h-9"
      />
    </div>
  );
}

type AddRowButtonProps = {
  onClick: () => void;
  disabled?: boolean;
  label: string;
};

export function AddRowButton({ onClick, disabled, label }: AddRowButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-status-success/10 hover:text-status-success disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
    >
      <Plus className="h-4 w-4" />
    </button>
  );
}

type DeleteRowButtonProps = {
  onClick: () => void;
  disabled?: boolean;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  size?: "sm" | "md";
};

export function DeleteRowButton({
  onClick,
  disabled,
  label,
  icon: Icon = X,
  size = "md",
}: DeleteRowButtonProps) {
  const iconSize = size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-status-danger/10 hover:text-status-danger disabled:opacity-20 disabled:cursor-not-allowed"
    >
      <Icon className={iconSize} />
    </button>
  );
}

type ShowAllToggleProps = {
  expanded: boolean;
  onToggle: () => void;
  totalCount: number;
  entityPlural: string;
};

export function ShowAllToggle({
  expanded,
  onToggle,
  totalCount,
  entityPlural,
}: ShowAllToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="mx-auto flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      {expanded ? (
        <>
          <ChevronUp className="h-4 w-4" />
          Show less
        </>
      ) : (
        <>
          <ChevronDown className="h-4 w-4" />
          Show all {totalCount} {entityPlural}
        </>
      )}
    </button>
  );
}
