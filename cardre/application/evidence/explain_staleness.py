"""ExplainStaleness — explain staleness for a single step.

Port of StalenessService.explain_step from cardre/services/staleness_service.py.
Uses UnitOfWork ports instead of direct store access.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cardre.application.evidence.evidence_resolver import resolve_evidence
from cardre.domain.errors import GraphValidationError
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec


@dataclass
class StalenessExplanation:
    step_id: str
    status: str
    upstream_changes: dict[str, bool] = field(default_factory=dict)
    missing_evidence: list[str] = field(default_factory=list)


@dataclass
class ExplainStalenessCommand:
    plan_version_id: str
    step_id: str
    branch_id: str | None = None
    plan_id: str | None = None


class ExplainStaleness:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        evidence_reader: Any | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._evidence_reader = evidence_reader

    def __call__(self, command: ExplainStalenessCommand) -> StalenessExplanation:
        uow = self._uow_factory()

        steps = uow.steps.get_steps(command.plan_version_id)
        spec_by_id = {s.step_id: s for s in steps}

        plan_id = command.plan_id
        if plan_id is None:
            plan_id = uow.plans.get_plan_id_for_version(command.plan_version_id)

        run_id = uow.runs.get_latest_successful_id(
            command.plan_version_id, branch_id=command.branch_id,
        )
        if run_id is None and command.branch_id is not None:
            run_id = uow.runs.get_latest_successful_id(
                command.plan_version_id, branch_id=None,
            )
        if run_id is None and plan_id is not None:
            run_id = uow.runs.get_latest_successful_id_for_plan(plan_id)

        step_has_evidence: dict[str, bool] = {}
        if run_id is not None:
            step_has_evidence[command.step_id] = any(
                rs.step_id == command.step_id and rs.status == RunStepStatus.SUCCEEDED
                for rs in uow.run_steps.get_for_run(run_id)
            )
        else:
            step_has_evidence[command.step_id] = False

        stale_cache: dict[str, bool] = {}
        upstream_changes: dict[str, bool] = {}

        for s in steps:
            is_stale = _step_is_stale(
                uow, s, steps,
                command.plan_version_id, command.branch_id, plan_id,
                stale_cache,
            )
            upstream_changes[s.step_id] = is_stale

        spec = spec_by_id.get(command.step_id)
        missing_evidence: list[str] = []
        if spec:
            for pid in spec.parent_step_ids:
                edges = uow.evidence.get_edges_for_plan_step(
                    command.plan_version_id, command.step_id,
                )
                has_edge = any(e.parent_step_id == pid for e in edges)
                if not has_edge:
                    missing_evidence.append(pid)

        if (spec and run_id is None) or not step_has_evidence.get(command.step_id, True):
            status = "missing"
        elif upstream_changes.get(command.step_id, True):
            status = "stale"
        else:
            status = "fresh"

        return StalenessExplanation(
            step_id=command.step_id,
            status=status,
            upstream_changes=upstream_changes,
            missing_evidence=missing_evidence,
        )


def _find_spec(step_id: str, steps: list[StepSpec]) -> StepSpec:
    for s in steps:
        if s.step_id == step_id:
            return s
    raise GraphValidationError(
        f"Missing parent step {step_id!r} referenced by staleness walk",
        context={"missing_step_id": step_id, "known_step_ids": [s.step_id for s in steps]},
    )


def _step_is_stale(
    uow: Any,
    spec: StepSpec,
    all_steps: list[StepSpec],
    plan_version_id: str,
    branch_id: str | None,
    plan_id: str | None,
    stale_cache: dict[str, bool],
) -> bool:
    if spec.step_id in stale_cache:
        return stale_cache[spec.step_id]

    pairs = resolve_evidence(
        uow,
        plan_version_id, spec.step_id,
        branch_id=branch_id, plan_id=plan_id,
        fingerprint_match=spec,
    )

    if not pairs:
        stale_cache[spec.step_id] = True
        return True

    rs = uow.run_steps.get(pairs[0][0].run_step_id)
    if rs is None:
        stale_cache[spec.step_id] = True
        return True

    fp = rs.execution_fingerprint

    for pid in spec.parent_step_ids:
        parent_spec = _find_spec(pid, all_steps)
        parent_stale = _step_is_stale(
            uow, parent_spec, all_steps,
            plan_version_id, branch_id, plan_id, stale_cache,
        )
        if parent_stale:
            stale_cache[spec.step_id] = True
            return True

        parent_pairs = resolve_evidence(
            uow,
            plan_version_id, pid,
            branch_id=branch_id, plan_id=plan_id,
            fingerprint_match=parent_spec,
        )

        if parent_pairs:
            parent_rs = uow.run_steps.get(parent_pairs[0][0].run_step_id)
            if parent_rs is not None:
                stored_parent_outputs = fp.get("parent_output_logical_hashes_by_step", {}).get(pid, [])
                current_parent_outputs = parent_rs.execution_fingerprint.get(
                    "output_artifact_logical_hashes", []
                )
                if stored_parent_outputs != current_parent_outputs:
                    stale_cache[spec.step_id] = True
                    return True
            else:
                stale_cache[spec.step_id] = True
                return True
        else:
            stale_cache[spec.step_id] = True
            return True

    stale_cache[spec.step_id] = False
    return False


def step_is_stale(
    uow: Any, spec: StepSpec, all_steps: list[StepSpec], plan_version_id: str,
    branch_id: str | None, plan_id: str | None,
) -> bool:
    """Determine whether a step or any of its recorded upstream inputs is stale."""
    return _step_is_stale(uow, spec, all_steps, plan_version_id, branch_id, plan_id, {})


__all__ = ["ExplainStaleness", "ExplainStalenessCommand", "StalenessExplanation", "step_is_stale"]
