"""Snapshot test for OpenAPI ``operationId`` stability.

FastAPI auto-derives an ``operationId`` from each handler's function name
when one is not set explicitly. Renaming any handler silently changes its
``operationId``, breaking every downstream agent integration that pins to
the value (`make verify-openapi` notices a *schema* diff but reports it as
"valid" if the only change is a string rename).

This snapshot test pins the full set of ``operationId``s in
``snapshots/operation_ids.txt``. Adding, removing, or renaming an
``operationId`` produces a clear diff against the snapshot — the test
fails and the developer must consciously update the file.

To regenerate the snapshot after an intentional change:

    make openapi
    uv run python -c "
    import json
    schema = json.load(open('openapi.json'))
    ops = sorted(
        op['operationId']
        for path in schema['paths'].values()
        for op in path.values()
        if isinstance(op, dict) and 'operationId' in op
    )
    print(*ops, sep='\\n')
    " > tests/api/snapshots/operation_ids.txt
"""

from __future__ import annotations

from pathlib import Path

from src.api.main import create_app

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "operation_ids.txt"


def _live_operation_ids() -> list[str]:
    schema = create_app().openapi()
    return sorted(
        op["operationId"]
        for path in schema["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    )


def test_every_in_schema_route_has_an_operation_id() -> None:
    """Catch the regression where a new route forgets to set ``operation_id=``.

    FastAPI auto-derives an id from the handler function name when missing —
    those derivations contain underscores + the path + the HTTP verb (e.g.
    ``list_categories_api_v1_categories_get``). A real, hand-written id never
    has the ``_api_v1_`` substring; flag any that do.
    """
    auto_derived = [op for op in _live_operation_ids() if "_api_v1_" in op]
    assert not auto_derived, (
        f"Routes missing explicit operation_id (FastAPI auto-derived): {auto_derived}. "
        "Add operation_id='someCamelCaseName' to the @router decorator."
    )


def test_operation_ids_match_snapshot() -> None:
    """Fail loudly when an ``operationId`` is added, removed, or renamed.

    The diff in the failure message is the manual review surface: every
    change to this set is a contract change for downstream consumers and
    deserves a deliberate snapshot update.
    """
    actual = _live_operation_ids()
    expected = SNAPSHOT_PATH.read_text().splitlines()

    actual_set = set(actual)
    expected_set = set(expected)
    added = sorted(actual_set - expected_set)
    removed = sorted(expected_set - actual_set)

    assert actual == expected, (
        "operationId set changed; review and regenerate "
        f"{SNAPSHOT_PATH.relative_to(Path.cwd()) if SNAPSHOT_PATH.is_relative_to(Path.cwd()) else SNAPSHOT_PATH}.\n"
        f"  added:   {added}\n"
        f"  removed: {removed}\n"
    )
