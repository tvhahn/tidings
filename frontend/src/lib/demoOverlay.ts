import type { BudgetConfigUpdateRequest, Transaction } from "@/types/api";

/**
 * Partial transaction state written by demo mutations (markReviewed,
 * setIgnored, setComment, softDelete, permanentDelete). Applied on top of
 * the underlying fixture when reads run through applyTxState.
 */
export type TxStateOverlay = {
  reviewed?: boolean;
  ignored?: boolean;
  comment?: string | null;
  deleted_at?: string | null;
  tombstone?: boolean;
};

/**
 * Category rule overlay — either sets a company→category mapping or deletes
 * a baseline mapping. Applied on top of overrides.json.
 */
export type OverrideOverlay = { action: "set"; category: string } | { action: "delete" };

type OverlayMap = {
  [K: `category-override:${string}:${string}`]: string;
  [K: `budget:${number}`]: BudgetConfigUpdateRequest;
  [K: `tx-state:${string}:${string}`]: TxStateOverlay;
  [K: `override:${string}`]: OverrideOverlay;
  [K: `override-dismissed:${string}:${string}`]: true;
  [K: `manual-tx:${string}`]: Transaction[];
};

const STORAGE_KEY_PREFIX = "demo-overlay:";

function storageKey(key: string): string {
  return `${STORAGE_KEY_PREFIX}${key}`;
}

function getStore(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function readOverlay<K extends keyof OverlayMap & string>(
  key: K
): OverlayMap[K] | undefined {
  const store = getStore();
  if (!store) return undefined;
  const raw = store.getItem(storageKey(key));
  if (raw === null) return undefined;
  try {
    return JSON.parse(raw) as OverlayMap[K];
  } catch {
    return undefined;
  }
}

export function writeOverlay<K extends keyof OverlayMap & string>(
  key: K,
  value: OverlayMap[K]
): void {
  const store = getStore();
  if (!store) return;
  store.setItem(storageKey(key), JSON.stringify(value));
}

export function deleteOverlay(key: string): void {
  const store = getStore();
  if (!store) return;
  store.removeItem(storageKey(key));
}

export function listByPrefix<T = unknown>(prefix: string): Array<{ key: string; value: T }> {
  const store = getStore();
  if (!store) return [];
  const out: Array<{ key: string; value: T }> = [];
  const full = `${STORAGE_KEY_PREFIX}${prefix}`;
  for (let i = 0; i < store.length; i++) {
    const k = store.key(i);
    if (!k || !k.startsWith(full)) continue;
    const raw = store.getItem(k);
    if (raw === null) continue;
    try {
      out.push({ key: k.slice(STORAGE_KEY_PREFIX.length), value: JSON.parse(raw) as T });
    } catch {
      // skip malformed entries
    }
  }
  return out;
}

export function categoryOverrideKey(
  forwardedTo: string,
  dateFileName: string
): `category-override:${string}:${string}` {
  return `category-override:${forwardedTo}:${dateFileName}`;
}

export function budgetOverrideKey(year: number): `budget:${number}` {
  return `budget:${year}`;
}

export function txStateKey(
  forwardedTo: string,
  dateFileName: string
): `tx-state:${string}:${string}` {
  return `tx-state:${forwardedTo}:${dateFileName}`;
}

export function overrideKey(company: string): `override:${string}` {
  return `override:${company}`;
}

export function overrideDismissedKey(
  company: string,
  category: string
): `override-dismissed:${string}:${string}` {
  return `override-dismissed:${company}:${category}`;
}

export function manualTxKey(month: string): `manual-tx:${string}` {
  return `manual-tx:${month}`;
}

/**
 * Append a user-added transaction to the per-month overlay. Reads the existing
 * array (if any), appends, and writes back. Returns the appended record so the
 * caller can echo it in a response.
 */
export function appendManualTransaction(month: string, tx: Transaction): Transaction {
  const key = manualTxKey(month);
  const existing = readOverlay(key) ?? [];
  const next: Transaction[] = [...existing, tx];
  writeOverlay(key, next);
  return tx;
}

export function readManualTransactions(month: string): Transaction[] {
  return readOverlay(manualTxKey(month)) ?? [];
}

/**
 * Merge the tx-state overlay for each transaction into the base fixture record.
 * Returned records are shallow clones; originals are untouched.
 */
export function applyTxState(transactions: Transaction[]): Transaction[] {
  const overlays = listByPrefix<TxStateOverlay>("tx-state:");
  if (overlays.length === 0) return transactions;
  const map = new Map<string, TxStateOverlay>();
  for (const { key, value } of overlays) {
    map.set(key.slice("tx-state:".length), value);
  }
  return transactions.map((t) => {
    const ov = map.get(`${t.forwarded_to}:${t.date_file_name}`);
    if (!ov) return t;
    const merged: Transaction = { ...t };
    if (ov.ignored !== undefined) merged.ignored = ov.ignored;
    if (ov.comment !== undefined) merged.comment = ov.comment;
    if (ov.deleted_at !== undefined) merged.deleted_at = ov.deleted_at;
    if (ov.reviewed === true) {
      merged.category_audit = {
        source: "manual",
        reviewed_at: new Date().toISOString(),
      };
    }
    return merged;
  });
}

/**
 * List all tx-state overlay entries. Used by fetchTrash to surface
 * overlay-deleted items that don't live in trash-{month}.json.
 */
export function listTxStateOverlays(): Array<{
  forwarded_to: string;
  date_file_name: string;
  state: TxStateOverlay;
}> {
  return listByPrefix<TxStateOverlay>("tx-state:").map(({ key, value }) => {
    const rest = key.slice("tx-state:".length);
    const idx = rest.indexOf(":");
    return {
      forwarded_to: rest.slice(0, idx),
      date_file_name: rest.slice(idx + 1),
      state: value,
    };
  });
}
