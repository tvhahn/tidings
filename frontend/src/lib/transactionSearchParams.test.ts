import { describe, expect, it } from "vitest";
import { searchParamsFromUrl, toRangeUrlParams } from "./transactionSearchParams";

describe("searchParamsFromUrl", () => {
  it("returns null when from/to are absent (month mode)", () => {
    expect(searchParamsFromUrl(new URLSearchParams(""))).toBeNull();
    expect(searchParamsFromUrl(new URLSearchParams("month=2026-03"))).toBeNull();
  });

  it("returns null when only one bound is present", () => {
    expect(searchParamsFromUrl(new URLSearchParams("from=2026-03"))).toBeNull();
    expect(searchParamsFromUrl(new URLSearchParams("to=2026-07"))).toBeNull();
  });

  it("maps a bare range with just from/to", () => {
    expect(searchParamsFromUrl(new URLSearchParams("from=2026-03&to=2026-07"))).toEqual({
      from: "2026-03",
      to: "2026-07",
    });
  });

  it("maps all optional filters onto the API field names", () => {
    const url = new URLSearchParams(
      "from=2026-01&to=2026-06&q=coffee&category=dining&institution=rbc&type=purchase&min=10&max=200&ignored=1&trash=1"
    );
    expect(searchParamsFromUrl(url)).toEqual({
      from: "2026-01",
      to: "2026-06",
      q: "coffee",
      category: "dining",
      institution: "rbc",
      type: "purchase",
      min_amount: 10,
      max_amount: 200,
      include_ignored: true,
      include_deleted: true,
    });
  });

  it("ignores non-numeric min/max and falsey toggles", () => {
    const url = new URLSearchParams("from=2026-01&to=2026-06&min=abc&ignored=0&trash=false");
    expect(searchParamsFromUrl(url)).toEqual({ from: "2026-01", to: "2026-06" });
  });

  it("accepts ignored=true as truthy", () => {
    const url = new URLSearchParams("from=2026-01&to=2026-06&ignored=true");
    expect(searchParamsFromUrl(url)).toEqual({
      from: "2026-01",
      to: "2026-06",
      include_ignored: true,
    });
  });
});

describe("toRangeUrlParams", () => {
  it("serializes only the active fields", () => {
    const url = toRangeUrlParams({ from: "2026-03", to: "2026-07" });
    expect(url.toString()).toBe("from=2026-03&to=2026-07");
  });

  it("uses the short URL keys for amounts and toggles", () => {
    const url = toRangeUrlParams({
      from: "2026-01",
      to: "2026-06",
      q: "coffee",
      category: "dining",
      institution: "rbc",
      type: "purchase",
      min_amount: 10,
      max_amount: 200,
      include_ignored: true,
      include_deleted: true,
    });
    expect(Object.fromEntries(url)).toEqual({
      from: "2026-01",
      to: "2026-06",
      q: "coffee",
      category: "dining",
      institution: "rbc",
      type: "purchase",
      min: "10",
      max: "200",
      ignored: "1",
      trash: "1",
    });
  });

  it("round-trips through searchParamsFromUrl", () => {
    const original = {
      from: "2026-02",
      to: "2026-05",
      q: "rent",
      min_amount: 500,
      include_ignored: true,
    };
    expect(searchParamsFromUrl(toRangeUrlParams(original))).toEqual(original);
  });
});
