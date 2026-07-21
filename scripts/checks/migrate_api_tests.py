"""One-shot codemod that migrates tests/unit/test_api_*.py to use the shared
helpers documented in docs/TESTS.md (Commit 2 of the /review-tests audit).

The script applies four mechanical substitutions:

1. Module-scope ``client = TestClient(app)`` is removed; tests that referenced
   ``client`` get an ``api_client`` parameter and uses are renamed
   ``client.<method>`` → ``api_client.<method>``.
2. ``assert resp.status_code == 2XX`` (optionally followed by an unused
   ``resp.json()``) is rewritten to ``assert_ok(resp)``; ``assert
   resp.status_code == 4XX/5XX`` becomes ``assert_problem(resp, <code>)``.
3. ``@patch("src.api.routers.<name>.run_sync", new_callable=AsyncMock)``
   decorators are swapped for ``@pytest.mark.parametrize("mock_run_sync",
   ["<name>"], indirect=True)`` — leveraging the existing fixture at
   ``tests/conftest.py:147``.
4. Imports for ``TestClient``, ``app``, ``AsyncMock``, ``patch`` are pruned
   when no longer used, and ``assert_ok`` / ``assert_problem`` /
   ``pytest`` imports are added when newly used.

Patterns the migrator deliberately leaves alone (judgment calls — the diff
flags them so they can be handled in follow-up):

- Per-file ``_make_*`` helpers that wrap factory output. These often encode
  domain-specific defaults (e.g. the $127K budget shape in test_api_budget.py)
  and aren't pure duplicates.
- ``test_api_data.py`` — already uses an explicit ``client`` fixture and an
  ``isolated_sqlite`` integration pattern; out of scope.
- Any file where a single test method patches ``run_sync`` from *multiple*
  routers in one go — the indirect-parametrize fixture only patches one
  router at a time.

Usage:

    uv run python scripts/checks/migrate_api_tests.py --check    # dry-run, exit 1 if changes pending
    uv run python scripts/checks/migrate_api_tests.py --apply    # write changes in place
    uv run python scripts/checks/migrate_api_tests.py --apply tests/unit/test_api_overrides.py  # one file

After applying, run ``uv run ruff format tests/`` and ``make verify-backend``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import libcst as cst
import libcst.matchers as m

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = REPO_ROOT / "tests" / "unit"
SKIP_FILES = {"test_api_data.py"}  # uses isolated_sqlite, out of scope


class FileMigrator(cst.CSTTransformer):
    """Per-file CST transformer. Stateful — one instance per file."""

    def __init__(self) -> None:
        super().__init__()
        self.removed_module_client = False
        self.uses_api_client = False
        self.uses_assert_ok = False
        self.uses_assert_problem = False
        self.added_indirect_parametrize = False
        # Runtime references that should remain after pruning.
        self.uses_TestClient = False  # noqa: N815
        self.uses_app = False
        self.uses_async_mock = False
        self.uses_patch = False

    # ------------------------------------------------------------------
    # Module-scope: drop `client = TestClient(app)`
    # ------------------------------------------------------------------
    def leave_Module(  # noqa: N802
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        new_body: list[cst.BaseStatement] = []
        for stmt in updated_node.body:
            if self._is_module_client_assignment(stmt):
                self.removed_module_client = True
                continue
            new_body.append(stmt)

        # Track which symbols are still referenced *after* removing the
        # module-scope client. We walk the post-transform tree to be safe.
        scanner = NameUsageScanner()
        cst.Module(body=new_body).visit(scanner)
        self.uses_TestClient = scanner.found_TestClient
        self.uses_app = scanner.found_app
        self.uses_async_mock = scanner.found_AsyncMock
        self.uses_patch = scanner.found_patch

        new_body = self._patch_imports(new_body)
        return updated_node.with_changes(body=new_body)

    @staticmethod
    def _is_module_client_assignment(stmt: cst.BaseStatement) -> bool:
        """Match top-level ``client = TestClient(app)``."""
        if not isinstance(stmt, cst.SimpleStatementLine):
            return False
        if len(stmt.body) != 1 or not isinstance(stmt.body[0], cst.Assign):
            return False
        assign = stmt.body[0]
        if len(assign.targets) != 1:
            return False
        target = assign.targets[0].target
        if not (isinstance(target, cst.Name) and target.value == "client"):
            return False
        return m.matches(
            assign.value,
            m.Call(func=m.Name("TestClient"), args=[m.Arg(value=m.Name("app"))]),
        )

    # ------------------------------------------------------------------
    # Function-level: swap @patch for parametrize, add api_client param
    # ------------------------------------------------------------------
    def leave_FunctionDef(  # noqa: N802
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        if not original_node.name.value.startswith("test_"):
            return updated_node

        # 1. decorator rewrite: @patch(...run_sync, new_callable=AsyncMock).
        # The patch decorator injects a `mock_run_sync` parameter; the
        # `mock_run_sync` indirect-parametrize fixture in tests/conftest.py
        # also yields a parameter of the same name, so the body and the
        # signature both stay as-is.
        new_decorators: list[cst.Decorator] = []
        run_sync_router: str | None = None
        for dec in updated_node.decorators:
            router = self._extract_run_sync_router(dec)
            if router is not None:
                if run_sync_router is not None:
                    # Multiple run_sync patches in one method — leave alone.
                    return updated_node
                run_sync_router = router
                continue
            new_decorators.append(dec)

        body_uses_client = self._body_references_client(updated_node)
        signature_changed = body_uses_client or run_sync_router is not None

        # 2. body rewrite: client.X(...) → api_client.X(...) and asserts
        new_body = updated_node.body
        if body_uses_client:
            new_body = cst.ensure_type(
                new_body.visit(ClientReferenceRenamer()), cst.IndentedBlock
            )
            self.uses_api_client = True

        assert_rewriter = AssertRewriter()
        new_body = cst.ensure_type(new_body.visit(assert_rewriter), cst.IndentedBlock)
        if assert_rewriter.used_ok:
            self.uses_assert_ok = True
        if assert_rewriter.used_problem:
            self.uses_assert_problem = True

        if run_sync_router is not None:
            new_decorators.append(self._make_indirect_parametrize(run_sync_router))
            self.added_indirect_parametrize = True

        if not signature_changed and new_decorators == list(updated_node.decorators):
            return updated_node.with_changes(body=new_body)

        new_params = self._rewrite_params(
            updated_node.params,
            add_api_client=body_uses_client,
            remaining_patch_count=(
                self._count_patch_decorators(new_decorators)
                if run_sync_router is not None
                else None
            ),
        )
        return updated_node.with_changes(
            decorators=new_decorators,
            params=new_params,
            body=new_body,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_run_sync_router(dec: cst.Decorator) -> str | None:
        """If `dec` is ``@patch("src.api.routers.<name>.run_sync"[, ...])``,
        return ``<name>``. Otherwise ``None``.

        Matches both forms in the codebase:
        - ``@patch("...run_sync", new_callable=AsyncMock)`` (the explicit form)
        - ``@patch("...run_sync")`` (relies on MagicMock's await magic — the
          mock_run_sync fixture replaces this with a proper AsyncMock, which
          is semantically equivalent for ``side_effect = ...`` callers).

        Skips ``@patch(...run_sync, return_value=X)`` and other prepared mocks
        because the fixture always yields a fresh AsyncMock and tests would
        need to set return_value/side_effect inside the body anyway.
        """
        call = dec.decorator
        if not isinstance(call, cst.Call):
            return None
        if not (isinstance(call.func, cst.Name) and call.func.value == "patch"):
            return None
        if not call.args:
            return None
        first = call.args[0].value
        if not isinstance(first, cst.SimpleString):
            return None
        match = re.fullmatch(
            r"^[\"']src\.api\.routers\.([a-z_]+)\.run_sync[\"']$", first.value
        )
        if not match:
            return None
        # Reject decorators that pre-configure the mock — those would lose
        # state when swapped for a fresh fixture.
        for arg in call.args[1:]:
            if arg.keyword is None:
                continue
            kw = arg.keyword.value
            if kw == "new_callable" and m.matches(arg.value, m.Name("AsyncMock")):
                continue  # matches our target shape
            if kw in {"return_value", "side_effect", "new", "wraps"}:
                return None
        return match.group(1)

    @staticmethod
    def _make_indirect_parametrize(router: str) -> cst.Decorator:
        return cst.Decorator(
            decorator=cst.Call(
                func=cst.Attribute(
                    value=cst.Attribute(
                        value=cst.Name("pytest"), attr=cst.Name("mark")
                    ),
                    attr=cst.Name("parametrize"),
                ),
                args=[
                    cst.Arg(value=cst.SimpleString('"mock_run_sync"')),
                    cst.Arg(
                        value=cst.List(
                            elements=[
                                cst.Element(value=cst.SimpleString(f'"{router}"'))
                            ]
                        )
                    ),
                    cst.Arg(
                        keyword=cst.Name("indirect"),
                        value=cst.Name("True"),
                    ),
                ],
            )
        )

    @staticmethod
    def _body_references_client(func: cst.FunctionDef) -> bool:
        scanner = ClientUsageScanner()
        func.body.visit(scanner)
        return scanner.found

    @staticmethod
    def _rewrite_params(
        params: cst.Parameters,
        *,
        add_api_client: bool,
        remaining_patch_count: int | None,
    ) -> cst.Parameters:
        new_params = list(params.params)

        if remaining_patch_count is not None:
            # @patch decorators each inject one positional arg. The indirect
            # `mock_run_sync` fixture now resolves by name. So `mock_run_sync`
            # must move past *all* remaining @patch positionals, regardless of
            # their parameter names (e.g. `_mock_config`, `_unused`).
            run_sync = next(
                (p for p in new_params if p.name.value == "mock_run_sync"),
                None,
            )
            if run_sync is not None:
                new_params = [p for p in new_params if p.name.value != "mock_run_sync"]
                self_offset = 1 if new_params and new_params[0].name.value == "self" else 0
                insert_idx = self_offset + remaining_patch_count
                insert_idx = min(insert_idx, len(new_params))
                new_params.insert(insert_idx, run_sync)

        if add_api_client and not any(p.name.value == "api_client" for p in new_params):
            new_params.append(
                cst.Param(
                    name=cst.Name("api_client"),
                    annotation=None,
                )
            )
        return params.with_changes(params=tuple(new_params))

    @staticmethod
    def _count_patch_decorators(decorators: list[cst.Decorator]) -> int:
        """Count decorators that inject a positional mock argument.

        Matches both ``@patch("...")`` and ``@patch("...", ...)``. Excludes
        ``@patch.dict(...)``, ``@patch.object(...)``, and pytest markers like
        ``@pytest.mark.parametrize``.
        """
        count = 0
        for dec in decorators:
            call = dec.decorator
            if isinstance(call, cst.Call) and isinstance(call.func, cst.Name) and call.func.value == "patch":
                count += 1
        return count

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------
    def _patch_imports(self, body: list[cst.BaseStatement]) -> list[cst.BaseStatement]:
        new_body: list[cst.BaseStatement] = []
        added_assert_import = not (self.uses_assert_ok or self.uses_assert_problem)
        added_pytest_import = not self.added_indirect_parametrize
        # Determine if pytest is already imported.
        has_pytest = any(self._is_pytest_import(s) for s in body)
        if has_pytest:
            added_pytest_import = True

        for stmt in body:
            stripped = self._prune_imports(stmt)
            if stripped is None:
                continue  # whole import line dropped
            new_body.append(stripped)

        # Insert assert_ok / assert_problem import.
        if not added_assert_import:
            names = []
            if self.uses_assert_ok:
                names.append("assert_ok")
            if self.uses_assert_problem:
                names.append("assert_problem")
            new_body = self._insert_after_last_import(
                new_body,
                cst.parse_statement(f"from tests.asserts import {', '.join(names)}\n"),
            )
        if not added_pytest_import:
            new_body = self._insert_after_last_import(
                new_body, cst.parse_statement("import pytest\n")
            )
        return new_body

    @staticmethod
    def _is_pytest_import(stmt: cst.BaseStatement) -> bool:
        return m.matches(
            stmt,
            m.SimpleStatementLine(
                body=[m.Import(names=[m.ImportAlias(name=m.Name("pytest"))])]
            ),
        )

    def _prune_imports(
        self, stmt: cst.BaseStatement
    ) -> cst.BaseStatement | None:
        """Trim unused symbols from `from X import a, b, c` statements."""
        if not isinstance(stmt, cst.SimpleStatementLine) or len(stmt.body) != 1:
            return stmt
        node = stmt.body[0]
        if isinstance(node, cst.ImportFrom):
            return self._prune_import_from(stmt, node)
        return stmt

    def _prune_import_from(
        self, stmt: cst.SimpleStatementLine, node: cst.ImportFrom
    ) -> cst.BaseStatement | None:
        if isinstance(node.names, cst.ImportStar):
            return stmt
        module_name = self._import_from_module(node)

        keep: list[cst.ImportAlias] = []
        for alias in node.names:
            local_name = (
                alias.asname.name.value
                if alias.asname is not None and isinstance(alias.asname.name, cst.Name)
                else alias.name.value
                if isinstance(alias.name, cst.Name)
                else None
            )
            if local_name is None:
                keep.append(alias)
                continue
            if module_name == "fastapi.testclient" and local_name == "TestClient":
                if not self.uses_TestClient:
                    continue
            if module_name == "src.api.main" and local_name == "app":
                if not self.uses_app:
                    continue
            if module_name == "unittest.mock":
                if local_name == "AsyncMock" and not self.uses_async_mock:
                    continue
                if local_name == "patch" and not self.uses_patch:
                    continue
            keep.append(alias)

        if not keep:
            return None
        if len(keep) == len(list(node.names)):
            return stmt
        # Strip the trailing comma on the last surviving alias.
        keep[-1] = keep[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
        return stmt.with_changes(body=[node.with_changes(names=keep)])

    @staticmethod
    def _import_from_module(node: cst.ImportFrom) -> str:
        if node.module is None:
            return ""
        parts: list[str] = []
        cur: cst.BaseExpression | None = node.module
        while cur is not None:
            if isinstance(cur, cst.Name):
                parts.insert(0, cur.value)
                break
            if isinstance(cur, cst.Attribute):
                parts.insert(0, cur.attr.value)
                cur = cur.value
                continue
            break
        return ".".join(parts)

    @staticmethod
    def _insert_after_last_import(
        body: list[cst.BaseStatement], stmt: cst.BaseStatement
    ) -> list[cst.BaseStatement]:
        # Find the last import line; insert immediately after.
        last = -1
        for i, s in enumerate(body):
            if isinstance(s, cst.SimpleStatementLine) and s.body and isinstance(
                s.body[0], (cst.Import, cst.ImportFrom)
            ):
                last = i
        if last < 0:
            return [stmt, *body]
        return [*body[: last + 1], stmt, *body[last + 1 :]]


# ----------------------------------------------------------------------
# Scanners — read-only visitors used to determine usage post-transform.
# ----------------------------------------------------------------------
class ClientUsageScanner(cst.CSTVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_Attribute(self, node: cst.Attribute) -> None:  # noqa: N802
        if isinstance(node.value, cst.Name) and node.value.value == "client":
            self.found = True


class NameUsageScanner(cst.CSTVisitor):
    """Tracks references to a fixed set of identifiers anywhere in the
    *body* of the module (excluding import statements themselves)."""

    def __init__(self) -> None:
        super().__init__()
        self.found_TestClient = False  # noqa: N815
        self.found_app = False
        self.found_AsyncMock = False  # noqa: N815
        self.found_patch = False
        self._depth_in_import = 0

    def visit_Import(self, node: cst.Import) -> None:  # noqa: N802
        self._depth_in_import += 1

    def leave_Import(self, original_node: cst.Import) -> None:  # noqa: N802
        self._depth_in_import -= 1

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:  # noqa: N802
        self._depth_in_import += 1

    def leave_ImportFrom(self, original_node: cst.ImportFrom) -> None:  # noqa: N802
        self._depth_in_import -= 1

    def visit_Name(self, node: cst.Name) -> None:  # noqa: N802
        if self._depth_in_import:
            return
        if node.value == "TestClient":
            self.found_TestClient = True
        elif node.value == "app":
            self.found_app = True
        elif node.value == "AsyncMock":
            self.found_AsyncMock = True
        elif node.value == "patch":
            self.found_patch = True


# ----------------------------------------------------------------------
# Body-level transformers
# ----------------------------------------------------------------------
class ClientReferenceRenamer(cst.CSTTransformer):
    """Renames every `client.<attr>` to `api_client.<attr>` inside a function
    body. Bare references to `client` (e.g., `client_factory(client)`) are not
    rewritten — the only legitimate use of `client` in this codebase is
    method-style HTTP calls."""

    def leave_Attribute(  # noqa: N802
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.Attribute:
        if (
            isinstance(updated_node.value, cst.Name)
            and updated_node.value.value == "client"
        ):
            return updated_node.with_changes(value=cst.Name("api_client"))
        return updated_node


class AssertRewriter(cst.CSTTransformer):
    """Rewrites `assert resp.status_code == N` lines.

    - 2xx (200..299) → `assert_ok(resp)` (drops a following `resp.json()` if
      it appears as the next bare expression statement, since assert_ok
      returns the body).
    - 4xx/5xx (>= 400) → `assert_problem(resp, N)`.

    Tests with a non-trivial assert message (e.g. `assert resp.status_code == 200, "msg"`)
    are left alone."""

    def __init__(self) -> None:
        super().__init__()
        self.used_ok = False
        self.used_problem = False

    def leave_IndentedBlock(  # noqa: N802
        self,
        original_node: cst.IndentedBlock,
        updated_node: cst.IndentedBlock,
    ) -> cst.IndentedBlock:
        new_body: list[cst.BaseStatement] = []
        for stmt in updated_node.body:
            replaced = self._maybe_rewrite_assert(stmt)
            if replaced is not None:
                new_body.append(replaced)
            else:
                new_body.append(stmt)
        return updated_node.with_changes(body=new_body)

    def _maybe_rewrite_assert(
        self, stmt: cst.BaseStatement
    ) -> cst.BaseStatement | None:
        if not isinstance(stmt, cst.SimpleStatementLine) or len(stmt.body) != 1:
            return None
        small = stmt.body[0]
        if not isinstance(small, cst.Assert) or small.msg is not None:
            return None
        comp = small.test
        if not isinstance(comp, cst.Comparison) or len(comp.comparisons) != 1:
            return None
        ct = comp.comparisons[0]
        if not isinstance(ct.operator, cst.Equal):
            return None
        # left: must be `<receiver>.status_code`
        if not (
            isinstance(comp.left, cst.Attribute)
            and isinstance(comp.left.attr, cst.Name)
            and comp.left.attr.value == "status_code"
            and isinstance(comp.left.value, cst.Name)
        ):
            return None
        receiver = comp.left.value.value
        # right: must be an integer literal
        if not isinstance(ct.comparator, cst.Integer):
            return None
        try:
            code = int(ct.comparator.value)
        except ValueError:
            return None
        if 200 <= code < 300:
            self.used_ok = True
            return cst.SimpleStatementLine(
                body=[
                    cst.Expr(
                        value=cst.Call(
                            func=cst.Name("assert_ok"),
                            args=[cst.Arg(value=cst.Name(receiver))],
                        )
                    )
                ]
            )
        if 400 <= code < 600:
            self.used_problem = True
            return cst.SimpleStatementLine(
                body=[
                    cst.Expr(
                        value=cst.Call(
                            func=cst.Name("assert_problem"),
                            args=[
                                cst.Arg(value=cst.Name(receiver)),
                                cst.Arg(value=cst.Integer(str(code))),
                            ],
                        )
                    )
                ]
            )
        return None


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------
def discover_files(extra_paths: list[str]) -> list[Path]:
    if extra_paths:
        return [Path(p).resolve() for p in extra_paths]
    return sorted(
        p
        for p in TEST_DIR.glob("test_api_*.py")
        if p.name not in SKIP_FILES
    )


def migrate(path: Path, *, apply: bool) -> tuple[bool, str]:
    """Returns (changed, new_source)."""
    src = path.read_text()
    tree = cst.parse_module(src)
    migrator = FileMigrator()
    new_tree = tree.visit(migrator)
    new_src = new_tree.code
    changed = new_src != src
    if changed and apply:
        path.write_text(new_src)
    return changed, new_src


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="dry-run; exit 1 if changes pending")
    group.add_argument("--apply", action="store_true", help="write changes in place")
    parser.add_argument("paths", nargs="*", help="optional explicit files (else: all test_api_*.py)")
    args = parser.parse_args(argv)

    files = discover_files(args.paths)
    if not files:
        print("no files matched", file=sys.stderr)
        return 1

    pending = []
    for path in files:
        try:
            changed, _ = migrate(path, apply=args.apply)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {path.relative_to(REPO_ROOT)}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        if changed:
            pending.append(path)
            verb = "wrote" if args.apply else "would change"
            print(f"{verb} {path.relative_to(REPO_ROOT)}")

    if args.check and pending:
        print(f"\n{len(pending)} file(s) pending migration", file=sys.stderr)
        return 1
    if not pending:
        print("no files needed migration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
