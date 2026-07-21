"""Verify the unified error response schema ({error, code, details})."""

from typing import Any, cast

from src.api.errors import ApiException
from tests.asserts import assert_problem


class TestHTTPExceptionHandler:
    """Plain HTTPException(detail=...) gets rewritten to the unified shape."""

    def test_404_has_unified_shape(self, api_client):
        # DELETE a non-existent transaction — route raises HTTPException(404)
        resp = api_client.delete("/api/v1/transactions/nobody@example.com/does_not_exist.eml")
        assert_problem(resp, 404)
        body = resp.json()
        assert set(body.keys()) == {"error", "code", "details"}
        assert body["code"] == "NOT_FOUND"
        assert "not found" in body["error"].lower()
        assert body["details"] is None

    def test_422_validation_has_unified_shape(self, api_client):
        # Bad month format should trip pydantic validation
        resp = api_client.get("/api/v1/summary?month=not-a-month")
        assert_problem(resp, 422)
        body = resp.json()
        assert set(body.keys()) == {"error", "code", "details"}
        assert body["code"] in {"VALIDATION_ERROR", "BAD_REQUEST"}
        assert body["details"] is not None  # carries the pydantic error list


class TestUnhandledExceptionHandler:
    """An uncaught (non-HTTP) exception is wrapped in the unified 500 envelope."""

    def test_unhandled_error_has_unified_shape(self, api_client_raising):
        from src.api.dependencies import get_spending_summary
        from src.api.main import app

        def _boom() -> Any:
            raise RuntimeError("kaboom")

        app.dependency_overrides[get_spending_summary] = _boom
        resp = api_client_raising.get("/api/v1/transactions?month=2026-02")
        assert_problem(resp, 500)
        body = resp.json()
        assert set(body.keys()) == {"error", "code", "details"}
        assert body["code"] == "INTERNAL_ERROR"
        assert body["details"] is None


class TestApiException:
    """ApiException carries a custom code + details through the handler."""

    def test_custom_code_is_preserved(self):
        import asyncio
        import json

        from src.api.main import http_exception_handler

        exc = ApiException(
            status_code=418,
            code="TEAPOT",
            message="short and stout",
            details={"kettle": True},
        )
        loop = asyncio.new_event_loop()
        try:
            # cast(Any, None): the handler doesn't read the Request, so passing None is fine
            # at runtime; the FastAPI signature requires Request[State].
            resp = loop.run_until_complete(http_exception_handler(cast("Any", None), exc))
        finally:
            loop.close()
        assert_problem(resp, 418)
        body = json.loads(bytes(resp.body))
        assert body == {"error": "short and stout", "code": "TEAPOT", "details": {"kettle": True}}
