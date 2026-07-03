"""Report collector — builds ReportBundle from immutable run artifacts.

Phase 5 rule: the collector is a read-only artifact consumer.
It must not become a second modelling execution path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import Diagnostic
from cardre.domain.run import RunStep
from cardre.readiness.limitation_codes import LimitationCode
from cardre.reporting.evidence_contract import REQUIRED_STEPS_COLLECTOR
from cardre.reporting.schema import (
    AffectedBinDetail,
    ArtifactEntry,
    BranchInfo,
    BranchSummary,
    ChampionInfo,
    CutoffInfo,
    CutoffRow,
    CutoffTable,
    DatasetRole,
    DiagnosticEntry,
    ExecutionFingerprint,
    GeneratedBy,
    Limitation,
    ManualBinningReviewState,
    ManualIntervention,
    MetricsByRole,
    ModelFeature,
    ModelInfo,
    PathwayStep,
    PathwaySummary,
    PsiEntry,
    RedundancyCluster,
    RedundancyClusterMember,
    RedundancyReviewInfo,
    ReportBundle,
    ReportGenerationInfo,
    ReproducibilityInfo,
    ResolvedStepRef,
    RunManifest,
    RunStatusInfo,
    ScoreScalingInfo,
    ValidationInfo,
    VariableBin,
    VariableInfo,
    WoeSmoothingInfo,
)
from cardre.store import ProjectStore
from cardre.store.run_repo import RunRepository

# ---------------------------------------------------------------------------
# Inlined step resolution helpers (formerly cardre.step_id)
# ---------------------------------------------------------------------------


@dataclass
class _ResolvedStepRef:
    requested_branch_id: str
    resolved_branch_id: str
    canonical_step_id: str
    step_id: str
    resolution: str  # "exact" or "ancestor"
    artifact_ids: list[str] = field(default_factory=list)


def _resolve_step_for_branch(
    *,
    branch_id: str,
    canonical_step_id: str,
    branch_step_map: list[dict[str, Any]],
    allow_ancestor: bool = True,
) -> _ResolvedStepRef | None:
    for row in branch_step_map:
        if row["canonical_step_id"] != canonical_step_id:
            continue
        is_shared = bool(row.get("is_shared_upstream", False))
        is_owned = bool(row.get("is_branch_owned", True))
        source_branch_id = row.get("source_branch_id")
        if is_owned and not is_shared:
            return _ResolvedStepRef(
                requested_branch_id=branch_id,
                resolved_branch_id=branch_id,
                canonical_step_id=canonical_step_id,
                step_id=row["step_id"],
                resolution="exact",
            )
        if is_shared and source_branch_id:
            if allow_ancestor:
                return _ResolvedStepRef(
                    requested_branch_id=branch_id,
                    resolved_branch_id=source_branch_id,
                    canonical_step_id=canonical_step_id,
                    step_id=row["step_id"],
                    resolution="ancestor",
                )
            return None
        return _ResolvedStepRef(
            requested_branch_id=branch_id,
            resolved_branch_id=branch_id,
            canonical_step_id=canonical_step_id,
            step_id=row["step_id"],
            resolution="exact",
        )
    return None


def _resolve_required_steps(
    *,
    branch_id: str,
    canonical_step_ids: list[str],
    branch_step_map: list[dict[str, Any]],
    allow_ancestor: bool = True,
) -> dict[str, _ResolvedStepRef]:
    result: dict[str, _ResolvedStepRef] = {}
    for cid in canonical_step_ids:
        ref = _resolve_step_for_branch(
            branch_id=branch_id,
            canonical_step_id=cid,
            branch_step_map=branch_step_map,
            allow_ancestor=allow_ancestor,
        )
        if ref is not None:
            result[cid] = ref
    return result


CARDRE_VERSION = "0.1.0"


def _to_schema_ref(ref) -> ResolvedStepRef:
    """Convert a step_id.ResolvedStepRef (dataclass) to a schema.ResolvedStepRef (Pydantic)."""
    return ResolvedStepRef(
        requested_branch_id=ref.requested_branch_id,
        resolved_branch_id=ref.resolved_branch_id,
        canonical_step_id=ref.canonical_step_id,
        step_id=ref.step_id,
        resolution=ref.resolution,
    )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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
        project = self.store.get_project(self.project_id)
        run = self.store.get_run(self.run_id)

        if project:
            bundle.summary.model_name = project.get("name", "")

        if run is None:
            self.limitations.append(Limitation(severity="blocker", code=LimitationCode.MISSING_RUN_MANIFEST, message="Run not found."))
            bundle.limitations = self.limitations
            return bundle

        plan_version_id = run["plan_version_id"]
        plan_id = self.store.get_plan_id_for_version(plan_version_id)

        # Run status info
        self._collect_run_status(bundle, run)

        # Source info — updated to canonical path by _read_canonical_manifest
        bundle.source.run_manifest_path = ""

        # Branch
        branch = self.store.get_branch(self.target_branch_id)
        if branch is None:
            self.limitations.append(Limitation(severity="blocker", code=LimitationCode.TARGET_BRANCH_NOT_FOUND, message=f"Branch {self.target_branch_id!r} not found."))
            bundle.limitations = self.limitations
            return bundle

        branch_head_pv = branch["head_plan_version_id"]
        bundle.summary.target_branch_id = self.target_branch_id

        # Branch step map via resolver
        step_map = self.store.get_branch_step_map(self.target_branch_id, plan_version_id)
        if not step_map and branch_head_pv:
            step_map = self.store.get_branch_step_map(self.target_branch_id, branch_head_pv)

        # Resolve required steps
        resolved = _resolve_required_steps(
            branch_id=self.target_branch_id,
            canonical_step_ids=REQUIRED_STEPS_COLLECTOR,
            branch_step_map=step_map,
        )

        # Modelling metadata (target column, value mapping)
        modelling_ref = _resolve_step_for_branch(
            branch_id=self.target_branch_id,
            canonical_step_id="define-metadata",
            branch_step_map=step_map,
        )
        if modelling_ref:
            self._collect_modelling_metadata(bundle, modelling_ref, plan_version_id)

        # Load plan steps for pathway info
        plan_steps = self.store.get_plan_version_steps(plan_version_id)

        # Build pathway summary
        pathway_steps: list[PathwayStep] = []
        for ps in plan_steps:
            resolution = "exact"
            step_branch_id = ps.branch_id or ""
            for _cid, ref in resolved.items():
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
        model_ref = resolved.get("model-fit")
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

        # Redundancy review
        self._collect_redundancy_review(bundle, plan_version_id)

        # Read canonical manifest for hashes
        self._read_canonical_manifest(bundle)

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

        row = self.store.get_champion_assignment(plan_id)
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

        for row in self.store.execute(
            "SELECT al.artifact_id FROM artifact_lineage al "
            "WHERE al.run_id = ? AND al.direction = 'output'",
            (run["run_id"],),
        ).fetchall():
            art = self.store.get_artifact(row["artifact_id"])
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
        self, bundle: ReportBundle, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker",                 code=LimitationCode.MISSING_WOE_IV_EVIDENCE,
                message=f"WOE/IV step {ref.step_id} has no successful run.",
            ))
            return

        evidence = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.WOE_IV_EVIDENCE)
        if evidence is None:
            self.limitations.append(Limitation(
                severity="warning",                 code=LimitationCode.WOE_SUMMARY_USED_INSTEAD_OF_EVIDENCE,
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
        self, bundle: ReportBundle, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_MODEL_COEFFICIENTS,
                message=f"Model step {ref.step_id} has no successful run.",
            ))
            return

        model_art = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.MODEL_ARTIFACT)
        if model_art is not None:
            target_column = model_art.target_column or str(getattr(model_art, "_raw", {}).get("target_column", ""))
            if target_column and not bundle.summary.target_column:
                bundle.summary.target_column = target_column
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
                target=target_column or bundle.summary.target_column or "",
                features=features,
                intercept=model_art.intercept,
                fit_dataset_role="train",
                source_step_refs=[_to_schema_ref(ref)],
            )
        else:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_MODEL_COEFFICIENTS,
                message=f"Model step {ref.step_id} produced no MODEL_ARTIFACT evidence.",
            ))

    def _collect_modelling_metadata(
        self, bundle: ReportBundle, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            return

        meta = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.MODELLING_METADATA)
        if meta is None:
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.MISSING_MODELLING_METADATA,
                message=f"Modelling metadata step {ref.step_id} produced no MODELLING_METADATA evidence.",
            ))
            return

        target_column = meta.target_column or str(getattr(meta, "_raw", {}).get("target_column", ""))
        if target_column and not bundle.summary.target_column:
            bundle.summary.target_column = target_column

    def _collect_score_scaling(
        self, bundle: ReportBundle, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_SCORE_SCALING,
                message=f"Score scaling step {ref.step_id} has no successful run.",
            ))
            return

        scaling = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.SCORE_SCALING)
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
                source_step_refs=[_to_schema_ref(ref)],
            )
        else:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_SCORE_SCALING,
                message=f"Score scaling step {ref.step_id} produced no SCORE_SCALING evidence.",
            ))

    def _collect_validation(
        self, bundle: ReportBundle, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
                message=f"Validation step {ref.step_id} has no successful run.",
            ))
            return

        val = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.VALIDATION_EVIDENCE)
        if val is None:
            val = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.VALIDATION_METRICS)
        if val is None:
            self.limitations.append(Limitation(
                severity="blocker", code=LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
                message=f"Validation step {ref.step_id} produced no VALIDATION_EVIDENCE or VALIDATION_METRICS evidence.",
            ))
            return

        validation = ValidationInfo(source_step_refs=[_to_schema_ref(ref)])
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
        self, bundle: ReportBundle, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> None:
        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.NO_CUTOFF_ANALYSIS,
                message=f"Cutoff analysis step {ref.step_id} has no successful run.",
            ))
            return

        cutoff = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.CUTOFF_ANALYSIS)
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
                bundle.cutoffs = CutoffInfo(cutoff_tables=tables, source_step_refs=[_to_schema_ref(ref)])
        else:
            self.limitations.append(Limitation(
                severity="warning", code=LimitationCode.NO_CUTOFF_ANALYSIS,
                message=f"Cutoff analysis step {ref.step_id} produced no CUTOFF_ANALYSIS evidence.",
            ))

    def _collect_manual_interventions(
        self, bundle: ReportBundle, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> None:
        # Populate review state from step params + annotation
        step_map = self.store.get_branch_step_map(self.target_branch_id, plan_version_id)
        if step_map:
            mb_ref = _resolve_step_for_branch(
                branch_id=self.target_branch_id,
                canonical_step_id="manual-binning",
                branch_step_map=step_map,
            )
            if mb_ref:
                for s in self.store.get_plan_version_steps(plan_version_id):
                    if s.step_id == mb_ref.step_id:
                        params = s.params
                        is_reviewed = params.get("reviewed", False)
                        is_accepted = params.get("accept_automated", False)
                        overrides = params.get("overrides", [])
                        edited_vars = list({ov.get("variable", "") for ov in overrides if ov.get("variable")})
                        reasons = list({ov.get("reason_code", "") for ov in overrides if ov.get("reason_code")})
                        # Read audit metadata from the latest review annotation
                        annotation, annotation_diags = self._get_latest_review_annotation(
                            mb_ref.step_id, plan_version_id,
                        )
                        if annotation_diags:
                            self.limitations.append(Limitation(
                                severity="warning", code=LimitationCode.MISSING_MANUAL_INTERVENTION_REASON,
                                message="Review annotation could not be read.",
                            ))
                        bundle.manual_binning_review = ManualBinningReviewState(
                            review_status="reviewed" if is_reviewed else ("accepted_automated" if is_accepted else "not_started"),
                            accepted_automated=is_accepted,
                            edited_variable_count=len(edited_vars),
                            variables_edited=edited_vars,
                            reasons=reasons,
                            reviewed_at=annotation.get("created_at", "") if annotation else "",
                            reviewed_by=annotation.get("reviewed_by", "") if annotation else "",
                            review_reason=annotation.get("review_reason", "") if annotation else "",
                        )
                        break

        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            return

        for row in self.store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (rs.run_step_id,),
        ).fetchall():
            aid = row["artifact_id"]
            art = self.store.get_artifact(aid)
            if art and art.role in ("definition", "report") and "manual" in art.path.lower():
                data = self.reader.read_optional(aid, EvidenceKind.BIN_DEFINITION)
                legacy = self.reader.read_optional(aid, EvidenceKind.MANUAL_BINNING_OVERRIDES)
                if data is None and legacy is None:
                    continue
                interventions: list[dict[str, Any]] = []
                if data is not None:
                    payload = data.to_dict() if hasattr(data, "to_dict") else getattr(data, "_raw", data)
                    if isinstance(payload, dict):
                        for var in list(payload.get("variables", [])) + list(payload.get("rejected", [])):
                            if isinstance(var, dict):
                                interventions.extend(var.get("override_history", []) or [])
                if not interventions and legacy is not None:
                    legacy_payload = legacy.to_dict() if hasattr(legacy, "to_dict") else getattr(legacy, "_raw", legacy)
                    if isinstance(legacy_payload, dict):
                        interventions.extend(legacy_payload.get("overrides", []) or [])
                for i, ov in enumerate(interventions):
                    bundle.manual_interventions.append(ManualIntervention(
                        intervention_id=f"mi_{i:03d}",
                        branch_id=ref.resolved_branch_id,
                        canonical_step_id=ref.canonical_step_id,
                        step_id=ref.step_id,
                        type=ov.get("user_action", ov.get("type", "unknown")),
                        variable_name=ov.get("variable_name", ov.get("variable", "")),
                        before_artifact=str(ov.get("before", "")),
                        after_artifact=str(ov.get("after", "")),
                        reason=ov.get("reason", ""),
                        created_at=ov.get("created_at", ""),
                    ))

    def _collect_redundancy_review(
        self, bundle: ReportBundle, plan_version_id: str,
    ) -> None:

        ref = None
        step_map = self.store.get_branch_step_map(self.target_branch_id, plan_version_id)
        if not step_map:
            return
        for _cid, r in _resolve_required_steps(
            branch_id=self.target_branch_id,
            canonical_step_ids=["variable-clustering"],
            branch_step_map=step_map,
        ).items():
            ref = r
            break

        if ref is None:
            return

        rs = self._resolve_run_step(ref, plan_version_id)
        if rs is None:
            self.limitations.append(Limitation(
                severity="warning",
                code=LimitationCode.MISSING_VARIABLE_CLUSTERING_EVIDENCE,
                message=f"Variable clustering step {ref.step_id} has no successful run.",
            ))
            return

        evidence = self.reader.read_step_output_optional(rs.run_step_id, EvidenceKind.VARIABLE_CLUSTERING)
        if evidence is None:
            self.limitations.append(Limitation(
                severity="warning",
                code=LimitationCode.MISSING_VARIABLE_CLUSTERING_EVIDENCE,
                message=f"Variable clustering step {ref.step_id} has no cardre.variable_clustering_evidence.v1 artifact.",
            ))
            return

        clusters = []
        for cl in evidence.clusters:
            members = [
                RedundancyClusterMember(
                    variable=m.variable,
                    iv=m.iv,
                    missing_rate=m.missing_rate,
                )
                for m in cl.variables
            ]
            clusters.append(RedundancyCluster(
                cluster_id=cl.cluster_id,
                variables=members,
                representative_suggestion=cl.representative_suggestion,
                representative_reason=cl.representative_reason,
                max_pairwise_abs_corr=cl.max_pairwise_abs_corr,
                notes=list(cl.notes),
            ))

        bundle.redundancy_review = RedundancyReviewInfo(
            method=evidence.method,
            input_representation=evidence.input_representation,
            similarity_metric=evidence.similarity_metric,
            threshold=evidence.threshold,
            absolute_correlation=evidence.absolute_correlation,
            missing_handling=evidence.missing_handling,
            candidate_limit=evidence.candidate_limit,
            representative_rule=evidence.representative_rule,
            minimum_pair_count=evidence.minimum_pair_count,
            cluster_count=len(evidence.clusters),
            singleton_count=len(evidence.singleton_variables),
            clusters=clusters,
            singleton_variables=list(evidence.singleton_variables),
            warnings=[dict(w) for w in evidence.warnings],
        )

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

        existing_m_hash = bundle.reproducibility.manifest_hash
        existing_pw_hash = bundle.reproducibility.pathway_hash
        bundle.reproducibility = ReproducibilityInfo(
            run_id=self.run_id,
            manifest_hash=existing_m_hash,
            pathway_hash=existing_pw_hash,
            execution_fingerprints=fingerprints,
            report_generation=ReportGenerationInfo(
                generated_at=bundle.generated_at,
                cardre_version=CARDRE_VERSION,
            ),
        )

    def _collect_artifacts(self, plan_version_id: str) -> list[ArtifactEntry]:
        entries: list[ArtifactEntry] = []
        seen: set[str] = set()
        for row in self.store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_id = ? AND direction = 'output'",
            (self.run_id,),
        ).fetchall():
            aid = row["artifact_id"]
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

    def _get_latest_review_annotation(self, step_id: str, plan_version_id: str) -> tuple[dict | None, list[Diagnostic]]:
        import json as _json

        try:
            with self.store.transaction() as conn:
                rows = conn.execute(
                    "SELECT payload_json, created_at FROM step_annotations "
                    "WHERE step_id = ? AND plan_version_id = ? AND kind = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (step_id, plan_version_id, "manual_binning_review"),
                ).fetchall()
            if not rows:
                return (None, [])
            payload = _json.loads(rows[0]["payload_json"])
            payload["created_at"] = rows[0]["created_at"]
            return (payload, [])
        except Exception as exc:
            return (None, [Diagnostic(
                code="REVIEW_ANNOTATION_UNREADABLE",
                message="Could not read review annotation.",
                exception_type=type(exc).__name__,
                context={"step_id": step_id, "plan_version_id": plan_version_id},
            )])

    def _collect_run_status(self, bundle: ReportBundle, run: dict) -> None:
        run_diags = self.store.get_run_diagnostics(self.run_id)
        bundle.run_status = RunStatusInfo(
            run_id=self.run_id,
            status=run.get("status", ""),
            started_at=run.get("started_at", ""),
            finished_at=run.get("finished_at"),
        )
        for d in run_diags:
            bundle.run_status.diagnostics.append(DiagnosticEntry(
                code=d.get("code", ""),
                message=d.get("message", ""),
                severity=d.get("severity", "warning"),
                category=d.get("category", ""),
                created_at=d.get("created_at", ""),
            ))
        if run.get("status") and run["status"] != "succeeded":
            self.limitations.append(Limitation(
                severity="blocker",
                code=LimitationCode.RUN_NOT_SUCCEEDED,
                message=f"Run status is '{run['status']}', expected 'succeeded'.",
            ))

    def _read_canonical_manifest(self, bundle: ReportBundle) -> None:
        """Try to read the canonical manifest.json and populate hash fields.

        Validates the manifest payload against the RunManifest model and
        recomputes the self-referential hash (from the raw dict) to detect
        corruption or tampering.
        """
        manifest_path = self.store.root / "exports" / f"manifest-{self.run_id}" / "manifest.json"
        if not manifest_path.exists():
            self.limitations.append(Limitation(
                severity="warning",
                code=LimitationCode.CANONICAL_MANIFEST_MISSING,
                message=f"No canonical manifest at {manifest_path}. "
                "Manifest hash and pathway hash will be empty in the report.",
            ))
            return
        try:
            import json
            raw = manifest_path.read_text()
            manifest_data = json.loads(raw)

            # Validate schema — extra fields are rejected if present
            RunManifest.model_validate(manifest_data)

            # Hash the raw parsed dict, not the Pydantic model, so that
            # extra or unexpected fields are caught by the hash check.
            payload_for_hash = dict(manifest_data)
            payload_for_hash["manifest_hash"] = ""
            expected_hash = json_logical_hash(payload_for_hash)
            actual_hash = manifest_data.get("manifest_hash", "")

            if actual_hash != expected_hash:
                self.limitations.append(Limitation(
                    severity="blocker",
                    code=LimitationCode.ARTIFACT_HASH_UNRESOLVED,
                    message=f"Canonical manifest hash mismatch at {manifest_path}: "
                    f"expected {expected_hash}, got {actual_hash}.",
                ))
                return

            pw_hash = manifest_data.get("pathway_hash", "")
            art_root = manifest_data.get("artifact_root", "")
            bundle.source.run_manifest_path = str(manifest_path)
            bundle.source.run_manifest_hash = actual_hash
            bundle.source.pathway_hash = pw_hash
            bundle.source.artifact_root = art_root
            bundle.reproducibility.manifest_hash = actual_hash
            bundle.reproducibility.pathway_hash = pw_hash

            bundle.run_status.execution_mode = manifest_data.get("execution_mode", "unknown")
            bundle.run_status.target_step_id = manifest_data.get("target_step_id")
            bundle.run_status.in_scope_step_ids = manifest_data.get("in_scope_step_ids", [])

        except json.JSONDecodeError as exc:
            self.limitations.append(Limitation(
                severity="blocker",
                code=LimitationCode.CANONICAL_MANIFEST_UNREADABLE,
                message=f"Invalid JSON in canonical manifest at {manifest_path}: {exc}",
            ))
        except Exception as exc:
            self.limitations.append(Limitation(
                severity="blocker",
                code=LimitationCode.CANONICAL_MANIFEST_UNREADABLE,
                message=f"Could not read or validate canonical manifest at {manifest_path}: {exc}",
            ))

    def _resolve_run_step(
        self, ref: _ResolvedStepRef, plan_version_id: str,
    ) -> RunStep | None:
        branch_id = ref.resolved_branch_id if ref.resolution == "ancestor" else None
        repo = RunRepository(self.store)
        rs = repo.get_latest_successful_step(plan_version_id, ref.step_id, branch_id=branch_id)
        if rs is None and branch_id is not None:
            rs = repo.get_latest_successful_step(plan_version_id, ref.step_id, branch_id=None)
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
