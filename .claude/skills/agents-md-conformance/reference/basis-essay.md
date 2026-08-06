# Making Our Monorepo Ergonomic for Agents

> How we built an agent-native codebase from principles rooted in verifiability, interoperability, and canonical context

**Source:** [@trybasis on X](https://x.com/trybasis/status/2056881705269580023)
**Author:** Basis (Atlas team) — Michael Crabtree (Atlas Tech Lead), [@RyanBMoffat](https://x.com/RyanBMoffat), [@BhavdeepSethi](https://x.com/BhavdeepSethi), [@SethSchiesel](https://x.com/SethSchiesel)
**Posted:** May 19, 2026 · 69.7K views · 208 likes · 27 reposts · 640 bookmarks
**Scraped:** 2026-05-20

> **Note (skill copy):** This is a text-only copy of the original Basis essay, vendored into the skill package as reference material for `agents-md-conformance` — here the essay is a sharpening lens rather than the rubric itself; the sibling `basis-principles-audit` skill vendors its own copy and scores against it directly. Two informational figures (Authority Map, Context Pyramid) are transcribed inline; two decorative figures (cover, principles diagram) are omitted because the surrounding prose covers them.

---

At Basis, we're obsessed with this question: How do we make our codebase ergonomic for agents? There are decades of learnings in software engineering on what a well-designed codebase looks like for humans (small functions, defined modules, no over-bloated documents, etc.). How do we evolve that for agents?

The [Atlas team at Basis](https://www.getbasis.ai/blogs/building-a-company-for-the-agi-era) is responsible for internal agents and context. Our product is the codebase itself. A codebase is two things at once. It is the source code that runs in production, and it is the context that coding agents use to make decisions. So to make our product truly friendly for our users, we had to make the monorepo as agent-native, as ergonomic, as possible.

**We did it. In three months, token usage per developer increased more than 5x and commit velocity increased by 2.5x.**

## Our Vision

Basis has placed a core bet on intelligence. From the very beginning of Basis three years ago, we believed that most of our code would soon be written by agents, and built our company accordingly. We hit that point in intelligence about nine months ago.

At that point, it became easy to imagine a world where agents consistently deliver high-quality, well-tested code while engineers focus on the challenging task of actually making engineering decisions.

But we weren't there yet. While coding agents are capable in isolation, they are prone to mistakes when dropped into a working codebase without supporting infrastructure.

This is not a new problem; it's also true of any new hire. A fast-growing company like Basis might onboard multiple engineers every month, so it has always been important to make your codebase easy to learn. But **unlike a human, an agent has to "onboard" to the codebase every single trajectory**. As we've adopted coding agents, suddenly the "onboardings" at Basis have gone from a handful a month to thousands a month. At this rate, any small inconsistencies, contradictions, and gaps compound quickly, while previously they may have gone unnoticed.

## Principles for an Agent-Native Codebase

The primary levers to empower coding agents are context and tools. To get to our end state of fluent agents, we developed five principles to guide the development of those levers.

1. **Canonicality.** Every artifact in the repo is either a source of truth about the system as it is today, or a record of intent and history. It is never both. An agent reading your codebase needs an explicit map of what to trust as a description of reality and what to read as a plan, a hypothesis, or a memory.
2. **Localization.** Context should live as close to where it is used as possible. It only moves up as it becomes more generally applicable. This reduces the likelihood that agents miss relevant context.
3. **Verifiability.** Agents need verification of their work. We built mechanisms to enforce that, including sub-agent roles, pre-commit hooks, and tests.
4. **Interoperability.** No layer of the architecture binds the team to a single vendor. AI technology is moving too fast to bet on a single platform. Locking into a vendor this early in AI development risks missing large benefits down the road.
5. **Default-no.** Any context that is loaded automatically must be scrutinized closely. Tokens that earn no behavior are a tax on every session, paid by every agent and every engineer. Stating it negatively is intentional. When the default is "include," loaded files balloon; when the default is "exclude," every line earns its place.

The architecture we built is the implementation of these principles in code.

## Canon vs. Not Canon

The first step in applying our principles was categorizing existing context into canonical and non-canonical categories. This was a rigorous process that forced the team to gather and collate many types of information from across the codebase, and then engage in intense discussions to reconcile them. Through that reconciliation process, we formalized our approach in a documentation-standards document that maps every artifact type in the repo to an authority level.

**Canon** is material a coding agent should treat as a source of truth about how the system works today. It includes root and nested `AGENTS.md` files, skills, the `docs/` directory, and inline code comments and docstrings. These artifacts say, "This is the current state and how we work in it."

**Not canon** is useful context that is not a source of truth about the current codebase. It includes plans and specs (`.specs/` and Linear), and historical rationale (`.notes/`).

Both categories are valuable. The potential mistake is treating not-canon as canon. A Linear ticket may describe a feature that was never implemented, or was implemented differently than planned. If the agent reads that ticket and treats it as truth, it will be confused about the correct state of the world. **By explicitly marking what is and is not canonical, we give agents a more nuanced ontology.**

The question this may raise is, "Why allow agents to see non-canonical information at all?" The answer is that non-canonical information can still be extremely valuable when parsing complex situations. Agents need a way to reach back to specific moments in history and answer questions like "Why did we write this code this way?" In a pre-agent world, the answer was a Slack DM to whoever wrote the commit. Now the answer is `.notes/`.

For example, when our [incident response agent, Clueso](https://www.getbasis.ai/blogs/clueso-how-we-built-an-agent-that-autonomously-resolves-78-of-bugs), debugs a user report, non-canonical context helps Clueso understand whether it is a bug or a feature. While specifications tell Clueso the latest intended behavior, the notes indicate important edge cases that were considered by the original code author.

Our full mapping is published below as the **Authority Map**.

> **Transcribed from the original Authority Map figure** (artifact-type → one-line gloss):
>
> | Canon (source of truth about today) | Not canon (intent, history, hypothesis) |
> |---|---|
> | **AGENTS.md** — root and nested directives: how we work, here. | **.specs/** — repo-backed product and tech specs. |
> | **Skills** — cross-cutting procedures loaded on match. | **Linear** — active project specs, alignment-stage decisions. |
> | **docs/** — durable architecture and onboarding. | **.notes/** — change-set tradeoffs, recorded close to the work. |
> | **Docstrings** — contract, invariants, side effects. | **PR descriptions** — why the diff exists; what it discarded. |
> | **Comments** — non-obvious local reasoning, in place. | **Slack threads** — the unrecorded conversation, fossilised. |
>
> Note: the prose above the diagram lists `AGENTS.md`, skills, `docs/`, `.specs/`, Linear, and `.notes/` only. Docstrings, comments, PR descriptions, and Slack threads appear only in the figure.

## The Six-Layer Architecture

> **Transcribed from the original "Context Pyramid" figure** (which only depicts layers 1–3, with a load-timing axis the prose does not state explicitly):
>
> The figure organizes context along a `UNIVERSAL ↔ LOCALIZED` axis and tags each layer with a load-timing rule:
>
> | Layer | Load timing | Examples shown in figure |
> |---|---|---|
> | Root `AGENTS.md` | Always loaded (universal) | principles, workflow, communication, type safety, naming |
> | Skills | Loaded on match | database, testing, backend, frontend, pr, docs, transactions |
> | Nested `AGENTS.md` | Loaded by directory (localized) | migrations-folder rules, folder-specific rules |
>
> Mental model: the root file pays the highest token cost (every session, every agent), so it carries only what's universal; nested files pay cost only when an agent enters the directory; skills pay cost only when a task matches their description.

The Authority Map gave us a clean six-layer architecture.

**Layer 1: Root AGENTS.md.** Our engineering principles, workflow definitions, and communication patterns. Loaded in every session. Currently around 300 lines. The most high-leverage file in the repository: every token is seen by every agent, every time. For Claude users, we merely symlink the `AGENTS.md`.

**Layer 2: Nested AGENTS.md files.** More than 100 of these across the monorepo, each scoped to its directory. The backend `AGENTS.md` specifies import conventions, concurrency patterns, and dependency rules. Each file is narrow and operational.

Example:

```markdown
### Imports

All Python imports go at the top of the file.
- Strongly avoid inline/deferred imports to work around circular imports.
A circular import means the module structure is wrong--fix the structure
instead.
- Only acceptable reason for a non-top-level import: the imported module
has expensive load-time side effects and the calling code path is
rarely executed.
```

**Layer 3: Skills.** The `.agents/skills/` directory contains skill packages covering backend architecture, frontend patterns, testing standards, documentation conventions, and domain-specific knowledge for products.

**Layer 4: Sub-agent roles.** The `.agents/roles/` directory defines more than half a dozen specialized agents, each with its own context window. The verifier runs diff-scoped tests and pre-commit hooks, then reports pass/fail with actionable failure details. The standards-enforcer validates code against all applicable `AGENTS.md` files and skills, checking for overly defensive programming, dead code, and missing test coverage.

```markdown
# verifier.md (frontmatter)
---
id: verifier
name: verifier
description: Runs diff-scoped tests, pre-commit hooks, and relevant lint/type checks, then reports pass/fail status with actionable failure details.
codex_agent_key: verifier
codex_model: gpt-5.5
codex_model_reasoning_effort: low
codex_model_verbosity: low
```

**Layer 5: Unified MCP.** Our unified MCP server gives agents access to external systems: Linear for project context, Slack for team communication, Better Stack for logs, PostHog for analytics, and dev database access for validation. An agent investigating a bug can pull the relevant Linear ticket, check production logs, and query the database without the engineer manually copying context into the prompt.

**Layer 6: Tests.** Automated enforcement that catches standard violations before they reach CI. Ruff for Python linting and formatting, BasedPyright for type checking, ESLint and Prettier for TypeScript, plus detections for large files, private keys, and merge conflicts. These hooks are the last line of defense; they enforce the standards even when an agent (or a human) forgets to follow them.

## Rewriting AGENTS.md

Our repo contained lots of `AGENTS.md` files that had been written before we codified our principles. We found about 20 of them, and they were in rough shape. Here are the three most common issues we saw across the `AGENTS.md` files.

**First**, many of the files described the codebase to the agent rather than instructing them. For example, one `AGENTS.md` said: "SRC is where we put all our source code." Of course, the agent already knows what an `src/` folder is; it has been trained on hundreds of thousands of repositories with that convention.

Compare that with an instruction like "use strict type checking" or "never use inline imports to work around circular dependencies; fix the module structure instead." These operational directives change the agent behavior. They tell the agent how we expect it to work.

**Second**, when our `AGENTS.md` files did include instructions, they were often all high-priority, "must-follow" directives. When you tell an agent in strongly worded terms that everything is important, it makes nothing important. One of the trickier parts of refining the rules was consistently embedding an accurate sense of priority into the prose. The default-no and localization principles helped guide us here. Removing unnecessary emphasis and placing instructions where they applied yielded the agent behavior we wanted.

**Third**, we also needed to organize information that applied in multiple scenarios across folders. For example, knowledge about the intricacies of our Tasks product could not properly live only in the backend `AGENTS.md`. This knowledge was necessary for frontend business logic as well. We embedded cross-folder knowledge in skills that could be loaded by the agent on demand. Originally we used a `/docs` folder, but moved to take advantage of the models all being post-trained to load skills effectively. (Docs now are for explicitly human-facing material.)

We codified five authoring rules for `AGENTS.md` files, each of them a corollary of the principles:

1. **Instruction quality.** Write for agents, not for humans. The objective of your `AGENTS.md` files should be to explain to an agent how to operate. They should not become permanent documentation for humans.
2. **Hierarchy-first placement.** Place context at the most specific directory that fully owns it. Information moves up only when it is genuinely shared.
3. **Resilient references.** Use descriptive names rather than exact file paths. Paths change; descriptions are stable.
4. **Text-only, search-friendly content.** No ASCII art, no binary content, no formatting that interferes with search or parsing.
5. **Default-no.** Would an agent reasonably need this information for the majority of tasks in this directory? If not, it belongs somewhere else.

The team rewrote `AGENTS.md` files across about 20 folders, migrating contextual knowledge to skills and replacing descriptive content with operational instructions. Examples of what survived the rewrite:

- Canon context is a source of truth you can trust to inform decisions. Non-canonical context is context that indicates intent, notes, temporary states, etc.
- Prefer early returns over deep nesting.
- Write code that can be understood without referencing other files. Be explicit rather than clever.

These are loaded into every agent session across the entire monorepo. They are the directives we want followed regardless of where an agent is working. The root `AGENTS.md` is currently around 300 lines, and every line has been argued over.

## The Cleanup

With the instruction layer rebuilt and the architecture in place, we finally turned to the codebase itself. Ryan Moffat used coding agents to audit every directory against the newly codified instructions, producing a list of nine projects with thousands of lines of violations.

We then deployed agents to fix the problems that agents had perpetuated. The agents that had been absorbing bad patterns were now given explicit, well-structured instructions to rewrite code according to the new standards.

The rewrite touched an estimated 20 to 30 percent of the entire codebase across the nine completed projects. The principles told us where the bar was; the cleanup was the cost of getting the existing code up to that bar so that it could serve as canon. There is no shortcut. An agent-native codebase demands more local correctness than a human-only one, because every file is context and the agents are constantly onboarding.

Refactoring with agents hit natural limits. Often, there were structural reasons for the technical debt that agents could not solve. We prioritized the most frequently visible parts of the codebase that agents could fix. We then prioritized the visible areas that required human intervention. The rest we left to be cleaned up in our normal processes.

## Maintaining Canonical Context

The first question anyone asks when they see our architecture is, "How do you keep all that from rotting?"

Maintenance starts with **owners**. Every canonical artifact at Basis carries an explicit owner field in YAML frontmatter at the top of the file. A CI/CD check ensures that any new skill or non-production markdown file has a corresponding owner. When our automated context cleanup system flags something, the owner is responsible for reviewing it.

We have a set of cloud agent automations that review the monorepo. This is what we call our **Automatic Context** system. Three of those automations target context directly:

- A CI/CD check ensures merges match our deterministic standards: validated frontmatter, descriptive prose where operational directives belong, and proper grammar.
- A scanner runs daily to do a broad sweep of skills and `AGENTS.md` files for staleness, contradictions, duplicated instructions, broken references, and missing context for recent changes.
- Workers run daily to pick up tickets from the scanner and implement small, scoped fixes.

The broader point: **automated context maintenance is only possible because we agreed on what is canonical**. A scanner can sweep `AGENTS.md` files and skills for contradictions because canonical context is, by definition, supposed to agree with itself. Non-canonical context is allowed to disagree with itself; specs are revised, plans are abandoned, `.notes/` entries capture decisions made at moments that no longer exist. If you do not draw the line between what must be self-consistent and what may not be, you cannot run a scanner over either category.

## Closing the Validation Loop

Alongside the problem of agents writing non-standard code, we also recognized that our testing wasn't standardized. One of our principles was that agents' work requires verification, so we expanded our testing frameworks. This was a separate effort, led by Bhavdeep Sethi on the platform side and the Atlas team on the agent behavior side.

We found a lot of success with an inter-team structure: pairing one engineer focused on solving the traditional technical problems of testing with another engineer focused on the agent's instructions. Bhavdeep built the testing infrastructure: unit tests, integration tests, proper fixtures and markers, CI integration. The Atlas team's contribution was embedding testing standards into the agent behavior layer. This approach treated agent behavior as a first-class requirement rather than an afterthought.

We created a testing skill that defines what tests are expected, when they are required, and how they should be structured. We extensively evaluated whether our guidelines induced agents to produce the tests we wanted. Sometimes agents were too verbose. Other times, they were extremely lazy. Getting the skill language correct required some work. It was worth the investment to have agents that consistently produced tests according to our standards.

## How We Judged the Result

We started with the simplest metric to measure: token usage per developer. The hypothesis was that if we solved the problems making coding agents perform poorly, engineers would be able to trust agents to do more work, which would let engineers manage more agents simultaneously, which would increase token usage. We set a goal of 5x token usage in one quarter. It felt ambitious because engineers at Basis were already coding-agent power users. When we hit that goal, we knew we were enabling developers to parallelize more and spend less time fixing agent output.

Increasing AI usage is only meaningful if it enhances the team's overall productivity. Weekly commit velocity over this time increased by 2.5 times. By the end of this work, 100% of our engineering team was working with multiple worktrees. Engineers were coming to us asking for better tooling to help them manage more agents.

## What's Next

Coding agents are a new kind of consumer of your codebase, with their own failure modes, their own appetite for context, and their own demands on what counts as a well-organized repo. Most companies have not begun to take that seriously. The ones that do will find, as we did, that the work is bigger than expected, the principles are non-obvious, and the payoff is substantial.

Now that we have given coding agents an ergonomic environment to succeed in, we are optimizing the entire AI-native software development lifecycle at Basis. This includes new approaches such as proof-based development, redesigning our code review process, and experimenting with automatic code maintenance — the natural extension of the Automatic Context machinery from the instruction layer to the code itself.

If you want to join an agent-native company, [we're hiring](https://www.getbasis.ai/careers).

---

*Michael Crabtree is Atlas Tech Lead at Basis. [@RyanBMoffat](https://x.com/RyanBMoffat) led the codebase standards audit and owns the Automatic Context system. [@BhavdeepSethi](https://x.com/BhavdeepSethi) built the testing infrastructure. [@SethSchiesel](https://x.com/SethSchiesel) contributed to this post.*

---

## Top Comments

**1. [@devstein64](https://x.com/devstein64/status/2057099800630440313) — Devin Stein** (May 20, 2026)
> amazing post - do you encourage agents to explore the curated context in AGENTS.md?

**2. [@loganzev](https://x.com/loganzev/status/2056944590381330828) — Logan** (May 20, 2026)
> Awesome post Crabtree is the best

**3. [@filchyboy](https://x.com/filchyboy/status/2057097616031461738) — Christopher Filkins** (May 20, 2026)
> This aligns well with the work I have been doing. Thanks for sharing.

**4. [@ortizmauricio_](https://x.com/ortizmauricio_/status/2056957306861158629) — Mauricio** (May 20, 2026)
> u got me w the chair

**5. [@nikunj](https://x.com/nikunj/status/2057136549880598789) — Nikunj Kothari** (May 20, 2026)
> Thanks for writing this - loved reading it. As a follow up, would love two things: 1) a concrete feature you built and how it went through with this structure. What you learned what the agents learned and what changes did you make.
> 2) more on the clean up / loops. As tokens increase, as PRs increase - how do you navigate that. what loops are you building
