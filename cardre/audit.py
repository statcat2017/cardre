"""Audit-trail data structures and hashing utilities.

Phase 1: every artifact has both physical_hash (raw file bytes) and
logical_hash (canonical representation) for reproducibility and staleness.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from cardre.store import ProjectStore


JsonDict = dict[str, Any]


CHUNK_SIZE = 1024 * 1024


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def physical_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_logical_hash(data: JsonDict) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def table_logical_hash(table: pl.DataFrame) -> str:
    sorted_cols = sorted(table.columns)
    table = table.select(sorted_cols)
    arrow_table = table.to_arrow()
    import io
    import pyarrow as pa
    buf = io.BytesIO()
    with pa.ipc.new_file(buf, arrow_table.schema) as writer:
        writer.write_table(arrow_table)
    return hashlib.sha256(buf.getvalue()).hexdigest()


def params_hash(params: JsonDict) -> str:
    return json_logical_hash(params)


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    role: str
    path: str
    physical_hash: str
    logical_hash: str
    media_type: str = "application/octet-stream"
    created_at: str = ""
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "role": self.role,
            "path": self.path,
            "physical_hash": self.physical_hash,
            "logical_hash": self.logical_hash,
            "media_type": self.media_type,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> ArtifactRef:
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            role=data["role"],
            path=data["path"],
            physical_hash=data["physical_hash"],
            logical_hash=data["logical_hash"],
            media_type=data.get("media_type", "application/octet-stream"),
            created_at=data.get("created_at", ""),
            metadata=dict(data.get("metadata", {})),
        )


class NodeType(ABC):
    node_type: str
    version: str
    category: str
    input_roles: list[str]
    output_roles: list[str]
    is_internal: bool = False
    is_deprecated: bool = False
    replacement_node_type: str | None = None

    @abstractmethod
    def run(self, context: ExecutionContext) -> NodeOutput:
        ...

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate param values and return a list of error messages.

        Executed at *run time* (just before ``run()``). The primary
        validation path is the schema layer (``parameter_schema`` +
        ``validate_against_schema``) at *plan-submission time*. Override
        this only for cross-parameter or runtime checks the schema
        cannot express.

        An empty list means the params are valid."""
        return []

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        """Return a parameter schema describing this node's method options and params.

        Used at *plan-submission time* for UI rendering, default merging,
        and schema-level validation (``validate_against_schema``).  Subclasses
        that participate in the Node Method & Parameter Schema Framework
        should override this to provide full metadata.

        The default implementation returns an empty schema."""
        from cardre.node_parameters import NodeParameterSchema as _NodeParameterSchema
        return _NodeParameterSchema(
            node_type=cls.node_type,
            node_version=getattr(cls, "version", "1"),
            title=cls.node_type,
        )


@dataclass
class ExecutionContext:
    store: ProjectStore
    run_id: str
    plan_version_id: str
    step_spec: StepSpec
    parent_run_steps: list[RunStepRecord]
    input_artifacts: list[ArtifactRef]
    validated_params: JsonDict
    runtime_metadata: JsonDict


@dataclass
class NodeOutput:
    artifacts: list[ArtifactRef]
    metrics: JsonDict
    execution_fingerprint: JsonDict | None = None


@dataclass(frozen=True)
class StepSpec:
    step_id: str
    node_type: str
    node_version: str
    category: str
    params: JsonDict
    params_hash: str
    parent_step_ids: list[str]
    branch_label: str
    position: int
    canonical_step_id: str = field(default="", kw_only=True)
    branch_id: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.canonical_step_id:
            object.__setattr__(self, "canonical_step_id", self.step_id)

    def to_dict(self) -> JsonDict:
        return {
            "step_id": self.step_id,
            "node_type": self.node_type,
            "node_version": self.node_version,
            "category": self.category,
            "params": self.params,
            "params_hash": self.params_hash,
            "parent_step_ids": self.parent_step_ids,
            "branch_label": self.branch_label,
            "position": self.position,
            "canonical_step_id": self.canonical_step_id,
            "branch_id": self.branch_id,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> StepSpec:
        return cls(
            step_id=data["step_id"],
            node_type=data["node_type"],
            node_version=data["node_version"],
            category=data["category"],
            params=dict(data.get("params", {})),
            params_hash=data.get("params_hash", json_logical_hash(dict(data.get("params", {})))),
            parent_step_ids=list(data.get("parent_step_ids", [])),
            branch_label=data.get("branch_label", ""),
            position=data.get("position", 0),
            canonical_step_id=data.get("canonical_step_id", data["step_id"]),
            branch_id=data.get("branch_id"),
        )


@dataclass(frozen=True)
class RunStepRecord:
    run_step_id: str
    run_id: str
    step_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None
    input_artifact_ids: list[str]
    output_artifact_ids: list[str]
    execution_fingerprint: JsonDict
    warnings: list[JsonDict]
    errors: list[JsonDict]
    is_carried_forward: bool = False


def replace_step_params(
    steps: list[StepSpec],
    step_id: str,
    new_params: JsonDict,
) -> list[StepSpec]:
    new_params_hash = json_logical_hash(new_params)
    return [
        StepSpec(
            step_id=s.step_id,
            node_type=s.node_type,
            node_version=s.node_version,
            category=s.category,
            params=new_params if s.step_id == step_id else s.params,
            params_hash=new_params_hash if s.step_id == step_id else s.params_hash,
            parent_step_ids=s.parent_step_ids,
            branch_label=s.branch_label,
            position=s.position,
            canonical_step_id=s.canonical_step_id,
            branch_id=s.branch_id,
        )
        for s in steps
    ]


__all__ = [
    "ArtifactRef",
    "ExecutionContext",
    "JsonDict",
    "NodeOutput",
    "NodeType",
    "RunStepRecord",
    "StepSpec",
    "json_logical_hash",
    "params_hash",
    "physical_hash",
    "relative_path",
    "replace_step_params",
    "table_logical_hash",
    "utc_now_iso",
]
