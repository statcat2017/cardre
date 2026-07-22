"""Step graph utilities — descendant/ancestor closure and step-ID remapping.

Pure functions with no I/O dependencies.  Extracted from ``BranchGraphRemapper``
so that the remapping logic lives in the domain kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Re-exported from the application step-graph module so that consumers
# can import from a single location.
from cardre.application.execution.step_graph import (  # noqa: F401
    ancestor_closure,
    descendant_closure,
)
from cardre.domain.step import StepSpec


@dataclass(frozen=True)
class RemappedGraph:
    """Result of remapping a branch's step graph.

    ``new_steps`` includes both duplicated (branch-owned) steps with
    remapped IDs and unmodified shared upstream steps.
    """
    branch_id: str
    new_steps: list[StepSpec] = field(default_factory=list)
    created_step_ids: dict[str, str] = field(default_factory=dict)
    shared_upstream_step_ids: list[str] = field(default_factory=list)
    source_of_new_step: dict[str, str] = field(default_factory=dict)
    branch_point_canonical_step_id: str = ""


def remap_step_graph(
    *,
    branch_id: str,
    name: str,
    branch_point_step: StepSpec,
    steps: list[StepSpec],
) -> RemappedGraph:
    """Remap step IDs for all steps downstream of *branch_point_step*.

    Steps in the descendant closure of *branch_point_step* get new IDs
    prefixed with their ``canonical_step_id`` and *branch_id*.  Their
    ``parent_step_ids`` are remapped to point at the new sibling IDs.

    Returns a ``RemappedGraph`` with duplicated (branch-owned) and
    shared upstream steps.
    """
    dup_closure = descendant_closure(branch_point_step.step_id, steps)

    step_id_map: dict[str, str] = {}
    for s in steps:
        if s.step_id in dup_closure:
            new_step_id = f"{s.canonical_step_id}__{branch_id}"
            step_id_map[s.step_id] = new_step_id
        else:
            step_id_map[s.step_id] = s.step_id

    created_step_ids: dict[str, str] = {}
    shared_upstream_step_ids: list[str] = []
    new_steps: list[StepSpec] = []
    source_of_new_step: dict[str, str] = {}

    for s in steps:
        if s.step_id in dup_closure:
            new_step_id = step_id_map[s.step_id]
            source_of_new_step[new_step_id] = s.step_id

            remapped_parents = [
                step_id_map.get(pid, pid)
                for pid in s.parent_step_ids
            ]

            new_spec = StepSpec(
                step_id=new_step_id,
                node_type=s.node_type,
                node_version=s.node_version,
                category=s.category,
                params=dict(s.params),
                params_hash=s.params_hash,
                parent_step_ids=remapped_parents,
                branch_label=name,
                position=s.position,
                canonical_step_id=s.canonical_step_id,
                branch_id=branch_id,
            )
            new_steps.append(new_spec)
            created_step_ids[s.canonical_step_id] = new_step_id
        else:
            new_steps.append(s)
            shared_upstream_step_ids.append(s.step_id)

    return RemappedGraph(
        branch_id=branch_id,
        new_steps=new_steps,
        created_step_ids=created_step_ids,
        shared_upstream_step_ids=shared_upstream_step_ids,
        source_of_new_step=source_of_new_step,
        branch_point_canonical_step_id=branch_point_step.canonical_step_id,
    )


__all__ = [
    "RemappedGraph",
    "ancestor_closure",
    "descendant_closure",
    "remap_step_graph",
]
