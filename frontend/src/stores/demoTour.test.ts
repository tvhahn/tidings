import { beforeEach, describe, expect, it, vi } from "vitest";

async function freshStore() {
  vi.resetModules();
  const mod = await import("./demoTour");
  return mod.useDemoTour;
}

describe("demoTour store", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("starts closed at step 0 with totalSteps 0", async () => {
    const useDemoTour = await freshStore();
    const s = useDemoTour.getState();
    expect(s.isOpen).toBe(false);
    expect(s.step).toBe(0);
    expect(s.totalSteps).toBe(0);
    expect(s.dismissedForever).toBe(false);
  });

  it("loads dismissed=true from localStorage", async () => {
    localStorage.setItem("demo-tour:dismissed", "true");
    const useDemoTour = await freshStore();
    expect(useDemoTour.getState().dismissedForever).toBe(true);
  });

  it("open resets step to 0 and sets isOpen", async () => {
    const useDemoTour = await freshStore();
    useDemoTour.getState().setStep(3);
    useDemoTour.getState().open();
    expect(useDemoTour.getState().isOpen).toBe(true);
    expect(useDemoTour.getState().step).toBe(0);
  });

  it("close persists dismissed=true and closes", async () => {
    const useDemoTour = await freshStore();
    useDemoTour.getState().open();
    useDemoTour.getState().close();
    expect(useDemoTour.getState().isOpen).toBe(false);
    expect(useDemoTour.getState().dismissedForever).toBe(true);
    expect(localStorage.getItem("demo-tour:dismissed")).toBe("true");
  });

  it("next advances step but stops at totalSteps - 1", async () => {
    const useDemoTour = await freshStore();
    useDemoTour.getState().setTotalSteps(3);
    useDemoTour.getState().next();
    expect(useDemoTour.getState().step).toBe(1);
    useDemoTour.getState().next();
    expect(useDemoTour.getState().step).toBe(2);
    useDemoTour.getState().next();
    expect(useDemoTour.getState().step).toBe(2);
  });

  it("back decrements step but stops at 0", async () => {
    const useDemoTour = await freshStore();
    useDemoTour.getState().setStep(2);
    useDemoTour.getState().back();
    expect(useDemoTour.getState().step).toBe(1);
    useDemoTour.getState().back();
    useDemoTour.getState().back();
    expect(useDemoTour.getState().step).toBe(0);
  });

  it("setTotalSteps updates total", async () => {
    const useDemoTour = await freshStore();
    useDemoTour.getState().setTotalSteps(5);
    expect(useDemoTour.getState().totalSteps).toBe(5);
  });
});
