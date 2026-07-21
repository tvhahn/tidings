import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AutoIgnoreRulesSection } from "@/components/settings/AutoIgnoreRulesSection";
import type { DismissedIgnoreRuleSuggestion, IgnoreRuleSuggestion } from "@/types/api";

// --- Mocks ------------------------------------------------------------------
const { dismissSpy, addSpy, applySpy, deleteSpy, undismissSpy } = vi.hoisted(() => ({
  dismissSpy: vi.fn(),
  addSpy: vi.fn(),
  applySpy: vi.fn(),
  deleteSpy: vi.fn(),
  undismissSpy: vi.fn(),
}));

let suggestions: IgnoreRuleSuggestion[] = [];
let dismissed: DismissedIgnoreRuleSuggestion[] = [];

vi.mock("@/hooks/useIgnoreRules", () => ({
  useIgnoreRules: () => ({ data: { rules: [], count: 0, version: 0 }, isLoading: false }),
  useIgnoreRuleSuggestions: () => ({ data: { suggestions, count: suggestions.length } }),
  useIgnoreRuleDismissedSuggestions: () => ({ data: { dismissed, count: dismissed.length } }),
  useAddIgnoreRule: () => ({ mutate: addSpy, isPending: false }),
  useDeleteIgnoreRule: () => ({ mutate: deleteSpy, isPending: false }),
  useApplyIgnoreRules: () => ({ mutate: applySpy, isPending: false }),
  useDismissIgnoreRuleSuggestion: () => ({ mutate: dismissSpy, isPending: false }),
  useUndismissIgnoreRuleSuggestion: () => ({ mutate: undismissSpy, isPending: false }),
}));

afterEach(() => {
  vi.clearAllMocks();
  suggestions = [];
  dismissed = [];
});

describe("AutoIgnoreRulesSection suggestions", () => {
  it("dismisses a suggestion with the merchant and does not accept it", () => {
    suggestions = [
      { merchant: "MiscPayment CARDCO", total_count: 4, ignored_count: 3, share: 0.75 },
    ];
    render(<AutoIgnoreRulesSection />);

    // The suggestion row offers both a dismiss and an accept affordance.
    fireEvent.click(
      screen.getByRole("button", { name: "Dismiss suggestion for MiscPayment CARDCO" })
    );

    expect(dismissSpy).toHaveBeenCalledWith("MiscPayment CARDCO");
    // Dismissing must not add a rule.
    expect(addSpy).not.toHaveBeenCalled();
  });

  it("renders no suggestions block when the list is empty", () => {
    suggestions = [];
    render(<AutoIgnoreRulesSection />);

    expect(screen.queryByText("Suggested rules")).not.toBeInTheDocument();
  });
});

describe("AutoIgnoreRulesSection dismissed suggestions", () => {
  it("hides the dismissed block when there are no dismissals", () => {
    dismissed = [];
    render(<AutoIgnoreRulesSection />);

    expect(screen.queryByText(/dismissed suggestion/)).not.toBeInTheDocument();
  });

  it("shows a count line and reveals rows on expand", () => {
    dismissed = [
      { merchant: "MiscPayment CARDCO", dismissed_at: "2026-07-16T00:00:00+00:00" },
      { merchant: "Costco", dismissed_at: "2026-07-10T00:00:00+00:00" },
    ];
    render(<AutoIgnoreRulesSection />);

    const toggle = screen.getByRole("button", { name: /2 dismissed suggestions/ });
    // Collapsed by default — rows are not yet rendered.
    expect(screen.queryByText("Costco")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.getByText("MiscPayment CARDCO")).toBeInTheDocument();
    expect(screen.getByText("Costco")).toBeInTheDocument();
  });

  it("restores a dismissal with the merchant", () => {
    dismissed = [{ merchant: "MiscPayment CARDCO", dismissed_at: "2026-07-16T00:00:00+00:00" }];
    render(<AutoIgnoreRulesSection />);

    fireEvent.click(screen.getByRole("button", { name: /1 dismissed suggestion/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Restore suggestion for MiscPayment CARDCO" })
    );

    expect(undismissSpy).toHaveBeenCalledWith("MiscPayment CARDCO");
  });
});
