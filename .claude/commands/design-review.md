---
name: design-review
description: Assemble a UI/UX expert panel to visually inspect the finance dashboard via Chrome DevTools and produce a structured design review with actionable recommendations grounded in the app's actual design system.
argument-hint: "[optional focus areas, e.g. 'budget page layout' or 'mobile navigation']"
---

# UI/UX Design Review — Expert Panel

You are conducting a comprehensive UI/UX design review of the finance dashboard at `http://localhost:5173` using a panel of five domain experts. You will visually inspect the app through Chrome DevTools MCP, then generate a structured expert panel analysis grounded in the app's actual design system.

**User-provided focus:** $ARGUMENTS

## Expert Panel

You will channel these five experts throughout the review. Each has a distinct lens and voice:

| Expert | Title | Lens |
|--------|-------|------|
| **Maya Chen** | Visual Design Lead | Composition, color theory, typography, spacing, visual hierarchy |
| **James Okafor** | Accessibility Engineer | WCAG compliance, contrast ratios, screen reader support, keyboard navigation |
| **Priya Sharma** | Interaction Designer | Usability, affordances, feedback patterns, micro-interactions |
| **David Park** | Information Architect | Content structure, navigation clarity, findability, data density |
| **Sofia Martinez** | Mobile & Responsive Specialist | Breakpoints, touch targets, content reflow, mobile-first patterns |

## App Architecture Reference

Ground all observations in these concrete design tokens, components, and files.

### Design System

- **Framework:** React 19 + Vite 7 + Tailwind CSS 4
- **Component library:** Radix UI primitives + shadcn/ui pattern (CVA variants + `cn()` utility)
- **Tailwind config:** CSS-based via `@theme inline` block in `index.css` (no `tailwind.config.js`)
- **Theming:** Light/dark/system via Zustand store (`stores/theme.ts`), `.dark` class on `<html>`, CSS variables switch between modes
- **Fonts:** Inter (sans-serif), loaded via `--font-sans` CSS variable
- **Charts:** Recharts
- **Icons:** Lucide React
- **Toasts:** Sonner

### Color Palette (OKLch)

**Light mode (`:root`):**

| Token | OKLch | Role |
|-------|-------|------|
| `background` | `oklch(1 0 0)` | Page background (white) |
| `foreground` | `oklch(0.145 0 0)` | Primary text (near-black) |
| `card` | `oklch(1 0 0)` | Card/popover backgrounds |
| `primary` | `oklch(0.205 0 0)` | Buttons, active states |
| `secondary` | `oklch(0.965 0 0)` | Secondary surfaces |
| `muted` | `oklch(0.965 0 0)` | Muted backgrounds |
| `muted-foreground` | `oklch(0.556 0 0)` | Secondary text, placeholders |
| `border` | `oklch(0.922 0 0)` | Borders, dividers |
| `destructive` | `oklch(0.577 0.245 27.325)` | Delete actions, error states |

**Dark mode (`.dark`):**

| Token | OKLch | Role |
|-------|-------|------|
| `background` | `oklch(0.145 0 0)` | Page background (near-black) |
| `foreground` | `oklch(0.985 0 0)` | Primary text (near-white) |
| `card` | `oklch(0.185 0 0)` | Card/popover backgrounds |
| `primary` | `oklch(0.985 0 0)` | Buttons, active states |
| `secondary` | `oklch(0.255 0 0)` | Secondary surfaces |
| `muted-foreground` | `oklch(0.65 0 0)` | Secondary text |
| `border` | `oklch(0.3 0 0)` | Borders, dividers |

**Status colors (both modes):**

| Token | Role |
|-------|------|
| `status-success` / `status-success-muted` | Positive values, deposits |
| `status-warning` / `status-warning-muted` | Budget alerts, attention items |
| `status-danger` / `status-danger-muted` | Over-budget, destructive |
| `status-info` / `status-info-muted` | Informational badges |

### Component Patterns

- **Button variants** (CVA): `default`, `destructive`, `outline`, `secondary`, `ghost`, `link` — sizes: `default`, `sm`, `lg`, `icon`
- **Badge variants**: `default`, `secondary`, `destructive`, `outline`
- **Card compound**: `Card > CardHeader + CardContent + CardFooter`
- **Desktop sidebar**: `hidden md:flex w-[240px]` with nav items — active: `bg-accent text-accent-foreground font-medium`
- **Mobile bottom tab**: `fixed bottom-0` icon-only nav, `md:hidden`
- **Content wrapper**: `mx-auto max-w-6xl p-4 pb-20 md:p-6`
- **Collapsible sections**: Radix Collapsible with custom expand/collapse animations (200ms/150ms)
- **Month transitions**: `month-fade-in` keyframe (150ms ease-out, translateY)

### Key Files

