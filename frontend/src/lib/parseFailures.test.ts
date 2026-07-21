import { describe, expect, it } from "vitest";
import type { ParseFailureSummary, RetryAllResponse } from "@/types/api";
import {
  PARSE_FAILURE_FILTERS,
  deriveRetryAllFilter,
  emailDomain,
  failureStageLabel,
  statusLabel,
  summarizeRetryAll,
} from "./parseFailures";

/** Minimal row factory — only the fields the retry-all derivation reads matter. */
function row(overrides: Partial<ParseFailureSummary>): ParseFailureSummary {
  return {
    detected_institution: null,
    from_email: null,
    ...overrides,
  } as ParseFailureSummary;
}

describe("failureStageLabel", () => {
  it("maps every known stage code to a calm human label", () => {
    expect(failureStageLabel("no_parser_match")).toBe("Bank not recognized");
    expect(failureStageLabel("extraction_empty")).toBe("No transaction details found");
    expect(failureStageLabel("ai_extraction_failed")).toBe("Couldn't read the details");
    expect(failureStageLabel("ai_validation_failed")).toBe("Details didn't check out");
    expect(failureStageLabel("db_validation_failed")).toBe("Couldn't be saved");
  });

  it("never renders a raw code — unknown stages fall back to a generic", () => {
    expect(failureStageLabel("some_new_stage")).toBe("Couldn't read this email");
    expect(failureStageLabel("")).toBe("Couldn't read this email");
  });
});

describe("statusLabel", () => {
  it("labels the non-active statuses", () => {
    expect(statusLabel("dismissed")).toBe("Set aside");
    expect(statusLabel("recovered")).toBe("Recovered");
    expect(statusLabel("retried")).toBe("Retried");
  });

  it("returns null for the active queue and unknown statuses", () => {
    expect(statusLabel("quarantined")).toBeNull();
    expect(statusLabel("whatever")).toBeNull();
  });
});

describe("PARSE_FAILURE_FILTERS", () => {
  it("exposes the three locked filters with their query statuses", () => {
    expect(PARSE_FAILURE_FILTERS.map((f) => f.key)).toEqual(["needs-review", "set-aside", "all"]);
    const byKey = Object.fromEntries(PARSE_FAILURE_FILTERS.map((f) => [f.key, f]));
    expect(byKey["needs-review"]?.status).toBe("quarantined");
    expect(byKey["set-aside"]?.status).toBe("dismissed");
    expect(byKey["all"]?.status).toBeUndefined();
  });

  it("gives every filter its own empty-state line", () => {
    for (const f of PARSE_FAILURE_FILTERS) {
      expect(f.empty.length).toBeGreaterThan(0);
      expect(f.empty).not.toContain("!");
    }
  });
});

describe("emailDomain", () => {
  it("extracts the domain from a bare address", () => {
    expect(emailDomain("alerts@rbc.com")).toBe("rbc.com");
  });

  it("strips a display name and trailing '>' from a 'Name <a@b.com>' sender", () => {
    expect(emailDomain("RBC Alerts <alerts@rbc.com>")).toBe("rbc.com");
    expect(emailDomain("alerts@rbc.com>")).toBe("rbc.com");
  });

  it("lowercases and trims", () => {
    expect(emailDomain("Alerts@RBC.COM ")).toBe("rbc.com");
  });

  it("returns null for missing or address-less input", () => {
    expect(emailDomain(null)).toBeNull();
    expect(emailDomain(undefined)).toBeNull();
    expect(emailDomain("")).toBeNull();
    expect(emailDomain("no-at-sign")).toBeNull();
  });
});

describe("deriveRetryAllFilter", () => {
  it("returns the shared institution when every row carries it", () => {
    const failures = [
      row({ detected_institution: "RBC", from_email: "a@rbc.com" }),
      row({ detected_institution: "RBC", from_email: "b@rbcroyalbank.com" }),
    ];
    expect(deriveRetryAllFilter(failures)).toEqual({ institution: "RBC" });
  });

  it("returns null when institutions are mixed null + a value (heterogeneous queue)", () => {
    // 2 RBC rows + 3 unknown-bank rows: the old subset bug returned {institution:'RBC'}.
    const failures = [
      row({ detected_institution: "RBC", from_email: "a@rbc.com" }),
      row({ detected_institution: "RBC", from_email: "b@rbc.com" }),
      row({ detected_institution: null, from_email: "x@unknownbank.example" }),
      row({ detected_institution: null, from_email: "y@another.example" }),
      row({ detected_institution: null, from_email: "z@third.example" }),
    ];
    expect(deriveRetryAllFilter(failures)).toBeNull();
  });

  it("falls back to the shared domain when no institution is detected but every domain matches", () => {
    const failures = [
      row({ detected_institution: null, from_email: "Notices <a@unknownbank.example>" }),
      row({ detected_institution: null, from_email: "b@unknownbank.example" }),
    ];
    expect(deriveRetryAllFilter(failures)).toEqual({ from_domain: "unknownbank.example" });
  });

  it("returns null when sender domains differ", () => {
    const failures = [
      row({ detected_institution: null, from_email: "a@one.example" }),
      row({ detected_institution: null, from_email: "b@two.example" }),
    ];
    expect(deriveRetryAllFilter(failures)).toBeNull();
  });

  it("returns null for an empty queue", () => {
    expect(deriveRetryAllFilter([])).toBeNull();
  });
});

describe("summarizeRetryAll", () => {
  const base: RetryAllResponse = {
    retried: 0,
    created: 0,
    duplicates: 0,
    still_failing: 0,
  } as RetryAllResponse;

  it("uses the singular noun for a single email", () => {
    expect(summarizeRetryAll({ ...base, retried: 1 })).toContain("Retried 1 email —");
  });

  it("uses the plural noun for multiple emails", () => {
    const summary = summarizeRetryAll({
      ...base,
      retried: 5,
      created: 2,
      duplicates: 1,
      still_failing: 2,
    });
    expect(summary).toBe("Retried 5 emails — 2 added, 1 already recorded, 2 still need review");
  });
});
