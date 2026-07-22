"""Node contracts: NodeDefinition, NodeContext, InputCollection, OutputPublisher, NodeType."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import polars as pl

from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.step import StepSpec
from cardre.nodes.parameters import NodeParameterSchema


@dataclass(frozen=True)
class ArtifactRoleSpec:
    role: str
    required: bool = True
    kinds: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactContract:
    roles: tuple[ArtifactRoleSpec, ...] = ()
    # Backward-compat: old nodes use input_roles/output_roles as lists
    input_roles: tuple[str, ...] = ()
    output_roles: tuple[str, ...] = ()

    @property
    def input_roles_list(self) -> list[str]:
        return list(self.input_roles)

    @property
    def output_roles_list(self) -> list[str]:
        return list(self.output_roles)


@dataclass(frozen=True)
class NodeDefinition:
    node_type: str
    version: str
    category: str
    description: str
    input_contract: ArtifactContract
    output_contract: ArtifactContract
    parameter_schema: NodeParameterSchema | None = None
    optional_dependencies: tuple[str, ...] = ()
    tier: str = "launch"


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
    def read(self, artifact: Any, kind: EvidenceKind) -> Any: ...
    def read_optional(self, artifact: Any, kind: EvidenceKind) -> Any | None: ...
    def read_dataframe(self, artifact: Any) -> pl.DataFrame: ...
    def target_metadata(self) -> Any | None: ...
    def find_frozen_bundle(self) -> Any | None: ...


@runtime_checkable
class OutputPublisher(Protocol):
    def publish_json(self, *, role: str, kind: EvidenceKind, payload: JsonDict,
                     metadata: JsonDict | None = None) -> Any: ...
    def publish_table(self, *, role: str, kind: EvidenceKind, frame: pl.DataFrame,
                      metadata: JsonDict | None = None) -> Any: ...
    def add_metric(self, name: str, value: float | int | str | bool) -> None: ...
    def add_warning(self, warning: JsonDict) -> None: ...
    def set_execution_fingerprint(self, fp: JsonDict) -> None: ...
    def build_result(self) -> Any: ...


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
    params: JsonDict
    runtime: RuntimeMeta


class NodeType(ABC):
    """Abstract base for all node types. Old nodes (pre-Batch 03) use class-level
    attributes; new nodes define ``__definition__``."""

    node_type: str = ""
    version: str = ""
    category: str = ""
    description: str = ""
    optional_dependencies: list[str] | None = None
    _deferred: bool = False

    @property
    def __definition__(self) -> NodeDefinition:
        """Backward-compatible accessor for nodes that don't set __definition__ explicitly."""
        if hasattr(self, '__definition_cached'):
            return self.__definition_cached
        defn = NodeDefinition(
            node_type=self.node_type,
            version=self.version,
            category=self.category,
            description=self.description or "",
            input_contract=ArtifactContract(),
            output_contract=ArtifactContract(),
            parameter_schema=self.parameter_schema(),
            optional_dependencies=tuple(self.optional_dependencies or []),
            tier="deferred" if self._deferred else "launch",
        )
        self.__definition_cached = defn  # type: ignore[attr-defined]
        return defn

    @abstractmethod
    def run(self, context: Any) -> NodeResult: ...

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        return []

    @classmethod
    def contract(cls) -> ArtifactContract:
        ir = tuple(getattr(cls, "input_roles", []))
        o_r = tuple(getattr(cls, "output_roles", []))
        return ArtifactContract(
            input_roles=ir,
            output_roles=o_r,
        )

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema | None:
        return None
