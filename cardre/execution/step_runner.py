"""Step runner — executes one node step and returns a typed result.

Extracted from ``PlanExecutor._execute_step``.  The step runner resolves
inputs, instantiates and validates the node, builds an execution context,
calls ``node.run()``, builds the execution fingerprint, and returns a
``StepExecutionResult`` describing success or failure.

The step runner does NOT persist anything — the caller (PlanExecutor) is
responsible for recording the result via a persistence collaborator.
"""

from __future__ import annotations

import enum
import sys
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from cardre.domain.errors import (
    MissingInputArtifactError,
    ParameterValidationError,
)
from cardre.domain.run import RunStep, RunStepStatus
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.execution.failure_classification import classify_step_failure
from cardre.execution.fingerprints import build_execution_fingerprint
from cardre.nodes.registry import NodeRegistry

if TYPE_CHECKING:
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import JsonDict
    from cardre.domain.step import StepSpec
    from cardre.store.db import ProjectStore


def _json_ready(value: Any) -> Any:
    """Recursively convert enum/ndarray/numpy values to JSON-safe types."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if isinstance(value, set):
        return [_json_ready(v) for v in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.ndarray,)):
        return [_json_ready(v) for v in value.tolist()]
    return value


@dataclass(frozen=True)
class StepExecutionResult:
    """Typed result of executing a single step via ``StepRunner``.

    Contains everything needed for persistence: resolved inputs, parent
    run-step records, output artifacts, fingerprint, warnings, and the
    structured failure entry (if ``status == FAILED``).
    """

    step_id: str
    node_type: str
    status: RunStepStatus
    fingerprint: JsonDict
    input_artifact_ids: list[str]
    input_artifact_ids_by_parent: dict[str, list[str]]
    output_artifact_ids: list[str]
    parent_run_steps: list[RunStep]
    warnings: list[JsonDict]
    errors: list[JsonDict]


class StepRunner:
    """Executes one node step and returns a ``StepExecutionResult``.

    Responsibilities:
    - Resolve input artifacts from parent step outputs.
    - Instantiate the node via ``NodeRegistry``.
    - Validate node parameters.
    - Build ``ExecutionContext``.
    - Call ``node.run(context)``.
    - Validate ``NodeOutput``.
    - Build the execution fingerprint.
    - Return a typed success/failure result.

    Does NOT:
    - Own run lifecycle or finalisation.
    - Persist run steps, evidence, or lineage.
    - Copy evidence for reuse.
    - Decide staleness.
    Note: *node* execution may still write artifacts to disk via
    ``context.store`` before returning ``NodeOutput`` — this method
    does not persist *run-step metadata*.
    """

    def __init__(self, store: ProjectStore, node_registry: NodeRegistry) -> None:
        self._store = store
        self._node_registry = node_registry

    def run_step(
        self,
        plan_version_id: str,
        run_id: str,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, RunStep],
    ) -> StepExecutionResult:
        """Execute a single step and return a typed result.

        Does not persist anything — the caller must record the result
        via a persistence collaborator.
        """
        parent_run_steps: list[RunStep] = [
            rs
            for pid in spec.parent_step_ids
            if (rs := run_step_records.get(pid)) is not None
        ]
        input_artifacts: list[ArtifactRef] = []
        input_artifact_ids_by_parent: dict[str, list[str]] = {}

        try:
            input_artifacts = self._resolve_inputs(spec, step_outputs)

            for pid in spec.parent_step_ids:
                parent_artifacts = step_outputs.get(pid, [])
                input_artifact_ids_by_parent[pid] = [
                    a.artifact_id for a in parent_artifacts
                ]

            node = self._node_registry.instantiate(spec.node_type)
            validation_errors = node.validate_params(dict(spec.params))
            if validation_errors:
                raise ParameterValidationError(
                    f"Step {spec.step_id!r} parameter validation "
                    f"failed: {'; '.join(validation_errors)}",
                    context={
                        "plan_version_id": plan_version_id,
                        "step_id": spec.step_id,
                        "node_type": spec.node_type,
                        "errors": validation_errors,
                    },
                )

            context = ExecutionContext(
                store=self._store,
                run_id=run_id,
                plan_version_id=plan_version_id,
                step_spec=spec,
                parent_run_steps=parent_run_steps,
                input_artifacts=input_artifacts,
                validated_params=dict(spec.params),
                runtime_metadata={
                    "run_id": run_id,
                    "plan_version_id": plan_version_id,
                    "step_id": spec.step_id,
                    "node_type": spec.node_type,
                },
            )

            node_output = node.run(context)
            if not isinstance(node_output, NodeOutput):
                raise TypeError(
                    f"Node {spec.node_type!r} returned "
                    f"{type(node_output)!r} instead of NodeOutput"
                )

            output_artifacts = list(node_output.artifacts)

            fp = build_execution_fingerprint(
                plan_version_id,
                spec,
                parent_run_steps,
                input_artifacts,
                output_artifacts,
            )
            if node_output.execution_fingerprint:
                fp.update(node_output.execution_fingerprint)
            if node_output.metrics:
                fp["node_metrics"] = dict(node_output.metrics)
            fp = _json_ready(fp)

            return StepExecutionResult(
                step_id=spec.step_id,
                node_type=spec.node_type,
                status=RunStepStatus.SUCCEEDED,
                fingerprint=fp,
                input_artifact_ids=[a.artifact_id for a in input_artifacts],
                input_artifact_ids_by_parent=input_artifact_ids_by_parent,
                output_artifact_ids=[a.artifact_id for a in output_artifacts],
                parent_run_steps=parent_run_steps,
                warnings=list(node_output.warnings or []),
                errors=[],
            )

        except Exception:
            tb = traceback.format_exc()
            exc_value = sys.exc_info()[1]
            error_entry = classify_step_failure(exc_value, tb)

            recorded_input_ids = [a.artifact_id for a in input_artifacts]
            fp = build_execution_fingerprint(
                plan_version_id,
                spec,
                parent_run_steps,
                input_artifacts,
                [],
            )
            fp = _json_ready(fp)

            return StepExecutionResult(
                step_id=spec.step_id,
                node_type=spec.node_type,
                status=RunStepStatus.FAILED,
                fingerprint=fp,
                input_artifact_ids=recorded_input_ids,
                input_artifact_ids_by_parent=input_artifact_ids_by_parent,
                output_artifact_ids=[],
                parent_run_steps=parent_run_steps,
                warnings=[],
                errors=[error_entry],
            )

    @staticmethod
    def _resolve_inputs(
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
    ) -> list[ArtifactRef]:
        """Resolve input artifacts from parent step outputs."""
        if not spec.parent_step_ids:
            return []
        artifacts: list[ArtifactRef] = []
        for pid in spec.parent_step_ids:
            parent_outputs = step_outputs.get(pid)
            if parent_outputs is None:
                raise MissingInputArtifactError(
                    f"Step {spec.step_id!r}: parent {pid!r} has no outputs "
                    "(not executed or missing)"
                )
            artifacts.extend(parent_outputs)
        return artifacts


__all__ = ["StepExecutionResult", "StepRunner"]
