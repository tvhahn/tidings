/** Single source of truth for the Journal headline's pace verdict.
 *
 *  Both the bar color (`tone`) and the words (`label`) come from the SAME
 *  branch here, so they can never disagree — the invariant `JournalHeadline`
 *  used to hold by mirroring two parallel ternaries (`barTone` / `paceLabel`).
 *
 *  When a commitment-aware projection is available (`projectedPct` non-null),
 *  the verdict keys on projected month-end vs. budget. Without it, the current
 *  spent-vs-elapsed thresholds stay, so the null-projection path is behavior-
 *  neutral against the shipped component. Pure — no React, no side effects. */

export type VerdictTone = "success" | "warning" | "danger";

export interface HeadlineVerdict {
  tone: VerdictTone;
  label: string;
}

export interface HeadlineVerdictArgs {
  /** 0–100+, spent share of budget. */
  spentPct: number;
  /** 0–100, today's elapsed-month position. */
  pacePct: number;
  /** 0–100+, projected month-end share of budget. Null when no commitment-aware
   *  projection exists (past months, no history, API failure) — the verdict
   *  falls back to the spent-vs-elapsed thresholds. */
  projectedPct: number | null;
}

// Locked thresholds. Commented so a later tune is a one-line change and the
// intent is legible next to the branch that reads it.
/** Projected month-end within a hair of the ceiling reads as a warning, not a
 *  clean pass — the last few points before 100% of budget. */
const CLOSE_TO_CEILING_PCT = 97;
/** Fallback band: how far spent may drift from elapsed before the words change.
 *  Mirrors `JournalHeadline`'s original `pacePct ± 5`. */
const PACE_TOLERANCE_PCT = 5;

export function headlineVerdict({
  spentPct,
  pacePct,
  projectedPct,
}: HeadlineVerdictArgs): HeadlineVerdict {
  if (projectedPct != null) {
    // Commitment-aware: honest end-of-month projection vs. the ceiling.
    if (projectedPct > 100) return { tone: "danger", label: "Over ceiling" };
    if (projectedPct > CLOSE_TO_CEILING_PCT) return { tone: "warning", label: "Close to ceiling" };
    return { tone: "success", label: "On pace" };
  }

  // Fallback — reproduces JournalHeadline's spent-vs-elapsed thresholds exactly
  // so the later rewire is behavior-neutral for null-projection months.
  if (spentPct >= 100) return { tone: "danger", label: "Over ceiling" };
  if (spentPct > pacePct + PACE_TOLERANCE_PCT) return { tone: "warning", label: "Ahead of pace" };
  if (spentPct >= pacePct - PACE_TOLERANCE_PCT) return { tone: "success", label: "On pace" };
  return { tone: "success", label: "Under pace" };
}
