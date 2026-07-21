Parse bank statement page images into structured transaction JSON using vision.

## Input

Read all PNG images from: `$ARGUMENTS` (default: `data/raw/sample_statements/output/images/`)

## Instructions

1. Use the Read tool to view each `page_*.png` image in the directory, in order.
2. For each page, identify the transaction table rows. Each row has columns: Date, Description, Withdrawals($), Deposits($), Balance($).
3. Extract every transaction row as structured JSON. Each transaction should have:
   - `date`: ISO format `YYYY-MM-DD`
   - `description`: full description text (combine multi-line descriptions)
   - `amount`: the dollar amount as a number (no dollar sign or commas)
   - `type`: `"withdrawal"` or `"deposit"`
   - `balance`: the running balance after this transaction (number, or null if not shown)
4. Skip non-transaction rows: Opening Balance, Closing Balance, headers, footers, disclaimers.
5. Handle multi-line descriptions: if a line has no date, it continues the previous transaction's description.
6. Handle sub-transactions on the same date: if a new amount appears without a date, it's a separate transaction sharing the previous date.
7. Save the combined output as JSON to `data/raw/sample_statements/output/parsed_vision.json`.
8. Print a summary: transaction count, date range, total debits, total credits.

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
