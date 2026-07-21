"""Storage factory — reads app config and instantiates the right backend.

Usage:
    from src.finance.storage import create_transactions_db, create_spending_summary, ...
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.finance.app_config import get_config
from src.finance.aws_region import get_aws_region
from src.finance.protocols import (
    IActivityStore,
    IBudgetService,
    ICategoryIconService,
    ICategoryService,
    IIgnoreRuleService,
    IMerchantAliasService,
    IOverrideService,
    IParseFailureStore,
    ISpendingSummary,
    ITransactionsDB,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource

    from src.finance.transaction_context import TransactionContextEnricher

logger = logging.getLogger(__name__)

_DEMO_DB_PATH = Path("data/demo.db")
_FINANCE_DB_PATH = Path("data/finance.db")


def _is_demo() -> bool:
    """Return True when demo mode is active."""
    return bool(get_config().get("demo_mode"))


def _get_user_id() -> str:
    # USER_ID env var wins over data/config.json so Lambda (which doesn't ship
    # the personal config file) can resolve the right user without a config sync.
    env_uid = os.environ.get("USER_ID")
    if env_uid:
        return env_uid
    config = get_config()
    return config.get("user_id", "default")


def _create_service(
    dynamo_factory: Callable[[], Any],
    local_cls: type[Any],
    *,
    local_kwargs: dict[str, Any] | None = None,
    dynamo_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Generic factory: pick DynamoDB or SQLite implementation based on config.

    Parameters
    ----------
    dynamo_factory : callable
        A zero-arg callable that returns the DynamoDB service instance.
        Wrapped in a callable so boto3 import is deferred.
    local_cls : type
        The SQLite implementation class.
    local_kwargs : dict | None
        Extra keyword arguments for the local class (beyond db_path/user_id).
    dynamo_kwargs : dict | None
        Extra keyword arguments forwarded to dynamo_factory (unused today but
        kept for forward-compat).
    """
    if _is_demo():
        return local_cls(db_path=_DEMO_DB_PATH, user_id=_get_user_id(), **(local_kwargs or {}))

    config = get_config()
    if config.get("storage") == "dynamodb":
        return dynamo_factory()
    return local_cls(db_path=_FINANCE_DB_PATH, user_id=_get_user_id(), **(local_kwargs or {}))


def _dynamo_resource() -> "DynamoDBServiceResource":
    import boto3

    return boto3.resource("dynamodb", region_name=get_aws_region())


# ---------------------------------------------------------------------------
# Public factory functions
# ---------------------------------------------------------------------------


def create_transactions_db() -> ITransactionsDB:
    """Create a TransactionsDB (DynamoDB) or TransactionsDBLocal (SQLite)."""
    if _is_demo():
        from src.finance.transaction_db_local import TransactionsDBLocal

        return TransactionsDBLocal(db_path=_DEMO_DB_PATH)

    config = get_config()
    if config.get("storage") == "dynamodb":
        from src.finance.transaction_db import TransactionsDB

        return TransactionsDB(_dynamo_resource())
    from src.finance.transaction_db_local import TransactionsDBLocal

    return TransactionsDBLocal(db_path=_FINANCE_DB_PATH)


def create_spending_summary() -> ISpendingSummary:
    """Create a SpendingSummary (DynamoDB) or SpendingSummaryLocal (SQLite)."""
    if _is_demo():
        from src.finance.spending_summary_local import SpendingSummaryLocal

        return SpendingSummaryLocal(db_path=_DEMO_DB_PATH)

    config = get_config()
    if config.get("storage") == "dynamodb":
        from src.finance.spending_summary import SpendingSummary

        return SpendingSummary(dyn_resource=_dynamo_resource())
    from src.finance.spending_summary_local import SpendingSummaryLocal

    return SpendingSummaryLocal(db_path=_FINANCE_DB_PATH)


def create_budget_service() -> IBudgetService:
    """Create a BudgetService (DynamoDB) or BudgetServiceLocal (SQLite)."""

    def _dynamo():
        from src.finance.budget_service import BudgetService

        return BudgetService(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.budget_service_local import BudgetServiceLocal

    return _create_service(_dynamo, BudgetServiceLocal)


def create_override_service() -> IOverrideService:
    """Create an OverrideService (DynamoDB) or OverrideServiceLocal (SQLite)."""

    def _dynamo():
        from src.finance.override_service import OverrideService

        return OverrideService(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.override_service_local import OverrideServiceLocal

    return _create_service(_dynamo, OverrideServiceLocal)


def create_ignore_rule_service() -> IIgnoreRuleService:
    """Create an IgnoreRuleService (DynamoDB) or IgnoreRuleServiceLocal (SQLite)."""

    def _dynamo():
        from src.finance.ignore_rule_service import IgnoreRuleService

        return IgnoreRuleService(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.ignore_rule_service_local import IgnoreRuleServiceLocal

    return _create_service(_dynamo, IgnoreRuleServiceLocal)


def create_category_service() -> ICategoryService:
    """Create a CategoryService (DynamoDB) or CategoryServiceLocal (SQLite)."""

    def _dynamo():
        from src.finance.category_service import CategoryService

        return CategoryService(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.category_service_local import CategoryServiceLocal

    return _create_service(_dynamo, CategoryServiceLocal)


def create_merchant_alias_service() -> IMerchantAliasService:
    """Create a MerchantAliasService (DynamoDB) or MerchantAliasServiceLocal (SQLite)."""

    def _dynamo():
        from src.finance.merchant_alias_service import MerchantAliasService

        return MerchantAliasService(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.merchant_alias_service_local import MerchantAliasServiceLocal

    return _create_service(_dynamo, MerchantAliasServiceLocal)


def create_parse_failure_store() -> IParseFailureStore:
    """Create a ParseFailureStore (DynamoDB) or ParseFailureStoreLocal (SQLite)."""

    def _dynamo():
        from src.finance.parse_failure_store import ParseFailureStore

        return ParseFailureStore(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.parse_failure_store_local import ParseFailureStoreLocal

    return _create_service(_dynamo, ParseFailureStoreLocal)


def create_activity_store() -> IActivityStore:
    """Create an ActivityStore (DynamoDB) or ActivityStoreLocal (SQLite)."""

    def _dynamo():
        from src.finance.activity_store import ActivityStore

        return ActivityStore(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.activity_store_local import ActivityStoreLocal

    return _create_service(_dynamo, ActivityStoreLocal)


def create_category_icon_service() -> ICategoryIconService:
    """Create a CategoryIconService (DynamoDB) or CategoryIconServiceLocal (SQLite)."""

    def _dynamo():
        from src.finance.category_icon_service import CategoryIconService

        return CategoryIconService(dyn_resource=_dynamo_resource(), user_id=_get_user_id())

    from src.finance.category_icon_service_local import CategoryIconServiceLocal

    return _create_service(_dynamo, CategoryIconServiceLocal)


def create_transaction_context_enricher() -> "TransactionContextEnricher":
    """Create a TransactionContextEnricher backed by the configured storage."""
    from src.finance.transaction_context import TransactionContextEnricher

    transactions_db = create_transactions_db()
    budget_service = create_budget_service()
    return TransactionContextEnricher(transactions_db, budget_service)
