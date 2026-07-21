import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BriefingMemoSection } from "@/components/settings/BriefingMemoSection";
import type { AppConfig } from "@/types/api";

// --- Mocks ------------------------------------------------------------------
const { mutateSpy, toastSuccessSpy } = vi.hoisted(() => ({
  mutateSpy: vi.fn(),
  toastSuccessSpy: vi.fn(),
}));

// mutate(data, opts) fires the success callback so we can assert the toast.
mutateSpy.mockImplementation((_data: unknown, opts?: { onSuccess?: () => void }) =>
  opts?.onSuccess?.()
);

let configValue: Partial<AppConfig> = {};

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ data: configValue }),
  useUpdateConfig: () => ({ mutate: mutateSpy, isPending: false }),
}));

vi.mock("sonner", () => ({ toast: { success: toastSuccessSpy } }));

function setConfig(over: Partial<AppConfig>) {
  configValue = over;
}

afterEach(() => {
  vi.clearAllMocks();
  configValue = {};
});

describe("BriefingMemoSection", () => {
  it("shows the persisted memo and disables save until edited", () => {
    setConfig({ insights_user_memo: "Household of four." });
    render(<BriefingMemoSection />);

    const textarea = screen.getByLabelText("Briefing memo") as HTMLTextAreaElement;
    expect(textarea.value).toBe("Household of four.");
    expect(screen.getByRole("button", { name: "Save memo" })).toBeDisabled();
  });

  it("saves an edited memo and confirms with a toast", () => {
    setConfig({ insights_user_memo: null });
    render(<BriefingMemoSection />);

    const textarea = screen.getByLabelText("Briefing memo");
    fireEvent.change(textarea, { target: { value: "Saving for a renovation." } });

    const save = screen.getByRole("button", { name: "Save memo" });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    expect(mutateSpy).toHaveBeenCalledWith(
      { insights_user_memo: "Saving for a renovation." },
      expect.anything()
    );
    expect(toastSuccessSpy).toHaveBeenCalledWith("Briefing memo saved");
  });

  it("clears the memo by sending null when emptied", () => {
    setConfig({ insights_user_memo: "old context" });
    render(<BriefingMemoSection />);

    fireEvent.change(screen.getByLabelText("Briefing memo"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save memo" }));

    expect(mutateSpy).toHaveBeenCalledWith({ insights_user_memo: null }, expect.anything());
  });
});
