"""Shared test factories — single source of truth for building test data.

Each factory returns a sensible default and accepts **overrides for any field.
"""

from collections.abc import Awaitable, Callable, Iterable
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from src.finance.budget_service import BudgetService
    from src.finance.statement_parser import StatementParseResult
    from src.finance.statement_reconciler import ReconcileResult
    from src.finance.transaction_db import TransactionsDB

DEFAULT_USER_PK = "USER#default"

# Sentinel distinguishing "branch never configured" from a legitimate ``None``
# result, so ``make_run_sync_dispatch`` can fail loudly instead of leaking a
# MagicMock when a test's mock is exercised down an unexpected path.
_UNSET: Any = object()


def make_transactions_db() -> "tuple[TransactionsDB, MagicMock]":
    """Create a TransactionsDB with a mocked DynamoDB resource.

    Returns (db, table) — table is the mock DynamoDB table for assertion.
    """
    from src.finance.transaction_db import TransactionsDB

    dyn_resource = MagicMock()
    table = MagicMock(name="dynamodb_table")
    dyn_resource.Table.return_value = table
    return TransactionsDB(dyn_resource), table


def make_budget_service(dyn_resource: MagicMock | None = None) -> "BudgetService":
    """Create a BudgetService with a mocked DynamoDB resource."""
    from src.finance.budget_service import BudgetService

    if dyn_resource is None:
        dyn_resource = MagicMock()
        dyn_resource.Table.return_value = MagicMock(name="dynamodb_table")
    return BudgetService(dyn_resource=dyn_resource)


def make_transaction_item(**overrides: Any) -> dict[str, Any]:
    """Build a fake DynamoDB transaction item.

    Superset of all fields used across test_api_transactions, test_api_search,
    and test_spending_summary.  Each test overrides only what it cares about.
    """
    base = {
        "ForwardedTo": "user@example.com",
        "DateFileName": "2026.02.15_10.30_test.eml",
        "Date": "02/15/2026 10:30 PST",
        "Amount": Decimal("42.50"),
        "Company": "Test Store",
        "Category": "groceries",
        "Institution": "RBC",
        "TransactionType": "purchase",
        "Name": "Alice",
        "Body": "long body text",
        "Subject": "Transaction Alert",
        "FileName": "s3://bucket/test.eml",
        "FromName": "RBC",
        "FromEmail": "alerts@rbc.com",
        "ToName": "Alice",
        "ToEmail": "user@example.com",
        "UserId": "alice",
        "TransactionHash": "abc123",
    }
    base.update(overrides)
    return base


def make_pdf_bytes() -> bytes:
    """Create minimal PDF bytes for validation."""
    return b"%PDF-1.4 test content for validation"


def make_parse_result(**overrides: Any) -> "StatementParseResult":
    """Create a StatementParseResult with default test data."""
    from src.finance.statement_parser import StatementParseResult

    defaults = {
        "transactions": [
            {
                "date": "2026-01-15",
                "description": "BillPayment WestlandUtilityCo",
                "amount": 98.75,
                "type": "withdrawal",
                "balance": 41793.95,
            },
            {
                "date": "2026-01-23",
                "description": "Monthlyfee",
                "amount": 4.0,
                "type": "withdrawal",
                "balance": 41789.95,
            },
        ],
        "metadata": {
            "institution": "RBC",
            "account_type": "chequing",
            "period_start": "2025-12-24",
            "period_end": "2026-01-23",
            "transaction_count": 2,
        },
        "raw_descriptions": ["BillPayment WestlandUtilityCo", "Monthlyfee"],
        "cleaned_descriptions": ["Northwind Energy Co", "Monthly fee"],
    }
    defaults.update(overrides)
    return StatementParseResult(**defaults)


def make_reconcile_result(**overrides: Any) -> "ReconcileResult":
    """Create a ReconcileResult with default test data."""
    from src.finance.statement_reconciler import MatchedTransaction, NewTransaction, ReconcileResult

    if overrides:
        return ReconcileResult(**overrides)

    matched_txn = {
        "date": "2026-01-15",
        "description": "BillPayment WestlandUtilityCo",
        "amount": 98.75,
        "type": "withdrawal",
        "balance": 41793.95,
    }
    new_txn = {
        "date": "2026-01-23",
        "description": "Monthlyfee",
        "amount": 4.0,
        "type": "withdrawal",
        "balance": 41789.95,
    }

    return ReconcileResult(
        matched=[
            MatchedTransaction(
                index=0,
                statement_txn=matched_txn,
                db_item={
                    "ForwardedTo": "test@example.com",
                    "DateFileName": "2026.01.15_12.00_test.eml",
                    "Company": "WESTLANDUTILITYCO",
                    "Amount": 98.75,
                    "Category": "utilities",
                },
                company_differs=True,
                cleaned_description="Northwind Energy Co",
                raw_description="BillPayment WestlandUtilityCo",
            )
        ],
        ambiguous=[],
        new=[
            NewTransaction(
                index=1,
                statement_txn=new_txn,
                cleaned_description="Monthly fee",
                raw_description="Monthlyfee",
                suggested_category="service charges/fees",
            )
        ],
    )


