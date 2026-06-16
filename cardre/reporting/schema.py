"""Report bundle schema for cardre.report_bundle.v1.

Every section of the report bundle is defined here as a Pydantic model
for deterministic serialization and validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from cardre.reporting.limitation_codes import LimitationCode  # noqa: F401


# ---------------------------------------------------------------------------
# Source step reference — tracks exact vs inherited resolution
# ---------------------------------------------------------------------------

class ResolvedStepRef(BaseModel):
    requested_branch_id: str
    resolved_branch_id: str
    canonical_step_id: str
    step_id: str
    resolution: str = "exact"  # "exact" | "ancestor"


# ---------------------------------------------------------------------------
# Source / run manifest
# ---------------------------------------------------------------------------

class ReportSource(BaseModel):
    run_manifest_path: str = ""
    run_manifest_hash: str = ""
    pathway_hash: str = ""
    artifact_root: str = ""


# ---------------------------------------------------------------------------
# Dataset role
# ---------------------------------------------------------------------------

class DatasetTargetSummary(BaseModel):
    good_count: int = 0
    bad_count: int = 0
    bad_rate: float = 0.0


class DatasetDateRange(BaseModel):
    min: str = ""
    max: str = ""


class DatasetRole(BaseModel):
    role: str
    dataset_id: str = ""
    row_count: int = 0
    column_count: int = 0
    target: DatasetTargetSummary = Field(default_factory=DatasetTargetSummary)
    date_range: DatasetDateRange = Field(default_factory=DatasetDateRange)
    artifacts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pathway step
# ---------------------------------------------------------------------------

class PathwayStep(BaseModel):
    canonical_step_id: str
    step_id: str
    branch_id: str = ""
    step_type: str = ""
    status: str = ""
    config_hash: str = ""
    resolution: str = "exact"


class PathwaySummary(BaseModel):
    pathway_id: str = ""
    steps: list[PathwayStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Branch info
# ---------------------------------------------------------------------------

class BranchInfo(BaseModel):
    branch_id: str
    name: str = ""
    parent_branch_id: str | None = None
    created_from_canonical_step_id: str | None = None
    is_target_branch: bool = False
    is_champion: bool = False
    status: str = ""


class BranchSummary(BaseModel):
    branching_model: str = ""
    target_branch_id: str = ""
    branches: list[BranchInfo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Champion
# ---------------------------------------------------------------------------

class ChampionInfo(BaseModel):
    champion_status: str = "not_available"  # "selected" | "not_available"
    assignment_id: str | None = None
    champion_branch_id: str | None = None
    comparison_artifact_id: str | None = None
    rationale: str | None = None
    selected_at: str | None = None
    target_branch_is_champion: bool = False


# ---------------------------------------------------------------------------
# WOE smoothing
# ---------------------------------------------------------------------------

class WoeSmoothingInfo(BaseModel):
    enabled: bool = False
    method: str = "additive"
    alpha: float = 0.5
    zero_cell_policy: str = "block"
    smoothing_applied: bool = False
    zero_cell_encountered: bool = False
    affected_bin_count: int = 0


class AffectedBinDetail(BaseModel):
    bin_id: str
    reason: str = ""
    raw_good_count: int = 0
    raw_bad_count: int = 0
    smoothed_good_count: float = 0.0
    smoothed_bad_count: float = 0.0
    raw_woe: float | None = None
    final_woe: float = 0.0


class VariableBin(BaseModel):
    bin_id: str
    label: str = ""
    lower: float | None = None
    upper: float | None = None
    good_count: int = 0
    bad_count: int = 0
    bad_rate: float = 0.0
    woe: float | None = None
    iv_contribution: float | None = None


class VariableInfo(BaseModel):
    variable_name: str
    role: str = "included"
    branch_id: str = ""
    type: str = ""
    final_bin_count: int = 0
    iv: float = 0.0
    monotonicity_status: str = ""
    manual_edits: bool = False
    woe_smoothing: WoeSmoothingInfo = Field(default_factory=WoeSmoothingInfo)
    source_step_refs: list[ResolvedStepRef] = Field(default_factory=list)
    bins: list[VariableBin] = Field(default_factory=list)
    affected_bins: list[AffectedBinDetail] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class ModelFeature(BaseModel):
    variable_name: str
    coefficient: float = 0.0
    standard_error: float | None = None
    p_value: float | None = None
    included: bool = True


class ModelInfo(BaseModel):
    model_type: str = "logistic_regression_scorecard"
    branch_id: str = ""
    target: str = ""
    features: list[ModelFeature] = Field(default_factory=list)
    intercept: float = 0.0
    regularisation: Any = None
    fit_dataset_role: str = "train"
    fitting_config_hash: str = ""


# ---------------------------------------------------------------------------
# Score scaling
# ---------------------------------------------------------------------------

class ScoreScalingInfo(BaseModel):
    base_score: int = 600
    base_odds: str = "50:1"
    pdo: int = 20
    factor: float = 0.0
    offset: float = 0.0
    score_direction: str = "higher_is_better"
    rounding: str = "nearest_integer"
    min_score: int = 0
    max_score: int = 0


# ---------------------------------------------------------------------------
# Validation metrics
# ---------------------------------------------------------------------------

class MetricsByRole(BaseModel):
    role: str
    row_count: int = 0
    auc: float | None = None
    gini: float | None = None
    ks: float | None = None
    bad_rate: float | None = None
    score_mean: float | None = None
    score_min: float | None = None
    score_max: float | None = None


class PsiEntry(BaseModel):
    comparison: str = ""
    score_psi: float | None = None


class StabilityInfo(BaseModel):
    psi_by_role: list[PsiEntry] = Field(default_factory=list)


class ValidationInfo(BaseModel):
    metrics_by_role: list[MetricsByRole] = Field(default_factory=list)
    stability: StabilityInfo = Field(default_factory=StabilityInfo)


# ---------------------------------------------------------------------------
# Cutoff
# ---------------------------------------------------------------------------

class CutoffRow(BaseModel):
    score_cutoff: float = 0.0
    approval_rate: float = 0.0
    bad_rate: float = 0.0
    capture_rate: float = 0.0


class CutoffTable(BaseModel):
    role: str = ""
    rows: list[CutoffRow] = Field(default_factory=list)


class SelectedCutoff(BaseModel):
    score: int | None = None
    selection_reason: str = ""


class CutoffInfo(BaseModel):
    cutoff_tables: list[CutoffTable] = Field(default_factory=list)
    selected_cutoff: SelectedCutoff = Field(default_factory=SelectedCutoff)


# ---------------------------------------------------------------------------
# Manual intervention
# ---------------------------------------------------------------------------

class ManualIntervention(BaseModel):
    intervention_id: str
    branch_id: str = ""
    canonical_step_id: str = ""
    step_id: str = ""
    type: str = ""
    variable_name: str = ""
    before_artifact: str = ""
    after_artifact: str = ""
    reason: str = ""
    created_at: str = ""


# ---------------------------------------------------------------------------
# Limitation / warning
# ---------------------------------------------------------------------------

class Limitation(BaseModel):
    severity: str = "warning"  # "warning" | "info" | "blocker"
    code: str
    message: str = ""


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class ExecutionFingerprint(BaseModel):
    step_id: str = ""
    canonical_step_id: str = ""
    python_version: str = ""
    platform: str = ""
    package_fingerprint: dict[str, Any] = Field(default_factory=dict)


class ReportGenerationInfo(BaseModel):
    generated_at: str = ""
    cardre_version: str = "0.1.0"


class ReproducibilityInfo(BaseModel):
    run_id: str = ""
    manifest_hash: str = ""
    pathway_hash: str = ""
    execution_fingerprints: list[ExecutionFingerprint] = Field(default_factory=list)
    report_generation: ReportGenerationInfo = Field(default_factory=ReportGenerationInfo)


# ---------------------------------------------------------------------------
# Artifact entry
# ---------------------------------------------------------------------------

class ArtifactEntry(BaseModel):
    artifact_id: str = ""
    artifact_type: str = ""
    role: str = ""
    logical_hash: str = ""
    physical_hash: str = ""
    path: str = ""


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class ReportSummary(BaseModel):
    model_name: str = ""
    target_column: str = ""
    observation_level: str = ""
    development_sample: str = "train"
    validation_samples: list[str] = Field(default_factory=list)
    candidate_branch_count: int = 0
    target_branch_id: str = ""
    champion_branch_id: str = ""
    final_variable_count: int = 0
    excluded_variable_count: int = 0
    report_status: str = ""


# ---------------------------------------------------------------------------
# Top-level ReportBundle
# ---------------------------------------------------------------------------

class GeneratedBy(BaseModel):
    cardre_version: str = "0.1.0"


class ReportBundle(BaseModel):
    schema_version: str = "cardre.report_bundle.v1"
    project_id: str = ""
    run_id: str = ""
    target_branch_id: str = ""
    report_mode: str = "branch"
    generated_at: str = ""
    generated_by: GeneratedBy = Field(default_factory=GeneratedBy)
    source: ReportSource = Field(default_factory=ReportSource)
    summary: ReportSummary = Field(default_factory=ReportSummary)
    dataset_roles: list[DatasetRole] = Field(default_factory=list)
    pathway: PathwaySummary = Field(default_factory=PathwaySummary)
    branches: BranchSummary = Field(default_factory=BranchSummary)
    champion: ChampionInfo = Field(default_factory=ChampionInfo)
    variables: list[VariableInfo] = Field(default_factory=list)
    model: ModelInfo = Field(default_factory=ModelInfo)
    score_scaling: ScoreScalingInfo = Field(default_factory=ScoreScalingInfo)
    validation: ValidationInfo = Field(default_factory=ValidationInfo)
    cutoffs: CutoffInfo = Field(default_factory=CutoffInfo)
    manual_interventions: list[ManualIntervention] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    reproducibility: ReproducibilityInfo = Field(default_factory=ReproducibilityInfo)
    artifacts: list[ArtifactEntry] = Field(default_factory=list)