| Concern | File(s) |
|---------|---------|
| Design tokens & colors | `frontend/src/index.css` (`:root`, `.dark`, `@theme inline`) |
| Layout, sidebar, bottom nav | `frontend/src/components/Layout.tsx` |
| Routing | `frontend/src/App.tsx` |
| Theme store | `frontend/src/stores/theme.ts` |
| UI primitives | `frontend/src/components/ui/` (button, badge, card, dialog, etc.) |
| Utility (cn) | `frontend/src/lib/utils.ts` |
| Transaction table | `frontend/src/components/TransactionTable.tsx` |
| Transaction cards (mobile) | `frontend/src/components/TransactionCard.tsx` |
| Summary cards | `frontend/src/components/SummaryCards.tsx` |
| Budget bars | `frontend/src/components/PaceBar.tsx`, `CeilingBar.tsx` |
| Day cards (journal) | `frontend/src/components/DayCard.tsx` |
| Journal rows | `frontend/src/components/JournalTransactionRow.tsx` |
| Category picker | `frontend/src/components/CategoryPicker.tsx` |
| Filter bar | `frontend/src/components/FilterBar.tsx` |
| Month picker | `frontend/src/components/MonthPicker.tsx` |
| Spending chart | `frontend/src/components/SpendingChart.tsx` |
| Settings sections | `frontend/src/components/settings/` |
| Statement upload/review | `frontend/src/components/StatementUpload.tsx`, `StatementReview.tsx` |

### Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/` | `JournalPage.tsx` | Day-grouped transaction journal with AI summaries |
| `/transactions` | `TransactionsPage.tsx` | Full transaction table with filtering |
| `/summary` | `SummaryPage.tsx` | Monthly spending summary + charts |
| `/budgets` | `BudgetPage.tsx` | Budget overview with pace bars |
| `/budgets/edit` | `BudgetEditPage.tsx` | Budget configuration |
| `/insights` | `InsightsPage.tsx` | AI spending analysis (SSE streaming) |
| `/income-statement` | `IncomeStatementPage.tsx` | Yearly income statement |
| `/search` | `SearchPage.tsx` | Cross-month transaction search + CSV export |
| `/statements` | `StatementsPage.tsx` | Bank statement upload + import |
| `/settings` | `SettingsPage.tsx` | App settings (theme, categories, aliases) |

### Breakpoints

- Mobile: base (< 768px) — bottom tab bar, stacked layouts
- Desktop: `md:` (768px+) — sidebar nav, wider grids
- Large: `lg:` (1024px+) — expanded grids (e.g., 4-col summary cards)

---

## Phase 1: Page Discovery

Build the review set from the known routes above:

1. **Default review set** (5 representative pages):
   - `/` (journal — the home page)
   - `/transactions` (data table — the most complex UI)
   - `/summary` (charts + cards)
   - `/budgets` (pace bars + budget data)
   - `/settings` (forms + toggles)

2. **Full page list**: all 10 routes listed in the Pages table above.

## Phase 2: User Interview

Use `AskUserQuestion` with all three questions in a **single call**:

### Question 1: Pages to review
**Header:** "Pages"

Options:
1. **Default set (Recommended)** — 5 representative pages: `/`, `/transactions`, `/summary`, `/budgets`, `/settings`
2. **All pages** — All 10 routes
3. **Custom selection** — Let me specify which pages

### Question 2: Review depth
**Header:** "Depth"

Present the three depth tiers. If the user provided `$ARGUMENTS`, mention it: *"I see you want to focus on: [args]. This applies to all depth levels."*

Options:
1. **Quick** — Desktop viewport only, static screenshots (~2 min). Good for a fast pulse check.
2. **Standard (Recommended)** — Desktop + mobile viewports, static screenshots (~5 min). Covers responsive behavior.
3. **Thorough** — Desktop + mobile + interactive state testing (hover, focus, click, theme toggle) (~8 min). Full audit.

### Question 3: Additional focus areas
**Header:** "Focus"

If `$ARGUMENTS` was provided, phrase as: *"You mentioned focusing on '$ARGUMENTS'. Any additional areas to emphasize?"*
If no `$ARGUMENTS`, phrase as: *"Any specific areas you'd like the panel to emphasize?"*

Options:
1. **No additional focus** — Comprehensive review across all dimensions
2. **Accessibility** — Extra attention to WCAG compliance, contrast, keyboard nav
3. **Visual polish** — Extra attention to spacing, alignment, typography, color harmony
4. **Data density** — Extra attention to table layouts, number formatting, information hierarchy

Wait for the user's answers before proceeding.

## Phase 3: Visual Inspection

Use Chrome DevTools MCP tools to systematically inspect each selected page.

### Viewports

Apply viewports based on selected depth:

- **Quick:** Desktop only
- **Standard / Thorough:** Desktop + Mobile

| Viewport | Settings |
|----------|----------|
| Desktop | `{ "width": 1280, "height": 800, "deviceScaleFactor": 1, "isMobile": false, "hasTouch": false }` |
| Mobile | `{ "width": 375, "height": 812, "deviceScaleFactor": 3, "isMobile": true, "hasTouch": true }` |

### For each page x viewport combination

**Static inspection (all depth levels):**

