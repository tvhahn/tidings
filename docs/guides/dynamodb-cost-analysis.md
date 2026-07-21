# DynamoDB Cost Estimate

Cost analysis for DynamoDB usage in this single-user personal finance dashboard. Last updated: 2026-04-28.

> Pricing reflects the November 2024 50% on-demand reduction (DynamoDB Standard table class, us-east-1).

## Usage Profile

- **Transaction volume:** ~75 emails/month (50-100 range)
- **Dashboard sessions:** ~4/day → ~120 sessions/month
- **ForwardedTo partitions:** 2-3 addresses
- **Billing mode:** On-demand (`PAY_PER_REQUEST`) for all tables
- **Data age:** ~12 months → ~900 total transactions in DB

## DynamoDB On-Demand Pricing (us-east-1)

| Unit | Price |
|------|-------|
| Read Request Unit (RRU) | $0.125 per million (1 RRU = 4KB eventually consistent) |
| Write Request Unit (WRU) | $0.625 per million (1 WRU = 1KB) |
| Storage | $0.25 per GB/month (first 25 GB free) |

## Item Size Estimates

| Item type | Estimated size | Notes |
|-----------|---------------|-------|
| Email transaction (with Body) | ~4KB | Includes full email body text, subject, headers |
| Statement transaction (no Body) | ~0.5KB | Omits email-specific fields |
| BudgetConfig item | ~2KB | Targets map with ~44 categories |
| Weighted average | ~3.5KB | Mostly email transactions |

## Read Costs Breakdown

### 1. Lambda Email Processing — 75 emails/month

| Operation | Per-email RRUs | Monthly RRUs | Notes |
|-----------|---------------|--------------|-------|
| Duplicate check (Query + filter on TransactionHash) | ~20 | 1,500 | Scans partition for current month (~38 items × 3.5KB) |
| Context enrichment (Query month-to-date) | ~20 | 1,500 | Same month query with projection on 5 fields |
| **Subtotal** | **~40** | **3,000** | |

### 2. Dashboard — Transactions Page (120 sessions/month)

| Operation | Per-session RRUs | Monthly RRUs | Notes |
|-----------|-----------------|--------------|-------|
| List transactions (2 partition queries) | ~35 | 4,200 | ~75 items × 3.5KB across 2 partitions |
| Trash query | ~5 | 600 | Same query, typically few soft-deleted items |
| **Subtotal** | **~40** | **4,800** | Every session loads this page |

### 3. Dashboard — Summary Page (~60% of sessions = 72/month)

| Operation | Per-visit RRUs | Monthly RRUs | Notes |
|-----------|---------------|--------------|-------|
| Current + previous month comparison | ~70 | 5,040 | 2 months × 2 partitions × ~75 items |
| 6-month trend | ~210 | 15,120 | 6 months × 2 partitions |
| Prefetch previous month | ~70 | 5,040 | Background fetch |
| **Subtotal** | **~350** | **25,200** | Heaviest read path |

### 4. Dashboard — Budget Page (~30% of sessions = 36/month)

| Operation | Per-visit RRUs | Monthly RRUs | Notes |
|-----------|---------------|--------------|-------|
| BudgetConfig GetItem (×2) | ~2 | 72 | Targets + Groups from BudgetConfig table |
| YTD month queries (Feb = 2 months) | ~70 | 2,520 | Scales with month-of-year |
| Historical averages (6 months, cached 1hr) | ~210 | 2,100 | Cached — ~10 actual fetches/month |
| **Subtotal** | **~280** | **4,692** | Lighter in Jan/Feb, heavier in Nov/Dec |

### 5. Misc Operations (~monthly)

| Operation | Monthly RRUs | Notes |
|-----------|-------------|-------|
| Transaction detail views (GetItem × 10) | ~10 | Clicking to see email body |
| Statement upload reconciliation (×1) | ~70 | Queries 1-2 months for matching |
| Cache invalidation re-queries (×10 edits) | ~350 | Transaction list refetch after edits |
| Override suggestion queries (×2) | ~600 | Scans 3 months for CategoryAudit |
| **Subtotal** | **~1,030** | |

