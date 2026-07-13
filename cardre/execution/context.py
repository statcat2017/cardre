"""Execution context and node output types.

These have execution coupling (store, run state) and belong in the
execution layer, not domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import SCHEMA_FROZEN_SCORECARD_BUNDLE

if TYPE_CHECKING:
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import JsonDict
    from cardre.domain.step import StepSpec
    from cardre.store import ProjectStore


ROLES_DATA = ("train", "test", "oot")


@dataclass(frozen=True)
class TargetMeta:
    target_column: str
    good_values: frozenset[str]
    bad_values: frozenset[str]
    indeterminate_values: frozenset[str]
    all_known: frozenset[str]


@dataclass
class ExecutionContext:
    """Full context passed to a node's run() method."""
    store: ProjectStore
    run_id: str
    plan_version_id: str
    step_spec: StepSpec
    parent_run_steps: list[Any]
    input_artifacts: list[ArtifactRef]
    validated_params: JsonDict
    runtime_metadata: JsonDict

    def data_artifacts(self, roles: tuple[str, ...] = ROLES_DATA) -> list[ArtifactRef]:
        return [a for a in self.input_artifacts if a.role in roles]

    def train_artifact(self) -> ArtifactRef | None:
        return next((a for a in self.input_artifacts if a.role == "train"), None)

    def require_train_artifact(self, node_type: str) -> ArtifactRef:
        art = self.train_artifact()
        if art is None:
            raise ValueError(f"{node_type} requires a train artifact")
        return art

    def find_frozen_bundle(self) -> ArtifactRef | None:
        return next(
            (a for a in self.input_artifacts
             if a.metadata.get("schema_version") == SCHEMA_FROZEN_SCORECARD_BUNDLE),
            None,
        )

    def target_metadata(self) -> TargetMeta | None:
        reader = ArtifactEvidenceReader(self.store)
        meta = reader.find_optional(self.input_artifacts, EvidenceKind.MODELLING_METADATA)
        if meta is None:
            return None
        return TargetMeta(
            target_column=meta.target_column,
            good_values=frozenset(str(v) for v in meta.good_values),
            bad_values=frozenset(str(v) for v in meta.bad_values),
            indeterminate_values=frozenset(str(v) for v in meta.indeterminate_values) if hasattr(meta, "indeterminate_values") else frozenset(),
            all_known=frozenset(str(v) for v in meta.all_known) if hasattr(meta, "all_known") else frozenset(),
        )


@dataclass
class NodeOutput:
    """Output produced by a single node execution."""
    artifacts: list[ArtifactRef]
    metrics: JsonDict
    execution_fingerprint: JsonDict | None = None
    warnings: list[JsonDict] | None = None


__all__ = ["ExecutionContext", "NodeOutput", "TargetMeta", "ROLES_DATA"]
