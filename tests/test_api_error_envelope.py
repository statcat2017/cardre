"""Tests for error envelope consistency across all routes.

Every error response must follow the shape::

    {
        "detail": {
            "code": "ERROR_CODE",
            "message": "Human-readable description.",
            "context": {}
        }
    }
"""

from __future__ import annotations

import uuid

from cardre.api.errors import (
    ARTIFACT_NOT_FOUND,
    BRANCH_NOT_FOUND,
    COMPARISON_NOT_FOUND,
    CONCURRENT_RUN,
    GOVERNANCE_DISABLED,
    MISSING_PROJECT_ID,
    PLAN_NOT_FOUND,
    PLAN_VERSION_IMMUTABLE,
    PLAN_VERSION_NOT_FOUND,
    PROJECT_NOT_FOUND,
    REVIEW_NOT_FOUND,
    RUN_EXECUTION_FAILED,
    RUN_NOT_FOUND,
    STEP_NOT_FOUND,
    STORE_VERSION_INCOMPATIBLE,
)

ERROR_CODES = [
    ARTIFACT_NOT_FOUND,
    BRANCH_NOT_FOUND,
    COMPARISON_NOT_FOUND,
    CONCURRENT_RUN,
    GOVERNANCE_DISABLED,
    MISSING_PROJECT_ID,
    PLAN_NOT_FOUND,
    PLAN_VERSION_IMMUTABLE,
    PLAN_VERSION_NOT_FOUND,
    PROJECT_NOT_FOUND,
    REVIEW_NOT_FOUND,
    RUN_EXECUTION_FAILED,
    RUN_NOT_FOUND,
    STEP_NOT_FOUND,
    STORE_VERSION_INCOMPATIBLE,
]


class TestErrorEnvelope:
    def test_all_error_codes_defined(self):
        """All expected error codes are present."""
        expected = {
            "ARTIFACT_NOT_FOUND",
            "BRANCH_NOT_FOUND",
            "COMPARISON_NOT_FOUND",
            "CONCURRENT_RUN",
            "GOVERNANCE_DISABLED",
            "MISSING_PROJECT_ID",
            "PLAN_NOT_FOUND",
            "PLAN_VERSION_IMMUTABLE",
            "PLAN_VERSION_NOT_FOUND",
            "PROJECT_NOT_FOUND",
            "REVIEW_NOT_FOUND",
            "RUN_EXECUTION_FAILED",
            "RUN_NOT_FOUND",
            "STEP_NOT_FOUND",
            "STORE_VERSION_INCOMPATIBLE",
        }
        assert set(ERROR_CODES) == expected, f"Missing codes: {expected - set(ERROR_CODES)}"

    def test_envelope_shape(self):
        """The error_response function produces the correct envelope."""
        from cardre.api.errors import error_response

        resp = error_response(
            code="TEST_CODE",
            message="Test message",
            status_code=400,
            context={"key": "value"},
        )
        body = resp.body.decode()
        import json
        parsed = json.loads(body)
        assert "detail" in parsed
        assert parsed["detail"]["code"] == "TEST_CODE"
        assert parsed["detail"]["message"] == "Test message"
        assert parsed["detail"]["context"] == {"key": "value"}

    def test_envelope_without_context(self):
        """Error envelope works when context is omitted."""
        from cardre.api.errors import error_response

        resp = error_response(
            code="SIMPLE_ERROR",
            message="Simple error",
            status_code=404,
        )
        body = resp.body.decode()
        import json
        parsed = json.loads(body)
        assert parsed["detail"]["code"] == "SIMPLE_ERROR"
        assert parsed["detail"]["context"] == {}

    def test_validation_error_envelope(self, api_client):
        """FastAPI validation errors should also produce detail.code."""
        # Missing project id on a project-scoped route should produce MISSING_PROJECT_ID
        resp = api_client.get("/projects/some-id/runs")
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data
        assert data["detail"]["code"] == "MISSING_PROJECT_ID"

    def test_404_produces_envelope(self, raw_project_path, api_client, store):
        """A 404 error from the API should have the right shape."""
        root = store.root
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert "code" in data["detail"]
        assert "message" in data["detail"]
        assert "context" in data["detail"]
