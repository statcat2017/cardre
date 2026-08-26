"""Pure invariant tests for plan topology and the run state machine.

Covers public/pure callable behavior only:

- ``validate_topology`` accepts empty / linear / diamond graphs and rejects
  duplicate ids, missing parents, self-loops and cycles.
- ``Run.transition_to`` permits exactly the documented legal edges and never
  lets a terminal status reopen to any other status.

Frozen ``Plan``/``PlanVersion`` immutability is already covered by
``tests/test_domain_plan.py``; it is intentionally not duplicated here.
"""

from __future__ import annotations

import pytest

from cardre.application.execution.topology import validate_topology
from cardre.domain.artifacts import params_hash
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import ErrorCode, GraphValidationError
from cardre.domain.run import Run, RunStatus
from cardre.domain.step import StepSpec


def _step(step_id: str, parents: list[str] | None = None) -> StepSpec:
    """Small typed helper to build a StepSpec with minimal fields."""
    return StepSpec(
        step_id=step_id,
        node_type="cardre.test",
        node_version="1",
        category="test",
        params={},
        params_hash=params_hash({}),
        parent_step_ids=list(parents or []),
        canonical_step_id=step_id,
    )


def _assert_graph_error(steps: list[StepSpec], *, match: str) -> None:
    """Assert validate_topology raises a typed graph validation error."""
    with pytest.raises(GraphValidationError, match=match) as exc:
        validate_topology(steps)
    assert exc.value.code is ErrorCode.GRAPH_VALIDATION_ERROR


# --- validate_topology: valid graphs -----------------------------------------


@pytest.mark.parametrize("steps", [[], [_step("a")], [_step("a"), _step("b")]])
def test_validate_topology_accepts_acyclic_graphs(steps: list[StepSpec]) -> None:
    # Must not raise.
    validate_topology(list(steps))


def test_validate_topology_accepts_linear_chain() -> None:
    steps = [_step("c", ("b",)), _step("b", ("a",)), _step("a")]
    validate_topology(steps)
    # Reordered in topological order (roots first).
    assert [s.step_id for s in steps] == ["a", "b", "c"]


def test_validate_topology_accepts_diamond() -> None:
    steps = [_step("d", ("b", "c")), _step("c", ("a",)), _step("b", ("a",)), _step("a")]
    validate_topology(steps)
    assert {s.step_id for s in steps} == {"a", "b", "c", "d"}


# --- validate_topology: invalid graphs ---------------------------------------


def test_validate_topology_rejects_duplicate_step_ids() -> None:
    steps = [_step("a"), _step("a")]
    _assert_graph_error(steps, match=r"Duplicate step_id 'a'")


def test_validate_topology_rejects_missing_parent() -> None:
    steps = [_step("a", ("ghost",))]
    _assert_graph_error(steps, match=r"missing parent 'ghost'")


@pytest.mark.parametrize("steps", [
    [_step("a", ("a",))],  # self-loop
    [_step("a", ("b",)), _step("b", ("a",))],  # two-node cycle
])
def test_validate_topology_rejects_cycles(steps: list[StepSpec]) -> None:
    _assert_graph_error(steps, match=r"Cycle detected in plan steps")


# --- Run.transition_to: legal edges ------------------------------------------

LEGAL_EDGES = [
    (RunStatus.SUBMITTED, RunStatus.RUNNING),
    (RunStatus.SUBMITTED, RunStatus.FAILED),
    (RunStatus.SUBMITTED, RunStatus.CANCELLED),
    (RunStatus.RUNNING, RunStatus.SUCCEEDED),
    (RunStatus.RUNNING, RunStatus.FAILED),
    (RunStatus.RUNNING, RunStatus.CANCELLED),
    (RunStatus.RUNNING, RunStatus.INTERRUPTED),
]


@pytest.mark.parametrize("current,target", LEGAL_EDGES)
def test_run_transition_allows_legal_edges(current: RunStatus, target: RunStatus) -> None:
    run = Run(run_id="r", plan_version_id="p", status=current.value, started_at=utc_now_iso())
    updated = run.transition_to(target.value)
    assert updated.status == target.value


# --- Run.transition_to: terminal statuses never reopen -------------------------


TERMINAL_STATUSES = [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED]


@pytest.mark.parametrize("terminal", TERMINAL_STATUSES)
@pytest.mark.parametrize("target", list(RunStatus))
def test_terminal_status_never_reopens(
    terminal: RunStatus, target: RunStatus
) -> None:
    run = Run(
        run_id="r-1",
        plan_version_id="p-1",
        status=terminal.value,
        started_at=utc_now_iso(),
    )
    with pytest.raises(ValueError):
        run.transition_to(target.value)
