"""Step requirements table and helper functions for readiness validation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.branch_step_resolver import resolve_step_for_branch
from cardre.readiness.dto import ReadinessFinding
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.types import ReportMode
from cardre.store import ProjectStore
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.champion_repo import ChampionRepository
from cardre.store.plan_repo import PlanRepository


@dataclass(frozen=True)
class StepRequirement:
    expected_schema: str | None = None
    expected_schemas: tuple[str, ...] | None = None
    expected_role: str | None = None
    missing_code: str = ""
    extra_check: Callable[..., list[ReadinessFinding]] | None = None
    check_fn: Callable[..., list[ReadinessFinding]] | None = None


def _output_artifact_refs(
    store: ProjectStore, run_step_id: str,
) -> list[dict[str, str]]:
    return [
        {"artifact_id": aid}
        for aid in ArtifactRepository(store).output_artifact_ids_for_run_step(run_step_id)
    ]


def _check_woe_iv_monotonicity(
    store: ProjectStore, ref: Any, rs: Any, report_mode: ReportMode,
) -> list[ReadinessFinding]:
    if report_mode != "champion":
        return []
    v1_art = None
    for row in _output_artifact_refs(store, rs.run_step_id):
        art = ArtifactRepository(store).get(row["artifact_id"])
        if art and art.metadata.get("schema_version") == "cardre.woe_iv_evidence.v1":
            v1_art = art
            break
    if v1_art is None:
        return []
    try:
        from cardre._evidence.reader import ArtifactEvidenceReader
        from cardre.engine.binning.diagnostics import monotonicity_status
        reader = ArtifactEvidenceReader(store)
        evidence = reader.read(v1_art.artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
        findings: list[ReadinessFinding] = []
        for var in evidence.variables:
            woe_by_bin: dict[str, float] = {}
            for b in var.bins:
                if b.woe is not None:
                    woe_by_bin[b.bin_id] = b.woe
            if len(woe_by_bin) >= 2:
                m_status = monotonicity_status(woe_by_bin)
                if m_status.value == "non_monotonic":
                    findings.append(ReadinessFinding(
                        severity="blocker", code=LimitationCode.NON_MONOTONIC_WOE_CHAMPION,
                        message=f"Final WOE variable {var.variable_name!r} "
                        "is non-monotonic. Re-bin to monotonic for champion promotion.",
                        step_id=ref.step_id,
                    ))
        return findings
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return [ReadinessFinding(
            severity="blocker", code=LimitationCode.WOE_EVIDENCE_READ_FAILURE,
            message=f"Failed to read final WOE evidence from step {ref.step_id} "
            f"for champion monotonicity check: {exc}",
            step_id=ref.step_id,
        )]


def _check_apply_model(
    store: ProjectStore, ref: Any, rs: Any, report_mode: ReportMode,
) -> list[ReadinessFinding]:
    scored_roles = {
        art.role
        for row in _output_artifact_refs(store, rs.run_step_id)
        if (art := ArtifactRepository(store).get(row["artifact_id"]))
        and art.role in {"train", "test", "oot"}
    }
    required_roles = {"train", "test", "oot"} if report_mode == "champion" else {"train", "test"}
    if not required_roles <= scored_roles:
        return [ReadinessFinding(
            severity="blocker", code=LimitationCode.MISSING_SCORE_APPLICATION,
            message=f"Apply-model step {ref.step_id} did not produce scored "
            f"{', '.join(sorted(required_roles))} artifacts.",
            step_id=ref.step_id,
        )]
    return []


STEP_REQUIREMENTS: dict[str, StepRequirement] = {
    "final-woe-iv": StepRequirement(
        expected_schema="cardre.woe_iv_evidence.v1",
        missing_code=LimitationCode.MISSING_WOE_IV_EVIDENCE,
        extra_check=_check_woe_iv_monotonicity,
    ),
    "initial-woe-iv": StepRequirement(
        expected_schema="cardre.woe_iv_evidence.v1",
        missing_code=LimitationCode.MISSING_WOE_IV_EVIDENCE,
    ),
    "score-scaling": StepRequirement(
        expected_schema="cardre.score_scaling.v1",
        missing_code=LimitationCode.MISSING_SCORE_SCALING,
    ),
    "freeze-scorecard-bundle": StepRequirement(
        expected_role="scorecard",
        missing_code=LimitationCode.MISSING_FINAL_SCORECARD,
    ),
    "apply-model": StepRequirement(
        missing_code=LimitationCode.MISSING_SCORE_APPLICATION,
        check_fn=_check_apply_model,
    ),
    "validation-metrics": StepRequirement(
        expected_schemas=("cardre.validation_metrics.v1", "cardre.validation_evidence.v1"),
        missing_code=LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
    ),
    "cutoff-analysis": StepRequirement(
        expected_schema="cardre.cutoff_analysis.v1",
        missing_code=LimitationCode.NO_CUTOFF_ANALYSIS,
    ),
    "scorecard-table-export": StepRequirement(
        expected_schema="cardre.scorecard_table.v1",
        missing_code=LimitationCode.MISSING_IMPLEMENTATION_EXPORTS,
    ),
    "scoring-export-python": StepRequirement(
        expected_schema="cardre.scoring_export_python.v1",
        missing_code=LimitationCode.MISSING_IMPLEMENTATION_EXPORTS,
    ),
    "scoring-export-sql": StepRequirement(
        expected_schema="cardre.scoring_export_sql.v1",
        missing_code=LimitationCode.MISSING_IMPLEMENTATION_EXPORTS,
    ),
    "model-fit": StepRequirement(
        expected_schema="cardre.model_artifact.v1",
        missing_code=LimitationCode.MISSING_MODEL_COEFFICIENTS,
    ),
}


def _check_oot_exists(store: ProjectStore, run_id: str) -> bool:
    for aid in ArtifactRepository(store).output_artifact_ids_for_run(run_id):
        art = ArtifactRepository(store).get(aid)
        if art and art.role == "oot":
            return True
    return False


def check_per_step_evidence(
    store: ProjectStore, required: list[str], resolved: Any, plan_version_id: str,
    report_mode: ReportMode, blockers: list[ReadinessFinding],
) -> None:
    for canonical_step_id in required:
        ref = resolved.get(canonical_step_id)
        if ref is None:
            continue

        from cardre.evidence_locator import EvidenceLocator
        resolved_evidence = EvidenceLocator(store).resolve_ref(
            plan_version_id,
            ref,
        )
        rs = resolved_evidence.run_step if resolved_evidence is not None else None
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
            blockers.extend(req.check_fn(store, ref, rs, report_mode))
        elif req.expected_schemas:
            has_artifact = any(
                art and art.metadata.get("schema_version") in req.expected_schemas
                for row in _output_artifact_refs(store, rs.run_step_id)
                if (art := ArtifactRepository(store).get(row["artifact_id"]))
            )
            if not has_artifact:
                blockers.append(ReadinessFinding(
                    severity="blocker", code=req.missing_code,
                    message=f"{canonical_step_id} step {ref.step_id} has no {req.expected_schemas[0]} artifact.",
                    step_id=ref.step_id,
                ))
        elif req.expected_schema:
            has_artifact = any(
                art and art.metadata.get("schema_version") == req.expected_schema
                for row in _output_artifact_refs(store, rs.run_step_id)
                if (art := ArtifactRepository(store).get(row["artifact_id"]))
            )
            if not has_artifact:
                blockers.append(ReadinessFinding(
                    severity="blocker", code=req.missing_code,
                    message=f"{canonical_step_id} step {ref.step_id} has no {req.expected_schema} artifact.",
                    step_id=ref.step_id,
                ))
        elif req.expected_role:
            has_artifact = any(
                art and art.role == req.expected_role
                for row in _output_artifact_refs(store, rs.run_step_id)
                if (art := ArtifactRepository(store).get(row["artifact_id"]))
            )
            if not has_artifact:
                blockers.append(ReadinessFinding(
                    severity="blocker", code=req.missing_code,
                    message=f"{canonical_step_id} step {ref.step_id} has no {req.expected_role} artifact.",
                    step_id=ref.step_id,
                ))

        if req.extra_check:
            blockers.extend(req.extra_check(store, ref, rs, report_mode))


def check_champion_readiness(
    store: ProjectStore, plan_id: str | None, target_branch_id: str,
    report_mode: ReportMode, blockers: list[ReadinessFinding], warnings: list[ReadinessFinding],
) -> None:
    if not plan_id:
        return
    if report_mode == "champion":
        champion = ChampionRepository(store).get_champion_assignment(plan_id, target_branch_id)
        if champion is None:
            blockers.append(ReadinessFinding(
                severity="blocker", code=LimitationCode.CHAMPION_ASSIGNMENT_MISSING,
                message=f"No active champion assignment for branch {target_branch_id!r} in champion report mode.",
            ))
    else:
        champ_check = ChampionRepository(store).get_champion_assignment(plan_id)
        if champ_check is None:
            warnings.append(ReadinessFinding(
                severity="warning", code=LimitationCode.NO_CHAMPION_ASSIGNMENT,
                message="No champion branch has been assigned for this plan.",
            ))
        elif champ_check["champion_branch_id"] != target_branch_id:
            warnings.append(ReadinessFinding(
                severity="warning", code=LimitationCode.TARGET_BRANCH_NOT_CHAMPION,
                message=f"Target branch {target_branch_id!r} is not the champion.",
            ))


def check_manual_binning_readiness(
    store: ProjectStore, plan_id: str | None, target_branch_id: str,
    plan_version_id: str, step_map: Any, blockers: list[ReadinessFinding], warnings: list[ReadinessFinding],
) -> None:
    if not plan_id:
        return
    mb_ref = resolve_step_for_branch(
        branch_id=target_branch_id,
        canonical_step_id="manual-binning",
        branch_step_map=step_map,
    )
    if mb_ref is None:
        warnings.append(ReadinessFinding(
            severity="warning", code=LimitationCode.NO_MANUAL_BINNING_STEP_ON_BRANCH,
            message="No manual-binning step found on this branch.",
        ))
        return
    mb_step = None
    for s in PlanRepository(store).get_version_steps(plan_version_id):
        if s.step_id == mb_ref.step_id:
            mb_step = s
            break
    if mb_step is None:
        return
    params = mb_step.params
    if not params.get("reviewed", False) and not params.get("accept_automated", False):
        blockers.append(ReadinessFinding(
            severity="blocker", code=LimitationCode.MANUAL_BINNING_NOT_REVIEWED,
            message="Manual binning has not been reviewed on this branch. "
            "Mark review complete or accept automated bins before generating the report.",
            step_id=mb_ref.step_id,
        ))
    else:
        overrides = params.get("overrides", [])
        if overrides and any(
            not ov.get("reason_code") or not ov.get("reason")
            for ov in overrides
        ):
            warnings.append(ReadinessFinding(
                severity="warning", code=LimitationCode.MANUAL_BINNING_REVIEWED_WITH_WARNINGS,
                message="Manual binning review is complete but some overrides are missing "
                "a reason code or reason. Consider reopening review to address them.",
                step_id=mb_ref.step_id,
            ))


def check_oot_readiness(
    store: ProjectStore, run_id: str, report_mode: ReportMode,
    blockers: list[ReadinessFinding], warnings: list[ReadinessFinding],
) -> None:
    if _check_oot_exists(store, run_id):
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
