import { describe, expect, it } from "vitest";
import { paceSeverity } from "./severity";

describe("paceSeverity", () => {
  it("returns neutral below 100%", () => {
    expect(paceSeverity(0)).toBe("neutral");
    expect(paceSeverity(50)).toBe("neutral");
    expect(paceSeverity(99.9)).toBe("neutral");
  });

  it("returns warning at 100% exactly", () => {
    expect(paceSeverity(100)).toBe("warning");
  });

  it("returns warning between 100 and 150", () => {
    expect(paceSeverity(125)).toBe("warning");
    expect(paceSeverity(150)).toBe("warning");
  });

  it("returns danger above 150", () => {
    expect(paceSeverity(150.1)).toBe("danger");
    expect(paceSeverity(200)).toBe("danger");
    expect(paceSeverity(25283)).toBe("danger");
  });
});
