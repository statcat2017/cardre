"""Shared step topology utilities for branch-aware ancestor resolution."""

from __future__ import annotations

from cardre.audit import StepSpec


AMBIGUOUS_CODE = "AMBIGUOUS_BRANCH_ANCESTOR"


class AmbiguousBranchAncestorError(ValueError):
    """Raised when multiple equally-distant ancestors match."""


def find_nearest_ancestor_by_canonical_step_id(
    steps: list[StepSpec],
    target_step_id: str,
    branch_step_map: list[dict],
    canonical_step_id: str,
) -> StepSpec | None:
    """Branch-aware BFS for nearest ancestor with a given canonical_step_id.

    Algorithm per Phase 4 tech spec Section 15.4.
    """
    steps_by_id = {s.step_id: s for s in steps}
    target = steps_by_id.get(target_step_id)
    if target is None:
        return None

    branch_scope_ids = {row["step_id"] for row in branch_step_map}

    visited = set()
    queue: list[tuple[str, int]] = [(pid, 1) for pid in target.parent_step_ids]
    candidates: list[tuple[int, int, StepSpec]] = []

    while queue:
        current_id, depth = queue.pop(0)
        if current_id in visited:
            continue
        visited.add(current_id)
        if current_id not in branch_scope_ids:
            continue
        current = steps_by_id.get(current_id)
        if current is None:
            continue
        if current.canonical_step_id == canonical_step_id:
            candidates.append((depth, current.position, current))
            continue
        for pid in current.parent_step_ids:
            queue.append((pid, depth + 1))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1]))
    best_depth = candidates[0][0]
    best = [item for item in candidates if item[0] == best_depth]
    if len(best) > 1 and best[0][1] == best[1][1]:
        raise AmbiguousBranchAncestorError(
            f"Multiple ancestors found for canonical step {canonical_step_id}"
        )
    return candidates[0][2]


BINNING_SOURCE_CANONICAL_IDS = ["binning", "fine-classing"]


def find_nearest_binning_source(
    steps: list[StepSpec],
    target_step_id: str,
    branch_step_map: list[dict],
) -> StepSpec | None:
    for canonical in BINNING_SOURCE_CANONICAL_IDS:
        spec = find_nearest_ancestor_by_canonical_step_id(
            steps, target_step_id, branch_step_map, canonical,
        )
        if spec is not None:
            return spec
    return None
