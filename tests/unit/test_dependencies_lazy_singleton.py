"""Regression tests for the lazy StatementStore singleton in src.api.dependencies.

The singleton must not be eagerly constructed at module import, because
StatementStore.__init__ raises when PYTEST_CURRENT_TEST is set and the path
defaults to data/statements.db — which would fire before any conftest fixture
could redirect it to a tmp path.
"""

import importlib

import src.api.dependencies as deps


def test_statement_store_is_lazy_until_first_access(monkeypatch):
    """Reloading the module under pytest must not construct StatementStore."""
    monkeypatch.setattr(deps, "_statement_store", None)
    reloaded = importlib.reload(deps)
    assert reloaded._statement_store is None


def test_get_statement_store_constructs_on_first_call(monkeypatch, tmp_path):
    """First call to get_statement_store() constructs; subsequent calls memoize."""
    from src.finance.statement_store import StatementStore

    tmp_store = StatementStore(db_path=tmp_path / "statements.db")
    monkeypatch.setattr(deps, "_statement_store", tmp_store)
    assert deps.get_statement_store() is tmp_store
    assert deps.get_statement_store() is tmp_store
