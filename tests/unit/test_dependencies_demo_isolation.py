"""Demo-isolation coverage for the lazy storage getters in src.api.dependencies.

The three lazy singletons (`get_statement_store`, `get_attachment_store`,
`get_tax_override_store`) carry a safety-critical rule: under `demo_mode` they
must build against the seeded ``DEMO_*_DB_PATH`` databases and never read or
write the host's real statement / attachment / override history. These tests
pin each getter to the demo DB under demo config and to the real DB otherwise,
and cover `reinitialize_services()` rebuilding the singletons after a mode flip.

Design notes:
- Config is read via ``src.finance.app_config.get_config`` imported at call time
  inside each getter, and the autouse ``_isolate_app_config_auth`` fixture pins
  ``app_config._cache``. We cooperate by copying that resolved config and
  overriding only ``demo_mode`` / ``storage`` on a fresh ``_cache`` dict.
- The ``DEMO_*_DB_PATH`` constants point at the real ``data/`` tree, so every
  test monkeypatches them (and the store ``DB_PATH`` class attrs) to ``tmp_path``
  — nothing here may touch the repo's real ``data/``.
- The stores' ``__init__`` refuses their default ``DB_PATH`` under
  ``PYTEST_CURRENT_TEST``; the non-demo tests point ``DB_PATH`` at a tmp file and
  drop that env var (monkeypatch restores it) so the real-path branch runs
  against a throwaway DB instead of raising.
- Singleton restoration: every module global these tests mutate is pre-registered
  with ``monkeypatch.setattr(deps, name, <current value>)`` before the mutation,
  so monkeypatch's teardown unconditionally restores the pre-test object — no
  sibling test inherits a store pointed at a deleted tmp DB.
"""

import src.api.dependencies as deps
from src.finance.attachment_store import AttachmentStore
from src.finance.statement_store import StatementStore
from src.finance.tax_override_store import TaxOverrideStore

# Every global reinitialize_services() reassigns (mirrors its `global` decls).
_REINIT_GLOBALS = (
    "_transactions_db",
    "_spending_summary",
    "_budget_service",
    "_override_service",
    "_ignore_rule_service",
    "_category_service",
    "_merchant_alias_service",
    "_category_icon_service",
    "_parse_failure_store",
    "_merchant_intelligence_service",
    "_forecast_service",
    "_statement_store",
    "_attachment_store",
    "_tax_override_store",
)


def _pin_config(monkeypatch, **overrides):
    """Copy the autouse-pinned resolved config and override chosen keys on _cache."""
    from src.finance import app_config

    cfg = dict(app_config.get_config())
    cfg.update(overrides)
    monkeypatch.setattr(app_config, "_cache", cfg)


# --- statement store ---------------------------------------------------------


def test_get_statement_store_uses_demo_db_in_demo_mode(monkeypatch, tmp_path):
    from src.finance import demo_loader

    demo_db = tmp_path / "demo-statements.db"
    monkeypatch.setattr(demo_loader, "DEMO_STATEMENTS_DB_PATH", demo_db)
    _pin_config(monkeypatch, demo_mode=True)
    monkeypatch.setattr(deps, "_statement_store", None)

    store = deps.get_statement_store()

    assert store._db_path == demo_db


def test_get_statement_store_uses_real_db_when_not_demo(monkeypatch, tmp_path):
    from src.finance import demo_loader

    real_db = tmp_path / "statements.db"
    demo_db = tmp_path / "demo-statements.db"
    monkeypatch.setattr(StatementStore, "DB_PATH", real_db)
    monkeypatch.setattr(demo_loader, "DEMO_STATEMENTS_DB_PATH", demo_db)
    _pin_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(deps, "_statement_store", None)
    # The default-path guard fires under pytest; drop the sentinel so the
    # real-path branch builds against the tmp DB_PATH instead of raising.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    store = deps.get_statement_store()

    assert store._db_path == real_db
    assert store._db_path != demo_db


# --- attachment store --------------------------------------------------------


def test_get_attachment_store_uses_demo_db_in_demo_mode(monkeypatch, tmp_path):
    from src.finance import demo_loader

    demo_db = tmp_path / "demo-attachments.db"
    monkeypatch.setattr(demo_loader, "DEMO_ATTACHMENTS_DB_PATH", demo_db)
    _pin_config(monkeypatch, demo_mode=True)
    monkeypatch.setattr(deps, "_attachment_store", None)

    store = deps.get_attachment_store()

    assert store._db_path == demo_db


def test_get_attachment_store_uses_real_db_when_not_demo(monkeypatch, tmp_path):
    from src.finance import demo_loader

    real_db = tmp_path / "attachments.db"
    demo_db = tmp_path / "demo-attachments.db"
    monkeypatch.setattr(AttachmentStore, "DB_PATH", real_db)
    monkeypatch.setattr(demo_loader, "DEMO_ATTACHMENTS_DB_PATH", demo_db)
    _pin_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(deps, "_attachment_store", None)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    store = deps.get_attachment_store()

    assert store._db_path == real_db
    assert store._db_path != demo_db


# --- tax override store ------------------------------------------------------


def test_get_tax_override_store_uses_demo_db_in_demo_mode(monkeypatch, tmp_path):
    from src.finance import demo_loader

    demo_db = tmp_path / "demo-tax-overrides.db"
    monkeypatch.setattr(demo_loader, "DEMO_TAX_OVERRIDES_DB_PATH", demo_db)
    _pin_config(monkeypatch, demo_mode=True)
    monkeypatch.setattr(deps, "_tax_override_store", None)

    store = deps.get_tax_override_store()

    assert store._db_path == demo_db


def test_get_tax_override_store_uses_real_db_when_not_demo(monkeypatch, tmp_path):
    from src.finance import demo_loader

    real_db = tmp_path / "tax_overrides.db"
    demo_db = tmp_path / "demo-tax-overrides.db"
    monkeypatch.setattr(TaxOverrideStore, "DB_PATH", real_db)
    monkeypatch.setattr(demo_loader, "DEMO_TAX_OVERRIDES_DB_PATH", demo_db)
    _pin_config(monkeypatch, demo_mode=False)
    monkeypatch.setattr(deps, "_tax_override_store", None)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    store = deps.get_tax_override_store()

    assert store._db_path == real_db
    assert store._db_path != demo_db


# --- reinitialize_services ---------------------------------------------------


def test_reinitialize_services_replaces_singletons(monkeypatch):
    """After a mode flip the storage singletons are new objects of the right
    backend type, and the three lazy stores are reset to None for re-creation."""
    from src.finance.spending_summary_local import SpendingSummaryLocal
    from src.finance.transaction_db_local import TransactionsDBLocal

    _pin_config(monkeypatch, storage="sqlite", demo_mode=False)
    # Pre-register every global reinitialize reassigns so its current object is
    # restored on teardown — otherwise a rebuilt store (pointed at this test's
    # tmp finance.db) would leak into sibling tests.
    for name in _REINIT_GLOBALS:
        monkeypatch.setattr(deps, name, getattr(deps, name))

    before_txns = deps.get_transactions_db()
    before_summary = deps.get_spending_summary()

    deps.reinitialize_services()

    after_txns = deps.get_transactions_db()
    after_summary = deps.get_spending_summary()

    assert after_txns is not before_txns
    assert after_summary is not before_summary
    assert isinstance(after_txns, TransactionsDBLocal)
    assert isinstance(after_summary, SpendingSummaryLocal)
    # Lazy stores are cleared so the next getter rebuilds against the new mode.
    assert deps._statement_store is None
    assert deps._attachment_store is None
    assert deps._tax_override_store is None
