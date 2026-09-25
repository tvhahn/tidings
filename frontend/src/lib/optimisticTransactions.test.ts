import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  composeUpdaters,
  mapRow,
  moveToTrash,
  optimisticallyUpdateCombined,
  removeFromAttention,
  restoreCombinedTransactions,
  restoreFromTrash,
} from "@/lib/optimisticTransactions";
import { makeCombined, makeTxn } from "@/test/factories";
import type { CombinedTransactionsResponse } from "@/types/api";

const REF = { forwardedTo: "user", dateFileName: "2026.02.10_09.00_b.eml" };
const target = makeTxn({ forwarded_to: REF.forwardedTo, date_file_name: REF.dateFileName });
const newer = makeTxn({ forwarded_to: "user", date_file_name: "2026.02.20_09.00_c.eml" });
const older = makeTxn({ forwarded_to: "user", date_file_name: "2026.02.01_09.00_a.eml" });
const DELETED_AT = "2026-02-25T12:00:00+00:00";

const dfns = (rows: { date_file_name: string }[]) => rows.map((t) => t.date_file_name);

describe("mapRow", () => {
  it("applies the row updater in every bucket and leaves other rows alone", () => {
    const combined = makeCombined({
      transactions: [newer, target],
      attention: [target],
      trash: [{ ...target, deleted_at: DELETED_AT }],
    });

    const next = mapRow(REF, (t) => ({ ...t, comment: "noted" }))(combined);

    expect(next.transactions.transactions.map((t) => t.comment)).toEqual([null, "noted"]);
    expect(next.attention.transactions[0]?.comment).toBe("noted");
    expect(next.trash.transactions[0]?.comment).toBe("noted");
    expect(combined.transactions.transactions[1]?.comment).toBeNull(); // input untouched
  });
});

describe("moveToTrash", () => {
  it("moves the row out of transactions and attention into trash, in server order", () => {
    const combined = makeCombined({
      transactions: [newer, target],
      attention: [target],
      trash: [
        { ...newer, date_file_name: "2026.02.28_x.eml", deleted_at: DELETED_AT },
        { ...older, deleted_at: DELETED_AT },
      ],
    });

    const next = moveToTrash(REF, DELETED_AT)(combined);

    expect(dfns(next.transactions.transactions)).toEqual([newer.date_file_name]);
    expect(next.transactions.count).toBe(1);
    expect(next.attention.transactions).toEqual([]);
    expect(next.attention.count).toBe(0);
    expect(dfns(next.trash.transactions)).toEqual([
      "2026.02.28_x.eml",
      target.date_file_name,
      older.date_file_name,
    ]);
    expect(next.trash.count).toBe(3);
    expect(next.trash.transactions[1]?.deleted_at).toBe(DELETED_AT);
  });

  it("leaves a month that does not hold the row unchanged", () => {
    const combined = makeCombined({ transactions: [newer] });
    const next = moveToTrash(REF, DELETED_AT)(combined);
    expect(next.transactions).toBe(combined.transactions);
    expect(next.trash).toBe(combined.trash);
  });
});

describe("restoreFromTrash", () => {
  it("moves the row back into transactions with deleted_at cleared", () => {
    const combined = makeCombined({
      transactions: [newer, older],
      trash: [{ ...target, deleted_at: DELETED_AT }],
    });

    const next = restoreFromTrash(REF)(combined);

    expect(next.trash.transactions).toEqual([]);
    expect(next.trash.count).toBe(0);
    expect(dfns(next.transactions.transactions)).toEqual([
      newer.date_file_name,
      target.date_file_name,
      older.date_file_name,
    ]);
    expect(next.transactions.count).toBe(3);
    expect(next.transactions.transactions[1]?.deleted_at).toBeNull();
  });
});

describe("composeUpdaters + removeFromAttention", () => {
  it("runs updaters left to right", () => {
    const combined = makeCombined({ transactions: [target], attention: [target] });
    const next = composeUpdaters(
      mapRow(REF, (t) => ({ ...t, ignored: true })),
      removeFromAttention(REF)
    )(combined);
    expect(next.transactions.transactions[0]?.ignored).toBe(true);
    expect(next.attention).toEqual({ month: "2026-02", count: 0, transactions: [] });
  });
});

describe("optimisticallyUpdateCombined / restoreCombinedTransactions", () => {
  it("updates every cached month and restores the exact snapshots", async () => {
    const qc = new QueryClient();
    const feb = makeCombined({ transactions: [target] }, "2026-02");
    const mar = makeCombined({ transactions: [newer] }, "2026-03");
    qc.setQueryData(["transactions-combined", "2026-02"], feb);
    qc.setQueryData(["transactions-combined", "2026-03"], mar);
    // A flat "transactions" key must not be swept up by the combined prefix.
    const flat = { month: "2026-02", count: 1, transactions: [target] };
    qc.setQueryData(["transactions", "2026-02"], flat);

    const snapshot = await optimisticallyUpdateCombined(qc, moveToTrash(REF, DELETED_AT));

    const febNext = qc.getQueryData<CombinedTransactionsResponse>([
      "transactions-combined",
      "2026-02",
    ]);
    expect(febNext?.transactions.count).toBe(0);
    expect(febNext?.trash.count).toBe(1);
    expect(qc.getQueryData(["transactions-combined", "2026-03"])).toEqual(mar);
    expect(qc.getQueryData(["transactions", "2026-02"])).toBe(flat);
    expect(snapshot).toHaveLength(2);

    restoreCombinedTransactions(qc, snapshot);

    expect(qc.getQueryData(["transactions-combined", "2026-02"])).toEqual(feb);
    expect(qc.getQueryData(["transactions-combined", "2026-03"])).toEqual(mar);
  });
});
