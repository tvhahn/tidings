#!/usr/bin/env python3
"""Cross-fixture consistency gate for the static demo (run in CI by demo-smoke).

Asserts the four invariants from the 2026-06-11 demo-realism spec, section 1.6:

1. Banned vocabulary — old-persona tokens appear in zero fixtures.
2. Identity — every transaction belongs to Mira (forwarded_to, name) and the
   institution set is exactly the persona's four banks.
3. Reconciliation — each month's summary total matches the sum of that month's
   spending transactions within $1; the trend fixture matches the summaries;
   the income statement carries no data after the demo month.
4. World clock — no fixture contains a day-resolution date after DEMO_TODAY
   (named allowlist only, no blanket exceptions), and no fixture file exists
   for months after the demo month.

Plus the lived-in-dataset shape from section 3.3:

5. Transport — at most two gasoline transactions per month, and only in the
   rental-story month (2026-03, the Niagara client trip).
6. Rent — exactly one rent row per month: $2,150.00 pre-authorized on the 1st.
7. Income — only Ridge Studio and Northwind Labs; recurring retainers are
   four figures (the old $241/$71 noise pattern must not return).
8. Month distinctness — full-month transaction counts in 60–95 with no two
   consecutive months equal; coefficient of variation of full-month spending
   totals >= 8%; the demo month is a partial month (35–60 rows).
9. AI narrative hygiene — no briefing or journal summary references the
   retired gas-commuter pattern; gasoline/fill language only in demo-month
   (rental story) files.

Usage: uv run python scripts/demo/check_demo_fixtures.py
Exits non-zero with a list of violations.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "frontend" / "public" / "demo-data"

DEMO_TODAY = "2026-03-19"
DEMO_MONTH = "2026-03"
MONTHS = [
    "2025-05",
    "2025-06",
    "2025-07",
    "2025-08",
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
]

FORWARDED_TO = "mira.tidings@example.com"
PERSONA_NAME = "Mira Lin Chen"
INSTITUTIONS = {"RBC", "CIBC", "Simplii", "Tangerine"}

# "Needs review" (parse-failures) fixture vocabularies — mirror the store's
# VALID_STATUSES / VALID_STAGES in src/finance/parse_failure_store_local.py.
PARSE_FAILURE_STATUSES = {"quarantined", "recovered", "retried", "dismissed"}
PARSE_FAILURE_STAGES = {
    "no_parser_match",
    "extraction_empty",
    "ai_extraction_failed",
    "ai_validation_failed",
    "db_validation_failed",
}

# Any email address; the parse-failure check flags any whose domain is not the
# persona's @example.com namespace (mirrors the demo-smoke workflow's grep).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Old-persona tokens — the generic, non-locating subset only.
# Region-specific canaries live in the untracked .pii-patterns, which the
# demo-smoke persona gate greps when present. Word-ish matching below avoids
# substring false positives.
BANNED_TOKENS = [
    "Telus",
    "Safeway",
    "Chevron",
    "Landlord",
    "demo@example.com",
    "Demo Bank",
]

# Day-resolution dates allowed past DEMO_TODAY, keyed by (filename, exact
# string). Empty: the world contains no future. Add entries deliberately.
DATE_ALLOWLIST: set[tuple[str, str]] = set()

# "MM/DD/YYYY", "YYYY-MM-DD", "YYYY.MM.DD" — anything with day resolution.
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"), lambda m: f"{m.group(3)}-{m.group(1)}-{m.group(2)}"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
    (re.compile(r"\b(\d{4})\.(\d{2})\.(\d{2})\b"), lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
]

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def fixture_files() -> list[Path]:
    """Served fixture JSONs — dotfiles are generation manifests, not fixtures."""
    return sorted(p for p in FIXTURE_DIR.glob("*.json") if not p.name.startswith("."))


def load(slug: str):
    return json.loads((FIXTURE_DIR / f"{slug}.json").read_text())


def month_transactions(month: str) -> list[dict]:
    return load(f"transactions-{month}")["transactions"]


def check_banned_vocabulary() -> None:
    pattern = re.compile("|".join(rf"(?<![A-Za-z]){re.escape(tok)}(?![A-Za-z])" for tok in BANNED_TOKENS))
    for path in fixture_files():
        for m in pattern.finditer(path.read_text()):
            err(f"banned token {m.group(0)!r} in {path.name}")


def check_identity() -> None:
    for month in MONTHS:
        for row in month_transactions(month):
            if row["forwarded_to"] != FORWARDED_TO:
                err(f"{month}: forwarded_to {row['forwarded_to']!r} != {FORWARDED_TO}")
            if row["name"] != PERSONA_NAME:
                err(f"{month}: name {row['name']!r} != {PERSONA_NAME}")
            if row["institution"] not in INSTITUTIONS:
                err(f"{month}: institution {row['institution']!r} not in {sorted(INSTITUTIONS)}")


def check_reconciliation() -> None:
    summary_totals: dict[str, float] = {}
    for month in MONTHS:
        rows = month_transactions(month)
        spend = sum(r["amount"] for r in rows if r["transaction_type"] != "deposit" and not r.get("ignored"))
        summary = load(f"summary-{month}")["current"]
        total = summary["total_spending"]
        summary_totals[month] = total
        if abs(total - spend) > 1.0:
            err(f"summary-{month} total {total:.2f} != transaction sum {spend:.2f} (±$1)")

    trend = load("summary-trend")
    for entry in trend["months"]:
        ym = entry["year_month"]
        if ym not in summary_totals:
            err(f"summary-trend contains month {ym} outside the fixture window")
            continue
        if abs(entry["total_spending"] - summary_totals[ym]) > 1.0:
            err(
                f"summary-trend {ym} total {entry['total_spending']:.2f} != "
                f"summary-{ym} total {summary_totals[ym]:.2f} (±$1)"
            )

    income = load("income-statement-2026")
    demo_month_idx = int(DEMO_MONTH.split("-")[1]) - 1
    for i, ym in enumerate(income["months"]):
        if i > demo_month_idx:
            inc = income["income"]["monthly_totals"][i]
            exp = income["total_expenses_monthly"][i]
            if inc or exp:
                err(f"income-statement has data in future month {ym}: income {inc}, expenses {exp}")


def check_world_clock() -> None:
    future_files = [
        p.name
        for p in fixture_files()
        if (m := re.search(r"(\d{4})-(\d{2})\.json$", p.name)) and f"{m.group(1)}-{m.group(2)}" > DEMO_MONTH
    ]
    for name in future_files:
        err(f"fixture file for month after {DEMO_MONTH}: {name}")

    for path in fixture_files():
        text = path.read_text()
        for pattern, to_iso in _DATE_PATTERNS:
            for m in pattern.finditer(text):
                iso = to_iso(m)
                if iso > DEMO_TODAY and (path.name, m.group(0)) not in DATE_ALLOWLIST:
                    err(f"date after {DEMO_TODAY} in {path.name}: {m.group(0)!r}")


RENTAL_MONTH = DEMO_MONTH  # the only month with a car (March Niagara trip)
RECURRING_INCOME_MIN = 1000.0
ONE_OFF_INCOME_MIN = 500.0
INCOME_COMPANIES = {"Ridge Studio Retainer", "Northwind Labs Retainer"}
FULL_MONTH_COUNT_RANGE = (60, 95)
PARTIAL_MONTH_COUNT_RANGE = (35, 60)
MIN_TOTAL_CV = 0.08

# Phrases that would resurrect the retired gas-commuter pattern in AI text.
GAS_PATTERN_RE = re.compile(
    r"(?:seven|eight|nine|ten|\b[7-9]\b|\b1[0-9]\b)\s+fills?\b"
    r"|gas[- ]commut|commuter pattern|airport runs",
    re.IGNORECASE,
)
GAS_WORDS_RE = re.compile(r"gasoline|petro-?canada|fill-?ups?|\bfills?\b", re.IGNORECASE)


def check_lived_in_shape() -> None:
    counts: dict[str, int] = {}
    totals: dict[str, float] = {}
    for month in MONTHS:
        rows = month_transactions(month)
        counts[month] = len(rows)
        totals[month] = load(f"summary-{month}")["current"]["total_spending"]

        gas = [r for r in rows if (r.get("category") or "").lower() == "gasoline"]
        if month == RENTAL_MONTH:
            if len(gas) > 2:
                err(f"{month}: {len(gas)} gasoline rows; the rental story allows at most 2")
        elif gas:
            err(f"{month}: {len(gas)} gasoline rows outside the rental month {RENTAL_MONTH}")

        rent = [r for r in rows if (r.get("category") or "").lower() == "rent"]
        if len(rent) != 1:
            err(f"{month}: expected exactly 1 rent row, found {len(rent)}")
        for r in rent:
            if r["amount"] != 2150.00:
                err(f"{month}: rent {r['amount']} != 2150.00")
            if r["date_file_name"][8:10] != "01":
                err(f"{month}: rent not on the 1st ({r['date_file_name'][:10]})")
            if r["transaction_type"] != "preauth":
                err(f"{month}: rent type {r['transaction_type']!r} != 'preauth'")

    income_months: dict[str, list[tuple[str, float]]] = {}
    for month in MONTHS:
        for r in month_transactions(month):
            if (r.get("category") or "").lower() == "income":
                income_months.setdefault(r["company"], []).append((month, r["amount"]))
    for company, hits in income_months.items():
        if company not in INCOME_COMPANIES:
            err(f"income from unexpected company {company!r}")
        recurring = len({m for m, _ in hits}) >= 3
        floor = RECURRING_INCOME_MIN if recurring else ONE_OFF_INCOME_MIN
        small = [(m, a) for m, a in hits if a < floor]
        # Recurring retainers may also carry one-off project deposits; only the
        # sub-$500 noise pattern is a violation for those.
        if recurring:
            small = [(m, a) for m, a in hits if a < ONE_OFF_INCOME_MIN]
        for m, a in small:
            err(f"income row below ${floor:.0f}: {company} {a} in {m} (noise pattern)")

    full_months = [m for m in MONTHS if m != DEMO_MONTH]
    for m in full_months:
        lo, hi = FULL_MONTH_COUNT_RANGE
        if not lo <= counts[m] <= hi:
            err(f"{m}: {counts[m]} transactions outside {lo}–{hi}")
    lo, hi = PARTIAL_MONTH_COUNT_RANGE
    if not lo <= counts[DEMO_MONTH] <= hi:
        err(f"{DEMO_MONTH}: {counts[DEMO_MONTH]} transactions outside partial-month range {lo}–{hi}")
    for prev, cur in zip(MONTHS, MONTHS[1:]):
        if counts[prev] == counts[cur]:
            err(f"consecutive months with equal transaction counts: {prev} and {cur} ({counts[cur]})")

    series = [totals[m] for m in full_months]
    mean = sum(series) / len(series)
    cv = (sum((t - mean) ** 2 for t in series) / len(series)) ** 0.5 / mean
    if cv < MIN_TOTAL_CV:
        err(f"monthly spending totals CV {cv:.1%} < {MIN_TOTAL_CV:.0%} — months too uniform")


def ai_text_chunks(path: Path) -> list[str]:
    doc = json.loads(path.read_text())
    if path.name.startswith("journal-summaries-"):
        return list(doc.get("summaries", {}).values())
    if isinstance(doc, list):  # insights-saved-full
        return [entry.get("content", "") for entry in doc]
    return []


def check_ai_narratives() -> None:
    ai_files = sorted(FIXTURE_DIR.glob("journal-summaries-*.json")) + sorted(
        FIXTURE_DIR.glob("insights-saved-full-*.json")
    )
    for path in ai_files:
        is_rental_month = RENTAL_MONTH in path.name
        for text in ai_text_chunks(path):
            if m := GAS_PATTERN_RE.search(text):
                err(f"AI text in {path.name} references the gas-commuter pattern: {m.group(0)!r}")
            if not is_rental_month and (m := GAS_WORDS_RE.search(text)):
                err(f"AI text in {path.name} mentions gasoline outside the rental month: {m.group(0)!r}")


def check_parse_failures() -> None:
    """The hand-authored "Needs review" fixture: shape, vocabularies, PII hygiene.

    Optional fixture — absence is valid (the demo then renders the empty state).
    This check is self-contained on the world-clock and email-domain invariants:
    it validates ``received_at`` against the demo clock and scans
    ``from_email`` / ``subject`` / ``body`` for non-``example.com`` addresses
    here, because the file-wide ``check_world_clock`` regex does not match
    ISO-8601 datetimes (the ``T`` separator breaks its word boundaries) and there
    is no file-wide email-domain check in this script. Banned vocabulary is still
    enforced file-wide by ``check_banned_vocabulary``.
    """
    path = FIXTURE_DIR / "parse-failures.json"
    if not path.exists():
        return
    doc = load("parse-failures")
    if not isinstance(doc, dict) or not isinstance(doc.get("failures"), list):
        err("parse-failures.json is not a {count, failures[]} object")
        return
    failures = doc["failures"]
    if doc.get("count") != len(failures):
        err(f"parse-failures.json: count {doc.get('count')} != {len(failures)} rows")
    for i, row in enumerate(failures):
        where = f"parse-failures[{i}]"
        if not row.get("id"):
            err(f"{where}: missing id")
        if row.get("status") not in PARSE_FAILURE_STATUSES:
            err(f"{where}: status {row.get('status')!r} not in {sorted(PARSE_FAILURE_STATUSES)}")
        if row.get("failure_stage") not in PARSE_FAILURE_STAGES:
            err(f"{where}: failure_stage {row.get('failure_stage')!r} not in {sorted(PARSE_FAILURE_STAGES)}")
        inst = row.get("detected_institution")
        if inst is not None and inst not in INSTITUTIONS:
            err(f"{where}: detected_institution {inst!r} not in {sorted(INSTITUTIONS)}")
        if not isinstance(row.get("body"), str):
            err(f"{where}: body must be a string (the detail expand renders it)")
        for forbidden in ("forwarded_to", "name", "institution"):
            if forbidden in row:
                err(f"{where}: unexpected real-account key {forbidden!r}")

        # World clock: received_at must not be after the demo's "today".
        # check_world_clock misses these — its date regex needs word boundaries
        # the ISO "T" separator breaks — so validate the date prefix directly.
        received = str(row.get("received_at") or "")
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", received)
        if not date_match:
            err(f"{where}: received_at {received!r} is not an ISO date")
        elif date_match.group(1) > DEMO_TODAY:
            err(f"{where}: received_at {date_match.group(1)} is after the demo clock {DEMO_TODAY}")

        # PII: every email address (the sender, or anything in the subject/body)
        # must live in the persona's @example.com namespace.
        for field in ("from_email", "subject", "body"):
            for match in _EMAIL_RE.finditer(str(row.get(field) or "")):
                if not match.group(0).endswith("@example.com"):
                    err(f"{where}: non-example.com email in {field}: {match.group(0)!r}")


# Positive spending allowlist — mirror src/finance/spending_aggregator.py so the
# reconciliation matches TaxPackService's own row filter exactly.
SPENDING_TYPES = {"purchase", "withdrawal", "preauth", "e-transfer"}


def check_tax_pack() -> None:
    """Tax pack (CRA claim lines) reconciliation.

    Each ``total`` in ``tax-pack-<year>.json`` must equal the sum of that line's
    mapped-category transactions in the year's transaction fixtures — spending
    types only, excluding ignored/deleted — within ±$1. Same reconcile-don't-
    parse shape as ``check_reconciliation``: the pack is a backend snapshot,
    never computed client-side, so this catches drift between the committed pack
    and the committed transactions. Also pins the pack's internal invariants
    (grand_total = Σ line totals; evidence_counts sum to transaction_count; the
    transactions array length matches transaction_count).
    """
    packs = sorted(FIXTURE_DIR.glob("tax-pack-*.json"))
    if not packs:
        err("no tax-pack-*.json fixture present")
        return
    for path in packs:
        name_match = re.search(r"tax-pack-(\d{4})\.json$", path.name)
        if not name_match:
            err(f"unexpected tax-pack fixture name: {path.name}")
            continue
        year = name_match.group(1)
        pack = json.loads(path.read_text())
        if pack.get("year") != int(year):
            err(f"{path.name}: year {pack.get('year')} != {year}")

        # Sum each mapped category across the year's transaction fixtures (only
        # the months that ship a fixture; the tax year may extend past the demo
        # window, but empty months contribute nothing on either side).
        year_months = [mo for mo in MONTHS if mo.startswith(f"{year}-")]
        cat_totals: dict[str, float] = {}
        for mo in year_months:
            for r in month_transactions(mo):
                if r.get("transaction_type") not in SPENDING_TYPES:
                    continue
                if r.get("ignored") or r.get("deleted_at"):
                    continue
                cat = (r.get("category") or "").lower()
                cat_totals[cat] = cat_totals.get(cat, 0.0) + float(r.get("amount") or 0.0)

        line_total_sum = 0.0
        for line in pack.get("lines", []):
            key = line.get("key")
            expected = sum(cat_totals.get(str(c).lower(), 0.0) for c in line.get("categories", []))
            actual = float(line.get("total") or 0.0)
            line_total_sum += actual
            if abs(actual - expected) > 1.0:
                err(
                    f"{path.name} line {key!r} total {actual:.2f} != "
                    f"transaction sum {expected:.2f} (±$1)"
                )
            ec = line.get("evidence_counts") or {}
            ec_sum = ec.get("receipt", 0) + ec.get("email", 0) + ec.get("statement", 0)
            if ec_sum != line.get("transaction_count"):
                err(
                    f"{path.name} line {key!r}: evidence_counts sum {ec_sum} != "
                    f"transaction_count {line.get('transaction_count')}"
                )
            if len(line.get("transactions", [])) != line.get("transaction_count"):
                err(
                    f"{path.name} line {key!r}: {len(line.get('transactions', []))} rows != "
                    f"transaction_count {line.get('transaction_count')}"
                )
        grand = float(pack.get("grand_total") or 0.0)
        if abs(grand - line_total_sum) > 1.0:
            err(
                f"{path.name}: grand_total {grand:.2f} != sum of line totals "
                f"{line_total_sum:.2f} (±$1)"
            )


def main() -> int:
    if not FIXTURE_DIR.is_dir():
        print(f"fixture directory missing: {FIXTURE_DIR}", file=sys.stderr)
        return 2
    check_banned_vocabulary()
    check_identity()
    check_reconciliation()
    check_world_clock()
    check_lived_in_shape()
    check_ai_narratives()
    check_parse_failures()
    check_tax_pack()
    if errors:
        print(f"check_demo_fixtures: {len(errors)} violation(s)", file=sys.stderr)
        for e in errors[:50]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  … and {len(errors) - 50} more", file=sys.stderr)
        return 1
    print(
        f"check_demo_fixtures: OK — {len(MONTHS)} months reconciled, "
        f"identity uniform, no banned vocabulary, no dates after {DEMO_TODAY}, "
        f"lived-in shape and AI narrative hygiene hold"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
