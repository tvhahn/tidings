---
name: add-a-parser
description: |
  Author a deterministic email parser for a bank Tidings doesn't yet
  support, working only from the user's quarantined ("Needs review") emails
  — scrubs real samples into fixtures, derives a conservative regex parser,
  and runs the suites. Invoke when the user says "add support for my bank",
  "my bank isn't supported", "write a parser for <bank>", or "bank not
  recognized".
disable-model-invocation: false
argument-hint: "[bank name]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(uv:*), Bash(git:*), Bash(curl:*)
---

# Add a bank parser (from the user's own quarantined emails)

Turn "my bank isn't supported" into a working, tested parser built **only from
real captured emails**. Run every Python command through `uv run`. Work in the
current checkout. Follow the numbered steps in order; do not skip the evidence
rule in Step 2.

## The evidence rule (read first, non-negotiable)

**A transaction type with no real captured sample is NOT parsed — it falls
through to AI extraction. Never invent template text, and never write a regex
you cannot trace to a specific line of a captured body.** Every regex you write
must be justified by a line you can point to in a scrubbed `.txt` fixture. If you
have no sample for "e-transfer", you write no e-transfer regex. That is correct
behavior, not a gap.

---

## Step 1 — Identify the target bank

If a bank name was passed as the argument, use it. Otherwise list the user's
quarantined emails so you (and they) can see which bank to build for. This
snippet works on **both** storage backends (SQLite and DynamoDB) because it goes
through the store factory:

```bash
uv run python -c '
from src.finance.storage import create_parse_failure_store
store = create_parse_failure_store()
rows = store.list_failures("quarantined", 1000)
if not rows:
    print("No quarantined parse failures found. Nothing to build a parser from yet.")
for r in rows:
    frm = r.get("from_email") or ""
    domain = frm.rsplit("@", 1)[-1] if "@" in frm else frm
    print(
        "id=" + str(r["id"]),
        "domain=" + str(domain),
        "detected=" + str(r.get("detected_institution")),
        "subject=" + str(r.get("subject")),
    )
'
```

Group the rows by `domain`. Each distinct bank domain (or a shared clearing
domain like `payments.interac.ca`) is a candidate. Pick the bank you were asked
about, and note its sender **domain** and the failure **ids** you'll pull bodies
from. Confirm the bank name with the user if it's ambiguous.

---

## Step 2 — Capture one scrubbed fixture per transaction type

Read the bodies of the failure ids from Step 1 and identify the distinct
transaction types present (purchase, withdrawal, deposit, e-transfer, payment,
…). **Capture at least one real body per type.** Re-read the evidence rule above.

### Preferred: the `to-fixture` endpoint (if the API server is running)

```bash
curl -X POST http://localhost:8000/api/v1/parse-failures/<FAILURE_ID>/to-fixture \
  -H "Content-Type: application/json" \
  -d '{"institution": "<Bank Name>"}'
```

(Port may differ — use the port your dev server is on.) It writes a scrubbed
`.txt` body and a `.json` skeleton under `tests/test_data/<slug>/` and returns
`{"txt_path": ..., "json_path": ...}`. Notes:

- **403** if the server is in demo mode, or is not running from a git checkout
  (it writes into the repo tree by design). Fall back to the manual snippet
  below.
- **409** if a fixture with that name already exists — it never overwrites. Pick
  a different failure or rename.
- **422** if you pass no `institution` and the row has no detected institution —
  always pass `"institution": "<Bank Name>"`.

### Fallback: scrub manually (server not running, or gated 403)

This calls the same `write_fixture_pair` the endpoint uses (identical scrub, path
scheme, no-overwrite guard, and skeleton), so a manually-written fixture is
byte-identical to an endpoint-written one:

