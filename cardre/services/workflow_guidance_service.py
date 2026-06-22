"""Workflow guidance aggregation service.

Reserved by ADR 0008. Phase 1 implements the build method.
This module must not import or re-implement any readiness logic
until Phase 1.
"""

from __future__ import annotations

from cardre.store import ProjectStore


class WorkflowGuidanceService:
    """Aggregates phase, next action, blockers, per-step readiness,
    and report readiness by delegating to existing backend services.

    Used by ``GET /plans/{plan_id}/workflow-guidance`` (Phase 1).
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
