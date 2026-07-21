import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import {
  invalidateAttachmentLinkCaches,
  invalidateTransactionDependents,
  mutations,
  TRANSACTION_DEPENDENT_PREFIXES,
} from "@/lib/queryConfigs";

// The invalidation contracts are the load-bearing, bug-prone half of the data
// layer: a mutation that forgets to invalidate a dependent view leaves the UI
// showing stale numbers. These tests pin the contract by spying on a real
// QueryClient's invalidateQueries and asserting which key prefixes get hit —
// no network, no observers, just the topology.

type InvalidateSpy = MockInstance<QueryClient["invalidateQueries"]>;

/**
 * The first-element prefix (`queryKey[0]`) of every recorded invalidateQueries
 * call. Matching by prefix keeps assertions robust to extra filter properties
 * (e.g. `refetchType`) riding along on the same filter object.
 */
function invalidatedPrefixes(spy: InvalidateSpy): unknown[] {
  return spy.mock.calls.map((call) => call[0]?.queryKey?.[0]);
}

describe("queryConfigs", () => {
  let qc: QueryClient;
  let spy: InvalidateSpy;

  beforeEach(() => {
    qc = new QueryClient();
    spy = vi.spyOn(qc, "invalidateQueries");
  });

  describe("invalidateTransactionDependents", () => {
    it("invalidates every transaction-dependent prefix except trash by default", () => {
      invalidateTransactionDependents(qc);

      const prefixes = invalidatedPrefixes(spy);
      for (const prefix of TRANSACTION_DEPENDENT_PREFIXES) {
        if (prefix === "trash") continue;
        expect(prefixes).toContain(prefix);
      }
      // Trash is excluded on the hot path so ordinary edits don't refetch it.
      expect(prefixes).not.toContain("trash");
    });

    it("invalidates trash too when includeTrash is set", () => {
      invalidateTransactionDependents(qc, { includeTrash: true });

      const prefixes = invalidatedPrefixes(spy);
      for (const prefix of TRANSACTION_DEPENDENT_PREFIXES) {
        expect(prefixes).toContain(prefix);
      }
      expect(prefixes).toContain("trash");
    });

    it("passes refetchType through to every invalidateQueries call", () => {
      invalidateTransactionDependents(qc, { refetchType: "none" });

      expect(spy).toHaveBeenCalled();
      for (const call of spy.mock.calls) {
        expect(call[0]).toMatchObject({ refetchType: "none" });
      }
    });
  });

  describe("invalidateAttachmentLinkCaches", () => {
    // Shared by the uploadAttachment/deleteAttachment/linkAttachment/parseReceipt
    // factories. The single-strong-match auto-link (L8) now runs through
    // linkAttachment too — the candidates GET is a pure read that only signals
    // eligibility — so the mutation factory owns this invalidation contract.
    it("invalidates the attachment, unlinked, candidate, and tax-pack prefixes", () => {
      invalidateAttachmentLinkCaches(qc);

      const prefixes = invalidatedPrefixes(spy);
      expect(prefixes).toContain("attachments");
      expect(prefixes).toContain("unlinkedAttachments");
      expect(prefixes).toContain("receiptCandidates");
      // Linking a receipt flips a row's tax-pack evidence to "receipt" (L15).
      expect(prefixes).toContain("tax-pack");
      // Linking a file changes no transaction data (L15).
      expect(prefixes).not.toContain("transactions");
    });

    it("is the exact contract of the upload/delete/link/parse attachment factories", () => {
      // An upload-with-txId auto-links and a delete un-links a linked receipt —
      // same tax-pack evidence / candidate-set fallout as an explicit link, so
      // all four factories share the helper's invalidation contract.
      spy.mockClear();
      mutations.uploadAttachment(qc).onSettled();
      const uploadPrefixes = invalidatedPrefixes(spy);

      spy.mockClear();
      mutations.deleteAttachment(qc).onSettled();
      const deletePrefixes = invalidatedPrefixes(spy);

      spy.mockClear();
      mutations.linkAttachment(qc).onSettled();
      const linkPrefixes = invalidatedPrefixes(spy);

      spy.mockClear();
      mutations.parseReceipt(qc).onSettled();
      const parsePrefixes = invalidatedPrefixes(spy);

      spy.mockClear();
      invalidateAttachmentLinkCaches(qc);
      const helperPrefixes = invalidatedPrefixes(spy);

      expect(uploadPrefixes).toEqual(helperPrefixes);
      expect(deletePrefixes).toEqual(helperPrefixes);
      expect(linkPrefixes).toEqual(helperPrefixes);
      expect(parsePrefixes).toEqual(helperPrefixes);
    });
  });

  describe("mutation onSettled invalidation contracts", () => {
    it("softDelete invalidates transaction dependents including trash", () => {
      mutations.softDelete(qc).onSettled();

      const prefixes = invalidatedPrefixes(spy);
      expect(prefixes).toContain("trash");
      expect(prefixes).toContain("transactions");
      expect(prefixes).toContain("summary");
    });

    it("updateCategory invalidates optimistically with refetchType: none", () => {
      mutations.updateCategory(qc).onSettled();

      const prefixes = invalidatedPrefixes(spy);
      expect(prefixes).toContain("transactions");
      const transactionsCall = spy.mock.calls.find((c) => c[0]?.queryKey?.[0] === "transactions");
      expect(transactionsCall?.[0]).toMatchObject({ refetchType: "none" });
    });

    it("importStatement invalidates transaction dependents and statements", () => {
      mutations.importStatement(qc).onSettled();

      const prefixes = invalidatedPrefixes(spy);
      expect(prefixes).toContain("transactions");
      expect(prefixes).toContain("summary");
      expect(prefixes).toContain("statements");
    });

    it("retryParseFailure invalidates transaction dependents only when a row was created", () => {
      mutations.retryParseFailure(qc).onSettled({ status: "created", failure_id: "f1" });

      const created = invalidatedPrefixes(spy);
      expect(created).toContain("parse-failures");
      expect(created).toContain("transactions");

      spy.mockClear();

      // A duplicate created no new transaction, so only the queue refreshes.
      mutations.retryParseFailure(qc).onSettled({ status: "duplicate", failure_id: "f1" });

      const duplicate = invalidatedPrefixes(spy);
      expect(duplicate).toContain("parse-failures");
      expect(duplicate).not.toContain("transactions");
    });
  });
});
