---
description: Download transactions, identify category misclassifications, and update overrides
argument-hint: "[months]"
---

Your task is to audit transaction categories and populate `src/finance/config/category_overrides.json` with corrections.

The valid categories are defined in `src/finance/config/categories.json`. All overrides MUST use one of these exact category strings.

## Step 1: Download fresh transaction data

Run the download script to get fresh data from DynamoDB:

```
uv run dev/cli/download_transaction_table.py
```

The CSV will be saved to `data/raw/transaction_db_rough/transactions.csv`.

## Step 2: Run the analysis script

Run the analysis script on the downloaded CSV. Use `$ARGUMENTS` as the months parameter if provided, otherwise default to 3:

```
uv run dev/cli/analyze_categories.py data/raw/transaction_db_rough/transactions.csv --months <N>
```

Capture the JSON output from stdout.

## Step 3: Read and analyze the JSON output

Read the JSON output and identify three types of issues:

1. **Inconsistent companies** (`is_inconsistent: true`) — The same company was assigned different categories across transactions. Determine the correct category based on majority count and your domain knowledge about the company.

2. **Miscellaneous companies** (`is_miscellaneous: true`) — Companies stuck in the fallback "Miscellaneous" category. Suggest a proper category based on the company name.

3. **Misjudged companies** — Even when consistent, some company+category pairs may be wrong. Use your domain knowledge to identify these (e.g., a gas station categorized as "Groceries").

## Step 4: Apply fixes

Split proposed overrides into two groups:

### High confidence — Apply automatically
These are obvious corrections where the right category is clear:
- Inconsistent companies where the majority category is clearly correct
- Well-known companies stuck in Miscellaneous (e.g., "STARBUCKS" → "Restaurant/Dining")
- Clear misjudgments based on company name

### Ambiguous — Ask the user
Use `AskUserQuestion` to present ambiguous cases to the user. For each ambiguous company, show:
- The company name
- Current category distribution
- Your suggested category and reasoning

Constrain answer options to relevant categories from the 38 predefined options. Batch related questions where possible (up to 4 questions per AskUserQuestion call).

## Step 5: Update category_overrides.json

1. Read the current `src/finance/config/category_overrides.json`
2. Merge new overrides additively (preserve existing entries, don't remove any)
3. Sort keys alphabetically for readability
4. Write the updated file

The format is a flat JSON object mapping company names (uppercase) to category strings:
```json
{
  "COMPANY NAME": "Category"
}
```

## Step 6: Print summary

Print a detailed summary with three sections:

**Overrides added:**
- List each new override: `COMPANY → Category (was: old categories with counts)`

**Overrides skipped:**
- Companies where the user declined a suggestion
- Companies that already had an existing override

**Companies unchanged:**
- Count of companies already correctly categorized

Also note the total number of transactions and companies analyzed.
