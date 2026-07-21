"""Synthetic RBC Chequing statement PDF generator.

Reads a paired expected-output JSON (the source of truth for transactions, dates,
amounts, balances) and renders a parser-compatible synthetic PDF via Jinja2 +
WeasyPrint. Output is deterministic given a fixed seed.

Usage:
    uv run python -m scripts.fixtures.generate_rbc_chequing_fixture \
        --data-source tests/test_data/rbc/Rbc_Chequing_2025-02-24_to_2025-03-24.json \
        --output tests/test_data/rbc/Rbc_Chequing_2025-02-24_to_2025-03-24.pdf \
        --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from faker import Faker
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from src.finance.statement_parser import MONTH_NUM_TO_ABBR, MONTH_NUM_TO_FULL

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "rbc_chequing_statement.html"

# Fixed PDF CreationDate for byte-identical output across runs (WeasyPrint honours
# SOURCE_DATE_EPOCH). Chosen to be before all committed fixture periods (2025+).
_DETERMINISTIC_EPOCH = "1735689600"  # 2025-01-01 UTC


@dataclass
class _RenderTxn:
    date_short: str
    description: str
    withdrawal: str
    deposit: str
    balance: str


def _fmt_amount(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.2f}"


def _short_date_concat(iso: str) -> str:
    """2025-02-27 -> '27Feb' (RBC format: day+month with no space)."""
    d = date.fromisoformat(iso)
    return f"{d.day}{MONTH_NUM_TO_ABBR[d.month]}"


def _full_date(iso: str) -> str:
    """2025-02-24 -> 'February 24, 2025'"""
    d = date.fromisoformat(iso)
    return f"{MONTH_NUM_TO_FULL[d.month]} {d.day}, {d.year}"


def _build_context(data: dict, fake: Faker) -> dict:
    meta = data["metadata"]
    txns = data["transactions"]
    totals = data["totals"]

    # Opening balance is the running balance before the first transaction.
    first = txns[0]
    if first["type"] == "deposit":
        opening_balance = first["balance"] - first["amount"]
    else:
        opening_balance = first["balance"] + first["amount"]

    render_txns: list[_RenderTxn] = []
    for t in txns:
        render_txns.append(
            _RenderTxn(
                date_short=_short_date_concat(t["date"]),
                description=t["description"],
                withdrawal=_fmt_amount(t["amount"]) if t["type"] == "withdrawal" else "",
                deposit=_fmt_amount(t["amount"]) if t["type"] == "deposit" else "",
                balance=_fmt_amount(t["balance"]),
            )
        )

    closing_balance = txns[-1]["balance"]

    street_num = fake.building_number()
    street = fake.street_name()
    city = fake.city()
    postal = fake.bothify("?#? #?#").upper()

    return {
        "period_start_text": _full_date(meta["period_start"]),
        "period_end_text": _full_date(meta["period_end"]),
        "account_number": f"{fake.random_number(digits=5, fix_len=True)}-{fake.random_number(digits=7, fix_len=True)}",
        "holder_name": fake.name().upper(),
        "co_holder_name": fake.name().upper(),
        "address_line1": f"{street_num} {street.upper()}",
        "address_city_province": f"{city.upper()} BC",
        "postal_code": postal,
        "opening_balance": _fmt_amount(opening_balance),
        "transactions": render_txns,
        "total_withdrawals": _fmt_amount(totals["funds_out"]),
        "total_deposits": _fmt_amount(totals["funds_in"]),
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
