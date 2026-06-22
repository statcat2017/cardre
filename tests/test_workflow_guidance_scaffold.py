"""Phase 0 scaffold test — locks the WorkflowGuidanceService seam.

Asserts the service exists, accepts a ProjectStore, and has zero
behaviour (no methods doing work). Phase 1 will add and test the
actual implementation.
"""

from __future__ import annotations

from cardre.services.workflow_guidance_service import WorkflowGuidanceService
from cardre.store import ProjectStore
import tempfile
from pathlib import Path


def test_workflow_guidance_service_exists():
    """The service can be constructed with a ProjectStore."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ProjectStore(Path(tmp))
        svc = WorkflowGuidanceService(store)
        assert isinstance(svc, WorkflowGuidanceService)
        assert hasattr(svc, "_store")
        assert svc._store is store


def test_workflow_guidance_service_has_no_public_methods():
    """Phase 0 scaffold must expose no behaviour — prevents
    premature re-implementation of readiness logic."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ProjectStore(Path(tmp))
        svc = WorkflowGuidanceService(store)
        public_methods = [
            m for m in dir(svc)
            if not m.startswith("_") and callable(getattr(svc, m, None))
        ]
        # Phase 1 will add .build() — this test is updated then.
        assert public_methods == [], f"Unexpected public methods: {public_methods}"
