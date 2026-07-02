"""Plan topology: validation and topological sort.

Pure functions extracted from PlanExecutor so callers can validate
plans without accessing private executor internals.
"""

from __future__ import annotations

from cardre.domain.errors import GraphValidationError
from cardre.domain.step import StepSpec


def validate_topology(steps: list[StepSpec]) -> None:
    """Validate plan step topology and reorder in topological order.

    Raises ``GraphValidationError`` on cycles or missing parent references.
    Mutates *steps* (sorts in place).
    """
    seen: set[str] = set()
    for step in steps:
        if step.step_id in seen:
            raise GraphValidationError(
                f"Duplicate step_id {step.step_id!r}",
                context={"step_id": step.step_id},
            )
        seen.add(step.step_id)

    step_ids = {s.step_id for s in steps}
    for step in steps:
        for pid in step.parent_step_ids:
            if pid not in step_ids:
                raise GraphValidationError(
                    f"Step {step.step_id!r} references missing parent {pid!r}",
                    context={"step_id": step.step_id, "parent_step_id": pid},
                )

    parent_map: dict[str, set[str]] = {s.step_id: set(s.parent_step_ids) & step_ids for s in steps}
    child_map: dict[str, list[str]] = {s.step_id: [] for s in steps}
    for s in steps:
        for pid in s.parent_step_ids:
            if pid in child_map:
                child_map[pid].append(s.step_id)

    in_degree = {sid: len(parents) for sid, parents in parent_map.items()}
    queue = sorted(sid for sid, deg in in_degree.items() if deg == 0)
    sorted_ids: list[str] = []
    while queue:
        sid = queue.pop(0)
        sorted_ids.append(sid)
        for child in child_map.get(sid, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
        queue.sort()

    if len(sorted_ids) != len(steps):
        raise GraphValidationError(
            f"Cycle detected in plan steps: {len(steps)} steps, "
            f"only {len(sorted_ids)} topologically sortable",
            context={"step_count": len(steps), "sortable_count": len(sorted_ids)},
        )

    step_by_id = {s.step_id: s for s in steps}
    steps[:] = [step_by_id[sid] for sid in sorted_ids]


__all__ = ["validate_topology"]
