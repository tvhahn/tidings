import { describe, expect, it } from "vitest";

import { ignoreToggleTooltip } from "./ignoreToggle";

describe("ignoreToggleTooltip", () => {
  it("offers to ignore an active row", () => {
    expect(ignoreToggleTooltip({ ignored: false, duplicate_of_tx_id: null })).toBe(
      "Ignore transaction"
    );
  });

  it("offers to restore a manually ignored row", () => {
    expect(ignoreToggleTooltip({ ignored: true, duplicate_of_tx_id: null })).toBe(
      "Restore transaction"
    );
  });

  it("explains a row stored as a repeated alert", () => {
    expect(ignoreToggleTooltip({ ignored: true, duplicate_of_tx_id: "abc" })).toBe(
      "Repeat of an earlier bank alert. Restore if it was a separate purchase"
    );
  });

  it("drops the explanation once a repeated alert is restored", () => {
    expect(ignoreToggleTooltip({ ignored: false, duplicate_of_tx_id: "abc" })).toBe(
      "Ignore transaction"
    );
  });
});