```bash
uv run python -c '
import json, pathlib
from src.finance.storage import create_parse_failure_store
from src.finance.fixture_scrub import scrub_body, write_fixture_pair

FAILURE_ID = "pf_REPLACE_ME"        # an id from Step 1
BANK = "<bank>"                     # dir slug: lowercase, underscores, e.g. maple_trust
NAME = "purchase_sample_1"          # fixture file stem (one per type/sample)
INSTITUTION = "<Bank Name>"         # exact institution string, e.g. Maple Trust

store = create_parse_failure_store()
row = store.get_failure(FAILURE_ID)
assert row is not None, "no failure with that id"
details = json.loads(row["email_json"])
body = str(details.get("body") or "")
scrubbed = scrub_body(body, forwarded_to=details.get("forwarded_to"))

try:
    txt_path, json_path = write_fixture_pair(
        test_data_root=pathlib.Path("tests/test_data"),
        dir_slug=BANK,
        file_slug=NAME,
        scrubbed_body=scrubbed,
        institution=INSTITUTION,
    )
except FileExistsError as exc:
    raise SystemExit("fixture exists — pick another NAME: " + str(exc))
print("wrote", txt_path)
print("wrote", json_path)
'
```

Repeat for each transaction type you have a real sample for. Then **read every
scrubbed `.txt`** and confirm no PII survived (names, full emails, card digits).
**Person names are NOT auto-redacted** — `scrub_body` catches emails, card
digits, and headers, but "from Jordan Lee" in an e-transfer body sails straight
through. Read each body and hand-replace any real person name (especially
e-transfer sender/recipient names and "Hi <name>," greetings) with a synthetic
one (e.g. "Jordan Lee" → "Alex Doe"), then make sure the fixture `.json`
expectation you write in Step 3 matches the synthetic name, not the real one.

---

## Step 3 — Complete the fixture `.json` expectations

Model: `tests/test_data/rbc/2024.10.22_15.45_abc123def456_rbc_purchase.json` —
open it. Each fixture `.json` has exactly these keys:

```json
{
    "institution": "Maple Trust",
    "name": "Demo User",
    "amount": 127.53,
    "company": "Costco Wholesale",
    "transaction_type": "purchase",
    "email_filepath": "tests/test_data/maple_trust/purchase_sample_1.txt"
}
```

For each fixture, read its scrubbed `.txt` and fill in the real values you see:
`amount` is a JSON number (float), `transaction_type` is one of
`purchase`/`withdrawal`/`deposit`/`e-transfer`/`preauth`, `company` is the
merchant, `name` is the cardholder (or `null` if the parser won't extract it).
For e-transfer, `company` is the counterparty — the sender for a received
transfer, the recipient for a sent one (see
`src/finance/parsers/etransfer_parser.py` for the sent-direction precedent) —
and `name` is the account holder's own name if the body states it (e.g. a
"Hi Alex," greeting), else `null`.
**Leave no `"TODO"` behind.** `email_filepath` must be the repo-relative path to
the matching `.txt`.

---

## Step 4 — Write the parser

Read `docs/guides/add-a-parser.md` (Part 1) once for the contract and locale
notes (currency symbol, decimal/thousand separators, non-English keywords).
Then create `src/finance/parsers/<bank>_parser.py`. Subclass
`TransactionParser`, implement one `parse_email`, and derive **every regex from a
line in your scrubbed fixtures**. Reference: `src/finance/parsers/rbc_parser.py`.

```python
# src/finance/parsers/maple_trust_parser.py
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


class MapleTrustParser(TransactionParser):
    """Parser for Maple Trust alert emails.

    Conservative fall-through: any body that matches no branch below returns the
    input email_details unchanged (only ``institution`` stamped), so unmatched
    or drifted templates fall through to recovery / AI extraction rather than
    being silently mis-parsed. Only transaction types with a real captured
    fixture are parsed here.
    """

    def parse_purchase(self, email_body_text: str) -> dict[str, Any] | None:
        # Both regexes trace to tests/test_data/maple_trust/purchase_sample_1.txt:
        #   "A purchase of $84.20 at AIR CANADA with your Maple Trust card ending in 0000."
        # The merchant capture is anchored on BOTH sides by fixture text
        # ("at ... with your") — never on a bare period.
        amount_match = re.search(rf"purchase of \$({AMOUNT_PATTERN})", email_body_text)
        company_match = re.search(r"at (.+?) with your", email_body_text)
        if not amount_match:
            return None
        return {
            "name": None,
            "amount": parse_amount(amount_match.group(1)),
            "company": company_match.group(1) if company_match else None,
            "transaction_type": "purchase",
        }

    def parse_etransfer(self, email_body_text: str) -> dict[str, Any] | None:
        # Both regexes trace to tests/test_data/maple_trust/etransfer_sample_1.txt:
        #   "You received an e-Transfer of $50.00 from Alex Doe and it has been deposited."
        amount_match = re.search(rf"e-Transfer of \$({AMOUNT_PATTERN})", email_body_text)
        sender_match = re.search(r"from (.+?) and it has been", email_body_text)
        if not amount_match:
            return None
        return {
            "name": None,
            "amount": parse_amount(amount_match.group(1)),
            "company": sender_match.group(1) if sender_match else None,
            "transaction_type": "e-transfer",
        }

    def parse_email(self, email_body_text: str, email_details: dict[str, Any]) -> dict[str, Any]:
        parsed_data = None
        if "purchase of" in email_body_text:
            parsed_data = self.parse_purchase(email_body_text)
        elif "e-Transfer of" in email_body_text:
            parsed_data = self.parse_etransfer(email_body_text)
        email_details["institution"] = "Maple Trust"
        return merge_details(email_details, parsed_data)
```

