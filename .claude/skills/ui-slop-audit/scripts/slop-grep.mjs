#!/usr/bin/env node
// slop-grep.mjs — deterministic UI-slop static checker for Tidings (ui-slop-audit v2).
// Node ESM, built-ins only (fs, path). READ-ONLY: never writes into the repo.
//
// ─────────────────────────────────────────────────────────────────────────────
// REFERENCE IMPLEMENTATION. This is a TESTED copy produced during the research for
// this spec (validated against frontend/src on 2026-07-01: 88 findings — P0=1,
// P1=17, P2=70; correctly flags InsightsSparkline.tsx:65 "fingernails" and excludes
// every §1 carve-out). The implementing agent should COPY this verbatim to
//   .claude/skills/ui-slop-audit/scripts/slop-grep.mjs
// then add the --report / --fail-on flags per IMPLEMENTATION_PLAN.md Phase 3, and
// re-run to confirm the same baseline. Do NOT install anything; this has no deps.
// ─────────────────────────────────────────────────────────────────────────────
//
// Usage:
//   node slop-grep.mjs [roots...] [--json] [--index-css <path>] [--include-marketing]
//
// Defaults: roots = <repo>/frontend/src and <repo>/frontend/public/demo-data (auto-detected
// relative to this file's location so a bare `node slop-grep.mjs` "just works").
//
// Token allow-lists (radius ramp, type scale, --font-* families) are PARSED from
// frontend/src/index.css at runtime — the registry stays wired to the real @theme tokens,
// so a token change updates the allow-lists with zero code edits. If index.css can't be
// found, a hardcoded fallback (extracted from index.css on 2026-07-01) is used.
//
// Exit code: 2 if any P0 rule matches (gate), else 0 (non-blocking for P1/P2).

