import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InsightsPage } from "@/pages/InsightsPage";
import { renderWithProviders } from "@/test/render";

// --- Mocks ------------------------------------------------------------------
// The page composes many hooks and child cards; the pager is the unit under
// test, so we stub the data hooks and the sibling cards and drive the list.

interface SavedItem {
  id: string;
  month: string;
  generated_at: string;
  figures_ok?: boolean | null;
}

let month = "2026-05";
let savedList: SavedItem[] = [];

vi.mock("@/hooks/useMonthParam", () => ({
  useMonthParam: () => [month, vi.fn()] as const,
}));

vi.mock("@/hooks/useDemoMode", () => ({ useDemoMode: () => false }));

vi.mock("@/hooks/useSavedInsights", () => ({
  useSavedInsights: () => ({ data: savedList, isLoading: false }),
  // Content is keyed off the requested id so we can assert which briefing shows.
  useSavedInsight: (id: string | null) => ({
    data: id ? { content: `Body for ${id}` } : undefined,
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useInsightsContext", () => ({ useInsightsContext: () => ({ data: null }) }));

vi.mock("@/hooks/useInsightsGeneration", () => ({
  useInsightsStatus: () => ({ data: { status: "idle" } }),
  useGenerateInsights: () => ({ mutate: vi.fn(), error: null }),
}));

// Sibling cards pull their own data — stub them to keep the page isolated.
vi.mock("@/components/MonthPicker", () => ({ MonthPicker: () => null }));
vi.mock("@/components/InsightsSparkline", () => ({ InsightsSparkline: () => null }));
vi.mock("@/components/insights/MomentumCard", () => ({ MomentumCard: () => null }));
vi.mock("@/components/insights/AnomaliesCard", () => ({ AnomaliesCard: () => null }));

function makeList(): SavedItem[] {
  return [
    { id: "c", month: "2026-05", generated_at: "2026-05-30T15:00:00Z" },
    { id: "b", month: "2026-05", generated_at: "2026-05-20T15:00:00Z" },
    { id: "a", month: "2026-05", generated_at: "2026-05-10T15:00:00Z" },
  ];
}

beforeEach(() => {
  month = "2026-05";
  savedList = makeList();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("InsightsPage briefing pager", () => {
  it("shows the newest briefing by default as '1 of 3' with next disabled", () => {
    renderWithProviders(<InsightsPage />, { route: "/insights?month=2026-05" });

    expect(screen.getByText("1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Body for c")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next briefing" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous briefing" })).toBeEnabled();
  });

  it("walks to older briefings and disables previous at the oldest", () => {
    renderWithProviders(<InsightsPage />, { route: "/insights?month=2026-05" });

    const prev = () => screen.getByRole("button", { name: "Previous briefing" });
    fireEvent.click(prev());
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(screen.getByText("Body for b")).toBeInTheDocument();

    fireEvent.click(prev());
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    expect(screen.getByText("Body for a")).toBeInTheDocument();
    expect(prev()).toBeDisabled();

    // Next walks back toward the newest.
    fireEvent.click(screen.getByRole("button", { name: "Next briefing" }));
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
  });

  it("hides the pager when only one briefing exists", () => {
    savedList = [makeList()[0]!];
    renderWithProviders(<InsightsPage />, { route: "/insights?month=2026-05" });

    expect(screen.queryByRole("button", { name: "Previous briefing" })).toBeNull();
    expect(screen.queryByText(/of 1/)).toBeNull();
    expect(screen.getByText("Body for c")).toBeInTheDocument();
  });

  it("resets to the newest briefing when the month changes", () => {
    const { rerender } = renderWithProviders(<InsightsPage />, {
      route: "/insights?month=2026-05",
    });

    fireEvent.click(screen.getByRole("button", { name: "Previous briefing" }));
    expect(screen.getByText("2 of 3")).toBeInTheDocument();

    // Simulate the month param changing under the page.
    month = "2026-04";
    savedList = [
      { id: "z", month: "2026-04", generated_at: "2026-04-28T15:00:00Z" },
      { id: "y", month: "2026-04", generated_at: "2026-04-14T15:00:00Z" },
    ];
    rerender(<InsightsPage />);

    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Body for z")).toBeInTheDocument();
  });
});