**This example is a shape, not your parser.** Write one branch per transaction
type you captured a fixture for in Step 2 (every sampled type gets a branch;
unsampled types get none). Derive each regex's terminating anchor from YOUR
fixture line: anchor the merchant/counterparty capture on distinctive literal
text on **both** sides (like `at (.+?) with your` above) — never on a bare `.`.
A lazy `(.+?)\.` runs to the sentence-ending period and swallows the whole
trailing clause ("AIR CANADA with your Maple Trust card ending in 0000" instead
of "AIR CANADA"). Before moving on, confirm each regex captures exactly the
merchant by testing it against your own `.txt`:

```bash
uv run python -c '
import re
body = open("tests/test_data/<bank>/purchase_sample_1.txt").read()
m = re.search(r"at (.+?) with your", body)   # paste each of YOUR regexes here
print(repr(m.group(1)) if m else "NO MATCH")
'
```

The printed value must be exactly the merchant (or counterparty), nothing more.
`AMOUNT_PATTERN` handles `$1,234.56` and `$1000.00` correctly — use it, don't
hand-roll amount regex. `parse_amount` returns a `float`. `merge_details` returns
`email_details` unchanged when `parsed_data is None` — that is the conservative
fall-through; keep it.

---

## Step 5 — Register in the three places (all in `src/finance/email_pipeline.py`)

All three edits are mandatory and must be done together (a key in `PARSER_KEYS`
that is missing from the `parsers` dict raises `KeyError` at runtime).

1. **`PARSER_KEYS`** — the module-level tuple at `src/finance/email_pipeline.py:27`.
   Append your institution key. Body-text detection matches with
   `if key in email_body_text`, so the key string **must appear verbatim in the
   captured bodies** (e.g. `"Maple Trust"` appears in the email text):
   ```python
   PARSER_KEYS: tuple[str, ...] = ("CIBC", "RBC", "MBNA", "Simplii", "PC Financial", "Maple Trust")
   ```

2. **The `parsers` dict** inside `parse_email_body` (around `:96`) — import the
   class at the top of the file and instantiate it under the same key:
   ```python
   from src.finance.parsers.maple_trust_parser import MapleTrustParser
   # ...
   parsers = {
       "CIBC": CIBCParser(),
       "RBC": RBCParser(),
       "MBNA": MBNAParser(),
       "Simplii": SimpliiParser(),
       "PC Financial": PCFinancialParser(),
       "Maple Trust": MapleTrustParser(),
   }
   ```

3. **`domain_map`** inside `_detect_institution_by_sender` (around `:63`) — add
   the sender domain **only if this bank has its own dedicated alert domain**:
   ```python
   domain_map = {
       "cibc.com": "CIBC",
       "alerts.rbc.com": "RBC",
       "mbna.ca": "MBNA",
       "pcfinancial.ca": "PC Financial",
       "mapletrust.ca": "Maple Trust",
   }
   ```
   **Interac-omission caveat (verbatim from the code):** a multi-institution
   sender domain like `payments.interac.ca` must **NOT** go in `domain_map` — many
   banks share it, so it must fall through to body-text detection (Step 5.1). If
   your bank's alerts arrive via Interac or another shared clearing service, skip
   this edit and rely on the `PARSER_KEYS` body-text match.

