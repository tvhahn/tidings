Parse pdfplumber text extraction output into structured transaction JSON.

## Input

Read text files from: `$ARGUMENTS` (default: `data/raw/sample_statements/output/text/`)

## Instructions

1. Read `all_pages.txt` and each `page_*_text.txt` / `page_*_tables.txt` file from the directory.
2. Note: pdfplumber often strips spaces between words (e.g., "BillPayment WestlandUtilityCo" instead of "Bill Payment Westland Utility Co"). Work with the text as-is.
3. Identify the transaction table section (starts after "Details of your account activity" header).
4. Parse each transaction row. The columns are: Date, Description, Withdrawals($), Deposits($), Balance($).
5. Transaction lines start with a date pattern like `30Dec`, `2Jan`, `13Jan` (day + month abbreviation, no space).
6. Lines without a date are either:
   - Description continuations (no amounts) — append to previous transaction's description
   - Sub-transactions on the same date (have amounts) — create a new transaction with the previous date
7. Determine withdrawal vs deposit: use the running balance to verify. If balance goes down, it's a withdrawal; if up, it's a deposit.
8. Extract each transaction as structured JSON with fields:
   - `date`: ISO format `YYYY-MM-DD`
   - `description`: full description text
   - `amount`: the dollar amount as a number
   - `type`: `"withdrawal"` or `"deposit"`
   - `balance`: the running balance after this transaction (number, or null if not shown)
9. Skip non-transaction rows: OpeningBalance, ClosingBalance, headers, footers.
10. Save output as JSON to `data/raw/sample_statements/output/parsed_text.json`.
11. Print a summary: transaction count, date range, total debits, total credits.

## Output Schema

```json
[
  {
    "date": "2026-01-15",
    "description": "INTERAC PURCHASE - 1234 SOBEYS #567 HALIFAX NS",
    "amount": 45.67,
    "type": "withdrawal",
    "balance": 1234.56
  }
]
```
