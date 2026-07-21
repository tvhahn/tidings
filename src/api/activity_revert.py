"""Activity-ledger revert dispatch (Phase 4).

The write-capture seam (:mod:`src.api.activity`) journals every mutating request
with a before/after image (L5). This module is the inverse: a dispatch table that
maps an entry's ``operation_id`` to a function that *undoes* it by re-applying the
recorded ``before`` image through the **same service methods** the original
handler used — never a raw SQL / DynamoDB write.

Every revert function follows the same three-step shape (locked decision L8):

1. **Re-read** the resource's current state.
2. **Stale guard** — subset-compare the entry's recorded ``after`` image against
   current state *on the after image's keys only*. If they diverge, someone (the
   user, another agent) has touched the resource since the entry was written, so
   the revert raises ``409 stale_revert`` rather than clobbering the newer edit.
   ``force=True`` overrides the check. A delete-shaped ``after`` (``None``) is
   stale when the resource exists again; a create-shaped ``before`` (``{}``)
   reverts to a delete. Bulk compares per-row and reports every stale ``tx_id``.
3. **Apply** the ``before`` image via the original service methods.

Services are injected from the router (so FastAPI ``dependency_overrides`` reach
the revert path in tests) as a :class:`RevertServices` bundle. The dispatch
functions are synchronous and the router calls them directly — cheap single-user
config reads/writes, matching this router's deliberate no-``run_sync`` convention.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.api.activity import REVERTIBLE_OPERATIONS
from src.api.errors import ApiException
from src.finance.tx_id import composite_from_tx_id

if TYPE_CHECKING:
    from src.finance.protocols import (
        IBudgetService,
        IMerchantAliasService,
        IOverrideService,
        ITransactionsDB,
    )


@dataclass(frozen=True)
class RevertServices:
    """The service singletons a revert function may need, injected by the router.

    Bundling them (rather than having each revert function call the dependency
    getters directly) keeps FastAPI ``dependency_overrides`` effective on the
    revert path — the same fakes/real backends the write used are the ones the
    revert applies against.
    """

    transactions_db: ITransactionsDB
    override_service: IOverrideService
    merchant_alias_service: IMerchantAliasService
    budget_service: IBudgetService


# A revert function: (entry, services, force) -> short result summary.
RevertFn = Callable[[dict[str, Any], RevertServices, bool], str]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_images(entry: dict[str, Any]) -> tuple[Any, Any]:
    """Parse an entry's stored ``before_json`` / ``after_json`` back to objects.

    ``before`` is ``None`` only when nothing was staged (never for a reversible
    entry); ``after`` is ``None`` for a delete-shaped image.
    """
    before_json = entry.get("before_json")
    after_json = entry.get("after_json")
    before = json.loads(before_json) if before_json else None
    after = json.loads(after_json) if after_json else None
    return before, after


def _norm(value: Any) -> Any:
    """Normalize a value for cross-source equality (JSON image vs live service).

    ``Decimal`` (from a DynamoDB-shaped read) and ``float`` (from a JSON image)
    must compare equal, so both collapse to ``float`` — and *recursively*, because
    a stored service document nests Decimals inside dicts/lists (e.g. a budget
    ``Data`` map produced by ``_floats_to_decimals``) while its JSON after-image
    nests plain floats. Without recursing, a stale guard comparing a nested-Decimal
    current state against a float after-image would spuriously 409 on an unchanged
    config for any non-integer amount. Equality stays exact (no tolerance):
    Decimal→float is lossless for the values these images carry.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _norm(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(item) for item in value]
    return value


