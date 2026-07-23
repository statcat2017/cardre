"""Resolve branch evidence for port-native reporting sections."""

from __future__ import annotations

from collections.abc import Callable

from cardre.application.evidence.evidence_resolver import resolve_run_step_evidence
from cardre.application.ports.unit_of_work import UnitOfWork
from cardre.application.reporting.contracts import ResolvedStepRef
from cardre.application.reporting.schema import Limitation
from cardre.domain.run import RunStep


def resolve_run_step(
    uow: UnitOfWork,
    ref: ResolvedStepRef,
    plan_version_id: str,
    add_limitation: Callable[[Limitation], None] | None = None,
    plan_id: str | None = None,
) -> RunStep | None:
    """Resolve a step through branch, full-plan, and cross-version evidence."""
    resolved = resolve_run_step_evidence(
        uow,
        plan_version_id,
        ref.step_id,
        branch_id=ref.resolved_branch_id,
        plan_id=plan_id,
    )
    if resolved is None:
        return None
    if ref.resolution == "ancestor" and add_limitation is not None:
        add_limitation(Limitation(
            severity="warning",
            code="INHERITED_BRANCH_EVIDENCE",
            message=f"Step {ref.canonical_step_id} is inherited from branch {ref.resolved_branch_id}.",
        ))
    return resolved.run_step
