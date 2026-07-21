import { create } from "zustand";

const DISMISSED_KEY = "demo-tour:dismissed";

function loadDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === "true";
  } catch {
    return false;
  }
}

function persistDismissed() {
  try {
    localStorage.setItem(DISMISSED_KEY, "true");
  } catch {
    // storage unavailable — silent
  }
}

interface DemoTourState {
  isOpen: boolean;
  step: number;
  dismissedForever: boolean;
  open: () => void;
  close: () => void;
  next: () => void;
  back: () => void;
  setStep: (step: number) => void;
  totalSteps: number;
  setTotalSteps: (total: number) => void;
}

export const useDemoTour = create<DemoTourState>((set, get) => ({
  isOpen: false,
  step: 0,
  dismissedForever: loadDismissed(),
  totalSteps: 0,
  open: () => set({ isOpen: true, step: 0 }),
  close: () => {
    persistDismissed();
    set({ isOpen: false, dismissedForever: true });
  },
  next: () => {
    const { step, totalSteps } = get();
    if (step < totalSteps - 1) set({ step: step + 1 });
  },
  back: () => {
    const { step } = get();
    if (step > 0) set({ step: step - 1 });
  },
  setStep: (step) => set({ step }),
  setTotalSteps: (total) => set({ totalSteps: total }),
}));
