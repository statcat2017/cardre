"""Canonical pathway spec — single source of truth for pathway definitions.

Replaces the hardcoded dict config arrays in sidecar/proof_pathway.py
with a clean dataclass-based spec and builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.audit import StepSpec, json_logical_hash


@dataclass
class PathwayStepSpec:
    """A single step in a pathway definition.

    Fields mirror StepSpec but omit auto-computed fields
    (params_hash, position).
    """
    step_id: str
    node_type: str
    params: dict[str, Any] = field(default_factory=dict)
    parent_step_ids: list[str] = field(default_factory=list)
    category: str = "transform"
    node_version: str = "1"
    branch_label: str = ""
    canonical_step_id: str | None = None  # defaults to step_id
    branch_id: str | None = None


@dataclass
class PathwaySpec:
    """Canonical pathway definition."""
    name: str
    description: str
    phases: list[list[PathwayStepSpec]]


def build_pathway_steps(spec: PathwaySpec) -> list[StepSpec]:
    """Build a flat list of StepSpec from a PathwaySpec.

    Steps are ordered by phase then position within each phase.
    Auto-computes params_hash and position.
    """
    steps: list[StepSpec] = []
    position = 0

    for phase in spec.phases:
        for ps in phase:
            params = dict(ps.params)
            steps.append(
                StepSpec(
                    step_id=ps.step_id,
                    node_type=ps.node_type,
                    node_version=ps.node_version,
                    category=ps.category,
                    params=params,
                    params_hash=json_logical_hash(params),
                    parent_step_ids=list(ps.parent_step_ids),
                    branch_label=ps.branch_label,
                    position=position,
                    canonical_step_id=ps.canonical_step_id or ps.step_id,
                    branch_id=ps.branch_id,
                )
            )
            position += 1

    return steps
