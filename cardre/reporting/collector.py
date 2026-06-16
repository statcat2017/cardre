"""Report collector — builds ReportBundle from immutable run artifacts.

Phase 5 rule: the collector is a read-only artifact consumer.
It must not become a second modelling execution path.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cardre.audit import RunStepRecord
from cardre.store import ProjectStore

from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
)
from cardre.reporting.evidence_resolver import (
    get_champion_assignment,
    resolve_branch,
    resolve_plan_context,
    resolve_project,
    resolve_run,
    resolve_run_step,
    resolve_step_map,
    resolve_required_steps,
)
from cardre.reporting.limitation_codes import LimitationCode
from cardre.reporting.schema import (
    AffectedBinDetail,
    ArtifactEntry,
    BranchInfo,
    BranchSummary,
    ChampionInfo,
    CutoffInfo,
    CutoffRow,
    CutoffTable,
    DatasetDateRange,
    DatasetRole,
    DatasetTargetSummary,
    ExecutionFingerprint,
    GeneratedBy,
    Limitation,
    ManualIntervention,
    MetricsByRole,
    ModelFeature,
    ModelInfo,
    PathwayStep,
    PathwaySummary,
    PsiEntry,
    ReportBundle,
    ReportGenerationInfo,
    ReportSource,
    ReportSummary,
    ReproducibilityInfo,
    ResolvedStepRef,
    ScoreScalingInfo,
    SelectedCutoff,
    StabilityInfo,
    ValidationInfo,
    VariableBin,
    VariableInfo,
    WoeSmoothingInfo,
)

REQUIRED_CANONICAL_STEPS = [
    "final-woe-iv",
    "logistic-regression",
    "score-scaling",
    "validation-metrics",
    "cutoff-analysis",
    "manual-binning",
]

CARDRE_VERSION = "0.1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_artifact_json(store: ProjectStore, artifact_id: str) -> dict | None:
    art = store.get_artifact(artifact_id)
    if art is None:
        return None
    path = store.artifact_path(art)
    if not path.exists():
        return None
    return json.loads(path.read_text())


class ReportCollector:
    """Collects evidence from immutable run artifacts and builds a ReportBundle."""

    def __init__(
        self,
        store: ProjectStore,
        project_id: str,
        run_id: str,
        target_branch_id: str,
        report_mode: str = "branch",
    ) -> None:
        self.store = store
        self.project_id = project_id
        self.run_id = run_id
        self.target_branch_id = target_branch_id
        self.report_mode = report_mode
        self.reader = ArtifactEvidenceReader(store)
        self.limitations: list[Limitation] = []

    def collect(self) -> ReportBundle:
        bundle = ReportBundle(
            schema_version="cardre.report_bundle.v1",
            project_id=self.project_id,
            run_id=self.run_id,
            target_branch_id=self.target_branch_id,
            report_mode=self.report_mode,
            generated_at=_utc_now(),
            generated_by=GeneratedBy(cardre_version=CARDRE_VERSION),
        )

        # Load core metadata via resolver
        project = resolve_project(self.store, self.project_id)
        run = resolve_run(self.store, self.run_id)

        if project:
            bundle.summary.model_name = project.get("name", "")

        if run is None:
            self.limitations.append(Limitation(severity="blocker", code=LimitationCode.MISSING_RUN_MANIFEST, message="Run not found."))
            bundle.limitations = self.limitations
            return bundle

        plan_version_id = run["plan_version_id"]
        plan_id, _ = resolve_plan_context(self.store, plan_version_id)

        # Source info
        bundle.source.run_manifest_path = str(self.store.root / "cardre.sqlite")

        # Branch
        branch = resolve_branch(self.store, self.target_branch_id)
        if branch is None:
            self.limitations.append(Limitation(severity="blocker", code=LimitationCode.TARGET_BRANCH_NOT_FOUND, message=f"Branch {self.target_branch_id!r} not found."))
            bundle.limitations = self.limitations
            return bundle

        branch_head_pv = branch["head_plan_version_id"]
        bundle.summary.target_branch_id = self.target_branch_id

        # Branch step map via resolver
        step_map = resolve_step_map(self.store, self.target_branch_id, plan_version_id, branch_head_pv)

        # Resolve required steps
        resolved = resolve_required_steps(
            branch_id=self.target_branch_id,
            canonical_step_ids=REQUIRED_CANONICAL_STEPS,
            branch_step_map=step_map,
        )

        # Load plan steps for pathway info
        plan_steps = self.store.get_plan_version_steps(plan_version_id)

        # Build pathway summary
        pathway_steps: list[PathwayStep] = []
        for ps in plan_steps:
            resolution = "exact"
            step_branch_id = ps.branch_id or ""
            for cid, ref in resolved.items():
                if ref and ref.canonical_step_id == ps.canonical_step_id:
                    resolution = ref.resolution
                    step_branch_id = ref.resolved_branch_id
                    break
            pathway_steps.append(PathwayStep(
                canonical_step_id=ps.canonical_step_id,
                step_id=ps.step_id,
                branch_id=step_branch_id,
                step_type=ps.node_type,
                status="",
                config_hash=ps.params_hash,
                resolution=resolution,
            ))
        bundle.pathway = PathwaySummary(pathway_id="scorecard_pathway", steps=pathway_steps)

        # Build branch summary
        all_branches = self.store.list_branches(self.project_id, plan_id=plan_id)
        branch_infos: list[BranchInfo] = []
        for b in all_branches:
            branch_infos.append(BranchInfo(
                branch_id=b["branch_id"],
                name=b.get("name", ""),
                parent_branch_id=b.get("base_branch_id"),
                created_from_canonical_step_id=b.get("branch_point_canonical_step_id"),
                is_target_branch=b["branch_id"] == self.target_branch_id,
                is_champion=False,
                status=b.get("status", ""),
            ))
        bundle.branches = BranchSummary(
            branching_model="plan_derived_lanes",
            target_branch_id=self.target_branch_id,
            branches=branch_infos,
        )

        # Champion via resolver
        bundle.champion = self._collect_champion(plan_id)

        # Update is_champion in branch list
        if bundle.champion.champion_branch_id:
            for bi in bundle.branches.branches:
                if bi.branch_id == bundle.champion.champion_branch_id:
                    bi.is_champion = True

        # Dataset roles
        bundle.dataset_roles = self._collect_dataset_roles(run, plan_version_id)

        # WOE/IV evidence
        woe_ref = resolved.get("final-woe-iv")
        if woe_ref:
            self._collect_woe_iv(bundle, woe_ref, plan_version_id)

        # Model
        model_ref = resolved.get("logistic-regression")
        if model_ref:
            self._collect_model(bundle, model_ref, plan_version_id)

        # Score scaling
        scaling_ref = resolved.get("score-scaling")
        if scaling_ref:
            self._collect_score_scaling(bundle, scaling_ref, plan_version_id)

        # Validation metrics
        val_ref = resolved.get("validation-metrics")
        if val_ref:
            self._collect_validation(bundle, val_ref, plan_version_id)

        # Cutoff
        cutoff_ref = resolved.get("cutoff-analysis")
        if cutoff_ref:
            self._collect_cutoff(bundle, cutoff_ref, plan_version_id)

        # Manual interventions
        manual_ref = resolved.get("manual-binning")
        if manual_ref:
            self._collect_manual_interventions(bundle, manual_ref, plan_version_id)

        # Reproducibility
        self._collect_reproducibility(bundle, plan_version_id)

        # Limitations
        bundle.limitations = self.limitations

        # Artifacts
        bundle.artifacts = self._collect_artifacts(plan_version_id)

        # Summary
        bundle.summary.report_status = "complete_with_warnings" if self.limitations else "complete"

        return bundle

    def _collect_champion(self, plan_id: str | None) -> ChampionInfo:
        if plan_id is None:
            return ChampionInfo(champion_status="not_available")

        row = get_champion_assignment(self.store, plan_id)
        if row is None:
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.NO_CHAMPION_ASSIGNMENT,
                message="No champion branch has been assigned for this run.",
            ))
            return ChampionInfo(champion_status="not_available")

        is_target = row["champion_branch_id"] == self.target_branch_id
        if not is_target and self.report_mode == "branch":
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.TARGET_BRANCH_NOT_CHAMPION,
                message=f"Target branch {self.target_branch_id!r} is not the champion.",
            ))

        return ChampionInfo(
            champion_status="selected",
            assignment_id=row["champion_assignment_id"],
            champion_branch_id=row["champion_branch_id"],
            comparison_artifact_id=row["comparison_artifact_id"],
            rationale=row["assigned_reason"],
            selected_at=row["assigned_at"],
            target_branch_is_champion=is_target,
        )

    def _collect_dataset_roles(self, run: dict[str, Any], plan_version_id: str) -> list[DatasetRole]:
        roles: list[DatasetRole] = []
        run_steps = self.store.get_run_steps(run["run_id"])

        for rs in run_steps:
            for aid in rs.output_artifact_ids:
                art = self.store.get_artifact(aid)
                if art and art.role in ("train", "test", "oot"):
                    roles.append(DatasetRole(
                        role=art.role,
                        dataset_id=art.artifact_id,
                        row_count=art.metadata.get("row_count", 0),
                        column_count=art.metadata.get("column_count", 0),
                    ))

        has_oot = any(r.role == "oot" for r in roles)
        if not has_oot:
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.NO_OOT_SAMPLE,
                message="No OOT dataset role was present for this run.",
            ))

        return roles

    def _collect_woe_iv(
        self, bundle: ReportBundle, ref: ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_WOE_IV_EVIDENCE_V1,
                message=f"WOE/IV step {ref.step_id} has no successful run.",
            ))
            return

        evidence = self.reader.read_step_output_optional(rs, EvidenceKind.WOE_IV_EVIDENCE)
        if evidence is None:
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.LEGACY_WOE_SUMMARY_USED,
                message=f"WOE/IV step {ref.step_id} has no cardre.woe_iv_evidence.v1 artifact.",
            ))
            return

        smoothing = evidence.smoothing
        zero_cell_policy = smoothing.zero_cell_policy

        for var in evidence.variables:
            woe_smoothing = WoeSmoothingInfo(
                enabled=smoothing.enabled,
                method=smoothing.method,
                alpha=smoothing.alpha,
                zero_cell_policy=zero_cell_policy,
                smoothing_applied=var.smoothing_applied,
                zero_cell_encountered=var.zero_cell_encountered,
                affected_bin_count=len(var.affected_bins),
            )

            if woe_smoothing.smoothing_applied:
                self.limitations.append(Limitation(
                    severity="warning", code=LimitationCode.SMOOTHING_APPLIED,
                    message=f"WOE smoothing applied to variable {var.variable_name}.",
                ))

            affected_bins = [
                AffectedBinDetail(**ab.detail)
                for ab in var.affected_bins
            ]

            var_bins = [
                VariableBin(
                    bin_id=b.bin_id,
                    label=b.label,
                    lower=b.lower,
                    upper=b.upper,
                    good_count=b.good_count,
                    bad_count=b.bad_count,
                    bad_rate=b.bad_rate,
                    woe=b.woe,
                    iv_contribution=b.iv_contribution,
                )
                for b in var.bins
            ]

            bundle.variables.append(VariableInfo(
                variable_name=var.variable_name,
                role=var.status,
                branch_id=ref.resolved_branch_id,
                final_bin_count=len(var_bins),
                iv=var.iv,
                woe_smoothing=woe_smoothing,
                source_step_refs=[ResolvedStepRef(
                    requested_branch_id=ref.requested_branch_id,
                    resolved_branch_id=ref.resolved_branch_id,
                    canonical_step_id=ref.canonical_step_id,
                    step_id=ref.step_id,
                    resolution=ref.resolution,
                )],
                bins=var_bins,
                affected_bins=affected_bins,
            ))

        if zero_cell_policy == "block":
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.ZERO_CELL_POLICY_USED,
                message=f"Zero-cell policy '{zero_cell_policy}' is configured.",
            ))

    def _collect_model(
        self, bundle: ReportBundle, ref: ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_MODEL_COEFFICIENTS,
                message=f"Model step {ref.step_id} has no successful run.",
            ))
            return

        model_art = self.reader.read_step_output_optional(rs, EvidenceKind.MODEL_ARTIFACT)
        if model_art is not None:
            features = [
                ModelFeature(
                    variable_name=c.variable_name,
                    coefficient=c.coefficient,
                    standard_error=c.standard_error,
                    p_value=c.p_value,
                )
                for c in model_art.coefficients
            ]
            bundle.model = ModelInfo(
                model_type="logistic_regression_scorecard",
                branch_id=ref.resolved_branch_id,
                target=model_art.target_column or bundle.summary.target_column or "",
                features=features,
                intercept=model_art.intercept,
                fit_dataset_role="train",
            )

    def _collect_score_scaling(
        self, bundle: ReportBundle, ref: ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_SCORE_SCALING,
                message=f"Score scaling step {ref.step_id} has no successful run.",
            ))
            return

        scaling = self.reader.read_step_output_optional(rs, EvidenceKind.SCORE_SCALING)
        if scaling is not None:
            bundle.score_scaling = ScoreScalingInfo(
                base_score=scaling.base_score,
                base_odds=scaling.base_odds,
                pdo=scaling.pdo,
                factor=scaling.factor,
                offset=scaling.offset,
                score_direction=scaling.score_direction,
                rounding=scaling.rounding,
                min_score=scaling.min_score,
                max_score=scaling.max_score,
            )

    def _collect_validation(
        self, bundle: ReportBundle, ref: ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
                message=f"Validation step {ref.step_id} has no successful run.",
            ))
            return

        val = self.reader.read_step_output_optional(rs, EvidenceKind.VALIDATION_METRICS)
        if val is None:
            return

        validation = ValidationInfo()
        for role_name, rm in val.metrics_by_role.items():
            validation.metrics_by_role.append(MetricsByRole(
                role=role_name,
                row_count=rm.row_count,
                auc=rm.auc,
                gini=rm.gini,
                ks=rm.ks,
                bad_rate=rm.bad_rate,
            ))
        for comp, psi_val in val.psi.items():
            validation.stability.psi_by_role.append(PsiEntry(
                comparison=comp,
                score_psi=psi_val,
            ))
        bundle.validation = validation

    def _collect_cutoff(
        self, bundle: ReportBundle, ref: ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.NO_CUTOFF_ANALYSIS,
                message=f"Cutoff analysis step {ref.step_id} has no successful run.",
            ))
            return

        cutoff = self.reader.read_step_output_optional(rs, EvidenceKind.CUTOFF_ANALYSIS)
        if cutoff is not None:
            tables = []
            for role_name, rows in cutoff.cutoff_tables.items():
                cutoff_rows = [
                    CutoffRow(
                        score_cutoff=r.score_cutoff,
                        approval_rate=r.approval_rate,
                        bad_rate=r.bad_rate,
                        capture_rate=r.capture_rate,
                    )
                    for r in rows
                ]
                tables.append(CutoffTable(role=role_name, rows=cutoff_rows))
            if tables:
                bundle.cutoffs = CutoffInfo(cutoff_tables=tables)

    def _collect_manual_interventions(
        self, bundle: ReportBundle, ref: ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            return

        for aid in rs.output_artifact_ids:
            art = self.store.get_artifact(aid)
            if art and art.role in ("definition", "report") and "manual" in art.path.lower():
                data = _get_artifact_json(self.store, aid)
                if data and "overrides" in data:
                    for i, ov in enumerate(data["overrides"]):
                        bundle.manual_interventions.append(ManualIntervention(
                            intervention_id=f"mi_{i:03d}",
                            branch_id=ref.resolved_branch_id,
                            canonical_step_id=ref.canonical_step_id,
                            step_id=ref.step_id,
                            type=ov.get("type", "unknown"),
                            variable_name=ov.get("variable_name", ov.get("variable", "")),
                            before_artifact=ov.get("before", ""),
                            after_artifact=ov.get("after", ""),
                            reason=ov.get("reason", ""),
                            created_at=ov.get("created_at", ""),
                        ))

    def _collect_reproducibility(
        self, bundle: ReportBundle, plan_version_id: str,
    ) -> None:
        run_steps = self.store.get_run_steps(self.run_id)
        fingerprints = []
        for rs in run_steps:
            fp = rs.execution_fingerprint
            fingerprints.append(ExecutionFingerprint(
                step_id=rs.step_id,
                canonical_step_id=fp.get("canonical_step_id", rs.step_id),
                python_version=fp.get("python_version", ""),
                platform=fp.get("platform", ""),
                package_fingerprint={},
            ))

        bundle.reproducibility = ReproducibilityInfo(
            run_id=self.run_id,
            execution_fingerprints=fingerprints,
            report_generation=ReportGenerationInfo(
                generated_at=bundle.generated_at,
                cardre_version=CARDRE_VERSION,
            ),
        )

    def _collect_artifacts(self, plan_version_id: str) -> list[ArtifactEntry]:
        entries: list[ArtifactEntry] = []
        run_steps = self.store.get_run_steps(self.run_id)
        seen: set[str] = set()
        for rs in run_steps:
            for aid in rs.output_artifact_ids:
                if aid in seen:
                    continue
                seen.add(aid)
                art = self.store.get_artifact(aid)
                if art:
                    entries.append(ArtifactEntry(
                        artifact_id=art.artifact_id,
                        artifact_type=art.artifact_type,
                        role=art.role,
                        logical_hash=art.logical_hash,
                        physical_hash=art.physical_hash,
                        path=art.path,
                    ))
        return entries

    def _resolve_run_step(
        self, ref: ResolvedStepRef, plan_version_id: str,
    ) -> RunStepRecord | None:
        rs = resolve_run_step(
            self.store, plan_version_id, ref.step_id,
            ref.resolved_branch_id, ref.resolution,
            run_id=self.run_id,
        )
        # Disclose when inherited/ancestor evidence is used
        if rs is not None and ref.resolution == "ancestor":
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.INHERITED_BRANCH_EVIDENCE,
                message=f"Step {ref.canonical_step_id} inherited from branch "
                f"{ref.resolved_branch_id} (ancestor resolution).",
            ))
        return rs


def generate_report_bundle(
    store: ProjectStore,
    project_id: str,
    run_id: str,
    target_branch_id: str,
    report_mode: str = "branch",
) -> ReportBundle:
    """Generate a complete ReportBundle for the given branch and run."""
    collector = ReportCollector(
        store=store,
        project_id=project_id,
        run_id=run_id,
        target_branch_id=target_branch_id,
        report_mode=report_mode,
    )
    return collector.collect()
