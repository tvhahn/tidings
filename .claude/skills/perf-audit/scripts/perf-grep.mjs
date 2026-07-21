#!/usr/bin/env node
// perf-grep.mjs — deterministic React-performance static checker (perf-audit skill).
// Node ESM, built-ins only (fs, path). READ-ONLY: never writes into the repo.
//
// Two rule sets:
//   • GENERIC rules (always on) — framework truths from the perf-audit frontend checklist
//     (rule ids cite the checklist: M5, C2, D1, W3, W4, F1/F2, K3, L1/L3, M2, I1).
//   • OVERLAY rules (on when a project overlay config is found) — repo anchors and
//     regression guards parsed from references/project-overlay.md's ```json config block:
//     required-pattern guards, month-prefetch-gap, staleTime/keepPreviousData factory
//     checks, eager-route guard, plus allow-lists that suppress generic rules.
//
// Usage:
//   node perf-grep.mjs [roots...] [--json] [--report] [--fail-on P0|P1|P2] [--overlay <path>]
//
// Defaults: root from overlay config (fallback: nearest frontend/src). In --json mode all
// logs go to stderr and stdout is a single JSON document. Findings are capped per rule
// (config maxPerRule, default 20) with the dropped count reported, so one noisy rule can't
// flood the report. Exit 2 when findings at/above --fail-on exist (default P0);
// --report never gates. Report-only rules (exhaustive-deps-suppression) never gate.

import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import { join, resolve, dirname, basename, sep, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------
const argv = process.argv.slice(2);
const flags = { json: false, report: false, failOn: "P0", overlay: null };
const rootArgs = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--json") flags.json = true;
  else if (a === "--report") flags.report = true;
  else if (a === "--overlay") flags.overlay = argv[++i];
  else if (a === "--fail-on") flags.failOn = (argv[++i] || "").toUpperCase();
  else if (a.startsWith("--fail-on=")) flags.failOn = a.slice("--fail-on=".length).toUpperCase();
  else rootArgs.push(resolve(a));
}
if (!["P0", "P1", "P2"].includes(flags.failOn)) {
  console.error(`perf-grep: --fail-on must be P0|P1|P2 (got "${flags.failOn}").`);
  process.exit(1);
}
const log = (...m) => console.error(...m); // stderr = logs; stdout = data

