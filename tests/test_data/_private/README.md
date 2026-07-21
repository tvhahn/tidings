# Private fixtures

This directory holds **uncommitted** real bank statement PDFs (and optional
paired expected-output JSON files) for local integration testing against real
data.

Everything in here except `.gitkeep` and this `README.md` is gitignored — see
the matching pattern in the repo root `.gitignore`. Real customer PDFs must
never enter version control.

## Layout

```
tests/test_data/_private/
  .gitkeep                        # tracked
  README.md                       # tracked
  RBC_Chequing_<period>.pdf       # YOUR file, ignored
  RBC_Chequing_<period>.json      # optional expected-output, ignored
  Simplii_Chequing_<period>.pdf   # ...
```

Use the same JSON shape as the committed fixtures
(`tests/test_data/{rbc,simplii}/*.json`) if you want field-by-field assertions.
A coarse "parser produced > 0 transactions" check is fine without paired JSON.

## Running private-fixture tests

Tests gated by `@pytest.mark.private_fixtures` are **skipped by default**. To
run them:

```bash
RUN_PRIVATE_FIXTURES=1 uv run pytest -m private_fixtures
```

Tests should also skip individually if their expected file is absent — so
contributors and CI without the local files silently skip rather than fail.

## Why this exists

Synthetic fixtures (committed under `tests/test_data/{rbc,simplii}/`) prove
the parser handles the synthetic shape we generate. Real statements catch
parser drift against real bank-PDF quirks: kerning, mid-row page breaks,
inconsistent column alignment, embedded images, font-subset edge cases,
JasperReports / PDFlib content-stream variations.

The maintainer keeps a stash of real statements at `data/raw/statements/`
(also gitignored). Copy one into here when you want to exercise it through the
test suite.
