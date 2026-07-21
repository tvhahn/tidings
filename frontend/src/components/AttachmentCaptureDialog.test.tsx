import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReceiptReview } from "@/components/AttachmentCaptureDialog";
import type { AttachmentResponse, ReceiptCandidate, ReceiptCandidatesResponse } from "@/types/api";

// The candidates GET is a pure read that only signals eligibility via
// `auto_link_candidate`; the client performs the write. These tests pin that the
// dialog fires the link mutation exactly once when the signal is set, and never
// when it is not. All data-layer hooks are mocked so we exercise the effect in
// isolation.
const { linkSpy, candidatesState } = vi.hoisted(() => ({
  linkSpy: vi.fn(),
  candidatesState: {
    data: undefined as ReceiptCandidatesResponse | undefined,
    isPending: false,
  },
}));

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ data: { ai_receipt_parsing_enabled: true } }),
}));
vi.mock("@/hooks/useParseReceipt", () => ({
  useParseReceipt: () => ({
    data: null,
    isPending: false,
    isError: false,
    error: null,
    mutate: vi.fn(),
  }),
}));
vi.mock("@/hooks/useLinkAttachment", () => ({
  useLinkAttachment: () => ({ mutate: linkSpy, isPending: false, variables: undefined }),
}));
vi.mock("@/hooks/useReceiptCandidates", () => ({
  useReceiptCandidates: () => candidatesState,
}));

function attachment(over: Partial<AttachmentResponse> = {}): AttachmentResponse {
  return {
    id: "att_1",
    content_type: "image/jpeg",
    created_at: "2026-02-15T10:30:00Z",
    kind: "receipt",
    original_filename: "receipt.jpg",
    parse_json: { merchant: "Booster Juice", total: 42.5 },
    parse_status: "parsed",
    sha256: "abc",
    size_bytes: 100,
    tx_id: null,
    updated_at: "2026-02-15T10:30:00Z",
    ...over,
  };
}

function candidate(over: Partial<ReceiptCandidate> = {}): ReceiptCandidate {
  return {
    already_has_receipt: false,
    amount: 42.5,
    amount_distance: 0,
    category: "dining",
    company: "Booster Juice",
    date: "2026-02-15",
    day_distance: 0,
    tier: 1,
    tx_id: "tx_1",
    ...over,
  };
}

describe("ReceiptReview auto-link", () => {
  beforeEach(() => {
    linkSpy.mockClear();
    candidatesState.data = undefined;
    candidatesState.isPending = false;
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("fires the link mutation for the tier-1 candidate and confirms the link", () => {
    candidatesState.data = {
      attachment_id: "att_1",
      auto_link_candidate: true,
      candidates: [candidate()],
    };

    render(<ReceiptReview attachment={attachment()} matching />);

    expect(linkSpy).toHaveBeenCalledTimes(1);
    expect(linkSpy).toHaveBeenCalledWith(
      { id: "att_1", txId: "tx_1" },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) })
    );
    expect(screen.getByText("Linked to Booster Juice.")).toBeInTheDocument();
  });

  it("fires the link mutation only once under StrictMode double-invocation", () => {
    candidatesState.data = {
      attachment_id: "att_1",
      auto_link_candidate: true,
      candidates: [candidate()],
    };

    render(
      <StrictMode>
        <ReceiptReview attachment={attachment()} matching />
      </StrictMode>
    );

    expect(linkSpy).toHaveBeenCalledTimes(1);
  });

  it("does not auto-link when the signal is false and shows the pickable list", () => {
    candidatesState.data = {
      attachment_id: "att_1",
      auto_link_candidate: false,
      candidates: [candidate(), candidate({ tx_id: "tx_2" })],
    };

    render(<ReceiptReview attachment={attachment()} matching />);

    expect(linkSpy).not.toHaveBeenCalled();
    expect(screen.getByText(/Pick the transaction/)).toBeInTheDocument();
  });
});
