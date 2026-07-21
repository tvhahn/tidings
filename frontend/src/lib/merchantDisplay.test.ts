import { describe, expect, it } from "vitest";
import { cleanMerchantName } from "@/lib/merchantDisplay";

describe("cleanMerchantName", () => {
  const cases: Array<[string, string]> = [
    ["SQ *MERIDIAN COFFEE CO", "MERIDIAN COFFEE CO"],
    ["Sq *meridian Coffee Co", "meridian Coffee Co"],
    ["SP HARBOUR BEAN COFFEE", "HARBOUR BEAN COFFEE"],
    ["Wal-mart #8801", "Wal-mart"],
    ["Costco Wholesale W880", "Costco Wholesale"],
    ["Northwind Foods 8802", "Northwind Foods"],
    ["Fuelstop@ - 4821", "Fuelstop"],
    ["Grocery Mart #123", "Grocery Mart"],
    ["Spotify P22015bdfe", "Spotify"],
    ["Starbucks 8007827282", "Starbucks"],
    ["Corner Bakehouse 5540921", "Corner Bakehouse"],
    ["WC*NORTHWIND MARKET", "NORTHWIND MARKET"],
    ["IN *ACME CONSULTING", "ACME CONSULTING"],
    ["Netflix.com", "Netflix.com"],
    ["Indigo Books", "Indigo Books"],
    ["Spotify", "Spotify"],
    ["7-Eleven", "7-Eleven"],
    ["A&W #1234", "A&W"],
    ["", ""],
  ];

  it.each(cases)("cleans %j to %j", (input, expected) => {
    expect(cleanMerchantName(input)).toBe(expected);
  });

  it("is idempotent for every case", () => {
    for (const [input] of cases) {
      const once = cleanMerchantName(input);
      expect(cleanMerchantName(once)).toBe(once);
    }
  });
});