def _matches(after: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether ``current`` matches ``after`` on every key present in ``after``."""
    return all(_norm(current.get(key)) == _norm(value) for key, value in after.items())


def _stale(message: str, *, stale_tx_ids: list[str] | None = None) -> ApiException:
    """A ``409 stale_revert`` — the resource changed since the entry was written."""
    details = {"stale_tx_ids": stale_tx_ids} if stale_tx_ids is not None else None
    return ApiException(status_code=409, code="stale_revert", message=message, details=details)


def _pop_year(before: dict[str, Any], after: dict[str, Any] | None) -> int:
    """Extract the target year a budget/groups entry addresses.

    The handlers stamp ``year`` into both images (it is the storage key — a query
    param, absent from the path). It is an address, not state, so it is *popped*
    here: the stale guard and the re-put must only see the document fields.
    """
    year = (after or {}).pop("year", None)
    if year is None:
        year = before.pop("year", None)
    else:
        before.pop("year", None)
    try:
        return int(year)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ApiException(
            status_code=409,
            code="stale_revert",
            message="cannot revert: target year is not recoverable from the entry",
        ) from exc


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def revert_patch_transaction(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Restore category / ignored / trashed state from a ``patchTransaction`` entry.

    The ``before`` and ``after`` images carry the PascalCase reversible core
    (``Category``, ``Ignored``, ``DeletedAt``); only the fields that actually
    changed are re-applied, each through the handler's own service method.
    """
    before, after = _parse_images(entry)
    forwarded_to, date_file_name = composite_from_tx_id(entry["resource_id"])
    db = services.transactions_db

    current = db.get_item(forwarded_to, date_file_name)
    if current is None:
        raise _stale("cannot revert: the transaction no longer exists")
    if not force:
        current_proj = {
            "Category": current.get("Category"),
            "Ignored": current.get("Ignored"),
            "DeletedAt": current.get("DeletedAt"),
        }
        if not _matches(after, current_proj):
            raise _stale("cannot revert: the transaction changed since this entry")

    changed: list[str] = []
    if _norm(before.get("Category")) != _norm(after.get("Category")):
        # Restoring a category that was previously unset would require clearing it
        # to null, which ``update_category`` cannot express (its ``new_category``
        # is typed non-null). Refuse honestly rather than silently leaving the
        # newer value. Checked before any mutation below, so no partial apply.
        if before.get("Category") is None:
            raise ApiException(
                status_code=409,
                code="revert_unsupported",
                message="cannot revert: the prior state had no category, which cannot be restored",
            )
        db.update_category(forwarded_to, date_file_name, before["Category"], "manual")
        changed.append("category")
    if bool(before.get("Ignored")) != bool(after.get("Ignored")):
        db.set_ignored(forwarded_to, date_file_name, bool(before.get("Ignored")))
        changed.append("ignored")
    if (before.get("DeletedAt") is not None) != (after.get("DeletedAt") is not None):
        db.set_deleted(forwarded_to, date_file_name, before.get("DeletedAt") is not None)
        changed.append("trashed")

    return f"restored transaction ({', '.join(changed)})" if changed else "restored transaction"


def revert_set_transaction_comment(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Restore the previous comment from a ``setTransactionComment`` entry."""
    before, after = _parse_images(entry)
    forwarded_to, date_file_name = composite_from_tx_id(entry["resource_id"])
    db = services.transactions_db

    current = db.get_item(forwarded_to, date_file_name)
    if current is None:
        raise _stale("cannot revert: the transaction no longer exists")
    if not force and not _matches(after, {"comment": current.get("Comment")}):
        raise _stale("cannot revert: the comment changed since this entry")

    db.set_comment(forwarded_to, date_file_name, before.get("comment"))
    return "restored transaction comment"


def revert_update_transaction_fields(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Restore company / amount / transaction_type / category from an update entry."""
    before, after = _parse_images(entry)
    forwarded_to, date_file_name = composite_from_tx_id(entry["resource_id"])
    db = services.transactions_db

    current = db.get_item(forwarded_to, date_file_name)
    if current is None:
        raise _stale("cannot revert: the transaction no longer exists")
    if not force:
        current_proj = {
            "company": current.get("Company"),
            "amount": current.get("Amount"),
            "transaction_type": current.get("TransactionType"),
            "category": current.get("Category"),
        }
        if not _matches(after, current_proj):
            raise _stale("cannot revert: the transaction fields changed since this entry")

    # Refuse honestly if restoring any changed axis would require clearing it to
    # null — ``update_fields`` takes typed non-null values (and a ``None``
    # category means "leave unchanged"), so it cannot clear a populated field.
    # Check ALL axes first, before any mutation, so a 409 never partially applies.
    for axis in ("company", "amount", "transaction_type", "category"):
        if _norm(before.get(axis)) != _norm(after.get(axis)) and before.get(axis) is None:
            raise ApiException(
                status_code=409,
                code="revert_unsupported",
                message=f"cannot revert: the prior state had no {axis}, which cannot be restored",
            )

    fields: dict[str, Any] = {}
    if before.get("company") is not None:
        fields["company"] = before["company"]
    if before.get("amount") is not None:
        fields["amount"] = before["amount"]
    if before.get("transaction_type") is not None:
        fields["transaction_type"] = before["transaction_type"]
    db.update_fields(forwarded_to, date_file_name, fields, before.get("category"))
    return "restored transaction fields"


def revert_bulk_update_category(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Restore each row's prior category from a ``bulkUpdateTransactionCategory`` entry.

    The images are the minimal per-row projection ``{tx_id, category,
    category_source}``. The stale guard compares each row's current category and
    source against its recorded ``after`` row and reports every diverging
    ``tx_id``; the revert is all-or-nothing (409 if any row is stale).
    """
    before, after = _parse_images(entry)
    db = services.transactions_db
    before_rows: list[dict[str, Any]] = before.get("rows", [])
    after_rows: list[dict[str, Any]] = after.get("rows", [])

    if not force:
        stale_ids: list[str] = []
        for row in after_rows:
            tx_id = row["tx_id"]
            forwarded_to, date_file_name = composite_from_tx_id(tx_id)
            current = db.get_item(forwarded_to, date_file_name)
            current_cat = current.get("Category") if current else None
            current_src = (current.get("CategoryAudit") or {}).get("source") if current else None
            if _norm(current_cat) != _norm(row.get("category")) or _norm(current_src) != _norm(
                row.get("category_source")
            ):
                stale_ids.append(tx_id)
        if stale_ids:
            raise _stale(
                f"cannot revert: {len(stale_ids)} transaction(s) changed since this entry",
                stale_tx_ids=stale_ids,
            )

    restored = 0
    for row in before_rows:
        category = row.get("category")
        if category is None:
            # The row was uncategorized before — no category to restore to.
            continue
        forwarded_to, date_file_name = composite_from_tx_id(row["tx_id"])
        db.update_category(forwarded_to, date_file_name, category, row.get("category_source") or "manual")
        restored += 1
    return f"restored {restored} transaction categor{'y' if restored == 1 else 'ies'}"


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def revert_put_override(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Undo a ``putOverride``: delete a created override, or restore the prior one."""
    before, after = _parse_images(entry)
    svc = services.override_service
    company = after["company"]

    current = _data_map(svc.get_overrides())
    current_category = current.get(company)
    if not force and _norm(current_category) != _norm(after.get("category")):
        raise _stale("cannot revert: the override changed since this entry")

    if before:
        # Updated an existing override — restore the prior category.
        svc.put_override(company, before["category"])
        return f"restored category override for {company}"
    # Created a new override — delete it.
    with contextlib.suppress(KeyError):
        svc.delete_override(company)
    return f"removed category override for {company}"


def revert_delete_override(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Undo a ``deleteOverride``: re-create the override from the before image."""
    before, _after = _parse_images(entry)
    svc = services.override_service
    company = before["company"]

    current = _data_map(svc.get_overrides())
    if not force and company in current:
        raise _stale("cannot revert: the override was re-created since this entry")

    svc.put_override(company, before["category"])
    return f"restored category override for {company}"


# ---------------------------------------------------------------------------
# Merchant aliases
# ---------------------------------------------------------------------------


def revert_put_merchant_alias(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Undo a ``putMerchantAlias``: delete a created alias, or restore the prior one."""
    before, after = _parse_images(entry)
    svc = services.merchant_alias_service
    raw_name = after["raw_name"]

    current = _data_map(svc.get_aliases())
    current_canonical = current.get(raw_name)
    if not force and _norm(current_canonical) != _norm(after.get("canonical_name")):
        raise _stale("cannot revert: the merchant alias changed since this entry")

    if before:
        svc.put_alias(raw_name, before["canonical_name"])
        return f"restored merchant alias for {raw_name}"
    with contextlib.suppress(KeyError):
        svc.delete_alias(raw_name)
    return f"removed merchant alias for {raw_name}"


def revert_delete_merchant_alias(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Undo a ``deleteMerchantAlias``: re-create the alias from the before image."""
    before, _after = _parse_images(entry)
    svc = services.merchant_alias_service
    raw_name = before["raw_name"]

    current = _data_map(svc.get_aliases())
    if not force and raw_name in current:
        raise _stale("cannot revert: the merchant alias was re-created since this entry")

    svc.put_alias(raw_name, before["canonical_name"])
    return f"restored merchant alias for {raw_name}"


# ---------------------------------------------------------------------------
# Budget + groups
# ---------------------------------------------------------------------------


def revert_put_budget_config(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Undo a ``putBudgetConfig``: re-put the prior targets + groups documents.

    The re-put passes the *current* stored version as ``expected_version`` — the
    row still exists (put updates, never deletes), so an overwrite conditioned on
    that version is the way to restore the before document.
    """
    before, after = _parse_images(entry)
    svc = services.budget_service
    year = _pop_year(before, after)

    targets_item = svc.get_targets(year)
    groups_item = svc.get_groups(year)
    if not force:
        current: dict[str, Any] = {}
        if targets_item is not None:
            current["targets"] = targets_item.get("Data")
        if groups_item is not None:
            current["groups"] = groups_item.get("Data")
        if not _matches(after or {}, current):
            raise _stale("cannot revert: the budget config changed since this entry")

    if "targets" in before:
        svc.put_targets(year, before["targets"], targets_item["Version"] if targets_item else None)
    if "groups" in before:
        svc.put_groups(year, before["groups"], groups_item["Version"] if groups_item else None)
    return f"restored budget config for {year}"


def revert_put_groups(entry: dict[str, Any], services: RevertServices, force: bool) -> str:
    """Undo a ``putGroups``: re-put the prior groups document for the year."""
    before, after = _parse_images(entry)
    svc = services.budget_service
    year = _pop_year(before, after)

    groups_item = svc.get_groups(year)
    if not force:
        current = {"groups": groups_item.get("Data")} if groups_item is not None else {}
        if not _matches(after or {}, current):
            raise _stale("cannot revert: the category groups changed since this entry")

    if "groups" in before:
        svc.put_groups(year, before["groups"], groups_item["Version"] if groups_item else None)
    return f"restored category groups for {year}"


def _data_map(item: dict[str, Any] | None) -> dict[str, Any]:
    """Return the ``Data`` map of a config item, or an empty map when absent.

    Override / alias services return ``{"Data": {...}, "Version": n}`` or ``None``
    when nothing has been written yet; the revert functions only care about the
    current ``company → category`` / ``raw → canonical`` map.
    """
    return dict(item.get("Data", {})) if item else {}


# ---------------------------------------------------------------------------
# Dispatch table — exactly the ten instrumented operations (L5/L8)
# ---------------------------------------------------------------------------

REVERT_DISPATCH: dict[str, RevertFn] = {
    "patchTransaction": revert_patch_transaction,
    "setTransactionComment": revert_set_transaction_comment,
    "updateTransactionFields": revert_update_transaction_fields,
    "bulkUpdateTransactionCategory": revert_bulk_update_category,
    "putOverride": revert_put_override,
    "deleteOverride": revert_delete_override,
    "putMerchantAlias": revert_put_merchant_alias,
    "deleteMerchantAlias": revert_delete_merchant_alias,
    "putBudgetConfig": revert_put_budget_config,
    "putGroups": revert_put_groups,
}

# The dispatch table and the capture seam's reversible-marking must never drift:
# an op marked reversible without a revert fn is a dead button; a revert fn for an
# op never marked reversible is unreachable.
assert set(REVERT_DISPATCH) == set(REVERTIBLE_OPERATIONS)  # noqa: S101 — import-time contract check
