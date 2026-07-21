import { describe, expect, it } from "vitest";
import { normalizeMerchant } from "./merchantNormalize";

// Parity cases from tests/unit/test_merchant_normalizer.py — keep aligned.
describe("normalizeMerchant", () => {
  it("passes a clean name through unchanged", () => {
    expect(normalizeMerchant("Safeway")).toBe("Safeway");
  });

  it("strips a hash store number", () => {
    expect(normalizeMerchant("Safeway #1234")).toBe("Safeway");
  });

  it("strips a 'Store NNN' suffix", () => {
    expect(normalizeMerchant("Walmart Store 567")).toBe("Walmart");
  });

  it("strips a 'Loc NN' suffix", () => {
    expect(normalizeMerchant("Tim Hortons Loc 42")).toBe("Tim Hortons");
  });

  it("strips a trailing province after a city", () => {
    expect(normalizeMerchant("SAFEWAY VANCOUVER BC")).toBe("SAFEWAY VANCOUVER");
  });

  it("strips a trailing province alone", () => {
    expect(normalizeMerchant("SAFEWAY BC")).toBe("SAFEWAY");
  });

  it("strips a trailing country code", () => {
    expect(normalizeMerchant("Amazon CA")).toBe("Amazon");
  });

  it("strips trailing punctuation", () => {
    expect(normalizeMerchant("Starbucks --")).toBe("Starbucks");
  });

  it("returns empty for empty input", () => {
    expect(normalizeMerchant("")).toBe("");
  });

  it("returns empty for whitespace-only input", () => {
    expect(normalizeMerchant("   ")).toBe("");
  });

  it("handles complex multi-pattern cleanup", () => {
    expect(normalizeMerchant("TIM HORTONS Store 123 US")).toBe("TIM HORTONS");
  });

  it("tolerates null/undefined", () => {
    expect(normalizeMerchant(null)).toBe("");
    expect(normalizeMerchant(undefined)).toBe("");
  });
});
