/**
 * Display-layer safety net for AI day-summary text.
 *
 * The summarization model occasionally echoes raw merchant descriptors in
 * ALL-CAPS ("WESTLAND UTILITY CO was the day's largest…"). This transform
 * softens runs of consecutive all-caps tokens to first-char-preserved
 * capitalization at render time only — it does NOT modify the stored summary.
 *
 * Single isolated all-caps tokens (acronyms like "CRA", "AWS", "GST") are left
 * untouched; only runs of 2+ adjacent all-caps tokens qualify, since a run is
 * what reads as a shouted merchant name rather than an intentional acronym.
 */

// A token qualifies as "all-caps" if it is >=2 chars, holds at least one A-Z
// letter, has no lowercase letters, and consists only of the allowed charset
// (uppercase letters, digits, and the punctuation that shows up inside merchant
// descriptors).
const ALLOWED_TOKEN = /^[A-Z0-9&'’.\-#*]+$/;

function isAllCapsToken(token: string): boolean {
  if (token.length < 2) return false;
  if (!/[A-Z]/.test(token)) return false;
  if (/[a-z]/.test(token)) return false;
  return ALLOWED_TOKEN.test(token);
}

// Title-case a single token: first character unchanged, remaining letters
// lowercased (digits untouched). Tokens containing `&` or `.` are left as-is
// so "A&W" and initialisms with periods survive verbatim.
function softenToken(token: string): string {
  if (token.includes("&") || token.includes(".")) return token;
  return token.charAt(0) + token.slice(1).toLowerCase();
}

export function titleCaseAllCapsRuns(text: string): string {
  if (!text) return text;
  // Split on whitespace while preserving the exact whitespace separators so the
  // output re-joins identically.
  const parts = text.split(/(\s+)/);
  // parts alternates token, whitespace, token, whitespace, ... — tokens sit at
  // even indices. Collect the token indices so we can detect adjacency runs.
  const tokenIndices: number[] = [];
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0 && parts[i] !== "") tokenIndices.push(i);
  }

  const qualifies = tokenIndices.map((i) => isAllCapsToken(parts[i] as string));

  // Walk consecutive qualifying tokens; a run of length >=2 gets softened.
  let runStart = 0;
  while (runStart < tokenIndices.length) {
    if (!qualifies[runStart]) {
      runStart++;
      continue;
    }
    let runEnd = runStart;
    while (runEnd + 1 < tokenIndices.length && qualifies[runEnd + 1]) {
      runEnd++;
    }
    if (runEnd > runStart) {
      for (let r = runStart; r <= runEnd; r++) {
        const idx = tokenIndices[r] as number;
        parts[idx] = softenToken(parts[idx] as string);
      }
    }
    runStart = runEnd + 1;
  }

  return parts.join("");
}
