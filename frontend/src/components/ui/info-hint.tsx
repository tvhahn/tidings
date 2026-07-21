import { Info } from "lucide-react";
import * as React from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type BaseProps = {
  label?: string;
  className?: string;
  iconClassName?: string;
};

type TooltipVariantProps = BaseProps & {
  variant: "tooltip";
  content: React.ReactNode;
};

type PopoverVariantProps = BaseProps & {
  variant?: "popover";
  content: React.ReactNode;
};

export type InfoHintProps = TooltipVariantProps | PopoverVariantProps;

const triggerClasses = cn(
  "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted-foreground/70",
  "hover:text-foreground focus-visible:text-foreground",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background",
  "transition-colors"
);

export function InfoHint(props: InfoHintProps) {
  const { label = "More info", className, iconClassName, content } = props;
  const icon = <Info className={cn("h-3.5 w-3.5", iconClassName)} aria-hidden="true" />;

  if (props.variant === "tooltip") {
    return (
      <Tooltip>
        <TooltipTrigger type="button" aria-label={label} className={cn(triggerClasses, className)}>
          {icon}
        </TooltipTrigger>
        <TooltipContent
          side="top"
          align="start"
          sideOffset={6}
          className="max-w-xs whitespace-normal text-xs leading-relaxed"
        >
          {content}
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Popover>
      <PopoverTrigger type="button" aria-label={label} className={cn(triggerClasses, className)}>
        {icon}
      </PopoverTrigger>
      <PopoverContent align="start" sideOffset={6} className="w-80 text-sm leading-relaxed">
        {content}
      </PopoverContent>
    </Popover>
  );
}
