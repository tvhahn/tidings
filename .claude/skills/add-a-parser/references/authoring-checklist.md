# Authoring checklist — echo before committing

Confirm every box to the user before you run `/commit`. An unchecked box means
the parser is not done.

## Evidence & fixtures

- [ ] Every transaction type parsed has **at least one real captured fixture**.
      No type is parsed from invented text. Types with no sample are left
      unparsed (they fall through to AI extraction) — that is correct.
- [ ] Every fixture `.txt` is **scrubbed**. Scan each one to prove no PII
      survived. This uses the scrubber's own `scan_for_pii` (emails, card
      numbers, plus any `.pii-patterns` rules), so it stays in lockstep when the
      scrubber tightens and it never re-flags the scrubber's own placeholders
      (`redacted@example.com`, `0000 0000 0000 0000`):
      ```bash
      uv run python -c '
      import pathlib
      from src.finance.fixture_scrub import scan_for_pii
      for p in pathlib.Path("tests/test_data/<bank>").glob("*.txt"):
          hits = scan_for_pii(p.read_text())
          print(p, "CLEAN" if not hits else ("LEAK: " + str(hits)))
      '
      ```
      Replace `<bank>` with your slug. Every line must print `CLEAN`.
- [ ] **Person names hand-checked.** The grep above only catches emails and card
      digits — person names (especially e-transfer sender/recipient names and
      "Hi <name>," greetings) are NOT auto-redacted and print `CLEAN` even when
      a real name survived. You read every scrubbed `.txt` yourself and replaced
      any real person name with a synthetic one (e.g. "Jordan Lee" → "Alex
      Doe"), updating the fixture `.json` expectation to match.
- [ ] The scan above **already covers** a repo-root `.pii-patterns` file:
      `scan_for_pii` auto-loads it (it is export-ignored and usually absent, in
      which case only the always-on email/card rules run). If the file is present
      and you want to confirm it is being applied, print the loaded rules — any
      fixture hit will already have surfaced as a `LEAK` above:
      ```bash
      test -f .pii-patterns && uv run python -c '
      from src.finance.fixture_scrub import _load_pii_patterns
      print("active .pii-patterns rules:", _load_pii_patterns(None))
      ' || echo "no .pii-patterns at repo root — skipping"
      ```
- [ ] No fixture `.json` still contains `"TODO"`:
      ```bash
      uv run grep -rl '"TODO"' tests/test_data/<bank>/ || echo "no TODOs remain"
      ```
      (The command should print `no TODOs remain`.)

## Traceability

- [ ] **Every regex in the parser is traceable to a specific fixture line.**
      List each regex and cite `fixture-file:line` for the body text it matches.
      A regex you cannot trace to a captured sample must be deleted.

## Registration (all three in `src/finance/email_pipeline.py`)

- [ ] Institution key appended to `PARSER_KEYS` (and the key string appears
      verbatim in the captured bodies).
- [ ] Parser imported and instantiated in the `parsers` dict in
      `parse_email_body`.
- [ ] `domain_map` updated **only** for a dedicated sender domain; a
      multi-institution / Interac (`payments.interac.ca`) domain is deliberately
      left out so it falls through to body-text detection.

## Property harness (`tests/property/test_parser_invariants.py`)

- [ ] Parser class added to `PARSERS` and to `BODY_FACTORIES`; single-word
      triggers added to `TRIGGER_SUBSTRINGS` if applicable.

## Parser behavior

- [ ] Conservative fall-through documented in the parser class docstring:
      unmatched bodies return the input unchanged (only `institution` stamped)
      so recovery / AI extraction can take over.
- [ ] `AMOUNT_PATTERN`, `parse_amount`, and `merge_details` are used (no
      hand-rolled amount parsing or dict merging).

## Tests & lint

- [ ] `uv run pytest tests/unit/test_<bank>_parser.py tests/property/ -v` green.
- [ ] `uv run pytest tests/ -m "not integration" -q` green.
- [ ] `uv run ruff check src/ tests/` clean; `uv run ruff format src/ tests/`
      applied.

## Backlog

- [ ] If the server was running, `retry-all` was run for the bank and the
      `{retried, created, duplicates, still_failing}` counts were reported to the
      user — or the step was reported as skipped because no server was running,
      with the note that the backlog can be recovered later via the same curl or
      the Needs review page's "Retry all" button.