def _resolve_dispatch_value(value: Any, label: str) -> Any:
    """Return ``value`` — or raise it when it is an exception instance.

    Lets ``make_run_sync_dispatch`` express both "this branch returns X" and
    "this branch raises E" through one parameter. An unconfigured branch
    (``_UNSET``) fails loudly so a mis-scoped mock surfaces instead of silently
    returning a MagicMock.
    """
    if value is _UNSET:
        raise AssertionError(f"run_sync dispatch: {label} branch was exercised but no value was configured")
    if isinstance(value, BaseException):
        raise value
    return value


def make_run_sync_dispatch(
    *,
    parser_parse: Any = None,
    parse_result: Any = _UNSET,
    passthrough: Iterable[str] = (),
    default: Any = _UNSET,
) -> Callable[..., Awaitable[Any]]:
    """Build an async ``side_effect`` for the ``mock_run_sync`` fixture that
    dispatches on the wrapped callable.

    The statement upload/import endpoints funnel every off-thread call through
    ``run_sync(func, *args, **kwargs)`` — the parser's ``parse``, plus persistence
    helpers (``save_statement``, ``get_transactions``, …). Tests stub these by
    inspecting ``func``:

    * ``func == parser_parse`` (the mock parser's ``.parse``) → yields
      ``parse_result``.
    * ``func.__name__`` in ``passthrough`` → the real function runs
      (``func(*args, **kwargs)``) so SQLite-backed persistence actually happens.
    * anything else → yields ``default``.

    "Yields" means: an ``Exception`` instance is raised, any other value is
    returned. This lets a single parameter model both the return-a-value and the
    raise-an-error closures the statement tests used (e.g. ``parse_result`` set to
    ``ValueError(...)`` to simulate a deterministic parse failure, or ``default``
    set to ``AssertionError(...)`` to assert nothing past parse runs). A branch
    left ``_UNSET`` raises a clear error if hit — never returns a stray MagicMock.
    """
    passthrough_names = frozenset(passthrough)

    async def run_sync_side_effect(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if parser_parse is not None and func == parser_parse:
            return _resolve_dispatch_value(parse_result, "parse_result")
        if passthrough_names and getattr(func, "__name__", "") in passthrough_names:
            return func(*args, **kwargs)
        return _resolve_dispatch_value(default, "default")

    return run_sync_side_effect


def make_db_item(
    date: str,
    amount: float,
    company: str,
    txn_type: str,
    forwarded_to: str = "test@example.com",
    date_file_name: str | None = None,
) -> dict[str, Any]:
    """Build a mock DynamoDB item for reconciliation testing.

    ``Amount`` is wrapped in ``Decimal`` to match what boto3 returns from DynamoDB —
    same rationale as ``make_transaction_item`` and ``make_budget_targets_item``.
    """
    if date_file_name is None:
        parts = date.split("-")
        date_file_name = f"{parts[0]}.{parts[1]}.{parts[2]}_12.00_test.eml"
    return {
        "ForwardedTo": forwarded_to,
        "DateFileName": date_file_name,
        "Date": f"{date.split('-')[1]}/{date.split('-')[2]}/{date.split('-', maxsplit=1)[0]} 12:00 PST",
        "Amount": Decimal(str(amount)),
        "Company": company,
        "TransactionType": txn_type,
        "Category": "groceries",
    }


def make_budget_targets_item(
    year: int = 2026,
    version: int = 1,
    ceiling: float | int | None = None,
    categories: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a fake DynamoDB BudgetConfig targets item.

    Numeric values are wrapped in Decimal to match what boto3 returns from
    DynamoDB — using plain ints here would cause API handlers (that coerce via
    Decimal arithmetic or JSON serializers) to behave differently from production.

    Matches the shape written by BudgetService.put_targets().
    """
    ceiling_dec = Decimal(5000) if ceiling is None else Decimal(str(ceiling))

    if categories is None:
        categories = {
            "groceries": {
                "target": Decimal(600),
                "input_mode": "monthly",
                "category_type": "variable",
                "monthly_amount": Decimal(600),
            },
            "rent": {
                "target": Decimal(2000),
                "input_mode": "monthly",
                "category_type": "fixed",
                "monthly_amount": Decimal(2000),
            },
        }

    base = {
        "PK": DEFAULT_USER_PK,
        "SK": f"BUDGET#targets#{year}",
        "Data": {"spending_ceiling": ceiling_dec, "categories": categories},
        "Version": version,
        "UpdatedAt": f"{year}-01-01",
    }
    base.update(overrides)
    return base


def make_groups_item(
    year: int = 2026,
    version: int = 1,
    groups: Any = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a fake DynamoDB BudgetConfig groups item.

    Defaults to `DEFAULT_GROUPS` from budget_service so tests stay in sync with
    the canonical grouping the app ships with. Matches the shape written by
    BudgetService.put_groups().
    """
    if groups is None:
        # Local import avoids a top-level circular risk with factory users that
        # stub the budget service module.
        from src.finance.budget_service import DEFAULT_GROUPS

        groups = DEFAULT_GROUPS

    base = {
        "PK": DEFAULT_USER_PK,
        "SK": f"BUDGET#groups#{year}",
        "Data": {"groups": groups},
        "Version": version,
        "UpdatedAt": f"{year}-01-01",
    }
    base.update(overrides)
    return base


def make_stmt_txn(
    date: str,
    amount: float,
    txn_type: str,
    description: str = "Test",
) -> dict[str, Any]:
    """Build a statement transaction dict for reconciliation testing."""
    return {
        "date": date,
        "description": description,
        "amount": amount,
        "type": txn_type,
        "balance": None,
    }
