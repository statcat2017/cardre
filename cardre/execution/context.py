"""Execution context and node output types.

These have execution coupling (store, run state) and belong in the
execution layer, not domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import JsonDict
    from cardre.domain.step import StepSpec
    from cardre.store import ProjectStore


@dataclass
class ExecutionContext:
    """Full context passed to a node's run() method."""
    store: ProjectStore
    run_id: str
    plan_version_id: str
    step_spec: StepSpec
    parent_run_steps: list
    input_artifacts: list[ArtifactRef]
    validated_params: JsonDict
    runtime_metadata: JsonDict


@dataclass
class NodeOutput:
    """Output produced by a single node execution."""
    artifacts: list[ArtifactRef]
    metrics: JsonDict
    execution_fingerprint: JsonDict | None = None
    warnings: list[JsonDict] | None = None


__all__ = ["ExecutionContext", "NodeOutput"]
