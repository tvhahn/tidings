import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IngestionHealthSection } from "@/components/settings/IngestionHealthSection";
import type { CoverageResponse, HealthStatus } from "@/types/api";

// --- Mocks ------------------------------------------------------------------
// The section reads two queries: useCoverage (the cadence + capture snapshot)
// and the /health probe (for the quarantine line). Mock both so the render is
// a pure function of fixture state.
let coverage: CoverageResponse | undefined;
let health: Partial<HealthStatus> | undefined;

vi.mock("@/hooks/useCoverage", () => ({
  useCoverage: () => ({ data: coverage, isLoading: false }),
}));

// The health query is the only direct useQuery call in the component.
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: health }),
}));

function institution(overrides: Partial<CoverageResponse["institutions"][number]>) {
  return {
    institution: "RBC",
    status: "active" as const,
    last_seen_at: "2026-03-18T09:00:00-04:00",
    days_since_last_seen: 1,
    median_gap_days: 3,
    threshold_gap_days: 7,
    dormant_cutoff_days: 45,
    event_days: 40,
    ...overrides,
  };
}

function coverageResponse(overrides: Partial<CoverageResponse>): CoverageResponse {
  return {
    institutions: [],
    capture: null,
    window_months: 12,
    checked_at: "2026-03-19T08:13:00-04:00",
    ...overrides,
  };
}

afterEach(() => {
  vi.clearAllMocks();
  coverage = undefined;
  health = undefined;
});

describe("IngestionHealthSection", () => {
  it("shows the quiet gap line and the one remediation sentence for a quiet institution", () => {
    coverage = coverageResponse({
      institutions: [
        institution({
          institution: "CIBC",
          status: "quiet",
          days_since_last_seen: 20,
          threshold_gap_days: 9,
        }),
      ],
    });
    render(<IngestionHealthSection />);

    expect(
      screen.getByText(/quiet for 20 days — you usually see a gap of no more than 9/)
    ).toBeInTheDocument();
    expect(screen.getByText("A statement import can fill the gap.")).toBeInTheDocument();
  });

  it("renders 'no steady cadence' for an irregular institution", () => {
    coverage = coverageResponse({
      institutions: [institution({ institution: "Simplii", status: "irregular" })],
    });
    render(<IngestionHealthSection />);

    expect(screen.getByText("no steady cadence")).toBeInTheDocument();
    // Irregular institutions are never framed as an alert / remediation.
    expect(screen.queryByText("A statement import can fill the gap.")).not.toBeInTheDocument();
  });

  it("renders the capture row only when capture data is present", () => {
    coverage = coverageResponse({ institutions: [institution({})], capture: null });
    const { rerender } = render(<IngestionHealthSection />);
    expect(
      screen.queryByText(/statement transactions in the months you've imported/)
    ).not.toBeInTheDocument();

    coverage = coverageResponse({
      institutions: [institution({})],
      capture: {
        overall: { caught: 47, total: 49, rate: 0.959 },
        by_institution: [{ institution: "CIBC", caught: 47, total: 49, rate: 0.959 }],
        by_type: [],
      },
    });
    rerender(<IngestionHealthSection />);
    expect(screen.getByText(/Alerts caught 47 of 49/)).toBeInTheDocument();
  });

  it("shows the quarantine line only when parse failures are present", () => {
    coverage = coverageResponse({ institutions: [institution({})] });
    health = { parse_failures_7d: 3 };
    render(<IngestionHealthSection />);
    expect(screen.getByText(/3 emails quarantined in the last 7 days/)).toBeInTheDocument();
  });

  it("renders the empty state when there is no alert history", () => {
    coverage = coverageResponse({ institutions: [] });
    render(<IngestionHealthSection />);
    expect(screen.getByText("No alert history yet.")).toBeInTheDocument();
  });
});
