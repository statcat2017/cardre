"""StepRunner — executes one node step within the new execution runtime.

Builds ``NodeContext`` from ports, calls ``node.run()``, validates outputs,
builds fingerprint, returns ``StepExecutionResult``.  Does NOT persist.
"""
from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cardre.application.execution.failure_classification import classify_step_failure
from cardre.application.execution.fingerprints import build_execution_fingerprint
from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import JsonDict
from cardre.domain.errors import NodeFailedWithArtifacts, NodeRoleAccessViolation
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec
from cardre.nodes.contracts import (
    ArtifactContract,
    NodeContext,
    NodeResult,
    RuntimeMeta,
)
from cardre.nodes.parameters import normalize_node_params


@dataclass
class StepExecutionResult:
    step_id: str
    node_type: str
    status: RunStepStatus
    fingerprint: JsonDict
    input_artifact_ids: list[str]
    output_artifact_ids: list[str]
    staged_artifacts: list[StagedArtifact] = field(default_factory=list)
    parent_run_steps: list[Any] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    errors: list[JsonDict] = field(default_factory=list)


class StepRunner:
    def __init__(
        self,
        node_catalogue: Any,
        artifact_store_factory: Callable[[], Any],
        evidence_reader_factory: Callable[[], Any],
    ) -> None:
        self._node_catalogue = node_catalogue
        self._artifact_store_factory = artifact_store_factory
        self._evidence_reader_factory = evidence_reader_factory

    def run_step(
        self,
        plan_version_id: str,
        run_id: str,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
        run_step_records: dict[str, Any],
        cancel_requested: bool = False,
    ) -> StepExecutionResult:
        from cardre.application.execution.input_collection import StepInputCollection
        from cardre.application.execution.output_publisher import StagingOutputPublisher

        parent_run_steps = [
            rs for pid in spec.parent_step_ids
            if (rs := run_step_records.get(pid)) is not None
        ]
        input_artifact_ids_by_parent: dict[str, list[str]] = {}
        input_artifacts: list[ArtifactRef] = []
        staged: list[StagedArtifact] = []

        try:
            # Resolve inputs from parent step outputs
            resolved = self._resolve_inputs(spec, step_outputs)

            # Instantiate node
            node = self._node_catalogue.instantiate(spec.node_type)

            # Normalize params
            schema = node.parameter_schema()
            if schema is not None:
                normalized_params = normalize_node_params(schema, dict(spec.params))
            else:
                normalized_params = dict(spec.params)

            validation_errors = node.validate_params(normalized_params)
            if validation_errors:
                from cardre.domain.errors import ParameterValidationError
                raise ParameterValidationError(
                    f"Step {spec.step_id!r} validation failed: {'; '.join(validation_errors)}"
                )

            input_roles = [
                rs.role for rs in node.__definition__.input_contract.roles
            ] if hasattr(node.__definition__, 'input_contract') and node.__definition__.input_contract.roles else (
                getattr(node, 'input_roles', []) or []
            )
            input_artifacts = self._filter_input_artifacts(spec, input_roles, resolved)

            for pid in spec.parent_step_ids:
                parent_arts = step_outputs.get(pid, [])
                input_artifact_ids_by_parent[pid] = [
                    a.artifact_id for a in parent_arts if a in input_artifacts
                ]

            artifact_store = self._artifact_store_factory()
            evidence_reader = self._evidence_reader_factory()

            inputs = StepInputCollection(evidence_reader, input_artifacts)

            output_contract = getattr(node.__definition__, 'output_contract', ArtifactContract())
            outputs = StagingOutputPublisher(artifact_store)

            runtime = RuntimeMeta(
                run_id=run_id,
                plan_version_id=plan_version_id,
                step_id=spec.step_id,
                node_type=spec.node_type,
            )

            context = NodeContext(
                run_id=run_id,
                plan_version_id=plan_version_id,
                step_spec=spec,
                inputs=inputs,
                outputs=outputs,
                params=normalized_params,
                runtime=runtime,
            )

            result = node.run(context)
            if not isinstance(result, NodeResult):
                raise TypeError(
                    f"Node {spec.node_type!r} returned {type(result)!r} instead of NodeResult"
                )

            staged = list(result.staged_artifacts)

            self._validate_output_roles(output_contract, staged, spec)

            output_artifact_ids = [
                s.provisional_artifact_id for s in staged
            ]
            fp = build_execution_fingerprint(
                plan_version_id, spec, parent_run_steps,
                input_artifacts, staged,
            )
            if result.execution_fingerprint:
                fp.update(result.execution_fingerprint)
            if result.metrics:
                fp["node_metrics"] = dict(result.metrics)

            return StepExecutionResult(
                step_id=spec.step_id,
                node_type=spec.node_type,
                status=RunStepStatus.SUCCEEDED,
                fingerprint=fp,
                input_artifact_ids=[a.artifact_id for a in input_artifacts],
                output_artifact_ids=output_artifact_ids,
                staged_artifacts=staged,
                parent_run_steps=parent_run_steps,
                warnings=list(result.warnings or []),
            )

        except NodeFailedWithArtifacts as exc:
            staged = list(getattr(exc, 'staged_artifacts', []))
            fp = build_execution_fingerprint(
                plan_version_id, spec, parent_run_steps,
                input_artifacts, staged,
            )
            error_entry = classify_step_failure(exc, traceback.format_exc())
            return StepExecutionResult(
                step_id=spec.step_id,
                node_type=spec.node_type,
                status=RunStepStatus.FAILED,
                fingerprint=fp,
                input_artifact_ids=[a.artifact_id for a in input_artifacts],
                output_artifact_ids=[s.provisional_artifact_id for s in staged],
                staged_artifacts=staged,
                parent_run_steps=parent_run_steps,
                errors=[error_entry],
            )

        except Exception as exc:
            tb = traceback.format_exc()
            error_entry = classify_step_failure(exc, tb)
            fp = build_execution_fingerprint(
                plan_version_id, spec, parent_run_steps,
                input_artifacts, [],
            )
            return StepExecutionResult(
                step_id=spec.step_id,
                node_type=spec.node_type,
                status=RunStepStatus.FAILED,
                fingerprint=fp,
                input_artifact_ids=[a.artifact_id for a in input_artifacts],
                output_artifact_ids=[],
                parent_run_steps=parent_run_steps,
                errors=[error_entry],
            )

    def _resolve_inputs(
        self,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
    ) -> list[ArtifactRef]:
        resolved: list[ArtifactRef] = []
        seen_ids: set[str] = set()
        for pid in spec.parent_step_ids:
            for art in step_outputs.get(pid, []):
                if art.artifact_id not in seen_ids:
                    resolved.append(art)
                    seen_ids.add(art.artifact_id)
        return resolved

    def _filter_input_artifacts(
        self,
        spec: StepSpec,
        allowed: list[str],
        artifacts: list[ArtifactRef],
    ) -> list[ArtifactRef]:
        if not allowed:
            return list(artifacts)
        if not artifacts:
            return artifacts
        filtered = [a for a in artifacts if a.role in allowed]
        if filtered:
            return filtered
        raise NodeRoleAccessViolation(
            f"Step {spec.step_id!r} received artifacts with roles "
            f"{sorted({a.role for a in artifacts})}, none match "
            f"input contract {sorted(allowed)}"
        )

    def _validate_output_roles(
        self,
        output_contract: ArtifactContract,
        staged: list[StagedArtifact],
        spec: StepSpec,
    ) -> None:
        required_roles = {
            rs.role for rs in output_contract.roles if rs.required
        }
        if not required_roles:
            return
        produced_roles = {s.role for s in staged}
        missing = required_roles - produced_roles
        if missing:
            raise ValueError(
                f"Step {spec.step_id!r} ({spec.node_type}) missing required "
                f"output roles: {missing}"
            )
