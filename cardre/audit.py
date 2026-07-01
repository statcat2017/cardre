"""V1 compatibility shim — re-exports from v2 modules.

Phase 5: existing node code (nodes/build/*, nodes/validate/*, prep.py,
reporting/collector.py, _evidence/*) imports from ``cardre.audit``.
These now live in ``cardre.domain.*``, ``cardre.execution.context``,
``cardre.nodes.contracts``, etc.

This shim preserves the v1 import surface so the ported node code
works without changing every import.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.artifacts import (
    CHUNK_SIZE,
    ArtifactRef,
    json_logical_hash,
    params_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.domain.diagnostics import JsonDict, parse_iso, utc_now_iso
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext, NodeOutput

# Re-export everything
# Note: NodeType is not in __all__ because it is imported lazily
# via __getattr__ to avoid circular imports with cardre.nodes.__init__.
__all__ = [
    "ArtifactRef",
    "CHUNK_SIZE",
    "ExecutionContext",
    "JsonDict",
    "NodeOutput",
    "RunStepRecord",
    "StepSpec",
    "json_logical_hash",
    "params_hash",
    "parse_iso",
    "physical_hash",
    "relative_path",
    "table_logical_hash",
    "utc_now_iso",
]


def __getattr__(name: str):
    """Lazy import of NodeType to avoid circular import.

    ``cardre.audit`` is imported by node code (via ``cardre.nodes.prep``),
    which in turn triggers ``cardre.nodes.__init__``.  ``cardre.nodes.contracts``
    is a leaf module with no ``cardre.audit`` import, so we resolve it lazily.
    """
    if name == "NodeType":
        from cardre.nodes.contracts import NodeType as _nt
        return _nt
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class RunStepRecord:
    """V1-compatible RunStepRecord with output_artifact_ids.

    In v2, ``RunStep`` does not carry artifact ID arrays — those are
    derived from ``evidence_edges`` + ``evidence_artifacts`` +
    ``artifact_lineage``.  This shim wraps a v2 ``RunStep`` and
    lazily resolves artifact IDs via the store.

    Compat shim used by reporting/collector.py and _evidence/reader.py.
    """

    def __init__(
        self,
        run_step: Any,
        store: Any | None = None,
    ) -> None:
        self._run_step = run_step
        self._store = store
        self._input_artifact_ids: list[str] | None = None
        self._output_artifact_ids: list[str] | None = None

    # --- Forwarded properties ---

    @property
    def run_step_id(self) -> str:
        return self._run_step.run_step_id

    @property
    def run_id(self) -> str:
        return self._run_step.run_id

    @property
    def step_id(self) -> str:
        return self._run_step.step_id

    @property
    def plan_version_id(self) -> str:
        return self._run_step.plan_version_id

    @property
    def status(self) -> str:
        return self._run_step.status.value if hasattr(self._run_step.status, 'value') else self._run_step.status

    @property
    def started_at(self) -> str:
        return self._run_step.started_at

    @property
    def finished_at(self) -> str | None:
        return self._run_step.finished_at

    @property
    def execution_fingerprint(self) -> JsonDict:
        return self._run_step.execution_fingerprint

    @property
    def warnings(self) -> list[JsonDict]:
        return self._run_step.warnings

    @property
    def errors(self) -> list[JsonDict]:
        return self._run_step.errors

    @property
    def is_carried_forward(self) -> bool:
        return False

    # --- Derived artifact IDs ---

    @property
    def input_artifact_ids(self) -> list[str]:
        if self._input_artifact_ids is not None:
            return self._input_artifact_ids
        self._input_artifact_ids = self._resolve_artifact_ids("input")
        return self._input_artifact_ids

    @property
    def output_artifact_ids(self) -> list[str]:
        if self._output_artifact_ids is not None:
            return self._output_artifact_ids
        self._output_artifact_ids = self._resolve_artifact_ids("output")
        return self._output_artifact_ids

    def _resolve_artifact_ids(self, direction: str) -> list[str]:
        if self._store is None:
            return []
        try:
            if direction == "output":
                # Output artifacts are those registered for this run_step_id
                # via artifact_lineage
                lineage_rows = self._store.execute(
                    "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ?",
                    (self._run_step.run_step_id,),
                ).fetchall()
                return [r["artifact_id"] for r in lineage_rows]
            else:
                # Input artifacts are those referenced by evidence_artifacts
                # for edges targeting this run_step
                rows = self._store.execute(
                    """SELECT DISTINCT ea.artifact_id
                       FROM evidence_artifacts ea
                       JOIN evidence_edges ee ON ea.evidence_edge_id = ee.evidence_edge_id
                       WHERE ee.run_step_id = ?""",
                    (self._run_step.run_step_id,),
                ).fetchall()
                return [r["artifact_id"] for r in rows]
        except Exception:
            return []

    # Allow dict-like access for v1 compatibility
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


def replace_step_params(
    steps: list[StepSpec],
    step_id: str,
    new_params: JsonDict,
) -> list[StepSpec]:
    """Return a new list with the step's params replaced (unchanged)."""
    result = []
    for s in steps:
        if s.step_id == step_id:
            from copy import deepcopy
            d = deepcopy(new_params)
            result.append(StepSpec(
                step_id=s.step_id,
                node_type=s.node_type,
                node_version=s.node_version,
                category=s.category,
                params=d,
                params_hash=json_logical_hash(d),
                parent_step_ids=list(s.parent_step_ids),
                branch_label=s.branch_label,
                position=s.position,
                canonical_step_id=s.canonical_step_id,
                branch_id=s.branch_id,
            ))
        else:
            result.append(s)
    return result