1. `emulate` — Set the viewport configuration
2. `navigate_page` — Load `http://localhost:5173{route}`
3. `take_screenshot` — Capture the viewport screenshot
4. `take_screenshot` with `fullPage: true` — Capture the full-page screenshot
5. `take_snapshot` — Capture the accessibility tree
6. `list_console_messages` — Check for errors/warnings (zero tolerance for React errors)

**Interactive inspection (Thorough depth only):**

7. `hover` on nav items, buttons, table rows, badges, and other interactive elements — screenshot each hover state
8. `press_key` Tab repeatedly to cycle through focusable elements — screenshot focus indicators
9. `click` nav items to test page transitions
10. Test theme toggling: navigate to `/settings`, click theme buttons, screenshot both modes
11. Test any page-specific interactions: month picker navigation, category picker dropdown, filter bar toggles, collapsible day cards

### Inspection notes

- Analyze each screenshot carefully as you take it — note observations per expert lens
- Track console errors/warnings — these will be reported in findings
- For the accessibility tree, look for missing labels, incorrect roles, heading hierarchy issues, and missing ARIA attributes on Radix primitives
- Pay special attention to financial data formatting: currency alignment, number readability, negative value indicators

## Phase 4: Expert Panel Analysis

After completing all visual inspection, generate the expert panel analysis.

### Guidelines

- Each expert reviews ALL screenshots and snapshots through their specific lens
- Use **blockquote format** (`>`) for direct quotes in each expert's distinct voice
- **Reference actual design tokens, component classes, and file paths** when making observations (e.g., "the `muted-foreground` text at `oklch(0.556)` against the `background` at `oklch(1)` gives X:1 contrast" not "the text seems too light")
- Surface **disagreements naturally** — don't force consensus
- If `$ARGUMENTS` or user-specified focus areas were provided, each expert should address those areas prominently
- Be specific about what elements, pages, and viewports each observation applies to
- For financial dashboards, pay extra attention to: data readability, number formatting consistency, status color semantics, and information density

### Expert voice examples

> **Maya Chen:** "The neutral OKLch palette is clean and professional, but every page feels the same temperature. The status colors (`status-success`, `status-warning`, `status-danger`) are the only chromatic relief — consider introducing a subtle brand accent for the sidebar active state instead of the achromatic `bg-accent`."

> **James Okafor:** "The `muted-foreground` token at `oklch(0.556)` against `background` at `oklch(1)` gives roughly 4.8:1 contrast in light mode — passes AA for body text but just barely. In dark mode, `oklch(0.65)` against `oklch(0.145)` drops to about 4.3:1. Secondary labels on budget bars should be bumped."

> **Sofia Martinez:** "The bottom tab bar has 9 items in a horizontal scroll at 375px — that's a lot of icons without labels. Users past the 5th icon won't even know they exist without scrolling. Consider grouping less-used items (Search, Statements, Settings) behind a 'More' tab."

## Phase 5: Structured Report

Present the complete report in this structure:

### 1. Executive Summary

- **Overall grade:** Letter grade (A through F) with a one-sentence justification
- **Strongest aspect:** What the app does best, with specific examples
- **Most important fix:** The single highest-impact improvement, with the specific file to modify

### 2. Per-Page Findings

Organize by page, then by viewport within each page. For each combination:

- What works well (with expert attribution)
- Issues found (with expert attribution, severity, and specific design token/component references)
- Screenshots referenced by viewport label

### 3. Cross-Cutting Themes

Identify 3-7 patterns that appear across multiple pages:

- Name each theme clearly
- Note which pages and viewports it appears on
- Include expert quotes showing different perspectives on the same issue
- Reference specific CSS tokens, components, or files involved

### 4. Prioritized Action List

A table with columns:

| # | Issue | Priority | Effort | File(s) to Modify | Expert |
|---|-------|----------|--------|-------------------|--------|
| 1 | Description | HIGH/MED/LOW | quick/moderate/significant | Specific file path(s) | Who flagged it |

Sort by priority (HIGH first), then by effort (quick first within same priority).

### 5. What's Working Well

3-5 specific strengths to preserve, with expert quotes explaining why they work. This section is important — it prevents "fixing" things that are already good.

---

## Operational Guidelines

- **Do not skip visual inspection.** Every observation must be grounded in actual screenshots, not assumptions about the code.
- **Do not generate generic advice.** Every recommendation must reference a specific design token, component, CSS class, or file path from the architecture reference.
- **Do not force consensus.** If Maya thinks the spacing is too tight but David thinks it aids scanability, present both views.
- **Do not hallucinate contrast ratios.** If you claim a contrast ratio, it must be based on the actual OKLch values from the color palette.
- **Test both themes.** This app supports light, dark, and system modes — review both light and dark at minimum.
- **Be efficient with screenshots.** Take what you need per the selected depth — don't over-capture on Quick or under-capture on Thorough.
- **Financial data matters.** Pay extra attention to currency formatting, number alignment, table readability, and status color semantics — these are the core of the app.
- **Use TaskCreate** to track progress through the phases if the review involves many pages.
