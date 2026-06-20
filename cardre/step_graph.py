"""Step graph utilities — ancestor/descendant closure computation.

Consolidates the duplicated graph algorithms scattered across
``PlanExecutor`` and ``BranchService``.
"""

from __future__ import annotations

from cardre.audit import StepSpec


def descendant_closure(step_id: str, steps: list[StepSpec]) -> set[str]:
    """Return all step_ids that are transitively downstream of *step_id*.

    Includes *step_id* itself.  Raises ``KeyError`` if *step_id* is not
    in *steps*.
    """
    step_ids = {s.step_id for s in steps}
    if step_id not in step_ids:
        raise KeyError(step_id)

    descendants: set[str] = set()
    changed = True
    while changed:
        changed = False
        for s in steps:
            if s.step_id in descendants:
                continue
            if s.step_id == step_id or descendants.intersection(s.parent_step_ids):
                descendants.add(s.step_id)
                changed = True
    return descendants | {step_id}


def ancestor_closure(step_id: str, steps: list[StepSpec]) -> set[str]:
    """Return all step_ids that are transitively upstream of *step_id*.

    Does not include *step_id* itself.  Returns empty set for root steps.
    Raises ``KeyError`` if *step_id* is not in *steps*.
    """
    step_ids = {s.step_id for s in steps}
    if step_id not in step_ids:
        raise KeyError(step_id)
    step_map = {s.step_id: s for s in steps}
    ancestors: set[str] = set()
    queue = list(step_map[step_id].parent_step_ids)
    while queue:
        pid = queue.pop()
        if pid in ancestors:
            continue
        ancestors.add(pid)
        if pid in step_map:
            queue.extend(step_map[pid].parent_step_ids)
    return ancestors
