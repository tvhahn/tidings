"""Synthetic PDF fixture generators for bank statement parsers.

Each generator reads a committed JSON expected-output file (source of truth) and
renders a matching synthetic PDF via WeasyPrint + Jinja2. Templates live in
scripts/fixtures/templates/.

Per-bank scripts (generate_simplii_fixture.py, generate_rbc_chequing_fixture.py)
are intentionally duplicated rather than abstracted — shared code should be
extracted only after a third bank makes the seams obvious.
"""
