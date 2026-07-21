import { EyeOff, Filter, X } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCategories } from "@/hooks/useCategories";
import { useCategoryGroups } from "@/hooks/useCategoryGroups";
import { DEFAULT_FILTERS, hasActiveFilters, type Filters } from "@/lib/filters";
import type { Transaction } from "@/types/api";

interface FilterBarProps {
  filters: Filters;
  onChange: (filters: Filters) => void;
  transactions: Transaction[];
}

function countActiveFilters(filters: Filters): number {
  let count = 0;
  if (filters.category !== DEFAULT_FILTERS.category) count++;
  if (filters.categoryGroup !== DEFAULT_FILTERS.categoryGroup) count++;
  if (filters.institution !== DEFAULT_FILTERS.institution) count++;
  if (filters.search !== DEFAULT_FILTERS.search) count++;
  if (filters.hideDeposits !== DEFAULT_FILTERS.hideDeposits) count++;
  if (filters.hideIgnored !== DEFAULT_FILTERS.hideIgnored) count++;
  return count;
}

export function FilterBar({ filters, onChange, transactions }: FilterBarProps) {
  const [mobileExpanded, setMobileExpanded] = useState(false);
  const { data } = useCategories();
  const { groups } = useCategoryGroups();
  const categories = data?.categories ?? [];

  // Derive unique institutions from current data
  const institutions = [
    ...new Set(transactions.map((t) => t.institution).filter(Boolean) as string[]),
  ].sort();

  // Compute the select value: group: prefix for groups, plain lowercase for individual
  const categorySelectValue = filters.categoryGroup
    ? `group:${filters.categoryGroup}`
    : filters.category;

  const handleCategoryChange = (v: string) => {
    if (v === "all") {
      onChange({ ...filters, category: "all", categoryGroup: undefined });
    } else if (v.startsWith("group:")) {
      onChange({ ...filters, category: "all", categoryGroup: v.slice(6) });
    } else {
      onChange({ ...filters, category: v, categoryGroup: undefined });
    }
  };

  const activeCount = countActiveFilters(filters);

  const filterControls = (
    <>
      <Select value={categorySelectValue} onValueChange={handleCategoryChange}>
        <SelectTrigger className="w-full md:w-[200px]">
          <SelectValue placeholder="All categories" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All categories</SelectItem>
          <SelectSeparator />
          <SelectGroup>
            <SelectLabel>Groups</SelectLabel>
            {[...new Set([...groups.map((g) => g.name), "Other"])].map((name) => (
              <SelectItem key={`group:${name}`} value={`group:${name}`}>
                {name}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectSeparator />
          <SelectGroup>
            <SelectLabel>Individual</SelectLabel>
            {categories.map((cat) => (
              <SelectItem key={cat} value={cat.toLowerCase()}>
                {cat}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>

      <Select
        value={filters.institution}
        onValueChange={(v) => onChange({ ...filters, institution: v })}
      >
        <SelectTrigger className="w-full md:w-[160px]">
          <SelectValue placeholder="All institutions" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All institutions</SelectItem>
          {institutions.map((inst) => (
            <SelectItem key={inst} value={inst.toLowerCase()}>
              {inst}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Input
        name="company_search"
        placeholder="Search merchants..."
        aria-label="Search merchants"
        value={filters.search}
        onChange={(e) => onChange({ ...filters, search: e.target.value })}
        className="w-full md:w-[200px]"
      />

      <Separator orientation="vertical" className="hidden h-6 md:block" />

      <div className="flex gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={filters.hideDeposits ? "secondary" : "outline"}
              size="sm"
              onClick={() => onChange({ ...filters, hideDeposits: !filters.hideDeposits })}
              className="gap-1.5 text-xs"
            >
              <EyeOff className="h-3.5 w-3.5" />
              Deposits
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {filters.hideDeposits ? "Show deposits" : "Hide deposits"}
          </TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={filters.hideIgnored ? "secondary" : "outline"}
              size="sm"
              onClick={() => onChange({ ...filters, hideIgnored: !filters.hideIgnored })}
              className="gap-1.5 text-xs"
            >
              <EyeOff className="h-3.5 w-3.5" />
              Ignored
            </Button>
          </TooltipTrigger>
          <TooltipContent>{filters.hideIgnored ? "Show ignored" : "Hide ignored"}</TooltipContent>
        </Tooltip>
      </div>

      {hasActiveFilters(filters) && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onChange(DEFAULT_FILTERS)}
              className="gap-1.5 text-xs text-muted-foreground"
            >
              <X className="h-3.5 w-3.5" />
              Clear
            </Button>
          </TooltipTrigger>
          <TooltipContent>Clear all filters</TooltipContent>
        </Tooltip>
      )}
    </>
  );

  return (
    <>
      {/* Desktop: always visible */}
      <div className="hidden md:flex flex-wrap items-center gap-3">{filterControls}</div>

      {/* Mobile: collapsible */}
      <div className="md:hidden space-y-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setMobileExpanded(!mobileExpanded)}
          className="gap-1.5 text-xs"
        >
          <Filter className="h-3.5 w-3.5" />
          Filters
          {activeCount > 0 && (
            <Badge variant="secondary" className="ml-1 px-1.5 py-0 text-[10px]">
              {activeCount}
            </Badge>
          )}
        </Button>
        {mobileExpanded && <div className="flex flex-col gap-3">{filterControls}</div>}
      </div>
    </>
  );
}
