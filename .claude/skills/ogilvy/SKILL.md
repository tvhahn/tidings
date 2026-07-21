---
name: ogilvy
description: Review or write selling copy — landing pages, headlines, feature blurbs, FAQs, README pitches — with David Ogilvy's discipline — facts over adjectives, one promise per surface, every claim verified against the product. Invoke for "Ogilvy analysis", "review the marketing copy", "does this headline sell", "make this page convert", or any persuasion-copy audit. Pairs with brand-voice, which owns the register.
---

# Ogilvy — copy that sells because it's true

Ogilvy's discipline in one sentence: **advertising is information in service of a sale, aimed at a busy, intelligent reader who owes you nothing.** "The consumer isn't a moron; she is your wife. You insult her intelligence if you assume that a mere slogan and a few vapid adjectives will persuade her to buy anything. She wants all the information you can give her." (*Confessions of an Advertising Man*, 1963.)

This skill applies that discipline to modern product pages. It is a **selling-logic** skill, not a register skill — where a house voice exists (for Tidings: `docs/brand/voice.md`, non-negotiable), the voice rules win on tone and vocabulary. Ogilvy's machinery below is voice-neutral: specificity, proof, one promise, no lies survive any register.

## The decision stack (in order — later steps only matter if earlier ones are right)

1. **Positioning.** What does this product do, and who is it for? Decided before any word is written. If two sections of a page answer this differently, that is the first bug.
2. **The promise.** One benefit the reader receives — unique, competitive, and actually deliverable. "Promise, large promise, is the soul of an advertisement" (Samuel Johnson, via Ogilvy). A page may have many features; it gets one promise.
3. **The big idea.** "Unless your advertising contains a big idea, it will pass like a ship in the night." The big idea is the one framing a reader retells to someone else. Test: can you say it in a sentence a stranger would repeat?
4. **Evidence.** Every claim backed by something checkable — a number, a mechanism, a screenshot that shows it. For software: **the code is the client. Verify each claim against the shipped product before publishing.** A claim the product doesn't honor is not copy, it's a bug with better typography.
5. **Words.** Only now. Headlines, body, captions — per the rules below.

## Headlines

- "On the average, five times as many people read the headline as read the body copy. When you have written your headline, you have spent eighty cents out of your dollar." Treat the H1/H2s of a page as where the money goes. (Era-specific stat; timeless priority.)
- **Promise in the headline.** A headline that only decorates wastes its slot. Benefit-carrying beats clever.
- **Specific and factual beats general and clever.** The standard is the Rolls-Royce line: "At 60 miles an hour the loudest noise in this new Rolls-Royce comes from the electric clock." The most specific true fact you can prove, stated flat. Ask of every headline: *what is this page's electric clock?*
- **Flag your prospect, exclude no prospect.** The headline should let the right reader recognize themselves ("the transaction emails you already receive") without shutting out others who qualify.
- **Simple language.** "Readers do not stop to decipher the meanings of obscure headlines."
- Long headlines are fine when the length is carrying facts. Never when it's carrying throat-clearing.

## Body copy

- **Long copy is allowed for considered purchases** — self-hosted software, finance tools, anything a reader researches before adopting. "The more you tell, the more you sell" — *conditional on every sentence pulling weight.* Length is earned by the reader's need to know, never by a word count.
- **Facts, not adjectives.** "Avoid superlatives, generalizations, and platitudes. Be specific and factual." Replace every adjective you can with a number, a mechanism, or a named thing. "Five banks parsed natively" beats "broad bank support"; "runs on a Raspberry Pi" beats "lightweight."
- **Write the way you talk. Naturally.** Short words, short sentences, short paragraphs. "Never use jargon words… They are hallmarks of a pretentious ass." (1982 "How to Write" memo.)
- **Don't self-describe; demonstrate.** A page that calls itself calm/simple/powerful in every section is bragging on a loop. Say it once; let the screenshots, the numbers, and the restraint of the prose prove it thereafter. Nobody was ever bored — or nagged — into buying.
- **Captions sell.** Readers hit image captions and alt text far more than you think: "each caption should be a miniature advertisement for the product." A caption reading "Dashboard screenshot" is a wasted slot; one reading "March, grouped by day — the over-pace rows warmed to rust" is copy.
- **Don't bury the news.** "Many copywriters have a fatal instinct for burying news." The most differentiated, most retellable fact on the page goes up top, not in FAQ answer #2.

