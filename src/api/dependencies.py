"""Shared singletons and async helpers for the FastAPI backend."""

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from dotenv import load_dotenv
from fastapi import HTTPException

from src.finance.attachment_store import AttachmentStore
from src.finance.coverage_service import CoverageService
from src.finance.embedding_cache import EmbeddingCache
from src.finance.forecast_service import ForecastService
from src.finance.merchant_intelligence import MerchantIntelligenceService
from src.finance.openai_client import OpenAIClient
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
from src.finance.statement_store import StatementStore
from src.finance.storage import (
    create_activity_store,
    create_budget_service,
    create_category_icon_service,
    create_category_service,
    create_ignore_rule_service,
    create_merchant_alias_service,
    create_override_service,
    create_parse_failure_store,
    create_spending_summary,
    create_transactions_db,
)
from src.finance.tax_override_store import TaxOverrideStore
from src.finance.upcoming_service import UpcomingService

load_dotenv()

_transactions_db = create_transactions_db()
_spending_summary = create_spending_summary()
_budget_service = create_budget_service()
_override_service = create_override_service()
_ignore_rule_service = create_ignore_rule_service()
_category_service = create_category_service()
_merchant_alias_service = create_merchant_alias_service()
_category_icon_service = create_category_icon_service()
_parse_failure_store = create_parse_failure_store()
_activity_store = create_activity_store()
_merchant_intelligence_service = MerchantIntelligenceService(_spending_summary, _merchant_alias_service)
_upcoming_service = UpcomingService(_spending_summary, _merchant_alias_service)
_forecast_service = ForecastService()
_statement_store: StatementStore | None = None
# Lazy like _statement_store: the coverage service holds a reference to the live
# StatementStore, which is itself lazily built against the demo/real DB path, so
# it must be constructed on first use (and reset on mode toggle) — not eagerly.
_coverage_service: CoverageService | None = None
_attachment_store: AttachmentStore | None = None
_tax_override_store: TaxOverrideStore | None = None
_embedding_cache = EmbeddingCache()

_openai_api_key = os.environ.get("OPENAI_API_KEY")
_openai_client: OpenAIClient | None = None
if _openai_api_key:
    _openai_client = OpenAIClient(model="text-embedding-3-small", api_key=_openai_api_key)

_executor = ThreadPoolExecutor(max_workers=12)


def reinitialize_services() -> None:
    """Re-create all storage-backed singletons (e.g. after demo_mode toggle)."""
    global _transactions_db, _spending_summary, _budget_service
    global _override_service, _ignore_rule_service, _category_service, _merchant_alias_service
    global _category_icon_service, _parse_failure_store, _merchant_intelligence_service
    global _upcoming_service, _forecast_service, _statement_store, _attachment_store, _tax_override_store
    global _coverage_service, _activity_store
    _statement_store = None  # lazily re-created against the right DB for the new mode
    _coverage_service = None  # depends on the statement store — reset so it rebinds
    _attachment_store = None  # same lazy-reset move as the statement store
    _tax_override_store = None  # same lazy-reset move as the attachment store
    _transactions_db = create_transactions_db()
    _spending_summary = create_spending_summary()
    _budget_service = create_budget_service()
    _override_service = create_override_service()
    _ignore_rule_service = create_ignore_rule_service()
    _category_service = create_category_service()
    _merchant_alias_service = create_merchant_alias_service()
    _category_icon_service = create_category_icon_service()
    _parse_failure_store = create_parse_failure_store()
    _activity_store = create_activity_store()
    _merchant_intelligence_service = MerchantIntelligenceService(_spending_summary, _merchant_alias_service)
    _upcoming_service = UpcomingService(_spending_summary, _merchant_alias_service)
    _forecast_service = ForecastService()


async def run_sync[T](func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous function in a thread pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))


