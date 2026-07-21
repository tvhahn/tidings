# Add a bank parser

Tidings turns the transaction-alert emails your bank already sends into a
private spending journal. Each supported bank has a small parser that reads one
email and returns structured fields (amount, merchant, type). Five Canadian
banks ship today (RBC, CIBC, MBNA, Simplii, PC Financial), but the architecture
is country- and language-neutral: a parser for any bank, anywhere, is the most
useful contribution you can make.

This guide is self-contained. Part 1 covers the email parser (the primary
path). Part 2 covers the PDF statement parser (a secondary path, for banks that
don't send alert emails or for reconciling uploaded statements).

## When your bank isn't supported yet

An alert from a bank Tidings doesn't recognize is not lost. If the body looks
like a transaction alert (a `$`-amount plus at least two alert keywords), it is
captured to the **Needs review** queue even with AI turned off. From there the
user can enter it by hand, or — with "Rescue unreadable emails with AI" enabled
in Settings — the app recovers it automatically by sending the body to the
configured AI provider (institution lands as `Other`). Those captured emails
are also the raw material for a real parser: the flow is capture → review →
rescue-or-author, and this guide is the *author* step. Once your parser lands,
`POST /api/v1/parse-failures/retry-all` recovers the whole backlog through it.

## Minimal setup

You don't need the full DevContainer to write a parser — a clone and `uv` are
enough:

```bash
git clone <your-fork-url> tidings && cd tidings
uv sync                       # creates .venv, installs Python 3.12 + deps
uv run pytest tests/unit/ -v  # confirm a green baseline
```

Always run Python through `uv run` (`uv run pytest`, `uv run python`), never
bare `python`/`pip` — only `uv run` sees the project's dependencies. Full
environment notes: [`environment-management.md`](environment-management.md).

## Start from your own quarantined emails

The best fixtures are the real alerts your instance already captured. List the
quarantined rows through the store factory (works on both storage backends):

```bash
uv run python -c '
from src.finance.storage import create_parse_failure_store
store = create_parse_failure_store()
for r in store.list_failures("quarantined", 1000):
    frm = r.get("from_email") or ""
    domain = frm.rsplit("@", 1)[-1] if "@" in frm else frm
    print("id=" + str(r["id"]), "domain=" + str(domain), "subject=" + str(r.get("subject")))
'
```

With the dev server running, turn a captured email straight into a scrubbed
fixture pair (PII redacted, amounts kept; refuses to overwrite, and requires a
git checkout with demo mode off):

```bash
curl -X POST http://localhost:8000/api/v1/parse-failures/<FAILURE_ID>/to-fixture \
  -H "Content-Type: application/json" -d '{"institution": "<Bank Name>"}'
```

It writes `tests/test_data/<slug>/<name>.txt` (the scrubbed body) plus a `.json`
skeleton whose `"TODO"` fields you complete from the body. Without a server,
scrub manually with `src/finance/fixture_scrub.scrub_body`.

Agents (and users running Claude Code) should prefer the
`.claude/skills/add-a-parser/` skill — it walks this whole guide end-to-end
from the captured emails, enforces the evidence rule (a transaction type with
no real sample is not parsed; it falls through to AI extraction), and finishes
with a bulk `retry-all` of the backlog.

---

## Part 1 — Email parser

### The contract

A parser lives under `src/finance/parsers/` and subclasses `TransactionParser`
from `src/finance/parser_base.py`. The abstract contract is one method:

```python
# src/finance/parser_base.py
class TransactionParser(ABC):
    @abstractmethod
    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        ...
```

`parse_email` receives the plain-text email body and the `email_details` dict
already extracted from the message (sender, date, etc.). It returns that dict
merged with the transaction fields you parse out: `name`, `amount`, `company`,
`transaction_type`, and `institution`. Use the `merge_details` and
`parse_amount` helpers exported from `parser_base.py` — don't reinvent them.
`AMOUNT_PATTERN` (also exported) matches comma-grouped or plain amounts
(`1,234.56`, `1000.00`) so `$1000.00` parses as `1000.0`, not `100.0`.

Reference parser: `src/finance/parsers/rbc_parser.py`. It's short, covers
purchases, withdrawals, and e-transfers, and is the cleanest thing to clone.

### Create the parser

Create `src/finance/parsers/<bank>_parser.py` (e.g. `td_parser.py`,
`chase_parser.py`, `barclays_parser.py`). Subclass `TransactionParser` and
implement `parse_email`:

```python
# src/finance/parsers/chase_parser.py
import logging
import re
from typing import Any

from src.finance.parser_base import (
    AMOUNT_PATTERN,
    TransactionParser,
    merge_details,
    parse_amount,
)

logger = logging.getLogger(__name__)


class ChaseParser(TransactionParser):
    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        parsed_data = None
        amount_match = re.search(rf"purchase of \$({AMOUNT_PATTERN})", email_body_text)
        if amount_match:
            parsed_data = {
                "name": None,
                "amount": parse_amount(amount_match.group(1)),
                "company": None,  # regex out the merchant here
                "transaction_type": "purchase",
            }
        email_details["institution"] = "Chase"
        return merge_details(email_details, parsed_data)
```

`merge_details` returns `email_details` unchanged when `parsed_data` is `None`,
so an email the parser doesn't recognise still flows through with its
`institution` stamped. Keep regexes readable and log matches at `DEBUG`. See how
`RBCParser.parse_purchase` splits amount and company into named patterns.

### Locale considerations

The five shipping parsers all handle Canadian-dollar emails with the
`$1,234.56` thousand-separator format. Parsing emails from elsewhere, watch:

- **Currency symbol.** `$` is hard-coded in the existing regexes. Yours may need
  `€`, `£`, `¥`, `kr`, `₹`, `R$`, or a three-letter code (`EUR 42.00`). Don't
  assume `$`.
- **Decimal and thousand separators.** `parse_amount` strips `,` as a thousand
  separator and treats `.` as the decimal point — fine for Canadian, US, and UK
  formats. If your bank writes `1.234,56` (German, Italian, Spanish, Portuguese
  conventions), do the swap inside your parser before calling `parse_amount`.
- **Date formats.** Bank emails vary widely (`DD/MM/YYYY`, `YYYY-MM-DD`,
  `15 Jan 2026`, `Jan 15`). Parse to a Python `datetime` early and let the
  existing pipeline format it.
- **Non-English bodies.** Regexes anchored on English keywords ("Purchase
  authorized", "You sent") won't match a Deutsche Bank or BNP Paribas email.
  Localize the keyword set in your parser; don't assume English in shared
  helpers.

### Register the parser

Everything routes through `src/finance/email_pipeline.py`. Wire your parser into
**three** places there:

1. **`PARSER_KEYS`** (module-level tuple) — the source of truth for which
   institution names can appear in an email body. Phase-2 body-text detection
   iterates it in order, and `parse_recovery` uses it to decide whether an
   unparsed email is even relevant. **A parser missing from here is invisible to
   body-text detection** (Interac e-transfers, emails with no matchable sender):

   ```python
   PARSER_KEYS: tuple[str, ...] = ("CIBC", "RBC", "MBNA", "Simplii", "PC Financial", "Chase")
   ```

2. **The `parsers` dict** built by `build_parsers()` in `email_pipeline.py`
   (parser imports sit at module top) — instantiates each parser. Both
   detection phases look the parser up here by key:

   ```python
   from src.finance.parsers.chase_parser import ChaseParser
   # ...
   parsers = {
       "CIBC": CIBCParser(),
       "RBC": RBCParser(),
       "MBNA": MBNAParser(),
       "Simplii": SimpliiParser(),
       "PC Financial": PCFinancialParser(),
       "Chase": ChaseParser(),
   }
   ```

3. **`_detect_institution_by_sender`'s `domain_map`** — maps the sender's email
   domain to your key, so Phase-1 sender detection runs before the body-text
   fallback:

   ```python
   domain_map = {
       "cibc.com": "CIBC",
       "alerts.rbc.com": "RBC",
       "mbna.ca": "MBNA",
       "pcfinancial.ca": "PC Financial",
       "chase.com": "Chase",
   }
   ```

   If your bank routes alerts through a generic clearing service like Interac,
   leave the domain out — body-text detection (step 1) picks them up. That's why
   `payments.interac.ca` is intentionally omitted.

### Add test fixtures

Drop sanitised email bodies (strip real names, account numbers, URLs) and their
expected parsed output under `tests/test_data/<institution>/` — a `.txt` file
for the raw body plus a matching `.json` for the expected fields. Example pair
already in the repo:

- `tests/test_data/rbc/2024.10.22_15.45_abc123def456_rbc_purchase.txt` — the raw
  email body.
- `tests/test_data/rbc/2024.10.22_15.45_abc123def456_rbc_purchase.json` — the
  expected output:

  ```json
  {
      "institution": "RBC",
      "name": "Demo User",
      "amount": 127.53,
      "company": "Costco Wholesale",
      "transaction_type": "purchase",
      "email_filepath": "tests/test_data/rbc/2024.10.22_15.45_abc123def456_rbc_purchase.txt"
  }
  ```

Cover at least one fixture per transaction type you support (purchase,
withdrawal, e-transfer, pre-auth, etc.) plus an `edge_case_*` fixture for
anything nasty (large amounts, unusual wording, non-ASCII merchant names). Put
Chase fixtures in `tests/test_data/chase/`.

Then add a parametrised test at `tests/unit/test_<bank>_parser.py` — copy
`tests/unit/test_rbc_parser.py`. `load_test_data("chase")` (from
`tests/conftest.py`) picks up every JSON in your fixture dir automatically.

### Run the tests

```bash
uv run pytest tests/unit/ -v -k chase   # tight loop
make verify                             # full gate before you open a PR
```

`tests/property/test_parser_invariants.py` runs shared invariants against every
parser in its explicit `PARSERS` list — register yours there, add a matching
`BODY_FACTORIES` entry (a body template with the amount slotted in; the
whitespace-invariant test KeyErrors without it), and add any common-word trigger
to `TRIGGER_SUBSTRINGS`. A parser missing from the list gets no property
coverage.

---

## Part 2 — PDF statement parser

For banks that don't send transaction alerts, or for users who want to reconcile
uploaded PDF statements against their email-derived history, Tidings also parses
statement PDFs. Two banks ship today (`RBCChequingParser`,
`SimpliiChequingParser`). This is a secondary path — email-first ingestion is
the product's core — but a real one that reaches users whose banks send no alert
emails at all.

For any other bank, the upload falls back to the AI statement parser
(`src/finance/statement_parser_ai.py`) when the user has opted in via
`ai_statement_parsing_enabled` — it prompts the configured AI provider with the
PDF's extracted text and fail-closed-validates the reply (every amount must
appear verbatim in the text). That fallback makes unsupported banks usable
immediately, but a deterministic parser is still the destination: it is free,
instant, offline, and its output never needs a "check this against the PDF"
caveat. Use the AI fallback's results as ground truth while building one.

### The contract

Statement parsers subclass `StatementParser`, defined in
`src/finance/statement_parser_base.py` (the public module
`src/finance/statement_parser.py` re-exports it and everything below, so the
`from src.finance.statement_parser import ...` surface stays stable):

```python
# src/finance/statement_parser_base.py
class StatementParser:
    institution: str = ""
    account_type: str = ""

    def parse(self, pdf_bytes: bytes) -> StatementParseResult: ...
    def validate_pdf(self, pdf_bytes: bytes) -> str | None: ...  # size/magic-byte check
```

`parse` returns a `StatementParseResult` (`transactions`, `metadata`,
`raw_descriptions`, `cleaned_descriptions`).

Reference parser: `src/finance/parsers/rbc_statement_parser.py`
(`RBCChequingParser`). It uses `pdfplumber` to read word positions and reuses
the shared helpers imported from `statement_parser_base` — `_detect_columns`,
`_extract_statement_period`, `_parse_page`, `clean_statement_description` — plus
the base's `validate_pdf()` and `_setup_logging()`.

### Two ways to extract the table

Statement PDFs vary in how cleanly they expose their text. Two slash-command
skills help during development:

- **`parse-statement-text`** (`.claude/commands/parse-statement-text.md`) — read
  pdfplumber's text output and structure it into JSON. Use this when the PDF has
  selectable text and recognizable column layouts.
- **`parse-statement-vision`** (`.claude/commands/parse-statement-vision.md`) —
  render each page to PNG and parse the image. Use this when the PDF is scanned
  or when text extraction loses the column structure.

Start with text extraction; fall back to vision when the text is unusable.
Either way, the goal is a list of `{date, description, amount, type, balance}`
records that your parser converts into a `StatementParseResult`.

### Create and register the parser

Create `src/finance/parsers/<bank>_statement_parser.py`, subclass
`StatementParser`, set `institution` and `account_type`, and implement `parse`
(clone `RBCChequingParser`). Then register it in
`src/finance/statement_parser.py`:

1. Import your parser class at the top of the module.
2. Add its name to `__all__`.
3. Extend `select_parser(pdf_bytes)` to detect your bank's PDF — typically by
   searching the first page or two for an institution marker. See how Simplii is
   detected (a `"simplii"` text match or a `"trans."` header word); anything not
   matched falls through to `RBCChequingParser`.

### Reconciliation

`src/finance/statement_reconciler.py` matches statement transactions against the
existing transaction store (DynamoDB or SQLite). It compares by amount, date,
and direction, so your parser must set each transaction's `type` to
`withdrawal` (outflow) or `deposit` (inflow) correctly — the reconciler maps
those onto the DB's `purchase`/`withdrawal`/`preauth` (outflow) and `deposit`
(inflow) types. The shared page-parsing helpers already emit the right types for
the shipping parsers.

### Add fixtures and run

Statement fixtures live alongside email fixtures under
`tests/test_data/<institution>/`: a `.pdf` plus a matching `.json` of the
expected output. Existing example:

- `tests/test_data/rbc/Rbc_Chequing_2025-02-24_to_2025-03-24.pdf`
- `tests/test_data/rbc/Rbc_Chequing_2025-02-24_to_2025-03-24.json`

Sanitise the PDF first — replace real account numbers, balances, and merchant
data with synthetic values that still exercise the parser's edge cases. The
email-fixture tests filter statement JSONs out by their different schema, so the
two can share a directory.

```bash
uv run pytest tests/ -v -k statement
make verify
```

---

When your parser is green, open a PR — see
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) for PR conventions. One bank per PR is
ideal.
