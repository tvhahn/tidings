import { create } from "zustand";

interface EditEntry {
  oldCategory: string;
  newCategory: string;
}

interface EditedTransactionsState {
  edited: Map<string, EditEntry>;
  markEdited: (key: string, oldCategory: string, newCategory: string) => void;
  undo: (key: string) => string | null;
  clear: () => void;
  isEdited: (key: string) => boolean;
}

function makeKey(forwardedTo: string, dateFileName: string): string {
  return `${forwardedTo}|${dateFileName}`;
}

export const useEditedTransactions = create<EditedTransactionsState>((set, get) => ({
  edited: new Map(),

  markEdited: (key, oldCategory, newCategory) => {
    set((state) => {
      const next = new Map(state.edited);
      next.set(key, { oldCategory, newCategory });
      return { edited: next };
    });
  },

  undo: (key) => {
    const entry = get().edited.get(key);
    if (!entry) return null;
    set((state) => {
      const next = new Map(state.edited);
      next.delete(key);
      return { edited: next };
    });
    return entry.oldCategory;
  },

  clear: () => set({ edited: new Map() }),

  isEdited: (key) => get().edited.has(key),
}));

export { makeKey };
