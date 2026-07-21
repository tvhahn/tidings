---
description: Apply category overrides to DynamoDB and audit full history for miscategorizations
---

Your task is to retroactively fix transaction categories in DynamoDB. This has two phases:
- **Phase A:** Apply existing `category_overrides.json` to all historical transactions
- **Phase B:** Audit the full history with parallel sub-agents to find remaining miscategorizations

The valid categories are defined in `src/finance/config/categories.json`. All category values MUST use one of these exact category strings.

## Step 1: Download fresh transaction data

Run the download script to get a fresh snapshot from DynamoDB (this serves as the rollback backup; the retroactive script itself scans the live table directly):

```
uv run dev/cli/download_transaction_table.py
```

The CSV will be saved to `data/raw/transaction_db_rough/transactions.csv`.

## Step 2: Apply existing overrides (Phase A)

First, preview what will change. The script scans the live store for the last 12 months by default:

```
uv run dev/cli/apply_category_overrides.py --dry-run
```

Parse the JSON summary from stdout and render the `tier_breakdown` map as a table before prompting for confirmation. Example:

```
Tier         Rows   Updates   Example
exact        1247      0      COFFEE SPOT #45 (already correctly tagged)
normalized    503    503      BOOSTER JUICE #999  →  restaurant/dining  (rule: BOOSTER JUICE #232)
alias          89     89      AMZN MKTP CA #8888  →  miscellaneous      (rule: AMAZON.CA)
blacklisted    41      0      SHOPPERS DRUG MART #789 (ambiguous — conflicting overrides, left as-is)
```

Also surface `total_updated`, `total_already_correct`, `total_blacklisted`, and the `scope_note` from the summary so the user knows CategoryAudit is written only on rows that actually change. Then ask for confirmation using `AskUserQuestion`.

If confirmed, apply the changes:

```
uv run dev/cli/apply_category_overrides.py
```

Capture the JSON summary from stdout for the final report. Pass `--months N` to widen or narrow the scan window, or `--offline PATH` to read from a CSV export instead of the live store.

**Rollback note:** If anything goes wrong, the backup CSV can restore all original categories via:
```
uv run dev/cli/restore_categories_from_csv.py data/raw/transaction_db_rough/transactions.csv
```

## Step 3: Launch parallel sub-agents (Phase B)

Using the downloaded CSV:

1. Filter out rows where `CategoryAudit` column exists and is non-empty (already reviewed in a prior run)
2. Split remaining transaction history into 3-month windows based on the `Date` column
3. For each window, create a **deduplicated view**: one row per unique `(Company, Category)` pair with a transaction count
4. Launch sub-agents in parallel via the `Task` tool (one per 3-month batch)

Each sub-agent receives:
- The deduplicated company+category table for its window
- The full categories list from `src/finance/config/categories.json`
- The current `src/finance/config/category_overrides.json` (so they don't re-flag overridden companies)
- Instructions to return **only** a JSON array of issues found:

```json
[
  {
    "company": "COMPANY NAME",
    "current_category": "miscellaneous",
    "proposed_category": "Restaurant/Dining",
    "confidence": "high",
    "reasoning": "Company name indicates a restaurant"
  }
]
```

Sub-agents should flag:
- Companies categorized as "miscellaneous" that should have a real category
- Companies with a clearly wrong category based on the company name
- They should NOT flag companies that already have an override in `category_overrides.json`

## Step 4: Aggregate and deduplicate findings

Collect JSON results from all sub-agents:
- Group by company (case-insensitive)
- If all sub-agents that flagged a company agree on the proposed fix → **high confidence**
- If sub-agents disagree on the proposed category → **ambiguous**
- Remove companies that already have overrides with the proposed category

## Step 5: Review and apply

**High confidence fixes** — Show the list to the user, then apply automatically (update DynamoDB via the `apply_category_overrides.py` script after adding the new overrides).

**Ambiguous fixes** — Present via `AskUserQuestion` (batched, up to 4 per call) with:
- Company name
- Current category distribution across batches
- Proposed category and reasoning
- Options constrained to relevant categories from the predefined list

For all approved fixes:
1. Update DynamoDB records by calling `uv run dev/cli/apply_category_overrides.py` after updating overrides
2. Add new entries to `src/finance/config/category_overrides.json` (additive merge, sorted alphabetically by key)

For rows confirmed correct (no change needed), mark them as reviewed using `TransactionsDB.mark_category_reviewed()` so future runs skip them.

## Step 6: Print summary

Print a final report:

```
Phase A — Override backfill:
  Updated: X transactions (Y companies)
  Already correct: X transactions (Y companies)

Phase B — Audit findings:
  Auto-fixed: X companies (Y transactions)
  User-approved: X companies (Y transactions)
  User-declined: X companies
  No issues found: X companies

New overrides added to category_overrides.json: X
Total transactions analyzed: X across N batches
```
