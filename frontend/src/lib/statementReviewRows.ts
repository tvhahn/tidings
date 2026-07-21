// Pure state model + assembly logic for StatementReview.
//
// The component renders five reconciliation buckets (new, matched, ambiguous,
// previously_imported, suspected_duplicates). Each row carries a small piece of
// editable state — an action toggle plus a company/category the user can edit.
// This module owns the *pure* parts of that model so they can be unit-tested
// without mounting React:
//   - the discriminated-union row-state type keyed by `section`,
//   - seeding initial state from an upload response,
//   - classifying a field update into a save-dispatch mode,
//   - the per-section assembly of the final import payload (handleSubmit),
//   - bulk action flips and small count/query helpers.
//
// Row keys are the positional `index` from the parser. Indices are unique
// across buckets (each parsed row lands in exactly one bucket), so a single flat
// `Record<number, RowState>` replaces the five per-bucket Records that used to
// live in the component.
import type { ImportAction, StatementUploadResponse } from "@/types/api";

export type SectionKey =
  | "new"
  | "matched"
  | "ambiguous"
  | "previously_imported"
  | "suspected_duplicates";

export type NewAction = "import" | "skip";
export type EnrichAction = "enrich" | "skip";
export type UpdateAction = "update" | "skip";
export type DupAction = "import" | "skip";

interface RowFields {
  company: string;
  category: string;
}

/** Row-state discriminated union keyed by `section`. The action literal set
 *  differs per section; company/category are shared. */
export type RowState =
  | ({ section: "new"; action: NewAction } & RowFields)
  | ({ section: "matched"; action: EnrichAction } & RowFields)
  | ({ section: "ambiguous"; action: EnrichAction } & RowFields)
  | ({ section: "previously_imported"; action: UpdateAction } & RowFields)
  | ({ section: "suspected_duplicates"; action: DupAction } & RowFields);

export type RowStates = Record<number, RowState>;

/** A partial field update dispatched from a row control. `action` is loosely
 *  typed because callers pass section-specific literals; `mergeRow` re-narrows. */
export interface RowUpdate {
  action?: string;
  company?: string;
  category?: string;
}

export type SaveMode = "immediate" | "debounced" | "none";

/** Seed row state for every bucket. Defaults mirror the original component:
 *  new→import, ambiguous→enrich, matched→enrich iff company_differs else skip,
 *  previously_imported→skip, suspected_duplicates→skip. */
export function initRowStates(data: StatementUploadResponse): RowStates {
  const states: RowStates = {};
  for (const item of data.new) {
    states[item.index] = {
      section: "new",
      action: "import",
      company: item.raw_description,
      category: item.suggested_category,
    };
  }
  for (const item of data.matched) {
    states[item.index] = {
      section: "matched",
      action: item.company_differs ? "enrich" : "skip",
      company: item.raw_description,
      category: item.suggested_category,
    };
  }
  for (const item of data.ambiguous) {
    states[item.index] = {
      section: "ambiguous",
      action: "enrich",
      company: item.raw_description,
      category: item.suggested_category,
    };
  }
  for (const item of data.previously_imported || []) {
    states[item.index] = {
      section: "previously_imported",
      action: "skip",
      company: item.raw_description,
      category: item.suggested_category,
    };
  }
  for (const item of data.suspected_duplicates || []) {
    states[item.index] = {
      section: "suspected_duplicates",
      action: "skip",
      company: item.raw_description,
      category: item.suggested_category,
    };
  }
  return states;
}

/** Merge an update into a row, preserving the discriminant. */
export function mergeRow(current: RowState, updates: RowUpdate): RowState {
  return { ...current, ...updates } as RowState;
}

/** Which save mode a field update triggers. Priority mirrors the original
 *  makeRowUpdater exactly: action→immediate, else company→debounced, else
 *  category→immediate. Company is the ONLY debounced field. */
export function classifyUpdate(updates: RowUpdate): SaveMode {
  if (updates.action !== undefined) return "immediate";
  if (updates.company !== undefined) return "debounced";
  if (updates.category !== undefined) return "immediate";
  return "none";
}

/** All row states belonging to one section (insertion order). */
export function sectionStates(states: RowStates, section: SectionKey): RowState[] {
  return Object.values(states).filter((s) => s.section === section);
}

