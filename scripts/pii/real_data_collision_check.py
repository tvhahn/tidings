#!/usr/bin/env python3
"""Search the tracked tree for values that exist in the maintainer's real transaction export.

This is the inverse of the pattern-alphabet audit (scripts/pii/audit_oss_release.py):
instead of scanning the tree for a fixed alphabet of known-bad tokens, it dumps
the maintainer's REAL transaction data and searches the tracked tree FOR those
real values. It finds transplanted real data the alphabet does not yet name —
real merchant strings dropped into test fixtures, bank-side transpositions of a
surname, truncated merchant prefixes, transaction reference codes, and amounts
that co-locate with any of the above.

The real export comes from dev/cli/download_transaction_table.py, which writes a
QUOTE_ALL CSV with a fixed column order. Token classes are derived from those
columns (see extract_tokens). Nothing about the maintainer's data is hard-coded
here, so this script is itself safe to ship.

Redaction: the terminal output is ALWAYS redacted — only counts, categories,
scanned-file counts, tracked file paths, and the report location are printed,
never a token or a matched line or any CSV value. The written reports redact
token text and matched lines as `<REDACTED:N chars>` unless --include-matches is
passed (the reports live under the gitignored logs/audit/ tree).

Exit codes:
  0  no non-dispositioned findings — no new collisions.
  1  one or more non-dispositioned findings — a new collision. Scrub the value
     out of the tree, or add it to .pii-dispositions if it is adjudicated safe.
  3  usage / environment error (missing CSV, failed download, git enumeration).

Usage:
  python scripts/pii/real_data_collision_check.py
  python scripts/pii/real_data_collision_check.py --download            # fetch + scan + delete
  python scripts/pii/real_data_collision_check.py --download --keep-csv
  python scripts/pii/real_data_collision_check.py --target /some/dir --include-matches
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# A collapsed email Body can exceed the default 128 KiB CSV field limit.
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:  # pragma: no cover - platform-dependent
    csv.field_size_limit(2**31 - 1)

BIG_FILE_BYTES = 5 * 1024 * 1024
REFERENCE_CAP = 20_000
REFERENCE_BOILERPLATE_FRACTION = 0.30
PER_TOKEN_MATCH_CAP = 25
CHUNK_SIZE = 500

# Columns that carry merchant / counterparty / person strings.
FULLSTRING_COLUMNS = ("FromName", "ToName", "Name", "Company")
# Columns that carry email addresses (or an id that may be an address).
EMAIL_COLUMNS = ("FromEmail", "ToEmail", "UserId")
# Columns whose free text carries transaction / Interac reference shapes.
REFERENCE_COLUMNS = ("Subject", "Body")

# Matches inside these contexts are legitimate public attribution — the same
# contexts audit_oss_release.py and the pre-push hook allowlist.
ATTRIBUTION_ALLOW = re.compile(
    r"github\\?\.com|ghcr\.io|Copyright|SPDX-FileCopyrightText",
    re.IGNORECASE,
)

# Email domains that are clearly placeholders / project-namespace — never real.
EMAIL_ALLOW_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "tidings.local",
    "localhost",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_REFERENCE_RE = re.compile(r"[A-Za-z0-9]{6,}")

# Normalizer: lowercase, collapse every run of chars outside [a-z0-9#*] to a
# single space, strip. `#` and `*` are load-bearing (store codes like `#0954`,
# `sq *` prefixes) and are deliberately preserved.
_NORMALIZE_RE = re.compile(r"[^a-z0-9#*]+")

# Generic English + finance/merchant words. Recall beats precision: a false
# positive is absorbed by .pii-dispositions, so this stays to genuinely generic
# words. Only word-class tokens (length >= 5) are filtered against it, but it is
# kept comprehensive so bank/merchant boilerplate never becomes a "word" token.
COMMON_WORDS = {
    # finance / merchant generics
    "payment",
    "payments",
    "transfer",
    "transfers",
    "purchase",
    "purchases",
    "online",
    "canada",
    "canadian",
    "credit",
    "debit",
    "insurance",
    "heating",
    "coffee",
    "market",
    "markets",
    "foods",
    "store",
    "stores",
    "wholesale",
    "restaurant",
    "restaurants",
    "services",
    "service",
    "mortgage",
    "cheque",
    "cheques",
    "deposit",
    "deposits",
    "withdrawal",
    "monthly",
    "annual",
    "limited",
    "company",
    "companies",
    "holdings",
    "holding",
    "account",
    "accounts",
    "balance",
    "balances",
    "transaction",
    "transactions",
    "amount",
    "amounts",
    "invoice",
    "invoices",
    "receipt",
    "receipts",
    "billing",
    "billed",
    "refund",
    "refunds",
    "charge",
    "charges",
    "charged",
    "interac",
    "etransfer",
    "email",
    "emails",
    "money",
    "funds",
    "banking",
    "banks",
    "branch",
    "branches",
    "savings",
    "checking",
    "chequing",
    "interest",
    "loan",
    "loans",
    "lending",
    "financial",
    "finance",
    "fee",
    "fees",
    "rate",
    "rates",
    "total",
    "totals",
    "subtotal",
    "taxes",
    "grocery",
    "groceries",
    "gas",
    "fuel",
    "energy",
    "utility",
    "utilities",
    "water",
    "hydro",
    "power",
    "internet",
    "mobile",
    "phone",
    "wireless",
    "cable",
    "streaming",
    "subscription",
    "subscriptions",
    "membership",
    "renewal",
    "supply",
    "supplies",
    "hardware",
    "software",
    "pharmacy",
    "medical",
    "dental",
    "clinic",
    "hospital",
    "doctor",
    "health",
    "auto",
    "automotive",
    "repair",
    "repairs",
    "rental",
    "rentals",
    "parking",
    "transit",
    "airline",
    "airlines",
    "flight",
    "hotel",
    "hotels",
    "travel",
    "shipping",
    "delivery",
    "courier",
    "postal",
    "freight",
    "logistics",
    "retail",
    "outlet",
    "outlets",
    "shop",
    "shopping",
    "vendor",
    "supplier",
    "merchant",
    "customer",
    "client",
    "clients",
    "office",
    "offices",
    "group",
    "groups",
    "global",
    "national",
    "international",
    "regional",
    "local",
    "central",
    "united",
    "general",
    "public",
    "private",
    "federal",
    "provincial",
    "municipal",
    "government",
    "corporation",
    "corp",
    "incorporated",
    "partners",
    "partnership",
    "enterprise",
    "enterprises",
    "solutions",
    "systems",
    "system",
    "technologies",
    "technology",
    "digital",
    "media",
    "network",
    "networks",
    "communications",
    "electric",
    "electrical",
    "electronics",
    "industrial",
    "industries",
    "manufacturing",
    "products",
    "product",
    "brands",
    "brand",
    "goods",
    "trading",
    "traders",
    "trade",
    "sales",
    "distribution",
    "distributor",
    "consulting",
    "consultants",
    "management",
    "associates",
    "agency",
    "agencies",
    "studio",
    "studios",
    "design",
    "designs",
    "creative",
    "capital",
    "ventures",
    "investment",
    "investments",
    "securities",
    "trust",
    "trusts",
    "mutual",
    "premium",
    "premiums",
    "policy",
    "policies",
    "claim",
    "claims",
    "coverage",
    "benefits",
    "benefit",
    "pension",
    "payroll",
    "salary",
    "wages",
    "income",
    "expense",
    "expenses",
    "budget",
    "quarterly",
    "weekly",
    "daily",
    "yearly",
    # common English (length >= 5 mostly)
    "about",
    "above",
    "after",
    "again",
    "against",
    "along",
    "already",
    "although",
    "always",
    "among",
    "another",
    "around",
    "because",
    "before",
    "being",
    "below",
    "between",
    "beyond",
    "could",
    "would",
    "should",
    "there",
    "their",
    "these",
    "those",
    "through",
    "under",
    "until",
    "which",
    "while",
    "where",
    "whose",
    "other",
    "others",
    "every",
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "great",
    "small",
    "large",
    "still",
    "right",
    "wrong",
    "early",
    "later",
    "please",
    "thank",
    "thanks",
    "regards",
    "sincerely",
    "hello",
    "dear",
    "notice",
    "notification",
    "alert",
    "alerts",
    "reminder",
    "confirm",
    "confirmation",
    "confirmed",
    "pending",
    "complete",
    "completed",
    "processed",
    "processing",
    "approved",
    "declined",
    "successful",
    "success",
    "failed",
    "error",
    "errors",
    "warning",
    "update",
    "updates",
    "updated",
    "change",
    "changes",
    "changed",
    "review",
    "reviewed",
    "detail",
    "details",
    "summary",
    "report",
    "reports",
    "statement",
    "statements",
    "period",
    "periods",
    "date",
    "dates",
    "time",
    "times",
    "number",
    "numbers",
    "reference",
    "code",
    "codes",
    "description",
    "category",
    "categories",
    "status",
    "value",
    "values",
    "type",
    "types",
    "name",
    "names",
    "address",
    "addresses",
    "location",
    "locations",
    "contact",
    "information",
    "message",
    "messages",
    "subject",
    "sender",
    "recipient",
    "friday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "august",
    "september",
    "october",
    "november",
    "december",
    "morning",
    "evening",
    "today",
    "tomorrow",
    "yesterday",
    "recent",
    "current",
    "previous",
    "next",
    "available",
    "unavailable",
    "active",
    "inactive",
    "enabled",
    "disabled",
    "primary",
    "secondary",
    "default",
    "standard",
    "custom",
    "special",
    "regular",
    "normal",
    "basic",
    "advanced",
    "simple",
    "quick",
    "fast",
    "slow",
    "temporary",
    "permanent",
    "official",
    "unofficial",
    "verified",
    "unverified",
    "secure",
    "security",
    "password",
    "username",
    "login",
    "logout",
    "signin",
    "signup",
    "welcome",
    "goodbye",
    "afternoon",
    "dollars",
    "cents",
    "toward",
    "towards",
    "within",
    "without",
    "during",
    "since",
    "unless",
    "however",
    "therefore",
    "otherwise",
    "meanwhile",
    "furthermore",
    "moreover",
    "street",
    "avenue",
    "boulevard",
    "drive",
    "court",
    "place",
    "road",
    "lane",
    "suite",
    "floor",
    "unit",
    "building",
    "tower",
    "plaza",
    "centre",
    "center",
    "north",
    "south",
    "east",
    "west",
    "northwest",
    "northeast",
    "southwest",
    "southeast",
    "province",
    "country",
    "region",
    "district",
    "county",
    "world",
    "worldwide",
    "people",
    "person",
    "family",
    "friend",
    "member",
    "community",
    "society",
    "association",
    "foundation",
    "institute",
    "university",
    "college",
    "school",
    "schools",
    "education",
    "student",
    "students",
    "program",
    "programs",
    "project",
    "projects",
    "resource",
    "resources",
    "material",
    "materials",
    "equipment",
    "machine",
    "machines",
    "device",
    "devices",
    "tool",
    "tools",
    "vehicle",
    "vehicles",
    "engine",
    "motor",
}


def _normalize(text: str) -> str:
    """Lowercase, collapse non-[a-z0-9#*] runs to single spaces, strip.

    Shared by token extraction, disposition-entry parsing, and tree-line
    matching so all three live in the same space. `#` and `*` survive.
    """
    return _NORMALIZE_RE.sub(" ", text.lower()).strip()


def _is_digits_spaces(text: str) -> bool:
    """True if ``text`` is only digits and spaces (rejects numeric full-strings)."""
    return all(ch.isdigit() or ch == " " for ch in text)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class Token:
    """A distinct value pulled from the CSV, with provenance and row frequency."""

    text: str  # matching key (normalized; raw canonical form for `amount`)
    cls: str
    rows: int = 0
    columns: set[str] = field(default_factory=set)
    variant_of: str | None = None
    dispositioned: bool = False
    also_classes: list[str] = field(default_factory=list)  # cross-class dupes folded in (e.g. "word")


@dataclass
class Finding:
    cls: str
    token: str
    file: str
    line: int
    match: str  # raw line (redacted unless --include-matches)
    variant_of: str | None = None
    anchor: str | None = None  # for `amount`: the "file:line" it co-located with

    def redacted_token(self) -> str:
        return f"<REDACTED:{len(self.token)} chars>"

    def redacted_line(self) -> str:
        return f"<REDACTED:{len(self.match)} chars>"


@dataclass
class ScanState:
    findings: list[Finding] = field(default_factory=list)
    dispositioned: list[Finding] = field(default_factory=list)
    seen: set[tuple[str, str, str, int]] = field(default_factory=set)
    counts: dict[tuple[str, str], int] = field(default_factory=dict)
    capped: set[tuple[str, str]] = field(default_factory=set)


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------


def _download(repo_root: Path) -> None:
    """Fetch a fresh transaction export by running the download CLI at repo_root.

    Raises RuntimeError on a non-zero return code. The error text mentions the
    return code only — never any CSV content.
    """
    result = subprocess.run(
        ["uv", "run", "python", "dev/cli/download_transaction_table.py"],  # noqa: S607
        cwd=str(repo_root),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"download_transaction_table.py exited {result.returncode}")


# --------------------------------------------------------------------------
# Disposition allowlist
# --------------------------------------------------------------------------


def load_dispositions(path: Path) -> tuple[set[str], bool]:
    """Parse the disposition allowlist into a set of normalized entries.

    Returns (normalized_entries, missing). One entry per line; `#` comments and
    blanks ignored. Each entry is normalized so comparison against a normalized
    token is exact. A missing file yields an empty set with missing=True.
    """
    if not path.is_file():
        return set(), True
    entries: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        norm = _normalize(line)
        if norm:
            entries.add(norm)
    return entries, False


# --------------------------------------------------------------------------
# Token extraction
# --------------------------------------------------------------------------


def _adjacent_transpositions(word: str) -> set[str]:
    """Every adjacent-character swap of ``word`` (bank-side surname misspellings)."""
    out: set[str] = set()
    chars = list(word)
    for i in range(len(chars) - 1):
        swapped = chars[:]
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        variant = "".join(swapped)
        if variant != word:
            out.add(variant)
    return out


def _bump(
    reg: dict[tuple[str, str], Token],
    row_seen: set[tuple[str, str]],
    cls: str,
    text: str,
    col: str | None,
    variant_of: str | None = None,
) -> Token:
    key = (cls, text)
    tok = reg.get(key)
    if tok is None:
        tok = Token(text=text, cls=cls, variant_of=variant_of)
        reg[key] = tok
    if col:
        tok.columns.add(col)
    if key not in row_seen:
        tok.rows += 1
        row_seen.add(key)
    return tok


def extract_tokens(csv_path: Path, dispositions: set[str]) -> tuple[dict[tuple[str, str], Token], list[str]]:
    """Read the export CSV and build the token registry keyed by (class, text).

    Token classes: full-string, prefix, word, word-variant, email, reference,
    amount. See the module docstring / packet spec for the exact rules. Missing
    columns are tolerated (row.get(col) or "").
    """
    notes: list[str] = []
    reg: dict[tuple[str, str], Token] = {}
    total_rows = 0

    with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            total_rows += 1
            row_seen: set[tuple[str, str]] = set()

            # --- merchant / counterparty / person columns ---
            for col in FULLSTRING_COLUMNS:
                cell = row.get(col) or ""
                norm = _normalize(cell)
                if not norm:
                    continue
                if len(norm) >= 5 and not _is_digits_spaces(norm):
                    _bump(reg, row_seen, "full-string", norm, col)
                words = norm.split()
                # prefix: proper leading prefixes of >= 2 words, joined len >= 7.
                # A 2-word prefix that contains a 1-char word (single-letter
                # merchant initials) is noise — it collides with normalized code
                # fragments like `if len(w)` -> `... a and w ...`. Require every
                # word >= 2 chars OR the prefix to span >= 3 words; the full-string
                # token still covers the real merchant either way.
                if len(words) >= 3:
                    for k in range(2, len(words)):
                        prefix_words = words[:k]
                        prefix = " ".join(prefix_words)
                        if len(prefix) < 7:
                            continue
                        if not (all(len(w) >= 2 for w in prefix_words) or len(prefix_words) >= 3):
                            continue
                        _bump(reg, row_seen, "prefix", prefix, col)
                # word: individual alphabetic words len >= 5, minus the stoplist.
                for w in words:
                    if len(w) >= 5 and w.isalpha() and w not in COMMON_WORDS:
                        _bump(reg, row_seen, "word", w, col)

            # --- email columns ---
            for col in EMAIL_COLUMNS:
                cell = row.get(col) or ""
                if "@" not in cell:
                    continue
                for m in _EMAIL_RE.finditer(cell):
                    addr = m.group(0).lower()
                    _, _, domain = addr.partition("@")
                    if domain in EMAIL_ALLOW_DOMAINS:
                        continue
                    norm = _normalize(addr)
                    if norm:
                        _bump(reg, row_seen, "email", norm, col)

            # --- reference columns ---
            for col in REFERENCE_COLUMNS:
                cell = row.get(col) or ""
                for m in _REFERENCE_RE.finditer(cell):
                    run = m.group(0)
                    has_digit = any(c.isdigit() for c in run)
                    has_letter = any(c.isalpha() for c in run)
                    if has_digit and has_letter:
                        _bump(reg, row_seen, "reference", run.lower(), col)

            # --- amount column ---
            cell = row.get("Amount") or ""
            try:
                value = float(cell)
            except (TypeError, ValueError):
                value = None
            if value is not None and abs(value) >= 100:
                canonical = f"{abs(value):.2f}"
                _bump(reg, row_seen, "amount", canonical, "Amount")

    # --- reference boilerplate drop + cap ---
    if total_rows > 0:
        threshold = total_rows * REFERENCE_BOILERPLATE_FRACTION
        for key in [k for k in reg if k[0] == "reference"]:
            if reg[key].rows > threshold:
                del reg[key]
    ref_keys = [k for k in reg if k[0] == "reference"]
    if len(ref_keys) > REFERENCE_CAP:
        ref_keys.sort(key=lambda k: reg[k].rows, reverse=True)
        for key in ref_keys[REFERENCE_CAP:]:
            del reg[key]
        notes.append(f"reference tokens capped at {REFERENCE_CAP} (from {len(ref_keys)} distinct).")

    # --- word-variant generation ---
    all_words = {text for (cls, text) in reg if cls == "word"}
    word_items = [(text, tok) for (cls, text), tok in reg.items() if cls == "word"]
    for text, tok in word_items:
        if len(text) < 6:
            continue
        for variant in _adjacent_transpositions(text):
            if variant in all_words or variant in COMMON_WORDS:
                continue
            key = ("word-variant", variant)
            existing = reg.get(key)
            if existing is None:
                reg[key] = Token(
                    text=variant,
                    cls="word-variant",
                    rows=tok.rows,
                    columns=set(tok.columns),
                    variant_of=text,
                )
            else:
                existing.columns.update(tok.columns)

    # --- cross-class dedupe ---
    # A value present as a full-string token AND as a same-text word/prefix token
    # produces two groups for one value (and would need two disposition entries).
    # Collapse to the full-string token, recording the dropped class in its
    # provenance, so dispositions and finding groups map 1:1 to values.
    fullstring_texts = [text for (cls, text) in reg if cls == "full-string"]
    for text in fullstring_texts:
        fs_tok = reg[("full-string", text)]
        for other_cls in ("word", "prefix"):
            other = reg.pop((other_cls, text), None)
            if other is not None:
                fs_tok.columns.update(other.columns)
                if other_cls not in fs_tok.also_classes:
                    fs_tok.also_classes.append(other_cls)

    # --- disposition marking ---
    for tok in reg.values():
        if _normalize(tok.text) in dispositions:
            tok.dispositioned = True

    notes.append(f"read {total_rows} CSV row(s); extracted {len(reg)} distinct token(s).")
    return reg, notes


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

_WORD_CLASSES = {"word", "word-variant"}


def build_matchers(
    reg: dict[tuple[str, str], Token],
) -> tuple[dict[str, tuple[list[re.Pattern[str]], dict[str, Token], bool]], dict[str, Token]]:
    """Compile chunked regex alternations per class; split off amount tokens.

    Word classes wrap the alternation in `(?<![a-z0-9])...(?![a-z0-9])`.
    Amounts are matched only in the proximity pass (raw-line substring), so they
    get no regex.
    """
    by_cls: dict[str, dict[str, Token]] = {}
    for (cls, text), tok in reg.items():
        by_cls.setdefault(cls, {})[text] = tok

    matchers: dict[str, tuple[list[re.Pattern[str]], dict[str, Token], bool]] = {}
    for cls, table in by_cls.items():
        if cls == "amount":
            continue
        is_word = cls in _WORD_CLASSES
        texts = [t for t in table if t]
        chunks: list[re.Pattern[str]] = []
        for i in range(0, len(texts), CHUNK_SIZE):
            group = texts[i : i + CHUNK_SIZE]
            alt = "|".join(re.escape(t) for t in group)
            if is_word:
                chunks.append(re.compile(rf"(?<![a-z0-9])(?:{alt})(?![a-z0-9])"))
            else:
                chunks.append(re.compile(rf"(?:{alt})"))
        matchers[cls] = (chunks, table, is_word)

    amount_tokens = {text: tok for (cls, text), tok in reg.items() if cls == "amount"}
    return matchers, amount_tokens


def _amount_forms(canonical: str) -> list[str]:
    """Raw-line substring forms of an amount: plain and comma-grouped."""
    forms = [canonical]
    try:
        grouped = f"{float(canonical):,.2f}"
    except ValueError:
        grouped = canonical
    if grouped != canonical:
        forms.append(grouped)
    return forms


def _amount_present(raw: str, form: str) -> bool:
    """True if ``form`` occurs in ``raw`` on a digit boundary (not inside a longer number).

    A plain substring test lets ``200.00`` match inside ``3200.00`` and ``400.00``
    inside ``$2,400.00``. Anchor every occurrence on digit boundaries instead: the
    char before the match must not be a digit, a grouping comma (a comma preceded
    by a digit), or a decimal point preceded by a digit; the char after must not be
    a digit. Applies uniformly to the plain and comma-grouped forms — so the
    grouped form ``2,400.00`` still matches ``$2,400.00`` exactly.
    """
    start = raw.find(form)
    while start != -1:
        end = start + len(form)
        before = raw[start - 1] if start > 0 else ""
        before2 = raw[start - 2] if start > 1 else ""
        after = raw[end] if end < len(raw) else ""
        bad_before = before.isdigit() or (before == "," and before2.isdigit()) or (before == "." and before2.isdigit())
        if not bad_before and not after.isdigit():
            return True
        start = raw.find(form, start + 1)
    return False


def _record(
    state: ScanState,
    tok: Token,
    rel: str,
    lineno: int,
    raw: str,
    anchors: list[Finding],
    anchor_ref: str | None = None,
) -> None:
    key = (tok.cls, tok.text)
    dedupe = (tok.cls, tok.text, rel, lineno)
    if dedupe in state.seen:
        return
    if state.counts.get(key, 0) >= PER_TOKEN_MATCH_CAP:
        state.capped.add(key)
        return
    state.seen.add(dedupe)
    state.counts[key] = state.counts.get(key, 0) + 1
    finding = Finding(
        cls=tok.cls,
        token=tok.text,
        file=rel,
        line=lineno,
        match=raw,
        variant_of=tok.variant_of,
        anchor=anchor_ref,
    )
    if tok.dispositioned:
        state.dispositioned.append(finding)
    else:
        state.findings.append(finding)
        if tok.cls != "amount":
            anchors.append(finding)


def scan_one(
    rel: str,
    lines: list[str],
    matchers: dict[str, tuple[list[re.Pattern[str]], dict[str, Token], bool]],
    amount_tokens: dict[str, Token],
    state: ScanState,
) -> None:
    """Scan one file's raw lines: regex classes, then the amount proximity pass."""
    anchors: list[Finding] = []
    for lineno, raw in enumerate(lines, start=1):
        if ATTRIBUTION_ALLOW.search(raw):
            continue
        norm = _normalize(raw)
        if not norm:
            continue
        for chunks, table, _is_word in matchers.values():
            for pattern in chunks:
                for m in pattern.finditer(norm):
                    tok = table.get(m.group(0))
                    if tok is not None:
                        _record(state, tok, rel, lineno, raw, anchors)

    # amount proximity: only for files with >= 1 non-dispositioned finding.
    if not anchors or not amount_tokens:
        return
    forms_by_amount = {text: _amount_forms(text) for text in amount_tokens}
    for anchor in anchors:
        lo = max(1, anchor.line - 2)
        hi = min(len(lines), anchor.line + 2)
        anchor_ref = f"{anchor.file}:{anchor.line}"
        for ln in range(lo, hi + 1):
            raw = lines[ln - 1]
            for text, tok in amount_tokens.items():
                if any(_amount_present(raw, form) for form in forms_by_amount[text]):
                    _record(state, tok, rel, ln, raw, anchors, anchor_ref=anchor_ref)


# --------------------------------------------------------------------------
# File gathering + classification
# --------------------------------------------------------------------------


def is_binary(path: Path) -> bool:
    try:
        chunk = path.open("rb").read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


def gather_tracked(repo_root: Path) -> list[tuple[Path, str]]:
    """The files reported by `git ls-files -z` at repo_root (never the working tree).

    Using the index (not an rglob) keeps untracked local-only files — e.g.
    .pii-patterns — out of the scan so they cannot self-match.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files exited {result.returncode}")
    out: list[tuple[Path, str]] = []
    for part in result.stdout.split(b"\0"):
        if not part:
            continue
        rel = part.decode("utf-8", errors="replace")
        abspath = repo_root / rel
        if abspath.is_file():
            out.append((abspath, rel))
    return out


def gather_target(target: Path) -> list[tuple[Path, str]]:
    """Every file under ``target``, skipping any path with a `.git` part."""
    out: list[tuple[Path, str]] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target)
        if ".git" in rel.parts:
            continue
        out.append((path, str(rel)))
    return out


def scan_files(
    files: list[tuple[Path, str]],
    matchers: dict[str, tuple[list[re.Pattern[str]], dict[str, Token], bool]],
    amount_tokens: dict[str, Token],
    state: ScanState,
) -> tuple[int, int]:
    """Scan each file (skipping oversize / binary / unreadable). Returns (scanned, skipped)."""
    scanned = 0
    skipped = 0
    for abspath, rel in files:
        try:
            size = abspath.stat().st_size
        except OSError:
            skipped += 1
            continue
        if size > BIG_FILE_BYTES:
            skipped += 1
            continue
        if is_binary(abspath):
            skipped += 1
            continue
        try:
            text = abspath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        scanned += 1
        scan_one(rel, text.splitlines(), matchers, amount_tokens, state)
    return scanned, skipped


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _group_by_token(findings: list[Finding]) -> dict[tuple[str, str], list[Finding]]:
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        groups.setdefault((f.cls, f.token), []).append(f)
    return groups


def _token_entry(
    key: tuple[str, str],
    items: list[Finding],
    reg: dict[tuple[str, str], Token],
    include_matches: bool,
) -> dict:
    cls, text = key
    tok = reg.get(key)
    rows = tok.rows if tok else 0
    columns = sorted(tok.columns) if tok else []
    variant_of = tok.variant_of if tok else None
    provenance: dict = {"columns": columns, "variant_of": variant_of}
    also = sorted(tok.also_classes) if tok else []
    if also:
        provenance["also_classes"] = [f"also {c}-class" for c in also]
    entry: dict = {
        "token_class": cls,
        "row_count": rows,
        "provenance": provenance,
        "redacted_token": f"<REDACTED:{len(text)} chars>",
    }
    if include_matches:
        entry["token"] = text
    match_list: list[dict] = []
    for f in items:
        m: dict = {
            "file": f.file,
            "line": f.line,
            "redacted_line": f.redacted_line(),
        }
        if f.anchor:
            m["anchor"] = f.anchor
        if include_matches:
            m["match"] = f.match
        match_list.append(m)
    entry["matches"] = match_list
    return entry


def _md_cell(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|")
    escaped = escaped.replace("\r", " ").replace("\n", " ")
    return f"`{escaped}`"


def write_reports(
    csv_path: Path,
    reg: dict[tuple[str, str], Token],
    state: ScanState,
    files_scanned: int,
    files_skipped: int,
    notes: list[str],
    base: Path,
    include_matches: bool,
) -> int:
    """Write the .json and .md collision reports; return the exit code (0 or 1)."""
    exit_code = 1 if state.findings else 0

    tokens_by_class: dict[str, int] = {}
    for cls, _text in reg:
        tokens_by_class[cls] = tokens_by_class.get(cls, 0) + 1

    # Raw match ROWS per class — distinct from finding groups (collapsed per token).
    # The two live under deliberately unlike names so a reader can't conflate them.
    match_lines_by_class: dict[str, int] = {}
    for f in state.findings:
        match_lines_by_class[f.cls] = match_lines_by_class.get(f.cls, 0) + 1

    if state.capped:
        notes.append(f"{len(state.capped)} token(s) hit the {PER_TOKEN_MATCH_CAP}-match cap; match lists truncated.")

    finding_groups = _group_by_token(state.findings)
    dispo_groups = _group_by_token(state.dispositioned)

    payload = {
        "csv": str(csv_path),
        "summary": {
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "findings": len(state.findings),
            "token_groups": len(finding_groups),
            "dispositioned": len(state.dispositioned),
            "exit_code": exit_code,
        },
        "tokens_by_class": tokens_by_class,
        "match_lines_by_class": match_lines_by_class,
        "findings": [_token_entry(key, items, reg, include_matches) for key, items in sorted(finding_groups.items())],
        "dispositioned": [
            _token_entry(key, items, reg, include_matches) for key, items in sorted(dispo_groups.items())
        ],
        "notes": notes,
    }

    base.parent.mkdir(parents=True, exist_ok=True)
    (base.parent / (base.name + ".json")).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    verdict = "🛑 collisions found" if exit_code == 1 else "✅ no collisions"
    md: list[str] = [
        "# Real-data collision report",
        "",
        f"**Verdict:** {verdict} (exit {exit_code})",
        f"**CSV:** `{csv_path}`",
        f"**Files scanned:** {files_scanned}  |  **skipped:** {files_skipped}",
        f"**Findings:** {len(state.findings)}  |  **Dispositioned:** {len(state.dispositioned)}",
        "",
    ]
    if include_matches:
        md += [
            "Matched text is shown in full below — this report lives in the gitignored",
            "`logs/audit/` tree. Re-run without `--include-matches` to redact.",
            "",
        ]
    else:
        md += [
            "Token text and matched lines are redacted. Re-run with `--include-matches`",
            "to write full values into the reports for inspection.",
            "",
        ]

    md += ["## Tokens extracted by class", "", "| Class | Count |", "|-------|-------|"]
    for cls, n in sorted(tokens_by_class.items(), key=lambda kv: -kv[1]):
        md.append(f"| {cls} | {n} |")

    match_col = "Match" if include_matches else "Line"

    def token_table(title: str, groups: dict[tuple[str, str], list[Finding]]) -> None:
        md.extend(["", f"## {title}", ""])
        if not groups:
            md.append("_none_")
            return
        for key, items in sorted(groups.items()):
            cls, text = key
            tok = reg.get(key)
            rows = tok.rows if tok else 0
            variant_of = tok.variant_of if tok else None
            shown_token = _md_cell(text) if include_matches else f"<REDACTED:{len(text)} chars>"
            header = f"### {cls} · {shown_token} · rows={rows}"
            if variant_of:
                header += f" · variant-of={_md_cell(variant_of) if include_matches else '<redacted>'}"
            md.append(header)
            md.append("")
            md.append(f"| File | Line | Anchor | {match_col} |")
            md.append("|------|------|--------|-------|")
            for f in items:
                anchor = f.anchor or ""
                shown = _md_cell(f.match) if include_matches else f.redacted_line()
                md.append(f"| `{f.file}` | {f.line} | {anchor} | {shown} |")
            md.append("")

    token_table(f"Findings — {len(state.findings)}", finding_groups)
    token_table(f"Dispositioned (allowlisted) — {len(state.dispositioned)}", dispo_groups)

    if notes:
        md.extend(["", "## Notes", ""] + [f"- {n}" for n in notes])

    (base.parent / (base.name + ".md")).write_text("\n".join(md) + "\n", encoding="utf-8")
    return exit_code


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]

    ap = argparse.ArgumentParser(
        description="Search the tracked tree for values from the maintainer's real transaction export."
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=repo_root / "data" / "raw" / "transaction_db_rough" / "transactions.csv",
        help="Transaction export CSV to search for (default: data/raw/transaction_db_rough/transactions.csv)",
    )
    ap.add_argument(
        "--download",
        action="store_true",
        help="Fetch a fresh export first; delete it after the scan unless --keep-csv",
    )
    ap.add_argument("--keep-csv", action="store_true", help="With --download, keep the fetched CSV")
    ap.add_argument(
        "--dispositions",
        type=Path,
        default=repo_root / ".pii-dispositions",
        help="Allowlist of adjudicated-sanctioned tokens (default: .pii-dispositions)",
    )
    ap.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Directory to scan instead of the git-tracked tree",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=repo_root / "logs" / "audit" / "collision-report",
        help="Report basename (default: logs/audit/collision-report)",
    )
    ap.add_argument(
        "--include-matches",
        action="store_true",
        help="Write full (unredacted) token text and matched lines into the reports",
    )
    args = ap.parse_args(argv)

    csv_path = args.csv.expanduser().resolve()

    if args.download:
        try:
            _download(repo_root)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            print(f"error: transaction download failed ({exc})", file=sys.stderr)
            return 3

    if not csv_path.is_file():
        print(f"error: transaction CSV not found: {csv_path}", file=sys.stderr)
        return 3

    dispositions, dispo_missing = load_dispositions(args.dispositions.expanduser().resolve())
    notes: list[str] = []
    if dispo_missing:
        notes.append(f"no dispositions file at {args.dispositions}; treated as empty.")
    else:
        notes.append(f"dispositions loaded from {args.dispositions} ({len(dispositions)} entr(y/ies)).")

    if args.download:
        notes.append("CSV kept (--keep-csv)." if args.keep_csv else "CSV deleted after scan (--download).")

    delete_after = args.download and not args.keep_csv
    exit_code = 3
    try:
        reg, extract_notes = extract_tokens(csv_path, dispositions)
        notes.extend(extract_notes)

        matchers, amount_tokens = build_matchers(reg)

        if args.target is not None:
            target = args.target.expanduser().resolve()
            if not target.is_dir():
                print(f"error: --target is not a directory: {target}", file=sys.stderr)
                return 3
            files = gather_target(target)
        else:
            try:
                files = gather_tracked(repo_root)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                print(f"error: could not enumerate tracked files ({exc})", file=sys.stderr)
                return 3

        state = ScanState()
        files_scanned, files_skipped = scan_files(files, matchers, amount_tokens, state)

        exit_code = write_reports(
            csv_path,
            reg,
            state,
            files_scanned,
            files_skipped,
            notes,
            args.output.expanduser().resolve(),
            args.include_matches,
        )

        _print_summary(reg, state, files_scanned, args.output.expanduser().resolve(), exit_code)
    finally:
        if delete_after and csv_path.exists():
            with contextlib.suppress(OSError):
                csv_path.unlink()

    return exit_code


def _print_summary(
    reg: dict[tuple[str, str], Token],
    state: ScanState,
    files_scanned: int,
    base: Path,
    exit_code: int,
) -> None:
    """Terminal summary — ALWAYS redacted: counts, classes, paths only."""
    tokens_by_class: dict[str, int] = {}
    for cls, _text in reg:
        tokens_by_class[cls] = tokens_by_class.get(cls, 0) + 1
    # match_lines_by_class counts raw match ROWS; token_groups is the collapsed
    # per-token group count. Printed under distinct labels so they can't be conflated.
    match_lines_by_class: dict[str, int] = {}
    for f in state.findings:
        match_lines_by_class[f.cls] = match_lines_by_class.get(f.cls, 0) + 1
    token_groups = len({(f.cls, f.token) for f in state.findings})

    verdict = "🛑 collisions found" if exit_code == 1 else "✅ no collisions"
    print(f"collision-check: scanned {files_scanned} files → exit {exit_code}  ({verdict})")
    if tokens_by_class:
        print("  tokens:  " + " · ".join(f"{c} {n}" for c, n in sorted(tokens_by_class.items())))
    print(f"  token-groups: {token_groups}")
    print(
        "  match-lines: "
        + (" · ".join(f"{c} {n}" for c, n in sorted(match_lines_by_class.items())) if match_lines_by_class else "none")
    )
    print(f"  dispositioned: {len(state.dispositioned)}")
    print(f"  reports: {base}.md / {base}.json")


if __name__ == "__main__":
    sys.exit(main())
