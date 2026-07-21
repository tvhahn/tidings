import { create } from "zustand";

interface FreshnessState {
  lastSyncAt: number | null;
  lastLatest: string | null;
  isPolling: boolean;
  pulseToken: number;
  setSync: (lastLatest: string | null, pulsed: boolean) => void;
  setPolling: (polling: boolean) => void;
}

/**
 * Global freshness state written by useFreshnessProbe and read by the
 * sync-status pill. `pulseToken` increments whenever the probe sees a newer
 * DateFileName; components can key animations off the change.
 */
export const useFreshness = create<FreshnessState>((set, get) => ({
  lastSyncAt: null,
  lastLatest: null,
  isPolling: false,
  pulseToken: 0,
  setSync: (lastLatest, pulsed) =>
    set({
      lastLatest,
      lastSyncAt: Date.now(),
      pulseToken: pulsed ? get().pulseToken + 1 : get().pulseToken,
    }),
  setPolling: (isPolling) => set({ isPolling }),
}));
