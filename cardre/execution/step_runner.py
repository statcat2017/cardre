"""Step runner — executes one node step and returns a typed result.

Extracted from ``PlanExecutor._execute_step``.  The step runner resolves
inputs, instantiates and validates the node, builds an execution context,
calls ``node.run()``, builds the execution fingerprint, and returns a
``StepExecutionResult`` describing success or failure.

The step runner does NOT persist anything — the caller (PlanExecutor) is
responsible for recording the result via a persistence collaborator.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cardre.domain.errors import (
    MissingInputArtifactError,
    NodeFailedWithArtifacts,
    NodeRoleAccessViolation,
    ParameterValidationError,
)
from cardre.domain.run import RunStep, RunStepStatus
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.execution.failure_classification import classify_step_failure
from cardre.execution.fingerprints import _json_ready, build_execution_fingerprint
from cardre.nodes.parameters import normalize_node_params
from cardre.nodes.registry import NodeRegistry

if TYPE_CHECKING:
    from cardre.domain.diagnostics import JsonDict
    from cardre.domain.step import StepSpec
    from cardre.store.db import ProjectStore

from cardre.domain.artifacts import ArtifactRef
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.run_step_repo import RunStepRepository


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
        resolved_input_artifacts: list[ArtifactRef] = []
        input_artifact_ids_by_parent: dict[str, list[str]] = {}

        try:
            resolved_input_artifacts = self._resolve_inputs(spec, step_outputs)

            node = self._node_registry.instantiate(spec.node_type)

            schema = node.parameter_schema()
            if schema is not None:
                try:
                    normalized_params = normalize_node_params(schema, dict(spec.params))
                except (ValueError, TypeError) as e:
                    raise ParameterValidationError(
                        f"Step {spec.step_id!r} parameter normalization "
                        f"failed: {e}",
                        context={
                            "plan_version_id": plan_version_id,
                            "step_id": spec.step_id,
                            "node_type": spec.node_type,
                            "error": str(e),
                        },
                    ) from e
            else:
                normalized_params = dict(spec.params)

            validation_errors = node.validate_params(normalized_params)
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
            input_artifacts = self._filter_input_artifacts(
                spec, node.contract().input_roles, resolved_input_artifacts,
            )

            for pid in spec.parent_step_ids:
                parent_artifacts = step_outputs.get(pid, [])
                input_artifact_ids_by_parent[pid] = [
                    a.artifact_id for a in parent_artifacts
                    if a in input_artifacts
                ]

            # Build the context: new-style nodes that have an explicit
            # __definition__ class variable get a NodeContext; old-style
            # nodes that rely on the backward-compat property get the
            # legacy ExecutionContext.
            if '__definition__' in type(node).__dict__:
                try:
                    bridge = _build_node_context_bridge(self._store, run_id, plan_version_id, spec, input_artifacts, normalized_params)
                    node_output_raw = node.run(bridge.node_context)
                    node_output = _node_result_to_output(node_output_raw, bridge)
                except Exception as exc:
                    raise RuntimeError(
                        f"Bridge execution failed for {spec.node_type!r}: {exc}"
                    ) from exc
            else:
                context = ExecutionContext(
                    store=self._store,
                    run_id=run_id,
                    plan_version_id=plan_version_id,
                    step_spec=spec,
                    parent_run_steps=parent_run_steps,
                    input_artifacts=input_artifacts,
                    validated_params=normalized_params,
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

        except NodeFailedWithArtifacts as exc:
            tb = traceback.format_exc()
            error_entry = classify_step_failure(exc, tb)

            recorded_input_ids = [a.artifact_id for a in input_artifacts]
            output_artifact_ids = [a.artifact_id for a in exc.artifacts]
            fp = build_execution_fingerprint(
                plan_version_id,
                spec,
                parent_run_steps,
                input_artifacts,
                exc.artifacts,
            )

            return StepExecutionResult(
                step_id=spec.step_id,
                node_type=spec.node_type,
                status=RunStepStatus.FAILED,
                fingerprint=fp,
                input_artifact_ids=recorded_input_ids,
                input_artifact_ids_by_parent=input_artifact_ids_by_parent,
                output_artifact_ids=output_artifact_ids,
                parent_run_steps=parent_run_steps,
                warnings=list(exc.warnings or []),
                errors=[error_entry],
            )

        except (NodeRoleAccessViolation, MissingInputArtifactError, ParameterValidationError):
            tb = traceback.format_exc()
            error_entry = classify_step_failure(sys.exc_info()[1], tb)

            recorded_input_ids = [a.artifact_id for a in input_artifacts]
            fp = build_execution_fingerprint(
                plan_version_id,
                spec,
                parent_run_steps,
                input_artifacts,
                [],
            )

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

        except Exception:
            tb = traceback.format_exc()
            error_entry = classify_step_failure(sys.exc_info()[1], tb)
            recorded_input_ids = [a.artifact_id for a in input_artifacts]

            fp = build_execution_fingerprint(
                plan_version_id,
                spec,
                parent_run_steps,
                input_artifacts,
                [],
            )

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

    def _resolve_inputs(
        self,
        spec: StepSpec,
        step_outputs: dict[str, list[ArtifactRef]],
    ) -> list[ArtifactRef]:
        from cardre.store.artifact_repo import ArtifactRepository

        repo = ArtifactRepository(self._store)
        resolved: list[ArtifactRef] = []
        seen_ids: set[str] = set()
        for pid in spec.parent_step_ids:
            for art in step_outputs.get(pid, []):
                # Re-read from store so we get the authoritative record
                ref = repo.get(art.artifact_id)
                if ref is not None and ref.artifact_id not in seen_ids:
                    resolved.append(ref)
                    seen_ids.add(ref.artifact_id)
                elif ref is None and art.artifact_id not in seen_ids:
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
            return artifacts
        if not artifacts:
            return artifacts
        filtered = [artifact for artifact in artifacts if artifact.role in allowed]
        if filtered:
            return filtered
        unexpected = sorted({artifact.role for artifact in artifacts})
        raise NodeRoleAccessViolation(
            f"Step {spec.step_id!r} ({spec.node_type}) received artifact role(s) "
            f"{unexpected}, but none match its input contract {sorted(allowed)}.",
            context={
                "step_id": spec.step_id,
                "node_type": spec.node_type,
                "unexpected_roles": unexpected,
                "allowed_roles": sorted(allowed),
            },
        )


# ---------------------------------------------------------------------------
# Backward-compat bridge: old-style step_runner calling new-style nodes
# ---------------------------------------------------------------------------


@dataclass
class _NodeContextBridge:
    """Carries a NodeContext plus the store/repo needed to publish staged artifacts."""
    node_context: Any
    fs_store: Any
    artifact_repo: Any

    def __getattr__(self, name: str) -> Any:
        return getattr(self.node_context, name)


def _build_node_context_bridge(
    store: ProjectStore,
    run_id: str,
    plan_version_id: str,
    spec: StepSpec,
    input_artifacts: list[ArtifactRef],
    normalized_params: JsonDict,
) -> _NodeContextBridge:
    """Build a NodeContext from the old execution-path plumbing.

    New-style nodes (those with ``__definition__``) expect a ``NodeContext``.
    The step runner constructs this bridge so old execution-path callers can
    invoke migrated nodes without changes.
    """
    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.application.execution.input_collection import StepInputCollection
    from cardre.application.execution.output_publisher import StagingOutputPublisher
    from cardre.nodes.contracts import NodeContext, RuntimeMeta

    _reader = _StoreArtifactReader(store)
    _artifact_repo = ArtifactRepository(store)
    _run_step_repo = RunStepRepository(store)
    _evidence_reader = EvidenceReader(_reader, _artifact_repo, _run_step_repo)

    inputs = StepInputCollection(_evidence_reader, input_artifacts)

    _fs_store = FsArtifactStore(store.root / "objects")
    outputs = StagingOutputPublisher(_fs_store)

    return _NodeContextBridge(
        node_context=NodeContext(
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=spec,
            inputs=inputs,
            outputs=outputs,
            params=normalized_params,
            runtime=RuntimeMeta(
                run_id=run_id,
                plan_version_id=plan_version_id,
                step_id=spec.step_id,
                node_type=spec.node_type,
            ),
        ),
        fs_store=_fs_store,
        artifact_repo=_artifact_repo,
    )


def _node_result_to_output(
    result: Any,
    bridge: _NodeContextBridge,
) -> NodeOutput:
    """Convert a ``NodeResult`` to a legacy ``NodeOutput``.

    Publishes any staged artifacts and registers them in the artifact repo
    so the old execution path can read artifact IDs from the output.
    """

    if isinstance(result, NodeOutput):
        return result

    staged = getattr(result, "staged_artifacts", []) or []
    metrics = getattr(result, "metrics", {}) or {}
    fingerprint = getattr(result, "execution_fingerprint", None)
    warnings = getattr(result, "warnings", None) or None

    if not staged:
        return NodeOutput(artifacts=[], metrics=metrics, execution_fingerprint=fingerprint, warnings=warnings)

    artifact_refs: list[ArtifactRef] = []
    for sa in staged:
        path = bridge.fs_store.publish(sa)
        art_ref = ArtifactRef(
            artifact_id=sa.provisional_artifact_id,
            artifact_type=sa.artifact_type,
            role=sa.role,
            path=str(path),
            physical_hash=sa.physical_hash,
            logical_hash=sa.logical_hash,
            media_type=sa.media_type,
            metadata=sa.metadata,
        )
        bridge.artifact_repo.register(art_ref)
        artifact_refs.append(art_ref)

    return NodeOutput(
        artifacts=artifact_refs,
        metrics=metrics,
        execution_fingerprint=fingerprint,
        warnings=warnings,
    )


class _StoreArtifactReader:
    """Minimal ``ArtifactReader`` adapter wrapping a ``ProjectStore``."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def read_bytes(self, artifact: object) -> bytes:
        if isinstance(artifact, ArtifactRef):
            return self._store.artifact_path(artifact).read_bytes()  # cardre-allow-artifact-read: low-level-evidence-parser
        artifact_id = str(artifact)
        from cardre.store.artifact_repo import ArtifactRepository
        art_ref = ArtifactRepository(self._store).get(artifact_id)
        if art_ref is not None:
            return self._store.artifact_path(art_ref).read_bytes()  # cardre-allow-artifact-read: low-level-evidence-parser
        raise ValueError(f"Cannot read artifact: {artifact_id}")

    def resolve_path(self, artifact: object) -> Path:
        if isinstance(artifact, ArtifactRef):
            return self._store.artifact_path(artifact)  # cardre-allow-artifact-read: low-level-evidence-parser
        return Path(str(artifact))


__all__ = ["StepExecutionResult", "StepRunner"]
