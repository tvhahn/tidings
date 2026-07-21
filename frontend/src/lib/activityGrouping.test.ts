import { describe, expect, it } from "vitest";
import type { ActivityEntry } from "@/types/api";
import {
  activityEntryTitle,
  formatActivityRelativeTime,
  formatBurstTimestamp,
  formatChangeCount,
  groupActivity,
  humanizeOperationId,
  principalLabel,
} from "./activityGrouping";

function entry(overrides: Partial<ActivityEntry> = {}): ActivityEntry {
  // Spread overrides last so explicit `null` (e.g. operation_id: null) is
  // respected rather than coalesced back to the default.
  return {
    id: "id",
    ts: "2026-03-19T12:00:00Z",
    principal_kind: "token",
    principal_id: "tok1",
    principal_label: "kitchen-agent",
    operation_id: "patchTransaction",
    method: "PATCH",
    path: "/api/v1/transactions/x",
    resource_id: null,
    summary: null,
    before: null,
    after: null,
    reversible: true,
    reverted_at: null,
    reverted_by: null,
    ...overrides,
  };
}

describe("groupActivity", () => {
  it("returns no groups for an empty list", () => {
    expect(groupActivity([])).toEqual([]);
  });

  it("collapses same-principal entries within the 10-minute window into one burst", () => {
    const groups = groupActivity([
      entry({ id: "a", ts: "2026-03-19T12:09:00Z" }),
      entry({ id: "b", ts: "2026-03-19T12:05:00Z" }),
      entry({ id: "c", ts: "2026-03-19T12:00:00Z" }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.count).toBe(3);
    expect(groups[0]!.ts).toBe("2026-03-19T12:09:00Z"); // newest first is preserved
    expect(groups[0]!.principalLabel).toBe("kitchen-agent");
  });

  it("splits into a new group when the gap exceeds the window (boundary)", () => {
    // Exactly 10 minutes stays in-burst; one second past starts a new group.
    const inBurst = groupActivity([
      entry({ id: "a", ts: "2026-03-19T12:10:00Z" }),
      entry({ id: "b", ts: "2026-03-19T12:00:00Z" }),
    ]);
    expect(inBurst).toHaveLength(1);

    const split = groupActivity([
      entry({ id: "a", ts: "2026-03-19T12:10:01Z" }),
      entry({ id: "b", ts: "2026-03-19T12:00:00Z" }),
    ]);
    expect(split).toHaveLength(2);
    expect(split[0]!.count).toBe(1);
    expect(split[1]!.count).toBe(1);
  });

  it("splits when the principal changes even inside the time window", () => {
    const groups = groupActivity([
      entry({
        id: "a",
        ts: "2026-03-19T12:05:00Z",
        principal_id: "tok1",
        principal_label: "kitchen-agent",
      }),
      entry({
        id: "b",
        ts: "2026-03-19T12:04:00Z",
        principal_id: "tok2",
        principal_label: "laptop-claude",
      }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]!.principalLabel).toBe("kitchen-agent");
    expect(groups[1]!.principalLabel).toBe("laptop-claude");
  });
});

describe("formatBurstTimestamp", () => {
  // Build reference dates with the local Date constructor so the assertions are
  // timezone-independent: both construction and formatting read local time.
  it("labels same-day, prior-day, and older timestamps", () => {
    const now = new Date(2026, 2, 19, 20, 47);
    const today = new Date(2026, 2, 19, 15, 14);
    const yesterday = new Date(2026, 2, 18, 23, 42);
    const older = new Date(2026, 0, 6, 8, 5);
    expect(formatBurstTimestamp(today.toISOString(), now.getTime())).toBe("today 3:14 pm");
    expect(formatBurstTimestamp(yesterday.toISOString(), now.getTime())).toBe("yesterday 11:42 pm");
    expect(formatBurstTimestamp(older.toISOString(), now.getTime())).toBe("Jan 6, 8:05 am");
  });
});

describe("formatChangeCount", () => {
  it("pluralizes", () => {
    expect(formatChangeCount(1)).toBe("1 change");
    expect(formatChangeCount(14)).toBe("14 changes");
  });
});

describe("principalLabel", () => {
  it("names token principals by their token label", () => {
    expect(
      principalLabel(entry({ principal_kind: "token", principal_label: "laptop-claude" }))
    ).toBe("laptop-claude");
  });

  it("maps non-token kinds to plain language", () => {
    expect(
      principalLabel(entry({ principal_kind: "tofu", principal_id: null, principal_label: null }))
    ).toBe("this device");
    expect(
      principalLabel(
        entry({ principal_kind: "session", principal_id: null, principal_label: null })
      )
    ).toBe("browser session");
    expect(
      principalLabel(
        entry({ principal_kind: "dev-bypass", principal_id: null, principal_label: null })
      )
    ).toBe("dev bypass");
  });
});

describe("activityEntryTitle", () => {
  it("prefers the staged summary, then a humanized operation id, then method + path", () => {
    expect(activityEntryTitle(entry({ summary: "Category set to Groceries" }))).toBe(
      "Category set to Groceries"
    );
    expect(activityEntryTitle(entry({ summary: null, operation_id: "putOverride" }))).toBe(
      "Put override"
    );
    expect(
      activityEntryTitle(
        entry({ summary: null, operation_id: null, method: "DELETE", path: "/api/v1/overrides/x" })
      )
    ).toBe("DELETE /api/v1/overrides/x");
  });

  it("humanizes the locked `revert of <id>` summary", () => {
    expect(
      activityEntryTitle(entry({ summary: "revert of 35b5f167c20f42e4ace6507f430c975e" }))
    ).toBe("reverted an earlier change");
    // A non-revert summary is left untouched.
    expect(activityEntryTitle(entry({ summary: "revert of last week" }))).toBe(
      "revert of last week"
    );
  });
});

describe("formatActivityRelativeTime", () => {
  it("reads 'just now' under a minute, then whole units, sharing one clock", () => {
    const now = new Date("2026-03-19T12:00:00Z").getTime();
    const at = (secBefore: number) => new Date(now - secBefore * 1000).toISOString();
    expect(formatActivityRelativeTime(at(0), now)).toBe("just now");
    expect(formatActivityRelativeTime(at(30), now)).toBe("just now");
    expect(formatActivityRelativeTime(at(59), now)).toBe("just now");
    expect(formatActivityRelativeTime(at(60), now)).toBe("1m ago");
    expect(formatActivityRelativeTime(at(59 * 60), now)).toBe("59m ago");
    expect(formatActivityRelativeTime(at(60 * 60), now)).toBe("1h ago");
    expect(formatActivityRelativeTime(at(26 * 60 * 60), now)).toBe("1d ago");
    expect(formatActivityRelativeTime(null, now)).toBe("—");
  });
});

describe("humanizeOperationId", () => {
  it("splits camelCase into a sentence-case phrase", () => {
    expect(humanizeOperationId("bulkUpdateTransactionCategory")).toBe(
      "Bulk update transaction category"
    );
    expect(humanizeOperationId("patchTransaction")).toBe("Patch transaction");
  });
});
