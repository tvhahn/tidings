"""Synthetic Simplii Chequing statement PDF generator.

Reads a paired expected-output JSON (the source of truth for transactions, dates,
amounts, balances) and renders a parser-compatible synthetic PDF via Jinja2 +
WeasyPrint. Output is deterministic given a fixed seed.

Usage:
    uv run python -m scripts.fixtures.generate_simplii_fixture \
        --data-source tests/test_data/simplii/Simplii_Chequing_2025-02-27_to_2025-03-30.json \
        --output tests/test_data/simplii/Simplii_Chequing_2025-02-27_to_2025-03-30.pdf \
        --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from faker import Faker
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from src.finance.statement_parser import MONTH_NUM_TO_ABBR, MONTH_NUM_TO_FULL

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "simplii_statement.html"

# Fixed PDF CreationDate for byte-identical output across runs (WeasyPrint honours
# SOURCE_DATE_EPOCH). Chosen to be before all committed fixture periods (2025+).
_DETERMINISTIC_EPOCH = "1735689600"  # 2025-01-01 UTC


@dataclass
class _RenderTxn:
    trans_date: str
    eff_date: str
    description: str
    withdrawal: str
    deposit: str
    balance: str


def _fmt_amount(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}"


def _short_date(iso: str) -> str:
    """2025-02-28 -> 'Feb 28'"""
    d = date.fromisoformat(iso)
    return f"{MONTH_NUM_TO_ABBR[d.month]} {d.day:02d}"


def _full_date(iso: str) -> str:
    """2025-02-27 -> 'February 27, 2025'"""
    d = date.fromisoformat(iso)
    return f"{MONTH_NUM_TO_FULL[d.month]} {d.day}, {d.year}"


def _build_context(data: dict, fake: Faker) -> dict:
    meta = data["metadata"]
    txns = data["transactions"]
    totals = data["totals"]

    first = txns[0]
    first_amount = first["amount"]
    first_balance = first["balance"]
    if first["type"] == "deposit":
        opening_balance = first_balance - first_amount
    else:
        opening_balance = first_balance + first_amount

    render_txns: list[_RenderTxn] = []
    for t in txns:
        short = _short_date(t["date"])
        render_txns.append(
            _RenderTxn(
                trans_date=short,
                eff_date=short,
                description=t["description"],
                withdrawal=_fmt_amount(t["amount"]) if t["type"] == "withdrawal" else "",
                deposit=_fmt_amount(t["amount"]) if t["type"] == "deposit" else "",
                balance=_fmt_amount(t["balance"]),
            )
        )

    closing_balance = txns[-1]["balance"]
    opening_short = _short_date(meta["period_start"])

    street_num = fake.building_number()
    street = fake.street_name()
    city = fake.city()
    postal = f"{fake.bothify('?#? #?#').upper()}"

    return {
        "period_start_text": _full_date(meta["period_start"]),
        "period_end_text": _full_date(meta["period_end"]),
        "statement_date_text": _full_date(meta["period_end"]),
        "account_number": str(fake.random_number(digits=10, fix_len=True)),
        "holder_name": fake.name().upper(),
        "co_holder_name": fake.name().upper(),
        "address_line1": f"{street_num} {street.upper()}",
        "address_city_province": f"{city.upper()} BC",
        "postal_code": postal,
        "opening_trans_date": opening_short,
        "opening_eff_date": opening_short,
        "opening_balance": _fmt_amount(opening_balance),
        "transactions": render_txns,
        "total_funds_out": _fmt_amount(totals["funds_out"]),
        "total_funds_in": _fmt_amount(totals["funds_in"]),
        "closing_balance": _fmt_amount(closing_balance),
    }


def generate(data_source: Path, output: Path, seed: int = 42) -> None:
    os.environ.setdefault("SOURCE_DATE_EPOCH", _DETERMINISTIC_EPOCH)

    with data_source.open("r", encoding="utf-8") as f:
        data = json.load(f)

    fake = Faker("en_CA")
    Faker.seed(seed)

    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(_TEMPLATE_NAME)
    context = _build_context(data, fake)
    html_text = template.render(**context)

    # base_url so the <link rel="stylesheet" href="simplii_statement.css"> resolves
    HTML(string=html_text, base_url=str(_TEMPLATES_DIR)).write_pdf(target=str(output))

    print(f"Wrote {output} ({output.stat().st_size:,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    generate(args.data_source, args.output, args.seed)


if __name__ == "__main__":
    main()
