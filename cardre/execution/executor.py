"""Backward-compat shim — preserved for test compatibility during Batch 05.

The old ``PlanExecutor`` class was replaced by ``ExecuteRun`` in
``cardre.application.runs.execute_run``.  This shim allows existing
test imports to resolve until they are updated.
"""

from __future__ import annotations

from typing import Any

from cardre.execution.context import ExecutionContext, NodeOutput  # noqa: F401
from cardre.execution.step_runner import StepRunner  # noqa: F401


class PlanExecutor:
    """Legacy stub — replaced by ``ExecuteRun``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def run_plan_version(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("PlanExecutor is a stub — use ExecuteRun from cardre.application.runs")
