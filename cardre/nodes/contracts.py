"""Node contracts: NodeDefinition, NodeContext, InputCollection, OutputPublisher, NodeType."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import polars as pl

from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.step import StepSpec
from cardre.nodes._params import NodeParams
from cardre.nodes.parameters import NodeParameterSchema


@dataclass(frozen=True)
class ArtifactRoleSpec:
    role: str
    required: bool = True
    kinds: tuple[Any, ...] = ()
    media_types: tuple[str, ...] = ()
    schema_versions: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ArtifactContract:
    roles: tuple[ArtifactRoleSpec, ...] = ()


@dataclass(frozen=True)
class NodeDefinition:
    """The single contract source for a node.

    Carries identity (node_type, version, category, description) and the
    typed input/output contracts. Runtime authorities for optional
    dependencies and parameter schemas live on the ``NodeType`` class and are
    consumed directly by the catalogue and ``StepRunner``.
    """
    node_type: str
    version: str
    category: str
    description: str
    input_contract: ArtifactContract
    output_contract: ArtifactContract


@dataclass
class RuntimeMeta:
    run_id: str
    plan_version_id: str
    step_id: str
    node_type: str


@runtime_checkable
class InputCollection(Protocol):
    def by_role(self, role: str) -> list[Any]: ...
    def by_kind(self, kind: EvidenceKind) -> list[Any]: ...
    def first(self, role: str) -> Any | None: ...
    def require(self, role: str, node_type: str) -> Any: ...
    def require_kind(self, kind: EvidenceKind, node_type: str) -> Any: ...
    def read(self, artifact: Any, kind: EvidenceKind) -> Any: ...
    def read_optional(self, artifact: Any, kind: EvidenceKind) -> Any | None: ...
    def read_dataframe(self, artifact: Any) -> pl.DataFrame: ...
    def read_bytes(self, artifact: Any) -> bytes: ...
    def target_metadata(self) -> Any | None: ...
    def find_frozen_bundle(self) -> Any | None: ...
    def artifact_ref(self, artifact_id: str) -> Any | None: ...


@runtime_checkable
class OutputPublisher(Protocol):
    def publish_json(self, *, role: str, kind: EvidenceKind, payload: JsonDict,
                     metadata: JsonDict | None = None) -> Any: ...
    def publish_table(self, *, role: str, kind: EvidenceKind, frame: pl.DataFrame,
                      metadata: JsonDict | None = None,
                      artifact_type: str | None = None) -> Any: ...
    def publish_bytes(self, *, role: str, kind: EvidenceKind, data: bytes,
                      media_type: str, logical_hash: str,
                      metadata: JsonDict | None = None) -> Any: ...
    def add_metric(self, name: str, value: float | int | str | bool) -> None: ...
    def add_warning(self, warning: JsonDict) -> None: ...
    def set_execution_fingerprint(self, fp: JsonDict) -> None: ...
    def build_result(self) -> NodeResult: ...


@dataclass
class NodeResult:
    staged_artifacts: list[Any] = field(default_factory=list)
    metrics: JsonDict = field(default_factory=dict)
    execution_fingerprint: JsonDict | None = None
    warnings: list[JsonDict] = field(default_factory=list)


@dataclass(frozen=True)
class NodeContext:
    run_id: str
    plan_version_id: str
    step_spec: StepSpec
    inputs: InputCollection
    outputs: OutputPublisher
    params: NodeParams
    runtime: RuntimeMeta


class NodeType(ABC):
    """Abstract base for all node types.

    Every executable node declares exactly one explicit ``__definition__``
    (a ``NodeDefinition``) as its single contract source.
    """

    node_type: str = ""
    version: str = ""
    category: str = ""
    description: str = ""
    optional_dependencies: list[str] | None = None

    @classmethod
    def node_definition(cls) -> NodeDefinition:
        """The single authoritative ``NodeDefinition`` for this node type."""
        return cls.__definition__

    @abstractmethod
    def run(self, context: Any) -> Any: ...

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return []

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema | None:
        return None
