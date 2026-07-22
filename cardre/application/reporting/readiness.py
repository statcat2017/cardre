"""Report readiness validation — determines whether a report can be generated.

Ports the logic from ``cardre.readiness.check`` and
``cardre.readiness.step_requirements`` to use ports instead of
ProjectStore.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cardre.branch_step_resolver import (
    ResolvedStepRef,
    resolve_required_steps,
)
from cardre.readiness.dto import ReadinessFinding, ReportReadinessResult
from cardre.readiness.limitation_codes import LimitationCode
from cardre.readiness.step_requirements import STEP_REQUIREMENTS
from cardre.reporting.evidence_contract import (
    REQUIRED_STEPS_BRANCH,
    REQUIRED_STEPS_CHAMPION,
)
from cardre.reporting.types import ReportMode


class EvidenceReaderPort:
    """Protocol for reading evidence — satisfied by adapters.evidence.reader.EvidenceReader."""

    def read_optional(self, artifact_id: str, kind: Any) -> Any | None: ...
    def read_step_output_optional(self, run_step_id: str, kind: Any) -> Any | None: ...


def check_report_readiness(
    uow: Any,
    evidence_reader: EvidenceReaderPort,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: ReportMode = "branch",
) -> ReportReadinessResult:
    blockers: list[ReadinessFinding] = []
    warnings: list[ReadinessFinding] = []

    if hasattr(uow, "branches") and hasattr(uow.branches, "get_branch"):
        branch_data = uow.branches.get_branch(target_branch_id)
    else:
        branch_data = _legacy_get(uow, "branch", target_branch_id)

    if branch_data is None:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.TARGET_BRANCH_NOT_FOUND,
            message=f"Target branch {target_branch_id!r} not found.",
        ))
        return _early_result(blockers, target_branch_id, run_id, report_mode)

    branch_dict = branch_data if isinstance(branch_data, dict) else _to_dict(branch_data)

    if branch_dict.get("status") != "active":
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.TARGET_BRANCH_INCOMPLETE,
            message=f"Target branch {target_branch_id!r} has status {branch_dict.get('status')!r}.",
        ))

    run_data = uow.runs.get(run_id) if hasattr(uow, "runs") else _legacy_get(uow, "run", run_id)
    if run_data is None:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.MISSING_RUN_MANIFEST,
            message=f"Run {run_id!r} not found.",
        ))
        return _early_result(blockers, target_branch_id, run_id, report_mode)

    run_dict = run_data if isinstance(run_data, dict) else _to_dict(run_data)

    if run_dict.get("status") != "succeeded":
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.RUN_NOT_SUCCEEDED,
            message=f"Run {run_id!r} has status {run_dict.get('status', 'unknown')!r}, expected 'succeeded'.",
        ))

    plan_version_id = run_dict["plan_version_id"]
    plan_id = uow.plans.get_plan_id_for_version(plan_version_id) if hasattr(uow.plans, "get_plan_id_for_version") else None
    if plan_id is None:
        plan_id = _legacy_plan_id_for_version(uow, plan_version_id)

    if plan_id is None:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.MISSING_PATHWAY,
            message=f"No plan found for plan version {plan_version_id!r}.",
        ))

    head_pv = branch_dict.get("head_plan_version_id")
    if hasattr(uow, "branches") and hasattr(uow.branches, "get_step_map"):
        step_map = uow.branches.get_step_map(target_branch_id, plan_version_id)
        if not step_map and head_pv:
            step_map = uow.branches.get_step_map(target_branch_id, head_pv)
    else:
        step_map = _legacy_step_map(uow, target_branch_id, plan_version_id, head_pv)

    if not step_map:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.TARGET_BRANCH_INCOMPLETE,
            message=f"No branch step map found for branch {target_branch_id!r} in plan version {plan_version_id!r}.",
        ))

    required = REQUIRED_STEPS_CHAMPION if report_mode == "champion" else REQUIRED_STEPS_BRANCH
    step_ids_in_map = {row.get("canonical_step_id", row.get("canonical_step_id", "")) for row in (step_map or [])}
    missing_steps = [s for s in required if s not in step_ids_in_map]
    if missing_steps:
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
            message=f"Required canonical steps not found in branch step map: {missing_steps}",
        ))

    resolved = resolve_required_steps(
        branch_id=target_branch_id,
        canonical_step_ids=required,
        branch_step_map=step_map or [],
    )

    _check_per_step_evidence(evidence_reader, uow, required, resolved, plan_version_id, blockers)
    _check_champion_readiness(uow, plan_id, target_branch_id, report_mode, blockers, warnings)
    _check_oot_readiness(evidence_reader, uow, run_id, report_mode, blockers, warnings)

    return ReportReadinessResult(
        blockers=blockers,
        warnings=warnings,
        target_branch_id=target_branch_id,
        run_id=run_id,
        report_mode=report_mode,
        checked_at=datetime.now(UTC).isoformat(),
    )


def _early_result(
    blockers: list[ReadinessFinding], target_branch_id: str, run_id: str, report_mode: ReportMode,
) -> ReportReadinessResult:
    return ReportReadinessResult(
        blockers=blockers,
        target_branch_id=target_branch_id,
        run_id=run_id,
        report_mode=report_mode,
        checked_at=datetime.now(UTC).isoformat(),
    )


def _output_artifact_refs(
    uow: Any, run_step_id: str,
) -> list[dict[str, str]]:
    if hasattr(uow, "artifacts") and hasattr(uow.artifacts, "output_artifact_ids_for_run_step"):
        return [
            {"artifact_id": aid}
            for aid in uow.artifacts.output_artifact_ids_for_run_step(run_step_id)
        ]
    return []


def _check_per_step_evidence(
    evidence_reader: EvidenceReaderPort, uow: Any, required: list[str],
    resolved: dict[str, ResolvedStepRef], plan_version_id: str,
    blockers: list[ReadinessFinding],
) -> None:

    for canonical_step_id in required:
        ref = resolved.get(canonical_step_id)
        if ref is None:
            continue

        locator = _make_locator(uow)
        if locator is not None:
            resolved_evidence = locator.resolve_ref(plan_version_id, ref)
            rs = resolved_evidence.run_step if resolved_evidence is not None else None
        else:
            rs = None

        if rs is None:
            blockers.append(ReadinessFinding(
                severity="blocker", code=LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
                message=f"No successful run step for {canonical_step_id} (step {ref.step_id}).",
                step_id=ref.step_id,
            ))
            continue

        req = STEP_REQUIREMENTS.get(canonical_step_id)
        if req is None:
            continue

        if req.check_fn:
            blockers.extend(req.check_fn(uow, ref, rs, "branch"))
        elif req.expected_schemas:
            _check_schemas(uow, ref, rs, req.expected_schemas, req.missing_code, canonical_step_id, blockers)
        elif req.expected_schema:
            _check_schema(uow, ref, rs, req.expected_schema, req.missing_code, canonical_step_id, blockers)
        elif req.expected_role:
            _check_role(uow, ref, rs, req.expected_role, req.missing_code, canonical_step_id, blockers)

        if req.extra_check:
            blockers.extend(req.extra_check(uow, ref, rs, "branch"))


def _check_schemas(
    uow: Any, ref: ResolvedStepRef, rs: Any, schemas: tuple[str, ...],
    missing_code: str, canonical_step_id: str, blockers: list[ReadinessFinding],
) -> None:
    has_artifact = any(
        _artifact_has_schema(uow, row["artifact_id"], schemas)
        for row in _output_artifact_refs(uow, rs.run_step_id)
    )
    if not has_artifact:
        blockers.append(ReadinessFinding(
            severity="blocker", code=missing_code,
            message=f"{canonical_step_id} step {ref.step_id} has no {schemas[0]} artifact.",
            step_id=ref.step_id,
        ))


def _check_schema(
    uow: Any, ref: ResolvedStepRef, rs: Any, schema: str,
    missing_code: str, canonical_step_id: str, blockers: list[ReadinessFinding],
) -> None:
    has_artifact = any(
        _artifact_has_schema(uow, row["artifact_id"], (schema,))
        for row in _output_artifact_refs(uow, rs.run_step_id)
    )
    if not has_artifact:
        blockers.append(ReadinessFinding(
            severity="blocker", code=missing_code,
            message=f"{canonical_step_id} step {ref.step_id} has no {schema} artifact.",
            step_id=ref.step_id,
        ))


def _check_role(
    uow: Any, ref: ResolvedStepRef, rs: Any, role: str,
    missing_code: str, canonical_step_id: str, blockers: list[ReadinessFinding],
) -> None:
    has_artifact = any(
        _artifact_has_role(uow, row["artifact_id"], role)
        for row in _output_artifact_refs(uow, rs.run_step_id)
    )
    if not has_artifact:
        blockers.append(ReadinessFinding(
            severity="blocker", code=missing_code,
            message=f"{canonical_step_id} step {ref.step_id} has no {role} artifact.",
            step_id=ref.step_id,
        ))


def _artifact_has_schema(uow: Any, artifact_id: str, schemas: tuple[str, ...]) -> bool:
    if hasattr(uow, "artifacts") and hasattr(uow.artifacts, "get"):
        art = uow.artifacts.get(artifact_id)
        if art is not None:
            meta = getattr(art, "metadata", {}) or {}
            return meta.get("schema_version", "") in schemas
    return False


def _artifact_has_role(uow: Any, artifact_id: str, role: str) -> bool:
    if hasattr(uow, "artifacts") and hasattr(uow.artifacts, "get"):
        art = uow.artifacts.get(artifact_id)
        if art is not None:
            return getattr(art, "role", "") == role
    return False


def _check_champion_readiness(
    uow: Any, plan_id: str | None, target_branch_id: str,
    report_mode: ReportMode, blockers: list[ReadinessFinding], warnings: list[ReadinessFinding],
) -> None:
    if not plan_id:
        return

    if report_mode == "champion":
        champion = _get_champion_assignment(uow, plan_id, target_branch_id)
        if champion is None:
            blockers.append(ReadinessFinding(
                severity="blocker", code=LimitationCode.CHAMPION_ASSIGNMENT_MISSING,
                message=f"No active champion assignment for branch {target_branch_id!r} in champion report mode.",
            ))
    else:
        champ_check = _get_champion_assignment(uow, plan_id)
        if champ_check is None:
            warnings.append(ReadinessFinding(
                severity="warning", code=LimitationCode.NO_CHAMPION_ASSIGNMENT,
                message="No champion branch has been assigned for this plan.",
            ))
        elif (isinstance(champ_check, dict) and champ_check.get("champion_branch_id") != target_branch_id) or (
            hasattr(champ_check, "champion_branch_id") and champ_check.champion_branch_id != target_branch_id
        ):
            warnings.append(ReadinessFinding(
                severity="warning", code=LimitationCode.TARGET_BRANCH_NOT_CHAMPION,
                message=f"Target branch {target_branch_id!r} is not the champion.",
            ))


def _get_champion_assignment(uow: Any, plan_id: str, target_branch_id: str | None = None) -> Any:
    if hasattr(uow, "champion") and hasattr(uow.champion, "get_champion_assignment"):
        try:
            if target_branch_id is not None:
                return uow.champion.get_champion_assignment(plan_id, target_branch_id)
            return uow.champion.get_champion_assignment(plan_id)
        except (AttributeError, NotImplementedError):
            pass
    return None


def _check_oot_readiness(
    evidence_reader: EvidenceReaderPort, uow: Any, run_id: str,
    report_mode: ReportMode, blockers: list[ReadinessFinding], warnings: list[ReadinessFinding],
) -> None:
    if _check_oot_exists(uow, run_id):
        return
    if report_mode == "champion":
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.NO_OOT_SAMPLE_CHAMPION,
            message="No OOT dataset role was present for this run. "
            "OOT is required for champion promotion.",
        ))
    else:
        warnings.append(ReadinessFinding(
            severity="warning", code=LimitationCode.NO_OOT_SAMPLE,
            message="No OOT dataset role was present for this run.",
        ))


def _check_oot_exists(uow: Any, run_id: str) -> bool:
    if hasattr(uow, "artifacts") and hasattr(uow.artifacts, "output_artifact_ids_for_run"):
        for aid in uow.artifacts.output_artifact_ids_for_run(run_id):
            art = uow.artifacts.get(aid)
            if art and getattr(art, "role", "") == "oot":
                return True
    return False


def _make_locator(uow: Any) -> Any | None:
    try:
        from cardre.evidence_locator import EvidenceLocator
        if hasattr(uow, "_store"):
            return EvidenceLocator(uow._store)
        if hasattr(uow, "store"):
            return EvidenceLocator(uow.store)
    except Exception:
        pass
    return None


def _legacy_get(uow: Any, kind: str, id: str) -> Any | None:
    try:
        meth = getattr(uow, f"get_{kind}", None)
        if meth is not None:
            return meth(id)
    except Exception:
        pass
    return None


def _legacy_plan_id_for_version(uow: Any, plan_version_id: str) -> str | None:
    try:
        from cardre.store.plan_repo import PlanRepository
        if hasattr(uow, "_store"):
            return PlanRepository(uow._store).get_plan_id_for_version(plan_version_id)
        if hasattr(uow, "store"):
            return PlanRepository(uow.store).get_plan_id_for_version(plan_version_id)
    except Exception:
        pass
    try:
        if hasattr(uow, "plans") and hasattr(uow.plans, "get_version"):
            pv = uow.plans.get_version(plan_version_id)
            if pv is not None:
                plan_id = getattr(pv, "plan_id", None) or (pv.get("plan_id") if isinstance(pv, dict) else None)
                return str(plan_id) if plan_id else None
    except Exception:
        pass
    return None


def _legacy_step_map(uow: Any, branch_id: str, plan_version_id: str, head_pv: str | None) -> list[dict[str, Any]]:
    try:
        from cardre.store.branch_repo import BranchRepository
        store = getattr(uow, "_store", None) or getattr(uow, "store", None)
        if store is not None:
            repo = BranchRepository(store)
            step_map = repo.get_step_map(branch_id, plan_version_id)
            if not step_map and head_pv:
                step_map = repo.get_step_map(branch_id, head_pv)
            return step_map or []
    except Exception:
        pass
    return []


def _not_found_repo() -> Any:
    class _NotFound:
        def get(self, *args: Any, **kwargs: Any) -> None:
            return None
        def get_branch(self, *args: Any, **kwargs: Any) -> None:
            return None
        def get_step_map(self, *args: Any, **kwargs: Any) -> list:
            return []
    return _NotFound()


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}


__all__ = [
    "EvidenceReaderPort",
    "check_report_readiness",
]