## The honesty gate (hard rules — a page fails review on any one of these)

1. **"Never write an advertisement which you wouldn't want your own family to read. You wouldn't tell lies to your own wife. Don't tell them to mine."** No claim the product doesn't currently honor. "Will ship next month" is not "does."
2. **Verify absolutes.** "Never", "nothing", "zero", "always", "all" are invitations for the reader to find the one counterexample. Keep an absolute only when the code makes it literally true; otherwise scope it ("no email content leaves for a model unless you add a key") — a precisely-scoped claim reads *more* trustworthy, not less.
3. **Beware negative claims misread.** Ogilvy: write "our salt contains no arsenic" and readers remember "arsenic." "No manual entry" can be read as "you can't enter one manually." Prefer the positive mechanism or add the qualifier ("no manual entry required").
4. **Quantified claims carry provenance.** A number you can't source is a superlative wearing a costume. (This applies to Ogilvy's own era stats — the 5×-headline and caption-readership figures are priority heuristics, not citable metrics.)

## Anti-patterns Ogilvy named (recognize on sight)

- **Puffery** — "vapid adjectives," superlatives, "bombast." Symptom: adjectives that survive the So-what test with no fact underneath.
- **Cleverness as the hero** — "Make the product the hero." If the wordplay is more memorable than the promise, cut the wordplay.
- **Committee copy** — a page that "embraces the divergent views of too many executives": three CTAs, four self-descriptions, every feature a headline. One promise; boil it down; "go the whole hog."
- **Boredom** — "Nobody was ever bored into buying a product." Calm is a register; boring is a failure. The cure is *interesting facts*, never added excitement.
- **Burying the news** — the genuinely novel thing hidden below the fold or inside an FAQ.
- **Jargon and bank formality** — write in "the colloquial language which your customers use in everyday conversation."

## Review procedure (auditing an existing page)

1. **Claim inventory.** Extract every verifiable statement — features, numbers, behaviors, absolutes. Table them.
2. **Verify each against the product.** Read the code / run the app / hit the endpoint. Verdicts: TRUE / FALSE / OVERCLAIM (true in spirit, absolute in wording) / UNVERIFIABLE. A marketing screenshot is also a claim — check it shows what the adjacent copy says.
3. **Run the stack top-down.** One positioning? One promise? A big idea? Evidence under each claim? Only then critique wording.
4. **Run the diagnostic** (below) and report findings in priority order: false claims first, overclaims second, selling-logic gaps third, style last.
5. **Propose rewrites, not directions.** "Tighten this" is not a finding. Quote the line; give the replacement; say why in one sentence.

## Diagnostic checklist

1. What is the positioning — and does every section agree on it?
2. What is the single promise? (If you list three, the page has none.)
3. What is the big idea — the sentence a reader retells?
4. Is every claim true of the shipped product *today*? Which absolutes survive a hostile reader?
5. Does the headline carry a promise or a fact — or just style?
6. What is the page's electric clock — its most specific, provable, surprising fact — and is it above the fold?
7. Could any adjective be replaced by a number, mechanism, or named thing?
8. Do captions and alt text sell, or just describe?
9. Is the product the hero, or is the writing the hero?
10. Is anything important buried — in an FAQ, a footer, a tooltip?
11. Would you read the whole page if it weren't yours? Where do you skim? Cut there.
12. Is it honest enough to show your family, and interesting enough that they'd finish it?

## What not to import from 1963

Print-era mechanics (layout dogma, serif rules, fixed copy lengths), the readership percentages as literal stats, and the hard-sell "free/new" lever where a house voice forbids urgency. Keep the engine — specificity, proof, one promise, honesty, news up front — and let the house voice own the register.

---

*Sources: "How to Write" memo (1982, in* The Unpublished David Ogilvy*); "How to Create Advertising That Sells" (O&M house ad, 38 points);* Confessions of an Advertising Man *(1963);* Ogilvy on Advertising *(1983). Quotes verbatim; era-specific statistics flagged as heuristics.*
