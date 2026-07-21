import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { InfoHint } from "@/components/ui/info-hint";

type Props = {
  title: string;
  infoHint?:
    | {
        label: string;
        content: React.ReactNode;
      }
    | undefined;
  count?: number | undefined;
  /** Unit word for the count, used in the badge's aria-label (e.g. "rules"). */
  countLabel?: string | undefined;
  /** Trailing slot, e.g. a search input or an action button. */
  toolbar?: React.ReactNode | undefined;
};

export function SettingsSectionHeader({ title, infoHint, count, countLabel, toolbar }: Props) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <h3 className="text-lg font-medium">{title}</h3>
        {infoHint ? <InfoHint label={infoHint.label} content={infoHint.content} /> : null}
        {typeof count === "number" ? (
          <Badge
            variant="secondary"
            className="text-xs"
            aria-label={countLabel ? `${count} ${countLabel}` : undefined}
          >
            {count}
          </Badge>
        ) : null}
      </div>
      {toolbar}
    </div>
  );
}