// ---------------------------------------------------------------------------
// Repo + overlay discovery
// ---------------------------------------------------------------------------
function findRepoRoot() {
  const seeds = [process.cwd(), HERE];
  for (const seed of seeds) {
    let dir = resolve(seed);
    for (let i = 0; i < 10; i++) {
      if (existsSync(join(dir, "frontend", "src")) || existsSync(join(dir, ".git"))) return dir;
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return process.cwd();
}
const repoRoot = findRepoRoot();

function loadOverlayConfig() {
  const candidates = flags.overlay
    ? [resolve(flags.overlay)]
    : [join(HERE, "..", "references", "project-overlay.md")];
  for (const p of candidates) {
    if (!existsSync(p)) continue;
    const md = readFileSync(p, "utf8");
    const m = md.match(/```json\s*\n([\s\S]*?)\n```/);
    if (!m) {
      log(`perf-grep: overlay found at ${p} but no \`\`\`json config block — generic rules only.`);
      return null;
    }
    try {
      const cfg = JSON.parse(m[1]);
      cfg.__source = p;
      return cfg;
    } catch (e) {
      log(`perf-grep: overlay config at ${p} is not valid JSON (${e.message}) — generic rules only.`);
      return null;
    }
  }
  log("perf-grep: no project overlay config found — running generic rules only.");
  return null;
}
const cfg = loadOverlayConfig();
const MAX_PER_RULE = cfg?.maxPerRule ?? 20;
const LOADING_VOCAB = cfg?.loadingFlagVocab ?? [
  "isFetching",
  "isPending",
  "isLoading",
  "isPlaceholderData",
];
const loadingRe = new RegExp(`\\b(?:${LOADING_VOCAB.join("|")})\\b`);

const roots = rootArgs.length
  ? rootArgs
  : [cfg?.root ? resolve(repoRoot, cfg.root) : join(repoRoot, "frontend", "src")].filter(existsSync);
if (roots.length === 0) {
  console.error("perf-grep: no scan root found; pass one explicitly.");
  process.exit(1);
}
const rel = (p) => relative(repoRoot, p);
// Does relpath end with any allow-list entry (entries are repo-relative suffixes)?
const inList = (path, list) => {
  const r = rel(path).split(sep).join("/");
  return (list || []).some((e) => r === e || r.endsWith("/" + e) || r.endsWith(e));
};

// ---------------------------------------------------------------------------
// File walking
// ---------------------------------------------------------------------------
const EXCLUDE_SEGMENTS = ["node_modules", "dist", "build", ".git", "coverage", "__tests__", "e2e"];
function isExcludedPath(p) {
  const parts = p.split(sep);
  if (parts.some((seg) => EXCLUDE_SEGMENTS.includes(seg))) return true;
  if (/\.(test|spec)\.[cm]?[jt]sx?$/.test(p)) return true;
  if (/\.stories\.[cm]?[jt]sx?$/.test(p)) return true;
  return false;
}
function walk(root) {
  const out = [];
  if (!existsSync(root)) return out;
  if (statSync(root).isFile()) return isExcludedPath(root) ? [] : [root];
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
const CODE_EXT = new Set(["tsx", "ts", "jsx", "js", "mjs"]);
const isCode = (p) => CODE_EXT.has((basename(p).split(".").pop() || "").toLowerCase());
const isComponentFile = (p) => /\.[jt]sx$/.test(p);

const files = [...new Set(roots.flatMap(walk))].filter(isCode);
const fileText = new Map();
const readLines = (p) => {
  if (!fileText.has(p)) {
    try {
      fileText.set(p, readFileSync(p, "utf8").split(/\r?\n/));
    } catch {
      fileText.set(p, null);
    }
  }
  return fileText.get(p);
};

// From startIdx, return the line-index window of the call opened on that line
// (paren/brace tracking; caps at maxLines). Good enough for hook bodies.
function callWindow(lines, startIdx, maxLines = 60) {
  let depth = 0;
  let opened = false;
  const end = Math.min(lines.length, startIdx + maxLines);
  for (let i = startIdx; i < end; i++) {
    for (const ch of lines[i]) {
      if (ch === "(" || ch === "{") {
        depth++;
        opened = true;
      } else if (ch === ")" || ch === "}") {
        depth--;
      }
    }
    if (opened && depth <= 0) return [startIdx, i];
  }
  return [startIdx, end - 1];
}

const GEOM_RE =
  /getBoundingClientRect|offsetWidth|offsetHeight|clientWidth|clientHeight|scrollWidth|scrollHeight|getComputedStyle/;
const SETSTATE_RE = /\bset[A-Z]\w*\s*\(/;

// ---------------------------------------------------------------------------
// Findings
// ---------------------------------------------------------------------------
const findings = [];
const dropped = new Map(); // ruleId -> count over cap
function addFinding(f) {
  const n = findings.filter((x) => x.rule === f.rule).length;
  if (n >= MAX_PER_RULE) {
    dropped.set(f.rule, (dropped.get(f.rule) || 0) + 1);
    return;
  }
  findings.push(f);
}
const mk = (rule, checklist, severity, path, lineNo, match, text, opts = {}) =>
  addFinding({
    rule,
    checklist,
    severity,
    reportOnly: !!opts.reportOnly,
    counter_move: opts.counterMove || "see checklist",
    file: rel(path),
    line: lineNo,
    match: String(match).slice(0, 120),
    text: String(text).trim().slice(0, 160),
  });

// ---------------------------------------------------------------------------
// PASS 1 — collect memoized component names (for spread-into-memo)
// ---------------------------------------------------------------------------
const memoNames = new Set();
for (const p of files) {
  const lines = readLines(p);
  if (!lines) continue;
  for (const line of lines) {
    for (const m of line.matchAll(/(?:const|let|var)\s+([A-Z][\w$]*)\s*=\s*(?:React\.)?memo\(/g))
      memoNames.add(m[1]);
  }
}

// ---------------------------------------------------------------------------
// PASS 2 — generic per-file rules
// ---------------------------------------------------------------------------
for (const path of files) {
  const lines = readLines(path);
  if (!lines) continue;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNo = i + 1;

    // L1 — exhaustive-deps-suppression (P2, report-only; never gates). Checked before
    // the comment skip — the suppression IS a comment.
    if (/eslint-disable(?:-next-line)?[^\n]*exhaustive-deps/.test(line))
      mk("exhaustive-deps-suppression", "L1", "P2", path, lineNo, "exhaustive-deps suppressed", line, {
        reportOnly: true,
        counterMove: "review each: stale closure or the reason memo got broken later",
      });
    if (/^\s*(?:\/\/|\*|\/\*)/.test(line)) continue; // skip comment lines

    // I1 — dim-container-loading-affordance (P0): conditional opacity on a container
    // that wraps a mapped list within the next ~15 lines.
    if (
      isComponentFile(path) &&
      /className/.test(line) &&
      /(transition-opacity|\bopacity-\d{1,2}\b)/.test(line) &&
      loadingRe.test(line) &&
      !inList(path, cfg?.dimAllowFiles)
    ) {
      const ahead = lines.slice(i, i + 15).join("\n");
      if (/\.map\s*\(/.test(ahead))
        mk("dim-container-loading-affordance", "I1", "P0", path, lineNo, "conditional opacity over .map", line, {
          counterMove: "small fixed-size hint outside the subtree; never dim the list",
        });
    }

    // C2 — context-provider-inline-value (P1): inline object/array as provider value.
    if (/value=\{\s*[\{\[]/.test(line)) {
      const back = lines.slice(Math.max(0, i - 4), i + 1).join("\n");
      if (/<[\w$.]*(?:Provider|Context)\b/.test(back))
        mk("context-provider-inline-value", "C2", "P1", path, lineNo, "value={{…}}", line, {
          counterMove: "useMemo the provider value; useCallback its functions",
        });
    }

    // D1 — debounce-in-render (P1): debounce/throttle built in a component/hook body.
    if (
      /\b(?:debounce|throttle)\s*\(/.test(line) &&
      !/^import\b|from\s+["']/.test(line) &&
      /^\s+/.test(line) && // indented ⇒ not module scope
      !/useMemo|useRef|useDebounce|useThrottle/.test(lines.slice(Math.max(0, i - 2), i + 1).join("\n"))
    )
      mk("debounce-in-render", "D1", "P1", path, lineNo, line.match(/\b(?:debounce|throttle)\s*\(/)[0], line, {
        counterMove: "build once via the ref-escape useDebounce pattern (checklist D3)",
      });

    // M5 — memo-first-arg-invocation (P1): useMemo(fn(), …) / useCallback(fn(), …).
    {
      const m = line.match(/\buse(?:Memo|Callback)\(\s*([\w$.]+)\(/);
      if (m && !/^(?:async|function)$/.test(m[1]))
        mk("memo-first-arg-invocation", "M5", "P1", path, lineNo, m[0], line, {
          counterMove: "pass a function, not a call",
        });
    }

    // L3 — memo-custom-comparator (P2, review-always). Identifier or inline-fn first arg.
    if (/(?:React\.)?\bmemo\(\s*[A-Za-z_$][\w$]*\s*,/.test(line) || (/\bmemo\(/.test(line) && /\},\s*\(/.test(line)))
      mk("memo-custom-comparator", "L3", "P2", path, lineNo, "memo(X, comparator)", line, {
        counterMove: "review: partial comparators create stale-closure bugs",
      });

    // W3 — module-scope-fetch (P1): a fetch/axios CALL executed at module top level
    // (column 0). A top-level fn *definition* containing fetch is fine — only flag when
    // no `=>`/`function` precedes the call on the line.
    {
      const m = line.match(/\bfetch\s*\(|axios\.(?:get|post|put|patch|delete)\s*\(/);
      if (
        m &&
        !/^\s/.test(line) &&
        !/^import\b|^export\s+(?:type|interface)\b/.test(line) &&
        !(line.slice(0, m.index).includes("=>") || line.slice(0, m.index).includes("function")) &&
        !inList(path, cfg?.rawFetchAllowlist) &&
        !(cfg?.prefetchMarkers || []).some((k) => line.includes(k))
      )
        mk("module-scope-fetch", "W3", "P1", path, lineNo, "top-level fetch", line, {
          counterMove: "move behind a router loader / prefetchQuery / lazy-chunk prefetch",
        });
    }

    // K3 — key-index-dynamic-list (P2, review): key={index|i|idx} near a .map.
    if (/key=\{(?:index|i|idx)\}/.test(line) && !/Skeleton/.test(line)) {
      // Skeleton placeholder rows are static by construction (checklist K3 carve-out).
      const back = lines.slice(Math.max(0, i - 10), i + 1).join("\n");
      if (/\.map\s*\(/.test(back) && !/Skeleton/.test(back.split("\n").slice(-3).join("\n")))
        mk("key-index-dynamic-list", "K3", "P2", path, lineNo, line.match(/key=\{(?:index|i|idx)\}/)[0], line, {
          counterMove: "stable id key if the list ever reorders/inserts; fine if truly static",
        });
    }

    // M2 — spread-into-memo (P2): {...props} onto a known-memoized component.
    if (memoNames.size) {
      const m = line.match(/<([A-Z][\w$]*)\b[^>]*\{\s*\.\.\./);
      if (m && memoNames.has(m[1]))
        mk("spread-into-memo", "M2", "P2", path, lineNo, `<${m[1]} {...}`, line, {
          counterMove: "pass explicit, stabilized props to memoized components",
        });
    }

    // F1 / F2 / W4 — effect-window rules.
    if (/\buseEffect\s*\(/.test(line)) {
      const [s, e] = callWindow(lines, i);
      const win = lines.slice(s, e + 1).join("\n");
      if (
        /\bfetch\s*\(|axios\./.test(win) &&
        SETSTATE_RE.test(win) &&
        !inList(path, cfg?.rawFetchAllowlist)
      )
        mk("raw-fetch-in-effect", "W4", "P1", path, lineNo, "fetch+setState in useEffect", line, {
          counterMove: "route through the query layer (queryConfigs/api client)",
        });
      if (GEOM_RE.test(win) && SETSTATE_RE.test(win))
        mk("dom-measure-in-useEffect", "F1", "P1", path, lineNo, "geometry read + setState", line, {
          counterMove: "useLayoutEffect for measure-then-set (this narrow case only)",
        });
    }
    if (/\buseLayoutEffect\s*\(/.test(line)) {
      const [s, e] = callWindow(lines, i);
      const win = lines.slice(s, e + 1).join("\n");
      if (!GEOM_RE.test(win))
        mk("useLayoutEffect-no-measure", "F2", "P2", path, lineNo, "useLayoutEffect without geometry read", line, {
          counterMove: "plain useEffect unless it measures the DOM before paint",
        });
    }
  }
}

// ---------------------------------------------------------------------------
// PASS 3 — overlay rules
// ---------------------------------------------------------------------------
const overlayNotes = [];
if (cfg) {
  // Required-pattern regression guards.
  for (const g of cfg.requiredPatterns || []) {
    const p = resolve(repoRoot, g.file);
    if (!existsSync(p)) {
      addFinding({
        rule: `guard:${g.id}`,
        checklist: "overlay",
        severity: g.severity || "P1",
        reportOnly: false,
        counter_move: g.why || "restore the guarded pattern",
        file: g.file,
        line: 1,
        match: "file missing",
        text: `regression guard: ${g.file} not found`,
      });
      continue;
    }
    const text = readFileSync(p, "utf8");
    if (!new RegExp(g.pattern, "m").test(text))
      addFinding({
        rule: `guard:${g.id}`,
        checklist: "overlay",
        severity: g.severity || "P1",
        reportOnly: false,
        counter_move: g.why || "restore the guarded pattern",
        file: g.file,
        line: 1,
        match: `pattern /${g.pattern}/ absent`,
        text: `regression guard: ${g.why || g.id}`,
      });
  }

  // month-prefetch-gap (P1): page uses a month-param hook but no prefetch marker.
  if (cfg.pagesDir && cfg.monthParamHooks?.length) {
    const pagesRoot = resolve(repoRoot, cfg.pagesDir);
    for (const p of files.filter((f) => f.startsWith(pagesRoot))) {
      if (inList(p, cfg.monthPrefetchExempt)) continue;
      const lines = readLines(p);
      if (!lines) continue;
      const text = lines.join("\n");
      const hookRe = new RegExp(`\\b(?:${cfg.monthParamHooks.join("|")})\\s*\\(`);
      if (!hookRe.test(text)) continue;
      const hasPrefetch = (cfg.prefetchMarkers || []).some((k) => text.includes(k));
      if (!hasPrefetch) {
        const lineNo = lines.findIndex((l) => hookRe.test(l)) + 1;
        mk("month-prefetch-gap", "I4", "P1", p, Math.max(1, lineNo), "month page without prefetch", lines[lineNo - 1] || "", {
          counterMove: "warm ±1 adjacent months (mirror usePrefetchMonth) or exempt with a reason",
        });
      }
    }
  }

  // Query-factory checks: staleTime + keepPreviousData on month-scoped factories.
  if (cfg.queryConfigsPath) {
    const qp = resolve(repoRoot, cfg.queryConfigsPath);
    if (existsSync(qp)) {
      const lines = readFileSync(qp, "utf8").split(/\r?\n/);
      const paramNames = cfg.monthFactoryParamNames || ["month"];
      for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^\s{2}([\w$]+):\s*\(([^)]*)\)\s*=>\s*\(\{\s*$/);
        if (!m) continue;
        const [, name, params] = m;
        const isMonthScoped = paramNames.some((pn) =>
          new RegExp(`\\b${pn}\\b\\s*[:?,)]|\\b${pn}\\b\\s*$`).test(params)
        );
        if (!isMonthScoped) continue;
        // capture block to the matching `}),`
        let end = i;
        for (let j = i + 1; j < Math.min(lines.length, i + 40); j++) {
          if (/^\s{2}\}\),?\s*$/.test(lines[j])) {
            end = j;
            break;
          }
        }
        const block = lines.slice(i, end + 1).join("\n");
        if (!/\bstaleTime\s*:/.test(block) && !(cfg.staleTimeExempt || []).includes(name))
          mk("staleTime-zero-on-month-query", "I4", "P2", qp, i + 1, `${name}: no staleTime`, m[0], {
            counterMove: "set a deliberate staleTime (default 0 refetches every mount/focus)",
          });
        if (
          !/placeholderData\s*:\s*keepPreviousData/.test(block) &&
          !(cfg.keepPreviousDataExempt || []).includes(name)
        )
          mk("keepPreviousData-regression-guard", "I4", "P2", qp, i + 1, `${name}: no keepPreviousData`, m[0], {
            counterMove: "placeholderData: keepPreviousData so month changes don't blank",
          });
      }
    } else overlayNotes.push(`queryConfigsPath not found: ${cfg.queryConfigsPath}`);
  }

  // static-route-import-regression-guard (P2): non-lazy page imports in the routes file.
  if (cfg.routesFile) {
    const rp = resolve(repoRoot, cfg.routesFile);
    if (existsSync(rp)) {
      const lines = readFileSync(rp, "utf8").split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^import\s*\{([^}]*)\}\s*from\s*["']@\/pages\//);
        if (!m) continue;
        for (const name of m[1].split(",").map((s) => s.trim()).filter(Boolean)) {
          if (!/Page$/.test(name)) continue;
          if ((cfg.eagerRouteAllowlist || []).includes(name)) continue;
          mk("static-route-import-regression-guard", "I-lazy", "P2", rp, i + 1, `${name} imported eagerly`, lines[i], {
            counterMove: "React.lazy the route or add to eagerRouteAllowlist with a reason",
          });
        }
      }
    } else overlayNotes.push(`routesFile not found: ${cfg.routesFile}`);
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
const count = (sev) => findings.filter((f) => f.severity === sev).length;
const p0count = count("P0");
const gateOrder = SEV_ORDER[flags.failOn];
const gating = findings.filter((f) => !f.reportOnly && SEV_ORDER[f.severity] <= gateOrder).length;
const willGate = !flags.report && gating > 0;

if (flags.json) {
  console.log(
    JSON.stringify(
      {
        repo_root: repoRoot,
        roots: roots.map(rel),
        overlay: cfg ? cfg.__source : null,
        overlay_notes: overlayNotes,
        files_scanned: files.length,
        max_per_rule: MAX_PER_RULE,
        dropped_over_cap: Object.fromEntries(dropped),
        total: findings.length,
        p0: p0count,
        p1: count("P1"),
        p2: count("P2"),
        report: flags.report,
        fail_on: flags.failOn,
        gating,
        findings,
      },
      null,
      2
    )
  );
} else {
  console.log("perf-grep — deterministic React-performance static checks (perf-audit)");
  console.log(`  repo root    : ${repoRoot}`);
  console.log(`  overlay      : ${cfg ? rel(cfg.__source) : "none (generic rules only)"}`);
  console.log(`  roots        : ${roots.map(rel).join(", ")}`);
  console.log(`  files scanned: ${files.length}`);
  for (const n of overlayNotes) console.log(`  note         : ${n}`);
  console.log("");
  const byRule = new Map();
  for (const f of findings) {
    if (!byRule.has(f.rule)) byRule.set(f.rule, []);
    byRule.get(f.rule).push(f);
  }
  for (const [rule, hits] of byRule) {
    const h0 = hits[0];
    console.log(
      `▸ ${rule}  [${h0.checklist}] [${[...new Set(hits.map((h) => h.severity))].join("/")}]${
        h0.reportOnly ? " [report-only]" : ""
      } — ${hits.length} hit(s)${dropped.has(rule) ? ` (+${dropped.get(rule)} over cap)` : ""}`
    );
    for (const h of hits) console.log(`    ${h.file}:${h.line}  ${h.match}   ⟨${h.text}⟩`);
  }
  console.log("");
  console.log(`Summary: ${findings.length} finding(s) — P0=${p0count}  P1=${count("P1")}  P2=${count("P2")}`);
  console.log(
    flags.report
      ? `REPORT (non-blocking): exit 0 regardless. ${p0count} P0 finding(s) present.`
      : willGate
        ? `FAIL: ${gating} gating finding(s) at or above ${flags.failOn} — exit 2.`
        : `OK: no gating findings at or above ${flags.failOn}.`
  );
}
process.exit(willGate ? 2 : 0);
