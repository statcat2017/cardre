"""Step resolution helper for reporting sections.

Moved out of ``collector.py`` so section modules can import it without
a reverse dependency on the collector module.
"""

from __future__ import annotations

from collections.abc import Callable

from cardre.branch_step_resolver import ResolvedStepRef
from cardre.domain.run import RunStep
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.schema import Limitation
from cardre.reporting.types import SectionContext
from cardre.store import ProjectStore


def _resolve_run_step(
    store: ProjectStore, ref: ResolvedStepRef, plan_version_id: str,
    add_limitation: Callable[[Limitation], None] | None = None,
) -> RunStep | None:
    from cardre.evidence_locator import EvidenceLocator
    resolved = EvidenceLocator(store).resolve_ref(
        plan_version_id,
        ref,
    )
    rs = resolved.run_step if resolved is not None else None
    if rs is not None and ref.resolution == "ancestor" and add_limitation is not None:
        add_limitation(Limitation(
            severity="warning", code=LimitationCode.INHERITED_BRANCH_EVIDENCE,
            message=f"Step {ref.canonical_step_id} inherited from branch "
            f"{ref.resolved_branch_id} (ancestor resolution).",
        ))
    return rs


def resolve_run_step(ctx: SectionContext, ref: ResolvedStepRef) -> RunStep | None:
    """Convenience wrapper that passes ctx.add_limitation to _resolve_run_step."""
    return _resolve_run_step(ctx.store, ref, ctx.plan_version_id, ctx.add_limitation)
