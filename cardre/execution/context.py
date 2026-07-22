"""Backward-compat shim: preserved for deferred-tier nodes.

This module will be removed when all nodes are ported to ``NodeContext``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class TargetMeta:
    target_column: str
    good_values: frozenset[str]
    bad_values: frozenset[str]
    indeterminate_values: frozenset[str] = frozenset()
    all_known: frozenset[str] = frozenset()


class ExecutionContext:
    """Legacy execution context — preserved for deferred-tier nodes."""

    def __init__(
        self,
        store: Any,
        run_id: str,
        plan_version_id: str,
        step_spec: Any,
        parent_run_steps: list[Any],
        input_artifacts: list[ArtifactRef],
        validated_params: JsonDict,
        runtime_metadata: JsonDict,
    ) -> None:
        self.store = store
        self.run_id = run_id
        self.plan_version_id = plan_version_id
        self.step_spec = step_spec
        self.parent_run_steps = parent_run_steps
        self.input_artifacts = input_artifacts
        self.validated_params = validated_params
        self.runtime_metadata = runtime_metadata

    def data_artifacts(self, roles: tuple[str, ...] | None = None) -> list[ArtifactRef]:
        if roles is None:
            from cardre.execution.context import ROLES_DATA
            roles = ROLES_DATA
        return [a for a in self.input_artifacts if a.role in roles]

    def train_artifact(self) -> ArtifactRef | None:
        return next((a for a in self.input_artifacts if a.role == "train"), None)

    def require_train_artifact(self, node_type: str) -> ArtifactRef:
        art = self.train_artifact()
        if art is None:
            raise ValueError(f"{node_type} requires a train artifact")
        return art

    def find_frozen_bundle(self) -> ArtifactRef | None:
        from cardre.domain.evidence.schemas import SCHEMA_FROZEN_SCORECARD_BUNDLE
        return next(
            (a for a in self.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )

    def target_metadata(self) -> TargetMeta | None:
        return None


@dataclass
class NodeOutput:
    artifacts: list[ArtifactRef]
    metrics: JsonDict
    execution_fingerprint: JsonDict | None = None
    warnings: list[JsonDict] | None = None


ROLES_DATA = ("train", "test", "oot")