/** Count rows in a section currently set to `action`. */
export function countAction(states: RowStates, section: SectionKey, action: string): number {
  return sectionStates(states, section).filter((s) => s.action === action).length;
}

/** True when at least one row in the section is NOT already `action` — i.e. a
 *  bulk button would actually flip something. */
export function someActionNot(states: RowStates, section: SectionKey, action: string): boolean {
  return sectionStates(states, section).some((s) => s.action !== action);
}

/** Flip every row in `section` to `action`. Returns the next state map plus the
 *  indices whose action actually changed (those need a save dispatched). */
export function bulkSetSectionAction(
  states: RowStates,
  section: SectionKey,
  action: string
): { next: RowStates; changed: number[] } {
  const next: RowStates = { ...states };
  const changed: number[] = [];
  for (const [key, val] of Object.entries(states)) {
    if (val.section !== section) continue;
    const idx = Number(key);
    if (val.action !== action) changed.push(idx);
    next[idx] = { ...val, action } as RowState;
  }
  return { next, changed };
}

/** Aggregate counts for the submit bar / button label. */
export function summarizeStates(states: RowStates): {
  importCount: number;
  enrichCount: number;
  updateCount: number;
} {
  const importCount =
    countAction(states, "new", "import") + countAction(states, "suspected_duplicates", "import");
  const enrichCount =
    countAction(states, "ambiguous", "enrich") + countAction(states, "matched", "enrich");
  const updateCount = countAction(states, "previously_imported", "update");
  return { importCount, enrichCount, updateCount };
}

/** Assemble the import payload from the current row states. This is a faithful
 *  extraction of the original handleSubmit — same section order, same
 *  ambiguous candidate-claiming (first-come-first-served over `data.ambiguous`),
 *  same skip/omit rules. */
export function assembleImportActions(
  data: StatementUploadResponse,
  states: RowStates
): ImportAction[] {
  const actions: ImportAction[] = [];

  // New — every seeded row is pushed with its action (import or skip).
  for (const item of data.new) {
    const state = states[item.index];
    if (!state) continue;
    actions.push({
      index: item.index,
      action: state.action,
      category: state.category,
      company: state.company,
    });
  }

  // Ambiguous — enrich rows claim a unique DB candidate, first-come first-served.
  const usedAmbiguousKeys = new Set<string>();
  for (const item of data.ambiguous) {
    const state = states[item.index];
    if (state && state.action === "enrich") {
      const candidate = item.candidates.find(
        (c) => !usedAmbiguousKeys.has(`${c.forwarded_to}|${c.date_file_name}`)
      );
      if (candidate) {
        usedAmbiguousKeys.add(`${candidate.forwarded_to}|${candidate.date_file_name}`);
        actions.push({
          index: item.index,
          action: "enrich",
          company: state.company,
          category: state.category,
          forwarded_to: candidate.forwarded_to,
          date_file_name: candidate.date_file_name,
        });
      } else {
        // All candidates already claimed — skip.
        actions.push({ index: item.index, action: "skip" });
      }
    } else {
      actions.push({ index: item.index, action: "skip" });
    }
  }

  // Matched — enrichable rows may be enriched against their single db_match.
  for (const item of data.matched) {
    const state = states[item.index];
    if (state && state.action === "enrich") {
      actions.push({
        index: item.index,
        action: "enrich",
        company: state.company,
        category: state.category,
        forwarded_to: item.db_match.forwarded_to,
        date_file_name: item.db_match.date_file_name,
      });
    }
  }

  // Previously imported — rows toggled to "update".
  for (const item of data.previously_imported || []) {
    const state = states[item.index];
    if (state && state.action === "update") {
      actions.push({
        index: item.index,
        action: "update",
        company: state.company,
        category: state.category,
        forwarded_to: item.db_match.forwarded_to,
        date_file_name: item.db_match.date_file_name,
      });
    }
  }

  // Suspected duplicates — every seeded row pushed as import or skip.
  for (const item of data.suspected_duplicates || []) {
    const state = states[item.index];
    if (!state) continue;
    if (state.action === "import") {
      actions.push({
        index: item.index,
        action: "import",
        category: state.category,
        company: state.company,
      });
    } else {
      actions.push({ index: item.index, action: "skip" });
    }
  }

  return actions;
}
