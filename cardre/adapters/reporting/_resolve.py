"""Step resolution helper for reporting sections — port-based version.

Ports ``cardre.reporting._resolve`` to use an EvidenceReaderPort
instead of ``cardre.evidence_locator.EvidenceLocator``.
"""

from __future__ import annotations

from collections.abc import Callable

from cardre.branch_step_resolver import ResolvedStepRef
from cardre.domain.run import RunStep
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import Limitation


class EvidenceReaderPort:
    """Protocol for evidence resolution — must support resolve_ref."""

    def resolve_ref(
        self,
        plan_version_id: str,
        ref: ResolvedStepRef,
        *,
        plan_id: str | None = None,
    ) -> RunStep | None: ...


def resolve_run_step(
    reader: EvidenceReaderPort,
    ref: ResolvedStepRef,
    plan_version_id: str,
    add_limitation: Callable[[Limitation], None] | None = None,
    plan_id: str | None = None,
) -> RunStep | None:
    """Resolve a branch step reference to a RunStep via the EvidenceReaderPort."""
    from cardre.evidence_locator import EvidenceLocator

    if isinstance(reader, EvidenceLocator):
        resolved = reader.resolve_ref(plan_version_id, ref, plan_id=plan_id)
        rs = resolved.run_step if resolved is not None else None
    elif hasattr(reader, "resolve_ref"):
        resolved = reader.resolve_ref(plan_version_id, ref, plan_id=plan_id)
        if resolved is not None and hasattr(resolved, "run_step"):
            rs = resolved.run_step
        else:
            rs = resolved
    else:
        rs = None

    if rs is not None and ref.resolution == "ancestor" and add_limitation is not None:
        add_limitation(Limitation(
            severity="warning", code=LimitationCode.INHERITED_BRANCH_EVIDENCE,
            message=f"Step {ref.canonical_step_id} inherited from branch "
            f"{ref.resolved_branch_id} (ancestor resolution).",
        ))
    return rs