### Total Monthly Reads

| Source | RRUs |
|--------|------|
| Lambda email processing | 3,000 |
| Transactions page | 4,800 |
| Summary page | 25,200 |
| Budget page | 4,692 |
| Misc operations | 1,030 |
| **Total** | **~38,700 RRUs** |

**Read cost: 38,700 / 1,000,000 × $0.125 = $0.0048/month**

## Write Costs Breakdown

| Operation | Per-event WRUs | Monthly events | Monthly WRUs | Notes |
|-----------|---------------|----------------|-------------|-------|
| PutItem (new transaction) | ~4 | 75 | 300 | 4KB item ÷ 1KB per WRU |
| UpdateItem (context enrichment) | ~1 | 75 | 75 | Small map update |
| UpdateItem (category/comment/review) | ~1 | 10 | 10 | Manual edits |
| Statement import PutItems | ~1 | 30 | 30 | ~1/month, ~30 txns each |
| BudgetConfig PutItem | ~2 | 2 | 4 | Rare config saves |
| **Total** | | | **~419 WRUs** | |

**Write cost: 419 / 1,000,000 × $0.625 = $0.0003/month**

## Storage Cost

| Data | Size | Notes |
|------|------|-------|
| 900 transactions × 3.5KB avg | ~3.2 MB | 12 months of data |
| BudgetConfig items (2 per year) | ~4 KB | Negligible |
| **Total** | **~3.2 MB** | Well under 25 GB free tier |

**Storage cost: $0.00 (free tier covers first 25 GB)**

At 75 txns/month, it would take ~700 years to reach 25 GB.

## Monthly Cost Summary

| Component | Monthly Cost |
|-----------|-------------|
| Reads (38,700 RRUs) | $0.005 |
| Writes (419 WRUs) | $0.000 |
| Storage (3.2 MB) | $0.000 |
| **Total** | **~$0.005/month** |
| **Annual** | **~$0.06/year** |

## Sensitivity Analysis

| Scenario | Monthly reads | Monthly writes | Monthly cost |
|----------|-------------|---------------|-------------|
| **Baseline** (current usage) | 38,700 | 419 | $0.005 |
| **Heavy dashboard** (10 opens/day) | ~90,000 | 419 | $0.01 |
| **More transactions** (200/month) | ~55,000 | 1,100 | $0.01 |
| **Year-end budget page** (Dec, 12 YTD months) | ~70,000 | 419 | $0.01 |
| **Worst case** (all above combined) | ~150,000 | 1,500 | $0.02 |

Even the worst case is under $0.25/year.

## Relative Cost Context

For perspective, here's where the real AWS costs are in this system:

| Service | Estimated monthly cost | Notes |
|---------|----------------------|-------|
| **DynamoDB** | **~$0.01** | This analysis |
| Lambda invocations | ~$0.01 | 75 invocations × ~5s each |
| S3 storage | ~$0.01 | Raw .eml files |
| SNS (SMS) | ~$0.90-2.40 | ~$0.012/SMS US (base $0.0077 + carrier fee ~$0.0042) × 75-200 messages |
| OpenAI API (gpt-5.4-nano) | <$0.01 | 75 categorization calls/month (~290 tokens each at $0.05/M input + $0.40/M output) |
| ECR storage | ~$0.10 | Docker image storage |

**DynamoDB is essentially free at single-user scale.** SNS SMS charges dominate the AWS bill; OpenAI categorization at gpt-5.4-nano pricing is a rounding error (well under a cent/month).

## Why It's So Cheap

1. **On-demand billing** — pay only for what you use, no idle capacity charges
2. **Eventually consistent reads** — half the cost of strongly consistent (used everywhere in this app)
3. **Efficient partition key design** — queries target 2 partitions, not full table scans
4. **5-minute React Query cache** — prevents redundant DynamoDB calls during browsing sessions
5. **25 GB free storage tier** — transaction data will never exceed this
6. **Single-user system** — orders of magnitude fewer requests than even a small multi-user app