def ensure_not_demo(detail: str) -> None:
    """Reject a write request when running in demo mode (403).

    The single demo-mode gate for write endpoints that mutate the host's real
    data/repo tree (backup import/export, fixture writes). Each caller supplies
    its own ``detail`` so the user-facing wording stays endpoint-specific. Looks
    up config through the module so tests can monkeypatch ``app_config.get_config``.
    """
    from src.finance import app_config

    if app_config.get_config().get("demo_mode", False):
        raise HTTPException(status_code=403, detail=detail)


def get_transactions_db() -> ITransactionsDB:
    return _transactions_db


def get_spending_summary() -> ISpendingSummary:
    return _spending_summary


def get_budget_service() -> IBudgetService:
    return _budget_service


def get_override_service() -> IOverrideService:
    return _override_service


def get_ignore_rule_service() -> IIgnoreRuleService:
    return _ignore_rule_service


def get_category_service() -> ICategoryService:
    return _category_service


def get_statement_store() -> StatementStore:
    global _statement_store
    if _statement_store is None:
        from src.finance.app_config import get_config
        from src.finance.demo_loader import DEMO_STATEMENTS_DB_PATH

        if get_config().get("demo_mode"):
            # Demo mode must never read (or write) the host's real statement
            # history — it gets its own seeded database.
            _statement_store = StatementStore(DEMO_STATEMENTS_DB_PATH)
        else:
            _statement_store = StatementStore()
    return _statement_store


def get_attachment_store() -> AttachmentStore:
    global _attachment_store
    if _attachment_store is None:
        from src.finance.app_config import get_config
        from src.finance.demo_loader import DEMO_ATTACHMENTS_DB_PATH

        if get_config().get("demo_mode"):
            # Demo mode must never read (or write) the host's real attachments —
            # it gets its own (unseeded, empty) database.
            _attachment_store = AttachmentStore(DEMO_ATTACHMENTS_DB_PATH)
        else:
            _attachment_store = AttachmentStore()
    return _attachment_store


def get_tax_override_store() -> TaxOverrideStore:
    global _tax_override_store
    if _tax_override_store is None:
        from src.finance.app_config import get_config
        from src.finance.demo_loader import DEMO_TAX_OVERRIDES_DB_PATH

        if get_config().get("demo_mode"):
            # Demo mode must never read (or write) the host's real overrides —
            # it gets its own (unseeded, empty) database.
            _tax_override_store = TaxOverrideStore(DEMO_TAX_OVERRIDES_DB_PATH)
        else:
            _tax_override_store = TaxOverrideStore()
    return _tax_override_store


def get_openai_client() -> OpenAIClient | None:
    return _openai_client


def get_merchant_alias_service() -> IMerchantAliasService:
    return _merchant_alias_service


def get_category_icon_service() -> ICategoryIconService:
    return _category_icon_service


def get_parse_failure_store() -> IParseFailureStore:
    return _parse_failure_store


def get_activity_store() -> IActivityStore:
    return _activity_store


def get_embedding_cache() -> EmbeddingCache:
    return _embedding_cache


def get_merchant_intelligence_service() -> MerchantIntelligenceService:
    return _merchant_intelligence_service


def get_coverage_service() -> CoverageService:
    """Return the module-level coverage service, built lazily on first use.

    Wires the live spending-summary + parse-failure singletons and reuses the
    same lazily-constructed ``StatementStore`` instance as every other consumer
    (via ``get_statement_store()``), so demo/real path selection and the
    ``reinitialize_services()`` mode toggle both flow through unchanged.
    """
    global _coverage_service
    if _coverage_service is None:
        _coverage_service = CoverageService(
            _spending_summary,
            _parse_failure_store,
            get_statement_store(),
        )
    return _coverage_service


def get_forecast_service() -> ForecastService:
    return _forecast_service


def get_upcoming_service() -> UpcomingService:
    return _upcoming_service


def shutdown_executor() -> None:
    _executor.shutdown(wait=False)
