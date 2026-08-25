"""Port-native report collector."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cardre.application.evidence.evidence_resolver import resolve_run_step_evidence
from cardre.application.evidence.explain_staleness import step_is_stale
from cardre.application.ports.artifact_store import ArtifactReader
from cardre.application.ports.evidence_reader import EvidenceReaderPort
from cardre.application.ports.unit_of_work import UnitOfWork
from cardre.application.reporting.contracts import EVIDENCE_KIND_BY_STEP, REQUIRED_STEPS_COLLECTOR
from cardre.application.reporting.schema import (
    AffectedBinDetail,
    ArtifactEntry,
    CutoffInfo,
    CutoffRow,
    CutoffTable,
    DiagnosticEntry,
    ImplementationArtifactInfo,
    Limitation,
    MetricsByRole,
    ModelFeature,
    ModelInfo,
    PathwayStep,
    PsiEntry,
    ReportBundle,
    ScoreScalingInfo,
    ValidationInfo,
    VariableBin,
    VariableInfo,
    WoeSmoothingInfo,
)
from cardre.domain.manifest import compute_manifest_hash


@dataclass(frozen=True)
class CollectReportCommand:
    project_id: str
    run_id: str


class ReportCollector:
    """Assemble immutable run evidence into a report bundle."""

    def __init__(self, evidence_reader: EvidenceReaderPort, artifact_reader: ArtifactReader) -> None:
        self._evidence_reader = evidence_reader
        self._artifact_reader = artifact_reader

    def collect(
        self,
        uow: UnitOfWork,
        project_id: str,
        run_id: str,
    ) -> ReportBundle:
        bundle = ReportBundle(
            project_id=project_id,
            run_id=run_id,
            generated_at=datetime.now(UTC).isoformat(),
        )
        project = uow.projects.get(project_id)
        run = uow.runs.get(run_id)
        if project is not None:
            bundle.summary.model_name = project.name
        if run is None:
            bundle.limitations = [Limitation(code="MISSING_RUN_MANIFEST", severity="blocker", message="Run not found.")]
            return bundle

        bundle.run_status.run_id = run.run_id
        bundle.run_status.status = str(run.status)
        bundle.run_status.started_at = run.started_at
        bundle.run_status.finished_at = run.finished_at
        bundle.run_status.diagnostics = [
            DiagnosticEntry(
                code=str(diagnostic.get("code", "UNKNOWN")),
                message=str(diagnostic.get("message", "")),
                severity=str(diagnostic.get("severity", "warning")),
                category=str(diagnostic.get("category", "")),
                created_at=str(diagnostic.get("created_at", "")),
            )
            for diagnostic in uow.runs.get_diagnostics(run.run_id)
        ]

        plan_id = uow.plans.get_plan_id_for_version(run.plan_version_id)
        plan_steps = {step.step_id: step for step in uow.plans.get_version_steps(run.plan_version_id)}
        limitations: list[Limitation] = []
        requested_steps = {step.step_id: step for step in uow.run_steps.get_for_run(run.run_id)}
        report_steps = dict(requested_steps)
        canonical_by_run_step_id: dict[str, str] = {}
        required_ids = set(REQUIRED_STEPS_COLLECTOR)
        for step in plan_steps.values():
            canonical_step_id = step.canonical_step_id
            if canonical_step_id not in required_ids:
                continue
            run_step = requested_steps.get(step.step_id)
            if run_step is None:
                evidence = resolve_run_step_evidence(
                    uow, run.plan_version_id, step.step_id,
                    plan_id=plan_id,
                    fingerprint_match=plan_steps.get(step.step_id),
                )
                run_step = evidence.run_step if evidence is not None and not step_is_stale(
                    uow, step, list(plan_steps.values()), run.plan_version_id,
                    plan_id, evidence.run_step,
                ) else None
            if run_step is not None:
                report_steps[run_step.run_step_id] = run_step
                canonical_by_run_step_id[run_step.run_step_id] = canonical_step_id
                evidence_kind = EVIDENCE_KIND_BY_STEP.get(canonical_step_id)
                if evidence_kind is not None:
                    typed_evidence = self._evidence_reader.read_step_output_optional(
                        run_step.run_step_id, evidence_kind,
                    )
                    if typed_evidence is not None:
                        bundle.modelling_metadata[canonical_step_id] = self._to_json(typed_evidence)
                        self._apply_typed_evidence(bundle, canonical_step_id, typed_evidence)
            bundle.pathway.steps.append(PathwayStep(
                canonical_step_id=canonical_step_id,
                step_id=step.step_id,
                step_type=step.node_type,
                config_hash=step.params_hash,
                status=run_step.status.value if run_step is not None else "missing",
            ))

        seen_artifacts: set[str] = set()
        for run_step in report_steps.values():
            for _, artifact in uow.artifacts.artifacts_for_run_step(run_step.run_step_id):
                if artifact.artifact_id in seen_artifacts:
                    continue
                seen_artifacts.add(artifact.artifact_id)
                bundle.artifacts.append(ArtifactEntry(
                    artifact_id=artifact.artifact_id,
                    artifact_type=artifact.artifact_type,
                    role=artifact.role,
                    logical_hash=artifact.logical_hash,
                    physical_hash=artifact.physical_hash,
                    path=artifact.path,
                ))
                canonical_step_id = canonical_by_run_step_id.get(run_step.run_step_id)
                implementation_field = {
                    "scorecard-table-export": "scorecard_table",
                    "scoring-export-python": "scoring_export_python",
                    "scoring-export-sql": "scoring_export_sql",
                }.get(canonical_step_id or "")
                if implementation_field and getattr(bundle.implementation_artifacts, implementation_field) is None:
                    setattr(
                        bundle.implementation_artifacts,
                        implementation_field,
                        ImplementationArtifactInfo(
                            artifact_type=artifact.artifact_type,
                            schema_version=getattr(
                                artifact,
                                "schema_version",
                                artifact.metadata.get("schema_version", ""),
                            ),
                            artifact_id=artifact.artifact_id,
                            description=f"Output from {canonical_step_id}",
                        ),
                    )
                if not self._artifact_reader.resolve_path(artifact).exists():
                    limitations.append(Limitation(
                        code="ARTIFACT_NOT_FOUND",
                        message=f"Artifact {artifact.artifact_id} is not available in the artifact store.",
                    ))

        bundle.reproducibility.run_id = run.run_id
        manifest_path = self._artifact_reader.root / "manifests" / "runs" / f"{run.run_id}.json"
        if not manifest_path.exists():
            limitations.append(Limitation(severity="blocker", code="CANONICAL_MANIFEST_MISSING", message="Canonical run manifest is missing."))
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                recorded_hash = manifest.get("manifest_hash", "")
                if not recorded_hash or recorded_hash != compute_manifest_hash(manifest):
                    limitations.append(Limitation(severity="blocker", code="ARTIFACT_HASH_UNRESOLVED", message="Canonical run manifest hash does not verify."))
                else:
                    if (
                        manifest.get("run_id") != run.run_id
                        or manifest.get("plan_version_id") != run.plan_version_id
                        or manifest.get("status") != str(run.status)
                    ):
                        limitations.append(Limitation(severity="blocker", code="CANONICAL_MANIFEST_MISMATCH", message="Canonical run manifest does not match the requested run."))
                    bundle.reproducibility.manifest_hash = recorded_hash
                    bundle.reproducibility.pathway_hash = manifest.get("pathway_hash", "")
            except (OSError, ValueError, TypeError):
                limitations.append(Limitation(severity="blocker", code="CANONICAL_MANIFEST_UNREADABLE", message="Canonical run manifest cannot be read."))
        bundle.limitations = limitations
        return bundle

    @staticmethod
    def _to_json(value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "to_dict"):
            return value.to_dict()
        return value

    def _apply_typed_evidence(
        self,
        bundle: ReportBundle,
        canonical_step_id: str,
        evidence: Any,
    ) -> None:
        if canonical_step_id == "final-woe-iv":
            smoothing = evidence.smoothing
            for variable in evidence.variables:
                bins = [
                    VariableBin(
                        bin_id=item.bin_id, label=item.label, lower=item.lower, upper=item.upper,
                        good_count=item.good_count, bad_count=item.bad_count, bad_rate=item.bad_rate,
                        woe=item.woe, iv_contribution=item.iv_contribution,
                    )
                    for item in variable.bins
                ]
                bundle.variables.append(VariableInfo(
                    variable_name=variable.variable_name,
                    role=variable.status,
                    final_bin_count=len(bins),
                    iv=variable.iv,
                    woe_smoothing=WoeSmoothingInfo(
                        enabled=smoothing.enabled, method=smoothing.method, alpha=smoothing.alpha,
                        zero_cell_policy=smoothing.zero_cell_policy,
                        smoothing_applied=variable.smoothing_applied,
                        zero_cell_encountered=variable.zero_cell_encountered,
                        affected_bin_count=len(variable.affected_bins),
                    ),
                    bins=bins,
                    affected_bins=[AffectedBinDetail(**item.detail) for item in variable.affected_bins],
                ))
        elif canonical_step_id == "model-fit":
            target = evidence.target_column or bundle.summary.target_column
            bundle.summary.target_column = target
            bundle.model = ModelInfo(
                target=target,
                features=[
                    ModelFeature(
                        variable_name=item.variable_name,
                        coefficient=item.coefficient,
                        standard_error=item.standard_error,
                        p_value=item.p_value,
                    )
                    for item in evidence.coefficients
                ],
                intercept=evidence.intercept,
            )
        elif canonical_step_id == "score-scaling":
            bundle.score_scaling = ScoreScalingInfo(
                base_score=evidence.base_score,
                base_odds=evidence.base_odds_text,
                points_to_double_odds=evidence.points_to_double_odds,
                factor=evidence.factor,
                offset=evidence.offset,
                score_direction=evidence.score_direction,
                rounding=evidence.rounding,
                min_score=evidence.min_score,
                max_score=evidence.max_score,
            )
        elif canonical_step_id == "validation-metrics":
            validation = ValidationInfo()
            for role, metrics in evidence.metrics_by_role.items():
                validation.metrics_by_role.append(MetricsByRole(
                    role=role, row_count=metrics.row_count, auc=metrics.auc, gini=metrics.gini,
                    ks=metrics.ks, bad_rate=metrics.bad_rate,
                ))
            validation.stability.psi_by_role = [
                PsiEntry(comparison=comparison, score_psi=value)
                for comparison, value in evidence.psi.items()
            ]
            bundle.validation = validation
        elif canonical_step_id == "cutoff-analysis":
            bundle.cutoffs = CutoffInfo(
                cutoff_tables=[
                    CutoffTable(
                        role=role,
                        rows=[
                            CutoffRow(
                                score_cutoff=row.score_cutoff,
                                approval_rate=row.approval_rate,
                                bad_rate=row.bad_rate,
                                capture_rate=row.capture_rate,
                            )
                            for row in rows
                        ],
                    )
                    for role, rows in evidence.cutoff_tables.items()
                ],
            )


__all__ = ["CollectReportCommand", "ReportCollector"]
