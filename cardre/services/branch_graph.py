"""Branch graph remapping — descendant closure, ID remapping, step construction.

Pure — no database writes.  Produces a ``BranchGraphClone`` that is
consumed by the transaction writer.

Edges are derived from remapped ``parent_step_ids`` by the plan repository,
not cloned separately (consistent with current behaviour).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cardre.domain.step import StepSpec
from cardre.execution.step_graph import descendant_closure

if TYPE_CHECKING:
    from cardre.services.branch_validator import ValidatedBranchData


@dataclass(frozen=True)
class BranchGraphClone:
    """Result of remapping a branch's graph from the validated branch data.

    ``new_steps`` includes both duplicated (branch-owned) steps with
    remapped IDs and unmodified shared upstream steps.
    """
    branch_id: str
    new_steps: list[StepSpec] = field(default_factory=list)
    created_step_ids: dict[str, str] = field(default_factory=dict)
    shared_upstream_step_ids: list[str] = field(default_factory=list)
    source_of_new_step: dict[str, str] = field(default_factory=dict)
    branch_point_canonical_step_id: str = ""


class BranchGraphRemapper:
    """Builds a branch graph clone from validated branch data.

    Computes descendant closure, remaps step IDs for duplicated steps,
    rebuilds ``parent_step_ids`` on duplicated steps to point at remapped
    parents, and returns a ``BranchGraphClone``.

    Edges are NOT cloned explicitly — they are derived from remapped
    ``parent_step_ids`` by the plan repository.
    """

    EXCLUDED_CANONICAL_STEP_IDS: set[str] = set()

    def build_clone(
        self,
        validated: ValidatedBranchData,
    ) -> BranchGraphClone:
        """Build the branch graph clone from validated data.

        Returns a ``BranchGraphClone`` with duplicated (branch-owned) and
        shared upstream steps.
        """
        import uuid

        branch_id = f"br_{uuid.uuid4().hex[:6]}"
        name = validated.name
        steps = validated.steps
        bp_step = validated.bp_step
        assert bp_step is not None, "bp_step must be resolved before remapping"

        dup_closure = descendant_closure(bp_step.step_id, steps)

        # Build step_id mapping: original -> generated (for duplicated steps)
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

        return BranchGraphClone(
            branch_id=branch_id,
            new_steps=new_steps,
            created_step_ids=created_step_ids,
            shared_upstream_step_ids=shared_upstream_step_ids,
            source_of_new_step=source_of_new_step,
            branch_point_canonical_step_id=bp_step.canonical_step_id,
        )


__all__ = ["BranchGraphClone", "BranchGraphRemapper"]
