"""Phase 1 tests — WorkflowGuidanceService delegation and key resolution.

Phase 0 locked the seam (constructible, zero public methods).
Phase 1 replaces that test with real delegation coverage.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cardre.store import ProjectStore
from cardre.services.workflow_guidance_service import (
    WorkflowGuidanceService,
    WorkflowGuidanceServiceError,
    BUILD_STREAM_CANONICAL_IDS,
    VALIDATE_STREAM_CANONICAL_IDS,
)


def _init_store(tmp: str) -> ProjectStore:
    """Create and initialize a fresh ProjectStore in a temp directory."""
    store = ProjectStore(Path(tmp))
    store.initialize()
    return store


def test_constructible():
    """Service can be constructed with a ProjectStore."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        assert isinstance(svc, WorkflowGuidanceService)


def test_raises_without_branch_and_run():
    """Raises WorkflowGuidanceServiceError when both branch_id and run_id are None."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        with pytest.raises(WorkflowGuidanceServiceError, match="At least one"):
            svc.build(plan_id="p1", project_id="prj1")


def test_default_step_guidance_keys():
    """All canonical steps appear in step_guidance output, even when no data exists."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        result = svc.build(plan_id="p1", project_id="prj1", branch_id="b1")
        for cid in BUILD_STREAM_CANONICAL_IDS + VALIDATE_STREAM_CANONICAL_IDS:
            assert cid in result.step_guidance, f"Missing {cid}"
            sg = result.step_guidance[cid]
            assert "readiness" in sg
            assert "primary_action" in sg
            assert "explanation" in sg
            assert "evidence_kinds" in sg


def test_phase_is_setup_when_no_train_artifact():
    """Phase is 'setup' when no train-role artifact exists."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        result = svc.build(plan_id="p1", project_id="prj1", branch_id="b1")
        assert result.phase == "setup"


def test_build_stream_constants_match():
    """Verify no overlap between build and validate stream constants."""
    build_set = set(BUILD_STREAM_CANONICAL_IDS)
    validate_set = set(VALIDATE_STREAM_CANONICAL_IDS)
    assert build_set & validate_set == set(), "Overlap between build and validate streams"
    assert "model-fit" in build_set or "logistic-regression" in build_set


def test_known_evidence_kinds():
    """Spot-check that important steps have evidence_kinds populated."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        svc = WorkflowGuidanceService(store)
        result = svc.build(plan_id="p1", project_id="prj1", branch_id="b1")
        mb = result.step_guidance.get("manual-binning", {})
        assert len(mb.get("evidence_kinds", [])) > 0, "manual-binning should have evidence_kinds"