import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import { join, resolve, dirname, basename, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Repo discovery: walk up from CWD / this file looking for a frontend/src dir.
// ---------------------------------------------------------------------------
function findFrontendSrc() {
  const seeds = [process.cwd(), HERE, "/workspace"];
  for (const seed of seeds) {
    let dir = resolve(seed);
    for (let i = 0; i < 8; i++) {
      const candidate = join(dir, "frontend", "src");
      if (existsSync(candidate)) return candidate;
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// CLI parse
// ---------------------------------------------------------------------------
const argv = process.argv.slice(2);
const flags = { json: false, includeMarketing: false, indexCss: null, report: false, failOn: "P0" };
const roots = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--json") flags.json = true;
  else if (a === "--include-marketing") flags.includeMarketing = true;
  else if (a === "--index-css") flags.indexCss = argv[++i];
  else if (a === "--report") flags.report = true;
  else if (a === "--fail-on") flags.failOn = (argv[++i] || "").toUpperCase();
  else if (a.startsWith("--fail-on=")) flags.failOn = a.slice("--fail-on=".length).toUpperCase();
  else roots.push(resolve(a));
}
if (!["P0", "P1", "P2"].includes(flags.failOn)) {
  console.error(`slop-grep: --fail-on must be one of P0|P1|P2 (got "${flags.failOn}").`);
  process.exit(1);
}

const frontendSrc = findFrontendSrc();
if (roots.length === 0) {
  if (frontendSrc) {
    roots.push(frontendSrc);
    const demo = resolve(frontendSrc, "..", "public", "demo-data");
    if (existsSync(demo)) roots.push(demo);
  } else {
    console.error("slop-grep: could not locate frontend/src; pass a root explicitly.");
    process.exit(1);
  }
}
const indexCssPath =
  flags.indexCss ||
  (frontendSrc && existsSync(join(frontendSrc, "index.css")) ? join(frontendSrc, "index.css") : null);

// ---------------------------------------------------------------------------
// Token allow-lists — parsed from index.css (fallback hardcoded from 2026-07-01).
// ---------------------------------------------------------------------------
function parseTokens(cssPath) {
  const fallback = {
    radiusPx: new Set([4, 6, 10, 12, 14, 20, 999]),
    typePx: new Set([44, 26, 20, 16, 14, 12.5, 11, 15, 28]),
    fontVars: new Set(["--font-sans", "--font-serif", "--font-mono"]),
    source: "hardcoded-fallback",
  };
  if (!cssPath || !existsSync(cssPath)) return fallback;
  const css = readFileSync(cssPath, "utf8");
  const radiusPx = new Set();
  const typePx = new Set();
  const fontVars = new Set();
  // --radius-xs: 4px;  --radius-tidings-lg: 14px;  --radius-full: 999px;
  for (const m of css.matchAll(/--radius[\w-]*\s*:\s*([\d.]+)px\b/g)) radiusPx.add(Number(m[1]));
  // --t-h1-size: 26px;  --t-small-size: 12.5px;
  for (const m of css.matchAll(/--t-[\w-]*-size\s*:\s*([\d.]+)px\b/g)) typePx.add(Number(m[1]));
  // --font-sans / --font-serif / --font-mono
  for (const m of css.matchAll(/(--font-(?:sans|serif|mono))\s*:/g)) fontVars.add(m[1]);
  ["--font-sans", "--font-serif", "--font-mono"].forEach((f) => fontVars.add(f));
  if (radiusPx.size === 0 || typePx.size === 0) return fallback;
  return { radiusPx, typePx, fontVars, source: cssPath };
}
const tokens = parseTokens(indexCssPath);

// ---------------------------------------------------------------------------
// Carve-outs
// ---------------------------------------------------------------------------
// CSS selectors whose gradients are functional affordances, not decoration.
const FUNCTIONAL_GRADIENT_SELECTORS = new Set([".scroll-shadow-x"]);
// Loading-context signals that make animate-spin / animate-pulse functional.
const LOADING_CONTEXT =
  /Loader2?\b|Spinner|Skeleton|isLoading|isPending|isFetching|\bloading\b|role=["']status["']|aria-busy/i;

// ---------------------------------------------------------------------------
// File walking + global excludes
// ---------------------------------------------------------------------------
const EXCLUDE_SEGMENTS = ["node_modules", "dist", "build", ".git", "coverage", "__tests__", "e2e"];
function isExcludedPath(p) {
  const parts = p.split(sep);
  if (parts.some((seg) => EXCLUDE_SEGMENTS.includes(seg))) return true;
  if (/\.(test|spec)\.[cm]?[jt]sx?$/.test(p)) return true;
  if (/\.stories\.[cm]?[jt]sx?$/.test(p)) return true;
  // marketing/ is NOT excluded here — voice rules (rule.voice) always scan it;
  // all other rules skip it at match time unless --include-marketing (see scan loop).
  return false;
}
const isMarketingPath = (p) => p.split(sep).includes("marketing");
function walk(root) {
  const out = [];
  if (!existsSync(root)) return out;
  const st = statSync(root);
  if (st.isFile()) return isExcludedPath(root) ? [] : [root];
  for (const name of readdirSync(root, { recursive: true })) {
    const full = join(root, name);
    if (isExcludedPath(full)) continue;
    let s;
    try {
      s = statSync(full);
    } catch {
      continue;
    }
    if (s.isFile()) out.push(full);
  }
  return out;
}

function extOf(p) {
  const b = basename(p);
  const i = b.lastIndexOf(".");
  return i < 0 ? "" : b.slice(i + 1).toLowerCase();
}
const CODE_EXT = new Set(["tsx", "ts", "jsx", "js"]);
const CSS_EXT = new Set(["css"]);
const isCode = (p) => CODE_EXT.has(extOf(p));
const isCss = (p) => CSS_EXT.has(extOf(p));
const isJson = (p) => extOf(p) === "json";

// Precompute enclosing CSS selector stacks per line (light brace tracker).
function cssSelectorStacks(lines) {
  const perLine = [];
  const stack = [];
  let pending = "";
  for (const raw of lines) {
    perLine.push(stack.slice());
    let line = raw.replace(/\/\*.*?\*\//g, "");
    for (const ch of line) {
      if (ch === "{") {
        stack.push(pending.trim().split(/\s+/).pop() || pending.trim());
        pending = "";
      } else if (ch === "}") {
        stack.pop();
        pending = "";
      } else if (ch === ";") {
        pending = "";
      } else {
        pending += ch;
      }
    }
  }
  return perLine;
}

// ---------------------------------------------------------------------------
// Rule registry
// ---------------------------------------------------------------------------
// Each rule: { id, family, severity, counterMove, scan(path), regex, keep(ctx) }
// keep(ctx) returns true to record the hit (false = suppressed carve-out).
// ctx = { m, line, lineNo, lines, path, cssStack, tokens, escalate() }
const rules = [
  {
    id: "font-literal-off-token",
    family: "A",
    severity: "P1",
    counterMove: "swap-for-type",
    description: "font-family / font-[…] literal not resolving to a --font-{sans,serif,mono} token.",
    scan: (p) => isCode(p) || isCss(p),
    regex: /font-family\s*:\s*([^;{}]+)|font-\[([^\]]+)\]/g,
    keep: ({ m }) => {
      const val = (m[1] || m[2] || "").trim();
      if (/var\(\s*--font-(sans|serif|mono)\s*\)/.test(val)) return false;
      // A bare `font-family: var(--font-...)` alias line is fine; anything else is a literal.
      return true;
    },
  },
  {
    id: "arbitrary-type-size",
    family: "A",
    severity: "P2",
    counterMove: "align-to-token",
    description: "text-[<n>px] literal off the type scale (--t-*-size tokens).",
    scan: isCode,
    regex: /text-\[([\d.]+)px\]/g,
    keep: ({ m, tokens }) => !tokens.typePx.has(Number(m[1])),
  },
  {
    id: "raw-bw-literal",
    family: "B",
    severity: "P1",
    counterMove: "align-to-token",
    description: "Raw #000/#fff hex or Tailwind black/white instead of an oklch token.",
    scan: (p) => isCode(p) || isCss(p),
    regex:
      /#(?:fff|000|ffffff|000000)\b|\b(?:text|bg|border|ring|fill|stroke|from|to|via|divide|outline|decoration|caret|accent|placeholder)-(?:black|white)\b/g,
    keep: () => true,
  },
  {
    id: "gradient-anywhere",
    family: "B",
    severity: "P0",
    counterMove: "remove",
    description: "Gradient fill/text (bg-gradient/linear/radial/conic, bg-clip-text, *-gradient()).",
    scan: (p) => isCode(p) || isCss(p),
    regex:
      /\bbg-gradient-to-[a-z]{1,2}\b|\bbg-(?:linear|radial|conic)(?:-to-[a-z]{1,2})?\b|\bbg-clip-text\b|\bbg-\[(?:linear|radial|conic)-gradient|(?:linear|radial|conic)-gradient\s*\(/g,
    keep: ({ path, cssStack, lineNo }) => {
      if (!isCss(path)) return true;
      const stack = cssStack ? cssStack[lineNo - 1] || [] : [];
      // Suppress functional scroll-shadow gradients (token-sourced overflow affordance).
      if (stack.some((s) => FUNCTIONAL_GRADIENT_SELECTORS.has(s))) return false;
      return true;
    },
  },
  {
    id: "glass-blur",
    family: "B/E",
    severity: "P0",
    counterMove: "remove",
    description: "Glassmorphism: backdrop-blur / backdrop-filter.",
    scan: (p) => isCode(p) || isCss(p),
    regex: /\bbackdrop-blur(?:-[a-z0-9]+)?\b|backdrop-filter\s*:/g,
    keep: () => true,
  },
  {
    id: "colored-glow-shadow",
    family: "C/E",
    severity: "P1",
    counterMove: "align-to-token",
    description: "Arbitrary colored/glow shadow (shadow-[…color…] / drop-shadow-[…]) off the shadow tokens.",
    scan: isCode,
    regex: /\b(?:drop-)?shadow-\[([^\]]+)\]/g,
    keep: ({ m }) => {
      const val = m[1] || "";
      // Only flag when the arbitrary shadow carries a color (a glow), not e.g. shadow-[0_1px_0].
      return /oklch|rgb|hsl|#|\bvar\(|color-mix|\/\d/.test(val);
    },
  },
  {
    id: "equal-thirds",
    family: "D",
    severity: "P2",
    counterMove: "tighten-spacing",
    description:
      "grid-cols-3 (heuristic pointer for three equal sibling cards — needs human confirm of card identity).",
    scan: isCode,
    regex: /\b(?:sm:|md:|lg:|xl:|2xl:)?grid-cols-3\b/g,
    keep: () => true,
  },
  {
    id: "perpetual-motion",
    family: "E",
    severity: "P1",
    counterMove: "remove",
    description:
      "animate-bounce/ping/pulse/spin outside a loading context (spin/pulse suppressed near a loader/skeleton).",
    scan: isCode,
    regex: /\banimate-(bounce|ping|pulse|spin)\b/g,
    keep: ({ m, lineNo, lines, path }) => {
      const kind = m[1];
      if (kind === "bounce" || kind === "ping") return true; // decorative/attention motion
      // spin / pulse: functional if a loader/skeleton signal is nearby or file is a skeleton primitive.
      if (/skeleton/i.test(basename(path))) return false;
      for (let d = -2; d <= 2; d++) {
        const l = lines[lineNo - 1 + d];
        if (l && LOADING_CONTEXT.test(l)) return false;
      }
      return true;
    },
  },
  {
    id: "radius-off-token",
    family: "C",
    severity: "P2", // escalates to P1 on data-viz elements (see escalate())
    counterMove: "square",
    description:
      "rounded[-side]-[<n>px] literal off the radius ramp (--radius-xs 4px … --radius-full 999px). Catches the sparkline 'fingernails'.",
    scan: isCode,
    regex: /\brounded(?:-(?:t|b|l|r|tl|tr|bl|br|s|e|ss|se|es|ee))?-\[([\d.]+)px\]/g,
    keep: ({ m, tokens }) => !tokens.radiusPx.has(Number(m[1])),
    escalate: ({ path, line }) =>
      /spark|chart|\bbar\b|recharts|sankey|graph|\bviz\b/i.test(basename(path)) ||
      /spark|chart|recharts|sankey|data-viz/i.test(line)
        ? "P1"
        : null,
  },
  {
    id: "round-fake-number",
    family: "F",
    severity: "P2",
    counterMove: "align-to-token",
    description: "Suspiciously clean money/placeholder data ($X.00, 99.99, X.00%, John Doe/Acme/Lorem/SmartFlow).",
    scan: (p) => isCode(p) || isJson(p),
    regex:
      /\$\d{1,3}(?:,\d{3})*\.00\b|\b99\.99\b|\b\d+\.00%|\b(?:John Doe|Jane Doe|Acme|Lorem ipsum|SmartFlow|Foo Bar)\b/g,
    keep: () => true,
  },
  {
    id: "emoji-in-ui",
    family: "F/G",
    severity: "P1",
    counterMove: "swap-for-type",
    description: "Emoji codepoints in UI strings (banned by brand voice). Arrows/typographic marks are NOT flagged.",
    scan: (p) => isCode(p) || isJson(p),
    // Real emoji ranges; deliberately excludes arrows U+2190–21FF and math/tech marks.
    regex:
      /[\u{1F000}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]\u{FE0F}?/gu,
    keep: () => true,
  },
  {
    id: "generic-cta",
    family: "G",
    severity: "P2",
    counterMove: "swap-for-type",
    description: "Generic CTA copy (Get Started / Learn More / Submit …) as a visible label, not code.",
    scan: isCode,
    regex:
      /(?<![A-Za-z])(Get Started|Learn More|Read More|Click Here|Sign Up Now|Discover More|Start Now|Try It Free|Submit)(?![A-Za-z(])/g,
    keep: ({ line }) => !/type\s*=\s*["']submit["']|on[A-Z]\w*Submit|handleSubmit|\bsubmitting\b/.test(line),
  },

  // ── Voice rules (docs/brand/voice.md absolutes, graduated by the 2026-07-15
  //    basis audit, G4). rule.voice: always scan marketing/ — voice applies to
  //    every user-facing string, and marketing is the highest-stakes surface.
  {
    id: "voice-exclamation",
    family: "G",
    severity: "P0",
    voice: true,
    counterMove: "swap-for-type",
    description:
      'Exclamation mark in copy — a string ending "…word!" or JSX text containing one. voice.md: "No exclamation marks. Ever."',
    scan: (p) => isCode(p) || isJson(p),
    regex: /[A-Za-z]![.…]?["'`]|>[^<>{}\n]*[A-Za-z]![^<>{}\n]*</g,
    keep: ({ line }) => !/!important|\brepresent!|![=~]/.test(line),
  },
  {
    id: "voice-banned-word",
    family: "G",
    severity: "P0",
    voice: true,
    counterMove: "swap-for-type",
    description:
      "Banned growth/hype vocabulary in a user-facing string (voice.md §3 banned words — high-precision subset).",
    scan: (p) => isCode(p) || isJson(p),
    regex:
      /\b(unlock|supercharge|skyrocket|crush|conquer|boost|effortless|seamless|revolutionary|disrupt|oops|whoops|awesome|amazing|magical|streak)\b|\blevel up\b/gi,
    keep: inCopyContext,
  },
  {
    id: "voice-banned-word-review",
    family: "G",
    severity: "P1",
    voice: true,
    counterMove: "swap-for-type",
    description:
      "Ambiguous banned-word candidates (win/level/score/achievement/challenge/urgent/critical/danger) in a user-facing string — human judges intent.",
    scan: (p) => isCode(p) || isJson(p),
    // Custom boundaries: hyphen/word chars on either side mean a token
    // (status-danger, danger-wash), which voice.md explicitly permits.
    regex: /(?<![-\w])(win|wins|level|score|achievement|challenge|urgent|critical|danger)(?![-\w])/gi,
    keep: (ctx) => inCopyContext(ctx) && !isBareTokenLiteral(ctx),
  },
  {
    id: "voice-title-case-label",
    family: "G",
    severity: "P1",
    voice: true,
    counterMove: "swap-for-type",
    description:
      "Title Case multi-word label inside an interactive element — voice.md mandates sentence case (proper nouns are the false-positive class; judge).",
    scan: isCode,
    regex: /<(Button|TabsTrigger|DropdownMenuItem|Badge|Link)\b[^>]*>\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\s*</g,
    keep: () => true,
  },
];

// A match counts as copy only inside a string literal or JSX text — an odd
// number of quote chars before the match means "inside a string"; a `>` with
// no subsequent `<`/`{` means JSX text. Comments and identifiers stay exempt.
function inCopyContext({ line, m }) {
  const before = line.slice(0, m.index);
  // Comments, imports, and re-exports carry identifiers/paths, not copy.
  // Plain `export const X = <p>…` stays eligible — one-liner components hold real copy.
  if (/^\s*(\/\/|\/?\*|import\b|export\s+(type\s+)?[{*].*\bfrom\b)/.test(line)) return false;
  const quotes = (before.match(/["'`]/g) || []).length;
  if (quotes % 2 === 1) return true;
  return />[^<{]*$/.test(before);
}

// `return "danger"` / `tone: "critical"` — a string literal that is EXACTLY the
// word is an internal token, not copy (copy is a sentence). Quote directly on
// both sides of the match means bare token.
function isBareTokenLiteral({ line, m }) {
  const pre = line[m.index - 1];
  const post = line[m.index + m[0].length];
  return /["'`]/.test(pre || "") && /["'`]/.test(post || "");
}

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------
const files = [...new Set(roots.flatMap(walk))];
const findings = [];

for (const path of files) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    continue;
  }
  const lines = text.split(/\r?\n/);
  const cssStack = isCss(path) ? cssSelectorStacks(lines) : null;

  const marketing = isMarketingPath(path);
  for (const rule of rules) {
    if (marketing && !rule.voice && !flags.includeMarketing) continue;
    if (!rule.scan(path)) continue;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const re = new RegExp(rule.regex.source, rule.regex.flags);
      let m;
      while ((m = re.exec(line)) !== null) {
        if (m[0] === "") {
          re.lastIndex++;
          continue;
        }
        const ctx = { m, line, lineNo: i + 1, lines, path, cssStack, tokens };
        if (rule.keep && !rule.keep(ctx)) continue;
        let severity = rule.severity;
        if (rule.escalate) severity = rule.escalate(ctx) || severity;
        findings.push({
          rule: rule.id,
          family: rule.family,
          severity,
          counter_move: rule.counterMove,
          file: path,
          line: i + 1,
          col: m.index + 1,
          match: m[0],
          text: line.trim().slice(0, 160),
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------
const SEV_ORDER = { P0: 0, P1: 1, P2: 2 };
findings.sort(
  (a, b) =>
    SEV_ORDER[a.severity] - SEV_ORDER[b.severity] ||
    a.rule.localeCompare(b.rule) ||
    a.file.localeCompare(b.file) ||
    a.line - b.line
);

const p0count = findings.filter((f) => f.severity === "P0").length;

// Gate decision. Default gates on P0 (exit 2) exactly as before. `--report` never
// gates (always exit 0); `--fail-on=<P0|P1|P2>` gates when any finding at or above
// that severity exists. This flag layer does not touch the rules or their severities.
const gateOrder = SEV_ORDER[flags.failOn];
const gatingCount = findings.filter((f) => SEV_ORDER[f.severity] <= gateOrder).length;
const willGate = !flags.report && gatingCount > 0;

if (flags.json) {
  console.log(
    JSON.stringify(
      {
        roots,
        index_css: indexCssPath,
        token_source: tokens.source,
        allow_lists: {
          radius_px: [...tokens.radiusPx].sort((a, b) => a - b),
          type_px: [...tokens.typePx].sort((a, b) => a - b),
          font_vars: [...tokens.fontVars],
        },
        files_scanned: files.length,
        total: findings.length,
        p0: p0count,
        report: flags.report,
        fail_on: flags.failOn,
        gating: gatingCount,
        findings,
      },
      null,
      2
    )
  );
} else {
  const rel = (p) => (frontendSrc ? p.replace(resolve(frontendSrc, "..", ".."), "").replace(/^\//, "") : p);
  console.log("slop-grep — deterministic UI-slop static checks (ui-slop-audit v2)");
  console.log(`  token source : ${tokens.source}`);
  console.log(`  radius ramp  : ${[...tokens.radiusPx].sort((a, b) => a - b).join(", ")} (px)`);
  console.log(`  type scale   : ${[...tokens.typePx].sort((a, b) => a - b).join(", ")} (px)`);
  console.log(`  roots        : ${roots.map(rel).join(", ")}`);
  console.log(`  files scanned: ${files.length}`);
  console.log("");
  const byRule = new Map();
  for (const f of findings) {
    if (!byRule.has(f.rule)) byRule.set(f.rule, []);
    byRule.get(f.rule).push(f);
  }
  for (const rule of rules) {
    const hits = byRule.get(rule.id) || [];
    const sev = hits.length ? [...new Set(hits.map((h) => h.severity))].join("/") : rule.severity;
    console.log(`▸ ${rule.id}  [family ${rule.family}] [${sev}] [cure: ${rule.counterMove}] — ${hits.length} hit(s)`);
    for (const h of hits) {
      console.log(`    ${rel(h.file)}:${h.line}:${h.col}  ${h.match}   ⟨${h.text}⟩`);
    }
  }
  console.log("");
  console.log(
    `Summary: ${findings.length} finding(s) — ` +
      `P0=${p0count}  P1=${findings.filter((f) => f.severity === "P1").length}  ` +
      `P2=${findings.filter((f) => f.severity === "P2").length}`
  );
  if (flags.report) {
    console.log(`REPORT (non-blocking): exit 0 regardless of severity. ${p0count} P0 finding(s) present.`);
  } else {
    console.log(
      willGate
        ? `FAIL: ${gatingCount} finding(s) at or above ${flags.failOn} — gating exit 2.`
        : `OK: no findings at or above ${flags.failOn}.`
    );
  }
}

process.exit(willGate ? 2 : 0);
