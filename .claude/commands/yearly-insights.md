---
description: Generate an AI-powered yearly spending review with multi-perspective analysis
argument-hint: "<year>"
---

Your task is to generate a comprehensive yearly spending review for the given year.

## Phase 1 — Data Gathering

Run the data gathering script. Use `$ARGUMENTS` as the year (required):

```
uv run dev/cli/gather_yearly_insights_data.py $ARGUMENTS
```

The context JSON will be saved to `data/insights/yearly/<year>/context_<year>.json`.

Read the generated context JSON file to understand the full financial picture for the year.

## Phase 2 — Core Analysis

Using the context data, produce these sections:

### 1. Executive Summary

Total income, total expenses, net savings, savings rate, budget ceiling comparison. One paragraph capturing the year's financial story.

### 2. Monthly Spending Arc

Month-by-month narrative: which months were expensive and why, seasonal patterns, the overall trajectory. Reference specific dollar amounts. Identify the highest and lowest spending months and what drove them.

### 3. Category Landscape

Top 10-15 categories ranked by annual spend. For each: annual total, budget target (if exists), variance, monthly average, classification (fixed/variable/lumpy). Group by fixed vs. variable vs. lumpy.

### 4. Top Merchants

Top 10 merchants by annual spend: total, frequency, average transaction, category. Note any surprising entries or concentration risks.

### 5. Budget Accuracy Assessment

Which targets were wrong by >15%? Provide specific revised targets with dollar amounts. Which categories are missing from the budget that should be added based on actual spending?

### 6. One-Time Events & Anomalies

Use the `commented_transactions` from the context to identify and quantify non-recurring spending. Calculate a "normalized annual spending" after removing identifiable one-time events. If there are no commented transactions, note that context is limited and flag months with unusual spikes as potential one-time events.

### 7. Wins

3-5 things that went well: categories under budget, spending decreases, good financial decisions evidenced by data. Be specific with numbers.

## Phase 3 — Analytical Perspectives

Launch 4 sub-agents simultaneously using the Task tool. Each agent receives the full context JSON and the core analysis from Phase 2. Each generates a focused perspective (3-5 sentences + one key stat).

**Important:** Launch all 4 as parallel Task tool calls in a single message. Each task should use `subagent_type: "general-purpose"`.

### Sub-agent 1: Budget Lens

Prompt the agent:
"Read the yearly spending context file at `data/insights/yearly/$ARGUMENTS/context_$ARGUMENTS.json`. You are analyzing this person's yearly spending from a budget strategist perspective. Focus on: where budget targets were wrong and need revision, optimal allocation for next year, structural gaps (categories with spending but no budget line). Be specific with dollar amounts. Output 3-5 sentences and highlight one key stat. Output ONLY your analysis text, no preamble."

### Sub-agent 2: Lifestyle Lens

Prompt the agent:
"Read the yearly spending context file at `data/insights/yearly/$ARGUMENTS/context_$ARGUMENTS.json`. You are analyzing this person's yearly spending from a lifestyle and values perspective. Focus on: where spending reflects intentional priorities vs. drift, quality-of-life categories (dining, entertainment, travel, hobbies) and whether they got good value, gift-giving patterns and relationships. Be warm but honest. Output 3-5 sentences and highlight one key stat. Output ONLY your analysis text, no preamble."

### Sub-agent 3: Efficiency Lens

Prompt the agent:
"Read the yearly spending context file at `data/insights/yearly/$ARGUMENTS/context_$ARGUMENTS.json`. You are analyzing this person's yearly spending from an efficiency and waste perspective. Focus on: subscription inventory and potential redundancies, merchant consolidation opportunities, recurring charges that might be forgotten, categories where small changes would yield meaningful annual savings. Be specific. Output 3-5 sentences and highlight one key stat. Output ONLY your analysis text, no preamble."

### Sub-agent 4: Trend Lens

Prompt the agent:
"Read the yearly spending context file at `data/insights/yearly/$ARGUMENTS/context_$ARGUMENTS.json`. You are analyzing this person's yearly spending from a trends and trajectory perspective. Focus on: which categories are growing/shrinking over the 12 months, where the person will be in 12 months if current trends continue, inflection points where spending patterns changed, emerging patterns. Use the monthly data to project. Output 3-5 sentences and highlight one key stat. Output ONLY your analysis text, no preamble."

## Phase 4 — Synthesis

After all 4 sub-agents return, assemble the final sections:

### 8. Analytical Perspectives

Present each perspective as a labeled subsection:

- **Budget Lens** — [sub-agent 1 output]
- **Lifestyle Lens** — [sub-agent 2 output]
- **Efficiency Lens** — [sub-agent 3 output]
- **Trend Lens** — [sub-agent 4 output]

### 9. Action Items for Next Year

5 concrete, specific recommendations with dollar amounts. Each should pass the "Monday morning test" — actionable immediately without further research. Draw from both the core analysis and the perspectives.

### 10. Suggested Budget Revisions

A markdown table with columns: Category | Current Target | Actual | Suggested Target | Notes. Include categories that need adjustment (>15% variance) and categories that should be added to the budget.

## Output

Save the complete analysis to `data/insights/yearly/$ARGUMENTS/yearly_review.md`. Also display the full analysis in the conversation.

Format as clean markdown. Use specific dollar amounts and percentages throughout. Be concise but insightful — connect dots across categories rather than restating numbers.
