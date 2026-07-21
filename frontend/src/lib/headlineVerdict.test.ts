import { describe, expect, it } from "vitest";
import { headlineVerdict } from "./headlineVerdict";

// The current shipped JournalHeadline thresholds (JournalHeadline.tsx:56-73),
// reimplemented here as the parity oracle for the null-projection fallback.
// tone and label are computed from the SAME nesting the component uses, so a
// drift in the helper is caught as a mismatched PAIR, never a stray tone.
function componentVerdict(
  spentPct: number,
  pacePct: number
): { tone: "success" | "warning" | "danger"; label: string } {
  const tone = spentPct >= 100 ? "danger" : spentPct > pacePct + 5 ? "warning" : "success";
  const label =
    spentPct >= 100
      ? "Over ceiling"
      : spentPct > pacePct + 5
        ? "Ahead of pace"
        : spentPct >= pacePct - 5
          ? "On pace"
          : "Under pace";
  return { tone, label };
}

describe("headlineVerdict — commitment-aware (projectedPct non-null)", () => {
  it("projects over the ceiling → danger, Over ceiling", () => {
    expect(headlineVerdict({ spentPct: 40, pacePct: 60, projectedPct: 105 })).toEqual({
      tone: "danger",
      label: "Over ceiling",
    });
  });

  it("just over 100% → danger, Over ceiling", () => {
    expect(headlineVerdict({ spentPct: 40, pacePct: 60, projectedPct: 100.5 })).toEqual({
      tone: "danger",
      label: "Over ceiling",
    });
  });

  it("exactly 100% → warning, Close to ceiling (ceiling not crossed)", () => {
    expect(headlineVerdict({ spentPct: 40, pacePct: 60, projectedPct: 100 })).toEqual({
      tone: "warning",
      label: "Close to ceiling",
    });
  });

  it("within a hair of the ceiling → warning, Close to ceiling", () => {
    expect(headlineVerdict({ spentPct: 40, pacePct: 60, projectedPct: 98 })).toEqual({
      tone: "warning",
      label: "Close to ceiling",
    });
  });

  it("at the close-to-ceiling threshold (97%) → success, On pace", () => {
    expect(headlineVerdict({ spentPct: 40, pacePct: 60, projectedPct: 97 })).toEqual({
      tone: "success",
      label: "On pace",
    });
  });

  it("comfortably under the ceiling → success, On pace", () => {
    expect(headlineVerdict({ spentPct: 20, pacePct: 60, projectedPct: 50 })).toEqual({
      tone: "success",
      label: "On pace",
    });
  });

  it("ignores spent/pace when a projection is present", () => {
    // spentPct would read 'Over ceiling' on the fallback path; projection wins.
    expect(headlineVerdict({ spentPct: 130, pacePct: 50, projectedPct: 80 })).toEqual({
      tone: "success",
      label: "On pace",
    });
  });
});

describe("headlineVerdict — fallback (projectedPct null)", () => {
  it("spent at/over budget → danger, Over ceiling", () => {
    expect(headlineVerdict({ spentPct: 100, pacePct: 50, projectedPct: null })).toEqual({
      tone: "danger",
      label: "Over ceiling",
    });
    expect(headlineVerdict({ spentPct: 112, pacePct: 50, projectedPct: null })).toEqual({
      tone: "danger",
      label: "Over ceiling",
    });
  });

  it("ahead of the elapsed-month pace → warning, Ahead of pace", () => {
    expect(headlineVerdict({ spentPct: 60, pacePct: 50, projectedPct: null })).toEqual({
      tone: "warning",
      label: "Ahead of pace",
    });
  });

  it("within the pace band → success, On pace", () => {
    expect(headlineVerdict({ spentPct: 52, pacePct: 50, projectedPct: null })).toEqual({
      tone: "success",
      label: "On pace",
    });
    expect(headlineVerdict({ spentPct: 48, pacePct: 50, projectedPct: null })).toEqual({
      tone: "success",
      label: "On pace",
    });
  });

  it("comfortably below pace → success, Under pace", () => {
    expect(headlineVerdict({ spentPct: 40, pacePct: 50, projectedPct: null })).toEqual({
      tone: "success",
      label: "Under pace",
    });
  });

  it("band boundaries fall on the On pace side (matches the component)", () => {
    // spent === pace + 5 → not 'ahead' (strict >); spent === pace - 5 → still 'on'.
    expect(headlineVerdict({ spentPct: 55, pacePct: 50, projectedPct: null })).toEqual({
      tone: "success",
      label: "On pace",
    });
    expect(headlineVerdict({ spentPct: 45, pacePct: 50, projectedPct: null })).toEqual({
      tone: "success",
      label: "On pace",
    });
  });

  it("matches the shipped component thresholds across a grid (tone+label parity)", () => {
    for (let pacePct = 0; pacePct <= 100; pacePct += 5) {
      for (let spentPct = 0; spentPct <= 140; spentPct += 1) {
        expect(headlineVerdict({ spentPct, pacePct, projectedPct: null })).toEqual(
          componentVerdict(spentPct, pacePct)
        );
      }
    }
  });
});
