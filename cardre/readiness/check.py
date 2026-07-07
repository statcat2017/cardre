"""Report readiness validation — determines whether a report can be generated.

Distinguishes champion mode (blocked without champion assignment) from
branch mode (warns but does not block without champion assignment).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Inlined step resolution helpers (formerly cardre.step_id)
# ---------------------------------------------------------------------------
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.readiness.dto import ReadinessBlocker, ReadinessWarning, ReportReadinessResult
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.evidence_contract import (
    REQUIRED_STEPS_BRANCH,
    REQUIRED_STEPS_CHAMPION,
)
from cardre.store import ProjectStore


@dataclass
class ResolvedStepRef:
    requested_branch_id: str
    resolved_branch_id: str
    canonical_step_id: str
    step_id: str
    resolution: str  # "exact" or "ancestor"
    artifact_ids: list[str] = field(default_factory=list)


def resolve_step_for_branch(
    *,
    branch_id: str,
    canonical_step_id: str,
    branch_step_map: list[dict[str, Any]],
    allow_ancestor: bool = True,
) -> ResolvedStepRef | None:
    for row in branch_step_map:
        if row["canonical_step_id"] != canonical_step_id:
            continue
        is_shared = bool(row.get("is_shared_upstream", False))
        is_owned = bool(row.get("is_branch_owned", True))
        source_branch_id = row.get("source_branch_id")
        if is_owned and not is_shared:
            return ResolvedStepRef(
                requested_branch_id=branch_id,
                resolved_branch_id=branch_id,
                canonical_step_id=canonical_step_id,
                step_id=row["step_id"],
                resolution="exact",
            )
        if is_shared and source_branch_id:
            if allow_ancestor:
                return ResolvedStepRef(
                    requested_branch_id=branch_id,
                    resolved_branch_id=source_branch_id,
                    canonical_step_id=canonical_step_id,
                    step_id=row["step_id"],
                    resolution="ancestor",
                )
            return None
        return ResolvedStepRef(
            requested_branch_id=branch_id,
            resolved_branch_id=branch_id,
            canonical_step_id=canonical_step_id,
            step_id=row["step_id"],
            resolution="exact",
        )
    return None


def resolve_required_steps(
    *,
    branch_id: str,
    canonical_step_ids: list[str],
    branch_step_map: list[dict[str, Any]],
    allow_ancestor: bool = True,
) -> dict[str, ResolvedStepRef]:
    result: dict[str, ResolvedStepRef] = {}
    for cid in canonical_step_ids:
        ref = resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id=cid,
            branch_step_map=branch_step_map,
            allow_ancestor=allow_ancestor,
        )
        if ref is not None:
            result[cid] = ref
    return result


def _check_oot_exists(store: ProjectStore, run_id: str) -> bool:
    rows = store.execute(
        "SELECT artifact_id FROM artifact_lineage WHERE run_id = ? AND direction = 'output'",
        (run_id,),
    ).fetchall()
    for row in rows:
        art = store.get_artifact(row["artifact_id"])
        if art and art.role == "oot":
            return True
    return False


BLOCKER_CODES = LimitationCode.blocker_codes()

WARNING_CODES = LimitationCode.warning_codes()


def check_report_readiness(
    store: ProjectStore,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: str = "branch",
) -> ReportReadinessResult:
    """Validate whether a report can be generated for the given branch and mode."""
    blockers: list[ReadinessBlocker] = []
    warnings: list[ReadinessWarning] = []

    # Resolve target branch
    branch = store.get_branch(target_branch_id)
    if branch is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_NOT_FOUND,
            f"Target branch {target_branch_id!r} not found.",
        ))
        return ReportReadinessResult(
            blockers=blockers,
            target_branch_id=target_branch_id,
            run_id=run_id,
            report_mode=report_mode,
            checked_at=datetime.now(UTC).isoformat(),
        )

    if branch.get("status") != "active":
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_INCOMPLETE,
            f"Target branch {target_branch_id!r} has status {branch.get('status')!r}.",
        ))

    # Resolve run
    run = store.get_run(run_id)
    if run is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_RUN_MANIFEST,
            f"Run {run_id!r} not found.",
        ))
        return ReportReadinessResult(
            blockers=blockers,
            target_branch_id=target_branch_id,
            run_id=run_id,
            report_mode=report_mode,
            checked_at=datetime.now(UTC).isoformat(),
        )

    if run.get("status") != "succeeded":
        blockers.append(ReadinessBlocker(
            LimitationCode.RUN_NOT_SUCCEEDED,
            f"Run {run_id!r} has status {run.get('status', 'unknown')!r}, expected 'succeeded'.",
        ))

    plan_version_id = run["plan_version_id"]
    plan_id = store.get_plan_id_for_version(plan_version_id)

    # Check plan
    if plan_id is None:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_PATHWAY,
            f"No plan found for plan version {plan_version_id!r}.",
        ))

    # Check branch step map
    head_pv = branch.get("head_plan_version_id")
    step_map = store.get_branch_step_map(target_branch_id, plan_version_id)
    if not step_map and head_pv:
        step_map = store.get_branch_step_map(target_branch_id, head_pv)
    if not step_map:
        blockers.append(ReadinessBlocker(
            LimitationCode.TARGET_BRANCH_INCOMPLETE,
            f"No branch step map found for branch {target_branch_id!r} in plan version {plan_version_id!r}.",
        ))

    # Check required canonical steps present in step map
    required = REQUIRED_STEPS_CHAMPION if report_mode == "champion" else REQUIRED_STEPS_BRANCH
    step_ids_in_map = {row["canonical_step_id"] for row in step_map}

    missing_steps = [s for s in required if s not in step_ids_in_map]
    if missing_steps:
        blockers.append(ReadinessBlocker(
            LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
            f"Required canonical steps not found in branch step map: {missing_steps}",
        ))

    # Per-step: resolve and check run evidence
    resolved = resolve_required_steps(
        branch_id=target_branch_id,
        canonical_step_ids=required,
        branch_step_map=step_map,
    )

    for canonical_step_id in required:
        ref = resolved.get(canonical_step_id)
        if ref is None:
            continue

        branch_id = ref.resolved_branch_id if ref.resolution == "ancestor" else None
        # Single Locator call — the Locator owns the branch→full→plan
        # fallback (ADR-0005 §3).  No caller-side retry.
        from cardre.evidence_locator import EvidenceLocator
        resolved_evidence = EvidenceLocator(store).resolve(
            plan_version_id, ref.step_id, branch_id=branch_id,
        )
        rs = resolved_evidence.run_step if resolved_evidence is not None else None
        if rs is None:
            blockers.append(ReadinessBlocker(
                LimitationCode.MISSING_REQUIRED_CANONICAL_STEP,
                f"No successful run step for {canonical_step_id} (step {ref.step_id}).",
                step_id=ref.step_id,
            ))
            continue

        # For WOE/IV, check evidence v1
        if canonical_step_id in ("final-woe-iv", "initial-woe-iv"):
            has_v1 = False
            v1_art = None
            for row in store.execute(
                "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
                (rs.run_step_id,),
            ).fetchall():
                art = store.get_artifact(row["artifact_id"])
                if art and art.metadata.get("schema_version") == "cardre.woe_iv_evidence.v1":
                    has_v1 = True
                    v1_art = art
                    break
            if not has_v1:
                blockers.append(ReadinessBlocker(
                    LimitationCode.MISSING_WOE_IV_EVIDENCE,
                    f"WOE/IV step {ref.step_id} has no cardre.woe_iv_evidence.v1 artifact. "
                    "Phase 5 requires the controlled evidence artifact.",
                    step_id=ref.step_id,
                ))
            elif canonical_step_id == "final-woe-iv" and report_mode == "champion" and v1_art is not None:
                try:
                    from cardre._evidence.reader import ArtifactEvidenceReader
                    from cardre.engine.binning.diagnostics import monotonicity_status
                    reader = ArtifactEvidenceReader(store)
                    evidence = reader.read(v1_art.artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
                    for var in evidence.variables:
                        woe_by_bin: dict[str, float] = {}
                        for b in var.bins:
                            if b.woe is not None:
                                woe_by_bin[b.bin_id] = b.woe
                        if len(woe_by_bin) >= 2:
                            m_status = monotonicity_status(woe_by_bin)
                            if m_status.value == "non_monotonic":
                                blockers.append(ReadinessBlocker(
                                    LimitationCode.NON_MONOTONIC_WOE_CHAMPION,
                                    f"Final WOE variable {var.variable_name!r} "
                                    "is non-monotonic. Re-bin to monotonic for champion promotion.",
                                    step_id=ref.step_id,
                                ))
                except Exception:
                    blockers.append(ReadinessBlocker(
                        LimitationCode.WOE_EVIDENCE_READ_FAILURE,
                        f"Failed to read final WOE evidence from step {ref.step_id} "
                        "for champion monotonicity check.",
                        step_id=ref.step_id,
                    ))

        # For score-scaling, check evidence artifact
        elif canonical_step_id == "score-scaling":
            has_artifact = any(
                art and art.metadata.get("schema_version") == "cardre.score_scaling.v1"
                for row in store.execute(
                    "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
                    (rs.run_step_id,),
                ).fetchall()
                if (art := store.get_artifact(row["artifact_id"]))
            )
            if not has_artifact:
                blockers.append(ReadinessBlocker(
                    LimitationCode.MISSING_SCORE_SCALING,
                    f"Score scaling step {ref.step_id} has no cardre.score_scaling.v1 artifact.",
                    step_id=ref.step_id,
                ))

        # For validation-metrics, check evidence artifact
        elif canonical_step_id == "validation-metrics":
            has_artifact = any(
                art and art.metadata.get("schema_version") in ("cardre.validation_metrics.v1", "cardre.validation_evidence.v1")
                for row in store.execute(
                    "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
                    (rs.run_step_id,),
                ).fetchall()
                if (art := store.get_artifact(row["artifact_id"]))
            )
            if not has_artifact:
                blockers.append(ReadinessBlocker(
                    LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
                    f"Validation metrics step {ref.step_id} has no cardre.validation_metrics.v1 artifact.",
                    step_id=ref.step_id,
                ))

        # For cutoff-analysis, check evidence artifact
        elif canonical_step_id == "cutoff-analysis":
            has_artifact = any(
                art and art.metadata.get("schema_version") == "cardre.cutoff_analysis.v1"
                for row in store.execute(
                    "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
                    (rs.run_step_id,),
                ).fetchall()
                if (art := store.get_artifact(row["artifact_id"]))
            )
            if not has_artifact:
                blockers.append(ReadinessBlocker(
                    LimitationCode.NO_CUTOFF_ANALYSIS,
                    f"Cutoff analysis step {ref.step_id} has no cardre.cutoff_analysis.v1 artifact.",
                    step_id=ref.step_id,
                ))

        # For model-fit, check evidence artifact
        elif canonical_step_id == "model-fit":
            has_artifact = any(
                art and art.metadata.get("schema_version") == "cardre.model_artifact.v1"
                for row in store.execute(
                    "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
                    (rs.run_step_id,),
                ).fetchall()
                if (art := store.get_artifact(row["artifact_id"]))
            )
            if not has_artifact:
                blockers.append(ReadinessBlocker(
                    LimitationCode.MISSING_MODEL_COEFFICIENTS,
                    f"Model step {ref.step_id} has no cardre.model_artifact.v1 artifact.",
                    step_id=ref.step_id,
                ))

    # Champion mode checks
    if plan_id:
        if report_mode == "champion":
            champion = store.get_champion_assignment(plan_id, target_branch_id)
            if champion is None:
                blockers.append(ReadinessBlocker(
                    LimitationCode.CHAMPION_ASSIGNMENT_MISSING,
                    f"No active champion assignment for branch {target_branch_id!r} in champion report mode.",
                ))
        else:
            champ_check = store.get_champion_assignment(plan_id)
            if champ_check is None:
                warnings.append(ReadinessWarning(
                    LimitationCode.NO_CHAMPION_ASSIGNMENT,
                    "No champion branch has been assigned for this plan.",
                ))
            elif champ_check["champion_branch_id"] != target_branch_id:
                warnings.append(ReadinessWarning(
                    LimitationCode.TARGET_BRANCH_NOT_CHAMPION,
                    f"Target branch {target_branch_id!r} is not the champion.",
                ))

    # Check manual-binning review status (branch-scoped via step map)
    if plan_id:
        mb_ref = resolve_step_for_branch(
            branch_id=target_branch_id,
            canonical_step_id="manual-binning",
            branch_step_map=step_map,
        )
        if mb_ref is None:
            warnings.append(ReadinessWarning(
                LimitationCode.NO_MANUAL_BINNING_STEP_ON_BRANCH,
                "No manual-binning step found on this branch.",
            ))
        else:
            mb_step = None
            for s in store.get_plan_version_steps(plan_version_id):
                if s.step_id == mb_ref.step_id:
                    mb_step = s
                    break
            if mb_step is not None:
                params = mb_step.params
                if not params.get("reviewed", False) and not params.get("accept_automated", False):
                    blockers.append(ReadinessBlocker(
                        LimitationCode.MANUAL_BINNING_NOT_REVIEWED,
                        "Manual binning has not been reviewed on this branch. "
                        "Mark review complete or accept automated bins before generating the report.",
                        step_id=mb_ref.step_id,
                    ))
                else:
                    # Warn if reviewed but overrides are missing reason_code
                    overrides = params.get("overrides", [])
                    if overrides and any(
                        not ov.get("reason_code") or not ov.get("reason")
                        for ov in overrides
                    ):
                        warnings.append(ReadinessWarning(
                            LimitationCode.MANUAL_BINNING_REVIEWED_WITH_WARNINGS,
                            "Manual binning review is complete but some overrides are missing "
                            "a reason code or reason. Consider reopening review to address them.",
                            step_id=mb_ref.step_id,
                        ))

    # Check OOT dataset role
    if not _check_oot_exists(store, run_id):
        if report_mode == "champion":
            blockers.append(ReadinessBlocker(
                LimitationCode.NO_OOT_SAMPLE_CHAMPION,
                "No OOT dataset role was present for this run. "
                "OOT is required for champion promotion.",
            ))
        else:
            warnings.append(ReadinessWarning(
                LimitationCode.NO_OOT_SAMPLE,
                "No OOT dataset role was present for this run.",
            ))

    return ReportReadinessResult(
        blockers=blockers,
        warnings=warnings,
        target_branch_id=target_branch_id,
        run_id=run_id,
        report_mode=report_mode,
        checked_at=datetime.now(UTC).isoformat(),
    )


__all__ = [
    "ReportReadinessResult",
    "ResolvedStepRef",
    "check_report_readiness",
    "resolve_step_for_branch",
    "resolve_required_steps",
]
