"""Plan execution action planning — typed actions and planner.

A planned action for a single step during execution — whether to
execute, reuse from a prior run, or skip.  The planner constructs action
lists for full-plan and to-node runs.

Pure — no database writes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from cardre.domain.evidence import ResolvedEvidence
from cardre.domain.step import StepSpec


@dataclass
class _StepAction:
    """A planned action for a single step during execution."""

    spec: StepSpec
    action: Literal["execute", "reuse", "skip"]
    evidence_source: ResolvedEvidence | None = None
    before_execute: Callable[[], None] | None = None
    reason_code: str = "execute"
    reason_context: dict[str, Any] = field(default_factory=dict)


class ExecutionActionPlanner:
    """Plans step actions for a plan version run.

    Decides whether each step should be executed, reused, or skipped.
    Pure — no database writes.
    """

    def plan_full_plan(self, steps: list[StepSpec]) -> list[_StepAction]:
        """All steps execute with reason ``full_plan``."""
        return [
            _StepAction(spec=s, action="execute", reason_code="full_plan")
            for s in steps
        ]

    def plan_to_node(
        self,
        steps: list[StepSpec],
        target_step_id: str,
    ) -> list[_StepAction]:
        """Only the ancestor closure of target_step_id executes.

        Staleness-aware reuse/skip is not implemented yet — pretending
        it would be dishonest (#214).
        """
        from cardre.execution.step_graph import ancestor_closure

        ancestors = ancestor_closure(target_step_id, steps)
        closure = ancestors | {target_step_id}
        closure_steps = [s for s in steps if s.step_id in closure]
        return [
            _StepAction(spec=s, action="execute", reason_code="to_node_closure")
            for s in closure_steps
        ]


__all__ = ["ExecutionActionPlanner", "_StepAction"]
