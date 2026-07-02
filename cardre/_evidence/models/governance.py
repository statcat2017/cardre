"""Governance / feature-selection / fairness / clustering data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict
from cardre._evidence.models.binning import SelectedVariable


@dataclass(frozen=True)
class FeatureSelectionEvidence:
    method: str
    selected: list[SelectedVariable]
    rejected: list[JsonDict] = field(default_factory=list)
    selected_count: int = 0
    rejected_count: int = 0
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> FeatureSelectionEvidence:
        selected = data.get("selected", [])
        if selected and isinstance(selected[0], str):
            selected_vars = [SelectedVariable(variable=str(v)) for v in selected]
        else:
            selected_vars = [
                SelectedVariable(
                    variable=s.get("variable", ""),
                    reason=s.get("reason", ""),
                    extra={k: v for k, v in s.items() if k not in ("variable", "reason")},
                )
                for s in selected
                if isinstance(s, dict)
            ]
        return cls(
            method=data.get("method", ""),
            selected=selected_vars,
            rejected=list(data.get("rejected", [])),
            selected_count=int(data.get("selected_count", len(selected_vars))),
            rejected_count=int(data.get("rejected_count", len(data.get("rejected", [])))),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ResamplingEvidence:
    strategy: str
    original: JsonDict
    resampled: JsonDict
    synthetic_rows_added: int = 0
    rows_dropped: int = 0
    sampling_ratio: float | None = None
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ResamplingEvidence:
        return cls(
            strategy=data.get("strategy", ""),
            original=dict(data.get("original", {})),
            resampled=dict(data.get("resampled", {})),
            synthetic_rows_added=int(data.get("synthetic_rows_added", 0)),
            rows_dropped=int(data.get("rows_dropped", 0)),
            sampling_ratio=data.get("sampling_ratio"),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class HyperparameterTuningEvidence:
    estimator_type: str
    search_method: str
    best_params: JsonDict
    best_score: float = 0.0
    cv_results_shape: list[int] = field(default_factory=list)
    feature_count: int = 0
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> HyperparameterTuningEvidence:
        return cls(
            estimator_type=data.get("estimator_type", ""),
            search_method=data.get("search_method", ""),
            best_params=dict(data.get("best_params", {})),
            best_score=float(data.get("best_score", 0.0)),
            cv_results_shape=list(data.get("cv_results_shape", [])),
            feature_count=int(data.get("feature_count", 0)),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ExplainabilityReport:
    model_family: str
    limitations: list[str]
    explanation_level: str = ""
    native_importance_available: bool = False
    global_importance_fields: list[str] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ExplainabilityReport:
        return cls(
            model_family=data.get("model_family", ""),
            limitations=[str(v) for v in data.get("limitations", [])],
            explanation_level=data.get("explanation_level", ""),
            native_importance_available=bool(data.get("native_importance_available", False)),
            global_importance_fields=[str(v) for v in data.get("global_importance_fields", [])],
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class FairnessReport:
    roles: JsonDict
    parity_summary: JsonDict
    sensitive_columns: list[str] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> FairnessReport:
        return cls(
            roles=dict(data.get("roles", {})),
            parity_summary=dict(data.get("parity_summary", {})),
            sensitive_columns=[str(v) for v in data.get("sensitive_columns", [])],
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ProxyRiskReport:
    proxy_flags: list[JsonDict]
    overall_risk: str
    sensitive_columns: list[str] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ProxyRiskReport:
        return cls(
            proxy_flags=list(data.get("proxy_flags", [])),
            overall_risk=data.get("overall_risk", ""),
            sensitive_columns=[str(v) for v in data.get("sensitive_columns", [])],
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class RejectInferenceResult:
    schema_version: str = ""
    source_artifact_id: str = ""
    method: str = "none"
    method_params: dict[str, Any] = field(default_factory=dict)
    missingness_assumption: str = "MAR"
    ignorability_note: str = ""
    theoretical_limitations: list[str] = field(default_factory=list)
    n_financed: int = 0
    n_non_financed: int = 0
    n_inferred_good: int = 0
    n_inferred_bad: int = 0
    n_never_labeled: int = 0
    resampling_factor: float | None = None
    weight_summary: dict[str, float] | None = None
    convergence: dict[str, Any] | None = None
    runtime_seconds: float = 0.0

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RejectInferenceResult:
        return cls(
            schema_version=data.get("schema_version", ""),
            source_artifact_id=data.get("source_artifact_id", ""),
            method=data.get("method", "none"),
            method_params=dict(data.get("method_params", {})),
            missingness_assumption=data.get("missingness_assumption", "MAR"),
            ignorability_note=data.get("ignorability_note", ""),
            theoretical_limitations=list(data.get("theoretical_limitations", [])),
            n_financed=data.get("n_financed", 0),
            n_non_financed=data.get("n_non_financed", 0),
            n_inferred_good=data.get("n_inferred_good", 0),
            n_inferred_bad=data.get("n_inferred_bad", 0),
            n_never_labeled=data.get("n_never_labeled", 0),
            resampling_factor=data.get("resampling_factor"),
            weight_summary=data.get("weight_summary"),
            convergence=data.get("convergence"),
            runtime_seconds=float(data.get("runtime_seconds", 0)),
        )


@dataclass(frozen=True)
class RejectPopulationConfig:
    schema_version: str = ""
    source_artifact_id: str = ""
    total_rows: int = 0
    financed_rows: int = 0
    non_financed_rows: int = 0
    indeterminate_rows: int = 0
    unlabeled_accepted_rows: int = 0
    rejection_source: str = "target_missing"
    rejection_column: str | None = None
    rejection_values: list[str] | None = None
    exclusion_categories: dict[str, int] = field(default_factory=dict)
    observation_window_note: str = ""

    @classmethod
    def from_json(cls, data: JsonDict) -> RejectPopulationConfig:
        return cls(
            schema_version=data.get("schema_version", ""),
            source_artifact_id=data.get("source_artifact_id", ""),
            total_rows=data.get("total_rows", 0),
            financed_rows=data.get("financed_rows", 0),
            non_financed_rows=data.get("non_financed_rows", 0),
            indeterminate_rows=data.get("indeterminate_rows", 0),
            unlabeled_accepted_rows=data.get("unlabeled_accepted_rows", 0),
            rejection_source=data.get("rejection_source", "target_missing"),
            rejection_column=data.get("rejection_column"),
            rejection_values=data.get("rejection_values"),
            exclusion_categories=dict(data.get("exclusion_categories", {})),
            observation_window_note=data.get("observation_window_note", ""),
        )


@dataclass(frozen=True)
class VariableClusteringEvidence:
    method: str
    input_representation: str = ""
    similarity_metric: str = ""
    threshold: float | None = None
    absolute_correlation: bool = True
    missing_handling: str = "pairwise"
    candidate_limit: int = 50
    minimum_pair_count: int = 30
    representative_rule: str = "highest_iv"
    clusters: list[VariableCluster] = field(default_factory=list)
    singleton_variables: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> VariableClusteringEvidence:
        from cardre._evidence.schemas import SCHEMA_VARIABLE_CLUSTERING_EVIDENCE
        raw_clusters = data.get("clusters", [])
        clusters = []
        for rc in raw_clusters:
            raw_vars = rc.get("variables", [])
            members = []
            for v in raw_vars:
                if isinstance(v, dict):
                    members.append(ClusterMember(
                        variable=v["variable"],
                        iv=v.get("iv"),
                        missing_rate=v.get("missing_rate"),
                    ))
                else:
                    members.append(ClusterMember(variable=str(v)))
            clusters.append(VariableCluster(
                cluster_id=rc.get("cluster_id", ""),
                variables=members,
                representative_suggestion=rc.get("representative_suggestion"),
                representative_reason=rc.get("representative_reason", ""),
                max_pairwise_abs_corr=rc.get("max_pairwise_abs_corr"),
                notes=list(rc.get("notes", [])),
            ))
        return cls(
            method=data.get("method", ""),
            input_representation=data.get("input_representation", ""),
            similarity_metric=data.get("similarity_metric", ""),
            threshold=data.get("threshold"),
            absolute_correlation=data.get("absolute_correlation", True),
            missing_handling=data.get("missing_handling", "pairwise"),
            candidate_limit=data.get("candidate_limit", 50),
            representative_rule=data.get("representative_rule", "highest_iv"),
            minimum_pair_count=data.get("minimum_pair_count", 30),
            clusters=clusters,
            singleton_variables=list(data.get("singleton_variables", [])),
            warnings=list(data.get("warnings", [])),
            schema_version=data.get("schema_version", SCHEMA_VARIABLE_CLUSTERING_EVIDENCE),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class ClusterMember:
    variable: str
    iv: float | None = None
    missing_rate: float | None = None


@dataclass(frozen=True)
class VariableCluster:
    cluster_id: str
    variables: list[ClusterMember] = field(default_factory=list)
    representative_suggestion: str | None = None
    representative_reason: str = ""
    max_pairwise_abs_corr: float | None = None
    notes: list[str] = field(default_factory=list)
