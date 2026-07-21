import { describe, expect, it } from "vitest";
import { titleCaseAllCapsRuns } from "@/lib/summaryText";

describe("titleCaseAllCapsRuns", () => {
  it("softens a run of all-caps merchant tokens", () => {
    expect(titleCaseAllCapsRuns("WESTLAND UTILITY CO was the day's largest item at $145")).toBe(
      "Westland Utility Co was the day's largest item at $145"
    );
  });

  it("keeps trailing alphanumeric store codes intact within a run", () => {
    expect(titleCaseAllCapsRuns("COSTCO WHOLESALE W880 drove most of the spending")).toBe(
      "Costco Wholesale W880 drove most of the spending"
    );
  });

  it("leaves an isolated all-caps acronym unchanged", () => {
    expect(titleCaseAllCapsRuns("The CRA refund arrived today")).toBe(
      "The CRA refund arrived today"
    );
  });

  it("preserves ampersand tokens verbatim while softening the rest of the run", () => {
    expect(titleCaseAllCapsRuns("Spending at A&W AND MCDONALDS rose")).toBe(
      "Spending at A&W And Mcdonalds rose"
    );
  });

  it("leaves ordinary sentence text unchanged", () => {
    expect(titleCaseAllCapsRuns("Netflix renewed at $8.95")).toBe("Netflix renewed at $8.95");
  });

  it("returns empty string unchanged", () => {
    expect(titleCaseAllCapsRuns("")).toBe("");
  });
});
