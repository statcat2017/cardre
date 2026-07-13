"""Plan execution action planning — typed actions and planner.

Pure action planning for supported execution paths. The planner now models only
real launch semantics: full-plan execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from cardre.domain.step import StepSpec


@dataclass
class _StepAction:
    """A planned action for a single step during execution."""

    spec: StepSpec
    action: Literal["execute"] = "execute"
    reason_code: str = "execute"
    reason_context: dict[str, Any] = field(default_factory=dict)


class ExecutionActionPlanner:
    """Plans step actions for a plan version run."""

    def plan_full_plan(self, steps: list[StepSpec]) -> list[_StepAction]:
        """All steps execute with reason ``full_plan``."""
        return [
            _StepAction(spec=s, action="execute", reason_code="full_plan")
            for s in steps
        ]

__all__ = ["ExecutionActionPlanner", "_StepAction"]
