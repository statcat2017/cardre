"""Tests for the standard API error envelope and CardreError hierarchy."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from cardre.errors import (
    CardreError,
    Diagnostic,
    Ok,
    Degraded,
    Fail,
    is_ok,
    is_degraded,
    is_fail,
    unwrap_or_raise,
    unwrap_or_degrade,
    GraphValidationError,
    ConcurrentRunError,
    RunLifecycleError,
    BranchValidationError,
    BranchEvidenceError,
)
from cardre.services.plan_service import PlanValidationError
from sidecar.error_handling import (
    _envelope,
    cardre_error_handler,
    http_exception_handler,
    request_validation_error_handler,
    generic_exception_handler,
)


# ---------------------------------------------------------------------------
# CardreError serialisation
# ---------------------------------------------------------------------------


class TestCardreErrorEnvelope:
    def test_subclass_serialises_with_class_defaults(self):
        err = GraphValidationError("Graph is broken")
        env = err.to_envelope()
        assert env["code"] == "GRAPH_VALIDATION_ERROR"
        assert env["message"] == "Graph is broken"
        assert env["recoverable"] is False
        assert env["severity"] == "error"
        assert env["context"] == {}
        assert env["diagnostics"] == []

    def test_subclass_with_per_instance_overrides(self):
        err = GraphValidationError(
            "Graph is broken",
            context={"step_id": "s1"},
            recoverable=True,
            severity="warning",
            diagnostics=[Diagnostic(code="SUB", message="sub")],
        )
        env = err.to_envelope()
        assert env["code"] == "GRAPH_VALIDATION_ERROR"
        assert env["message"] == "Graph is broken"
        assert env["recoverable"] is True
        assert env["severity"] == "warning"
        assert env["context"] == {"step_id": "s1"}
        assert len(env["diagnostics"]) == 1
        assert env["diagnostics"][0]["code"] == "SUB"

    def test_plan_validation_error_maps_extra_to_context(self):
        err = PlanValidationError("STALE_VERSION", "Plan was modified", status_code=409, extra={"latest_version_id": "v2"})
        env = err.to_envelope()
        assert env["code"] == "STALE_VERSION"
        assert env["message"] == "Plan was modified"
        assert env["context"] == {"latest_version_id": "v2"}

    def test_concurrent_run_error(self):
        err = ConcurrentRunError("A run is already in progress")
        env = err.to_envelope()
        assert env["code"] == "CONCURRENT_RUN"
        assert env["message"] == "A run is already in progress"

    def test_run_lifecycle_error(self):
        err = RunLifecycleError("Run record missing")
        env = err.to_envelope()
        assert env["code"] == "RUN_LIFECYCLE_ERROR"

    def test_branch_validation_error(self):
        err = BranchValidationError("BRANCH_POINT_NOT_ALLOWED", context={"step_id": "s1"})
        env = err.to_envelope()
        assert env["code"] == "BRANCH_POINT_NOT_ALLOWED"
        assert env["context"] == {"step_id": "s1"}

    def test_branch_evidence_error(self):
        err = BranchEvidenceError("SHARED_UPSTREAM_STALE", context={"stale_steps": ["s1"]})
        env = err.to_envelope()
        assert env["code"] == "SHARED_UPSTREAM_STALE"
        assert env["context"] == {"stale_steps": ["s1"]}


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


class TestResult:
    def test_ok_unwrap(self):
        r: Ok[int] = Ok(42)
        assert is_ok(r)
        assert not is_degraded(r)
        assert not is_fail(r)
        assert unwrap_or_raise(r) == 42

    def test_degraded_unwrap(self):
        r: Degraded[int] = Degraded(0, [Diagnostic(code="X", message="y")])
        assert is_degraded(r)
        assert unwrap_or_raise(r) == 0
        assert unwrap_or_degrade(r, default=-1) == 0

    def test_fail_raises(self):
        r: Fail = Fail([Diagnostic(code="X", message="y")])
        assert is_fail(r)
        with pytest.raises(CardreError) as exc_info:
            unwrap_or_raise(r)
        assert exc_info.value.code == "CARDRE_ERROR"
        assert exc_info.value.message == "y"

    def test_fail_degrade_returns_default(self):
        r: Fail = Fail([Diagnostic(code="X", message="y")])
        result = unwrap_or_degrade(r, default=42)
        assert result == 42


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_basic_envelope(self):
        resp = _envelope("TEST_CODE", "Test message", 400)
        body = json.loads(resp.body)
        assert resp.status_code == 400
        assert body["detail"]["code"] == "TEST_CODE"
        assert body["detail"]["message"] == "Test message"
        assert "request_id" in body["detail"]
        assert "error_id" in body["detail"]

    def test_envelope_with_diagnostics(self):
        resp = _envelope("X", "Y", 500, diagnostics=[{"code": "SUB", "message": "sub"}])
        body = json.loads(resp.body)
        assert len(body["detail"]["diagnostics"]) == 1
        assert body["detail"]["diagnostics"][0]["code"] == "SUB"


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


class MockRequest:
    state = type("State", (), {"request_id": "req-123"})()


class TestExceptionHandlers:
    def test_cardre_error_handler(self):
        err = GraphValidationError("Graph broken", context={"step_id": "s1"})
        resp = cardre_error_handler(MockRequest(), err)
        body = json.loads(resp.body)
        assert resp.status_code == 500
        assert body["detail"]["code"] == "GRAPH_VALIDATION_ERROR"
        assert body["detail"]["message"] == "Graph broken"
        assert body["detail"]["context"] == {"step_id": "s1"}
        assert body["detail"]["request_id"] == "req-123"

    def test_http_exception_dict_detail(self):
        exc = HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Item not found"})
        resp = http_exception_handler(MockRequest(), exc)
        body = json.loads(resp.body)
        assert resp.status_code == 404
        assert body["detail"]["code"] == "NOT_FOUND"
        assert body["detail"]["message"] == "Item not found"
        assert body["detail"]["request_id"] == "req-123"

    def test_http_exception_string_detail(self):
        exc = HTTPException(status_code=400, detail="RUN_FAILED")
        resp = http_exception_handler(MockRequest(), exc)
        body = json.loads(resp.body)
        assert resp.status_code == 400
        assert body["detail"]["code"] == "HTTP_ERROR"
        assert body["detail"]["message"] == "RUN_FAILED"

    def test_request_validation_error(self):
        try:
            from pydantic import BaseModel

            class TestModel(BaseModel):
                name: str

            TestModel()  # missing required field
        except ValidationError as e:
            rve = RequestValidationError(e.errors())
            resp = request_validation_error_handler(MockRequest(), rve)
            body = json.loads(resp.body)
            assert resp.status_code == 422
            assert body["detail"]["code"] == "VALIDATION_ERROR"
            assert len(body["detail"]["diagnostics"]) > 0
            assert body["detail"]["diagnostics"][0]["code"] == "VALIDATION_ERROR"

    def test_generic_exception(self):
        exc = RuntimeError("Something broke")
        resp = generic_exception_handler(MockRequest(), exc)
        body = json.loads(resp.body)
        assert resp.status_code == 500
        assert body["detail"]["code"] == "INTERNAL_ERROR"
        assert body["detail"]["message"] == "An internal error occurred."
        assert body["detail"]["request_id"] == "req-123"
        assert len(body["detail"]["diagnostics"]) == 1
        assert body["detail"]["diagnostics"][0]["exception_type"] == "RuntimeError"
