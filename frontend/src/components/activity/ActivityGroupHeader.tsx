import {
  formatBurstTimestamp,
  formatChangeCount,
  type ActivityGroup,
} from "@/lib/activityGrouping";

interface ActivityGroupHeaderProps {
  group: ActivityGroup;
  nowMs: number;
}

export function ActivityGroupHeader({ group, nowMs }: ActivityGroupHeaderProps) {
  return (
    <p className="px-1 text-xs text-muted-foreground">
      <span className="font-medium text-fg-secondary">{group.principalLabel}</span>
      {" · "}
      {formatChangeCount(group.count)}
      {" · "}
      {formatBurstTimestamp(group.ts, nowMs)}
    </p>
  );
}