---

## Step 6 — Wire the property harness, then test

**6a. Cover the new parser in the property suite.** `tests/property/test_parser_invariants.py`
uses an explicit `PARSERS` list — add your class there so the shared invariants
run against it, and add a matching body factory (a `BODY_FACTORIES[...]` KeyError
otherwise) plus any single-word trigger phrases:

- Import the class and append it to `PARSERS` (around `:36`).
- Add an entry to `BODY_FACTORIES` (around `:86`) whose factory returns a body
  string derived from one of your real fixtures with the amount slotted in, e.g.
  `MapleTrustParser: lambda amount: f"Your purchase of ${amount} at TEST MERCHANT."`
- If your parser triggers on a common English word, add that literal to
  `TRIGGER_SUBSTRINGS` (around `:51`) so the no-hallucination test excludes it.

**6b. Add the unit test.** Create `tests/unit/test_<bank>_parser.py` (generic
template — `load_test_data` picks up every JSON in your fixture dir):

```python
import pytest

from src.finance.parsers.maple_trust_parser import MapleTrustParser
from tests.conftest import load_test_data, read_file

email_details = load_test_data("maple_trust")


@pytest.fixture
def parser() -> MapleTrustParser:
    return MapleTrustParser()


@pytest.mark.parametrize(
    "email_filepath, expected_institution, expected_name, expected_amount, expected_company, expected_transaction_type",
    [
        (
            detail["email_filepath"],
            detail.get("institution"),
            detail.get("name"),
            detail.get("amount"),
            detail.get("company"),
            detail.get("transaction_type"),
        )
        for detail in email_details
        if "email_filepath" in detail
    ],
    ids=[detail["filename"].removesuffix(".json") for detail in email_details if "email_filepath" in detail],
)
def test_parse_email(
    parser: MapleTrustParser,
    email_filepath: str,
    expected_institution: str | None,
    expected_name: str | None,
    expected_amount: float | None,
    expected_company: str | None,
    expected_transaction_type: str | None,
) -> None:
    email_body = read_file(email_filepath)
    result = parser.parse_email(email_body, {})
    assert result.get("institution") == expected_institution
    assert result.get("name") == expected_name
    assert result.get("amount") == expected_amount
    assert result.get("company") == expected_company
    assert result.get("transaction_type") == expected_transaction_type
```

**6c. Run.** Replace `<bank>` with your slug:

```bash
uv run pytest tests/unit/test_<bank>_parser.py tests/property/ -v
uv run pytest tests/ -m "not integration" -q
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

All must be green before moving on. If a fixture assertion fails, fix the
`.json` expectation to match the real body — never loosen a regex to fit an
invented value.

---

## Step 7 — Recover the backlog (if the API server is running)

Retry-all re-runs the deterministic parsers (never AI) across the quarantined
backlog. For an unknown bank the rows were quarantined with **no** detected
institution, so filter by `from_domain` (the sender domain from Step 1). Use
`institution` only for a bank the pipeline already detected:

```bash
curl -X POST http://localhost:8000/api/v1/parse-failures/retry-all \
  -H "Content-Type: application/json" \
  -d '{"from_domain": "mapletrust.ca"}'
```

Report the response `{retried, created, duplicates, still_failing}` to the user
in plain words (e.g. "retried 12, recovered 9, 1 duplicate, 2 still unreadable").
`still_failing` rows are the types you had no sample for — that's expected.

If no server is running, skip this step — there is no manual equivalent (the
bulk-retry path lives behind the API). Tell the user plainly that the backlog
was not recovered and can be recovered later with the same curl above (or from
the Needs review page's "Retry all" button) once the server is up.

---

## Step 8 — Commit

Echo the checklist in `references/authoring-checklist.md` (confirm every item),
then commit via the Skill tool: invoke `skill: "commit"`. Do not create a branch
unless the user asks.

## Before you finish — echo this

Read `references/authoring-checklist.md` and confirm each box out loud to the
user before committing. Any unchecked box means the parser is not done.
