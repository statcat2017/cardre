"""Typed evidence data models."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class BinVariable:
    variable: str
    dtype: str = ""
    kind: str = ""
    bins: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {"variable": self.variable, "dtype": self.dtype, "kind": self.kind, "bins": self.bins}


@dataclass(frozen=True)
class BinDefinition:
    variables: list[BinVariable]
    source_artifact_id: str
    _lifecycle: Any = field(default=None, repr=False)

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> BinDefinition:
        from cardre.engine.binning.definition import LifecycleBinDefinition
        lifecycle = LifecycleBinDefinition.from_payload(data)
        variables = [
            BinVariable(
                variable=v.get("variable", ""),
                dtype=v.get("dtype", ""),
                kind=v.get("kind", ""),
                bins=list(v.get("bins", [])),
            )
            for v in data.get("variables", [])
        ]
        return cls(variables=variables, source_artifact_id=artifact_id, _lifecycle=lifecycle)

    def to_dict(self) -> JsonDict:
        if self._lifecycle is not None:
            return self._lifecycle.to_payload()
        return {"variables": [v.to_dict() for v in self.variables]}

    @property
    def lifecycle(self) -> Any | None:
        return self._lifecycle

    @property
    def rejected(self) -> list[Any]:
        if self._lifecycle is not None:
            return list(self._lifecycle.rejected)
        return []

    @property
    def warnings(self) -> list[JsonDict]:
        if self._lifecycle is not None:
            return list(self._lifecycle.warnings)
        return []

    @property
    def source(self) -> JsonDict | None:
        if self._lifecycle is not None:
            return self._lifecycle.source
        return None


@dataclass(frozen=True)
class SelectedVariable:
    variable: str
    reason: str = ""
    extra: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class SelectionDefinition:
    selected: list[SelectedVariable]
    method: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SelectionDefinition:
        selected = [
            SelectedVariable(
                variable=s.get("variable", ""),
                reason=s.get("reason", ""),
                extra={k: v for k, v in s.items() if k not in ("variable", "reason")},
            )
            for s in data.get("selected", [])
        ]
        return cls(selected=selected, method=data.get("method", ""), source_artifact_id=artifact_id)

    @property
    def selected_names(self) -> set[str]:
        return {s.variable for s in self.selected}

    def to_dict(self) -> JsonDict:
        return {
            "selected": [
                {"variable": s.variable, "reason": s.reason, **s.extra}
                for s in self.selected
            ],
            "method": self.method,
        }


@dataclass(frozen=True)
class ModellingMetadata:
    target_column: str
    good_values: list[Any]
    bad_values: list[Any]
    indeterminate_values: list[Any] = field(default_factory=list)
    extra: JsonDict = field(default_factory=dict)
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ModellingMetadata:
        return cls(
            target_column=data.get("target_column", ""),
            good_values=list(data.get("good_values", [])),
            bad_values=list(data.get("bad_values", [])),
            indeterminate_values=list(data.get("indeterminate_values", [])),
            extra={k: v for k, v in data.items()
                   if k not in ("target_column", "good_values", "bad_values", "indeterminate_values")},
            _raw=data,
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class SampleDefinition:
    sample_method: str = "full_population"
    sample_domain: str = "ttd"
    total_rows: int = 0
    financed_rows: int = 0
    non_financed_rows: int = 0
    rejection_source: str | None = None
    rejection_column: str | None = None
    rejection_values: list[Any] | None = None
    approval_column: str | None = None
    approval_values: list[Any] = field(default_factory=list)
    weight_column: str | None = None
    sample_description: str = ""
    extra: JsonDict = field(default_factory=dict)
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SampleDefinition:
        return cls(
            sample_method=data.get("sample_method", "full_population"),
            sample_domain=data.get("sample_domain", "ttd"),
            total_rows=data.get("total_rows", 0),
            financed_rows=data.get("financed_rows", 0),
            non_financed_rows=data.get("non_financed_rows", 0),
            rejection_source=data.get("rejection_source"),
            rejection_column=data.get("rejection_column"),
            rejection_values=data.get("rejection_values"),
            approval_column=data.get("approval_column"),
            approval_values=list(data.get("approval_values", [])),
            weight_column=data.get("weight_column"),
            sample_description=data.get("sample_description", ""),
            extra={k: v for k, v in data.items()
                   if k not in ("sample_method", "sample_domain", "total_rows",
                                "financed_rows", "non_financed_rows",
                                "rejection_source", "rejection_column",
                                 "rejection_values", "approval_column",
                                 "approval_values", "weight_column",
                                 "sample_description")},
            _raw=data,
            source_artifact_id=artifact_id,
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
class AffectedBin:
    bin_id: str
    detail: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class WoeBin:
    bin_id: str
    label: str = ""
    lower: float | None = None
    upper: float | None = None
    good_count: int = 0
    bad_count: int = 0
    bad_rate: float = 0.0
    woe: float | None = None
    iv_contribution: float | None = None


@dataclass(frozen=True)
class WoeSmoothing:
    enabled: bool = False
    method: str = "additive"
    alpha: float = 0.5
    zero_cell_policy: str = "block"


@dataclass(frozen=True)
class WoeIvVariable:
    variable_name: str
    iv: float = 0.0
    status: str = "included"
    bins: list[WoeBin] = field(default_factory=list)
    affected_bins: list[AffectedBin] = field(default_factory=list)
    smoothing_applied: bool = False
    zero_cell_encountered: bool = False
    warnings: list[JsonDict] = field(default_factory=list)


@dataclass(frozen=True)
class WoeIvEvidence:
    variables: list[WoeIvVariable]
    smoothing: WoeSmoothing = field(default_factory=WoeSmoothing)
    schema_version: str = ""
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> WoeIvEvidence:
        config = data.get("config", {})
        smoothing_config = config.get("smoothing", {})
        smoothing = WoeSmoothing(
            enabled=smoothing_config.get("enabled", False),
            method=smoothing_config.get("method", "additive"),
            alpha=smoothing_config.get("alpha", 0.5),
            zero_cell_policy=smoothing_config.get("zero_cell_policy", "block"),
        )

        variables = []
        for v in data.get("variables", []):
            bins = [
                WoeBin(
                    bin_id=b.get("bin_id", ""),
                    label=b.get("label", ""),
                    lower=b.get("lower"),
                    upper=b.get("upper"),
                    good_count=b.get("good_count", 0),
                    bad_count=b.get("bad_count", 0),
                    bad_rate=b.get("bad_rate", 0.0),
                    woe=b.get("woe"),
                    iv_contribution=b.get("iv_contribution"),
                )
                for b in v.get("bins", [])
            ]
            affected_bins = [
                AffectedBin(bin_id=ab.get("bin_id", ""), detail=ab)
                for ab in v.get("affected_bins", [])
            ]
            variables.append(WoeIvVariable(
                variable_name=v.get("variable_name", v.get("variable", "")),
                iv=float(v.get("iv", 0)),
                status=v.get("status", "included"),
                bins=bins,
                affected_bins=affected_bins,
                smoothing_applied=v.get("smoothing_applied", False),
                zero_cell_encountered=v.get("zero_cell_encountered", False),
                warnings=list(v.get("warnings", [])),
            ))

        return cls(
            variables=variables,
            smoothing=smoothing,
            schema_version=data.get("schema_version", ""),
            _raw=data,
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class Coefficient:
    variable_name: str
    coefficient: float = 0.0
    standard_error: float | None = None
    p_value: float | None = None


@dataclass(frozen=True)
class ModelArtifact:
    model_family: str
    features: list[str]
    target_column: str
    intercept: float = 0.0
    coefficients: list[Coefficient] = field(default_factory=list)
    coefficients_dict: dict[str, float] = field(default_factory=dict)
    training: JsonDict = field(default_factory=dict)
    warnings: list[JsonDict] = field(default_factory=list)
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""
    ensemble_type: str = ""
    base_models: list[JsonDict] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    voting: str = ""
    threshold: float | None = None
    estimator_reference: JsonDict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ModelArtifact:
        coefficients: list[Coefficient] = []
        coefficients_dict: dict[str, float] = {}
        raw_coeffs = data.get("coefficients", [])
        model_payload = data.get("model_payload", {}) if isinstance(data.get("model_payload", {}), dict) else {}
        model_family = str(data.get("model_family", "")).strip()

        if isinstance(raw_coeffs, dict):
            coefficients_dict = {
                k: v for k, v in raw_coeffs.items()
                if isinstance(v, (int, float))
            }
            coefficients = [
                Coefficient(variable_name=k, coefficient=v)
                for k, v in coefficients_dict.items()
            ]
        elif isinstance(raw_coeffs, list):
            for c in raw_coeffs:
                if isinstance(c, dict):
                    coefficients.append(Coefficient(
                        variable_name=c.get("variable_name", c.get("variable", "")),
                        coefficient=c.get("coefficient", 0.0),
                        standard_error=c.get("standard_error"),
                        p_value=c.get("p_value"),
                    ))
                    var_name = c.get("variable_name") or c.get("variable", "")
                    if var_name and isinstance(c.get("coefficient"), (int, float)):
                        coefficients_dict[var_name] = c["coefficient"]

        features = data.get("features", [])
        if not features and coefficients_dict:
            features = list(coefficients_dict.keys())
        if not model_family and (coefficients_dict or raw_coeffs):
            model_family = "logistic_regression"

        return cls(
            model_family=model_family,
            features=features,
            target_column=data.get("target_column", ""),
            intercept=float(data.get("intercept", 0)),
            coefficients=coefficients,
            coefficients_dict=coefficients_dict,
            training=data.get("training", {}),
            warnings=list(data.get("warnings", [])),
            _raw=data,
            source_artifact_id=artifact_id,
            ensemble_type=str(model_payload.get("ensemble_type", "")),
            base_models=list(model_payload.get("base_models", [])),
            weights=[float(v) for v in model_payload.get("weights", []) if isinstance(v, (int, float))],
            voting=str(model_payload.get("voting", "")),
            threshold=model_payload.get("threshold"),
            estimator_reference=dict(data.get("estimator_reference", {})),
        )

    def as_legacy_dict(self) -> JsonDict:
        return {
            "model_family": self.model_family,
            "coefficients": self.coefficients_dict,
            "intercept": self.intercept,
            "features": self.features,
            "target_column": self.target_column,
        }


@dataclass(frozen=True)
class ScoreScaling:
    base_score: int = 600
    base_odds: str = "50:1"
    pdo: int = 20
    factor: float = 0.0
    offset: float = 0.0
    score_direction: str = "higher_is_better"
    rounding: str = "nearest_integer"
    min_score: int = 0
    max_score: int = 0
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ScoreScaling:
        raw_odds = data.get("base_odds", "50:1")
        base_odds = str(raw_odds) if not isinstance(raw_odds, str) else raw_odds
        higher_score_is_lower_risk = data.get("higher_score_is_lower_risk")
        pdo = data.get("pdo", data.get("points_to_double_odds", 20))
        base_score = data.get("base_score", 600)
        if "factor" in data and "offset" in data:
            factor = float(data.get("factor", 0))
            offset = float(data.get("offset", 0))
        else:
            factor = float(pdo) / math.log(2)
            odds_ratio = base_odds
            if isinstance(raw_odds, str) and ":" in raw_odds:
                num, den = raw_odds.split(":", 1)
                odds_ratio = float(num) / float(den)
            else:
                odds_ratio = float(raw_odds)
            offset = float(base_score) - factor * math.log(odds_ratio)
        return cls(
            base_score=base_score,
            base_odds=base_odds,
            pdo=pdo,
            factor=factor,
            offset=offset,
            score_direction=(
                "higher_is_lower_risk"
                if higher_score_is_lower_risk is True
                else data.get("score_direction", "higher_is_better")
            ),
            rounding=data.get("rounding", "nearest_integer"),
            min_score=data.get("min_score", 0),
            max_score=data.get("max_score", 0),
            _raw=data,
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class RoleMetrics:
    row_count: int = 0
    auc: float | None = None
    gini: float | None = None
    ks: float | None = None
    bad_rate: float | None = None


@dataclass(frozen=True)
class ValidationMetrics:
    metrics_by_role: dict[str, RoleMetrics] = field(default_factory=dict)
    psi: dict[str, float] = field(default_factory=dict)
    target: JsonDict = field(default_factory=dict)
    gates: list[JsonDict] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ValidationMetrics:
        metrics_by_role: dict[str, RoleMetrics] = {}
        raw_metrics = data.get("roles", data.get("metrics", {}))
        if not raw_metrics:
            for key in ("train", "test", "oot"):
                if key in data and isinstance(data[key], dict):
                    raw_metrics[key] = data[key]

        for role, m in raw_metrics.items():
            bad_rate: float | None = m.get("bad_rate")
            if bad_rate is None and "bad_count" in m and "row_count" in m:
                rc = m.get("row_count", 0)
                bad_rate = float(m["bad_count"]) / rc if rc > 0 else None
            metrics_by_role[role] = RoleMetrics(
                row_count=m.get("row_count", 0),
                auc=m.get("auc"),
                gini=m.get("gini"),
                ks=m.get("ks"),
                bad_rate=bad_rate,
            )

        psi: dict[str, float] = {}
        raw_psi = data.get("stability", data.get("psi", {}))
        if isinstance(raw_psi, dict):
            psi = {k: float(v) for k, v in raw_psi.items() if isinstance(v, (int, float))}

        return cls(
            metrics_by_role=metrics_by_role,
            psi=psi,
            target=dict(data.get("target", {})),
            gates=list(data.get("gates", [])),
            warnings=list(data.get("warnings", [])),
            _raw=data,
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class CutoffRow:
    score_cutoff: float = 0.0
    approval_rate: float = 0.0
    bad_rate: float = 0.0
    capture_rate: float = 0.0


@dataclass(frozen=True)
class CutoffAnalysis:
    cutoff_tables: dict[str, list[CutoffRow]] = field(default_factory=dict)
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> CutoffAnalysis:
        raw_tables = data.get("cutoff_tables", data.get("tables", {}))
        tables: dict[str, list[CutoffRow]] = {}
        for role, rows in raw_tables.items():
            if isinstance(rows, list):
                tables[role] = [
                    CutoffRow(
                        score_cutoff=r.get("score_cutoff", r.get("score", 0)),
                        approval_rate=r.get("approval_rate", 0.0),
                        bad_rate=r.get("bad_rate", 0.0),
                        capture_rate=r.get("capture_rate", 0.0),
                    )
                    for r in rows
                ]
        return cls(cutoff_tables=tables, _raw=data, source_artifact_id=artifact_id)


@dataclass(frozen=True)
class WoeTable:
    mapping: dict[str, dict[str, float]]
    columns: list[str]
    dataframe: Any = None
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""


@dataclass(frozen=True)
class IvTable:
    dataframe: Any
    columns: list[str]
    _raw: JsonDict = field(default_factory=dict, repr=False)
    source_artifact_id: str = ""


@dataclass(frozen=True)
class ScoredDataset:
    dataframe: Any
    _raw: JsonDict = field(default_factory=dict, repr=False)


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
class ArtifactEvidenceSummary:
    artifact_id: str
    role: str
    artifact_type: str
    media_type: str
    schema_version: str = ""
    kind: str = ""
    source_artifact_id: str = ""


@dataclass(frozen=True)
class SplitSummary:
    strategy: str
    row_counts: dict[str, int]
    target_rates: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SplitSummary:
        return cls(
            strategy=data.get("strategy", ""),
            row_counts={k: int(v) for k, v in dict(data.get("row_counts", {})).items()},
            target_rates={
                str(role): {str(k): int(v) for k, v in dict(counts).items()}
                for role, counts in dict(data.get("target_rates", {})).items()
            },
            warnings=list(data.get("warnings", [])),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ProfileSummary:
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = field(default_factory=list)
    dtypes: dict[str, str] = field(default_factory=dict)
    null_counts: dict[str, int] = field(default_factory=dict)
    numeric_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    profile_steps: list[JsonDict] = field(default_factory=list)
    profiles: list[JsonDict] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    quality_warnings: list[JsonDict] = field(default_factory=list)
    recommended_exclude_columns: list[str] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ProfileSummary:
        profiles = data.get("profiles", [])
        if isinstance(profiles, dict):
            profiles = list(profiles.values())
        columns = data.get("columns", [])
        if isinstance(columns, dict):
            columns = list(columns.keys())
        return cls(
            row_count=int(data.get("row_count", 0)),
            column_count=int(data.get("column_count", 0)),
            columns=[str(c) for c in columns],
            dtypes={str(k): str(v) for k, v in dict(data.get("dtypes", {})).items()},
            null_counts={str(k): int(v) for k, v in dict(data.get("null_counts", {})).items()},
            numeric_stats={str(k): dict(v) for k, v in dict(data.get("numeric_stats", {})).items()},
            profile_steps=list(data.get("profile_steps", [])),
            profiles=list(profiles),
            warnings=list(data.get("warnings", [])),
            quality_warnings=list(data.get("quality_warnings", [])),
            recommended_exclude_columns=[str(c) for c in data.get("recommended_exclude_columns", [])],
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ExclusionSummary:
    rows_before: int
    rows_after: int
    rows_excluded: int
    rules: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ExclusionSummary:
        return cls(
            rows_before=int(data.get("rows_before", 0)),
            rows_after=int(data.get("rows_after", 0)),
            rows_excluded=int(data.get("rows_excluded", 0)),
            rules=list(data.get("rules", [])),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class WoeTransformEvidence:
    target_column: str
    transformed_variables: list[str]
    selected_only: bool = False
    row_count: int = 0
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> WoeTransformEvidence:
        return cls(
            target_column=data.get("target_column", ""),
            transformed_variables=[str(v) for v in data.get("transformed_variables", [])],
            selected_only=bool(data.get("selected_only", False)),
            row_count=int(data.get("row_count", 0)),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ApplyWoeEvidence:
    policy: JsonDict
    roles: dict[str, JsonDict]
    warnings: list[JsonDict] = field(default_factory=list)
    bin_definition_artifact_id: str = ""
    woe_table_artifact_id: str = ""
    selection_artifact_id: str | None = None
    frozen_bundle_artifact_id: str | None = None
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ApplyWoeEvidence:
        return cls(
            policy=dict(data.get("policy", {})),
            roles={str(k): dict(v) for k, v in dict(data.get("roles", {})).items()},
            warnings=list(data.get("warnings", [])),
            bin_definition_artifact_id=data.get("bin_definition_artifact_id", ""),
            woe_table_artifact_id=data.get("woe_table_artifact_id", ""),
            selection_artifact_id=data.get("selection_artifact_id"),
            frozen_bundle_artifact_id=data.get("frozen_bundle_artifact_id"),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ApplyModelEvidence:
    roles: dict[str, JsonDict]
    model_artifact_id: str
    warnings: list[JsonDict] = field(default_factory=list)
    scorecard_artifact_id: str | None = None
    frozen_bundle_artifact_id: str | None = None
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ApplyModelEvidence:
        return cls(
            roles={str(k): dict(v) for k, v in dict(data.get("roles", {})).items()},
            model_artifact_id=data.get("model_artifact_id", ""),
            warnings=list(data.get("warnings", [])),
            scorecard_artifact_id=data.get("scorecard_artifact_id"),
            frozen_bundle_artifact_id=data.get("frozen_bundle_artifact_id"),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ReportBundleEvidence:
    schema_version: str
    project_id: str
    run_id: str
    target_branch_id: str = ""
    report_mode: str = "branch"
    generated_at: str = ""
    generated_by: JsonDict = field(default_factory=dict)
    source: JsonDict = field(default_factory=dict)
    summary: JsonDict = field(default_factory=dict)
    artifacts: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ReportBundleEvidence:
        from cardre._evidence.schemas import SCHEMA_REPORT_BUNDLE
        schema_version = data.get("schema_version", "")
        if schema_version and schema_version != SCHEMA_REPORT_BUNDLE:
            from cardre._evidence.kinds import EvidenceKind, EvidenceParseError
            raise EvidenceParseError(
                f"Unexpected report bundle schema_version {schema_version!r}",
                kind=EvidenceKind.REPORT_BUNDLE,
                artifact_id=artifact_id,
                expected_schema=SCHEMA_REPORT_BUNDLE,
                actual_schema=schema_version,
            )
        return cls(
            schema_version=schema_version or SCHEMA_REPORT_BUNDLE,
            project_id=data.get("project_id", ""),
            run_id=data.get("run_id", ""),
            target_branch_id=data.get("target_branch_id", ""),
            report_mode=data.get("report_mode", "branch"),
            generated_at=data.get("generated_at", ""),
            generated_by=dict(data.get("generated_by", {})),
            source=dict(data.get("source", {})),
            summary=dict(data.get("summary", {})),
            artifacts=list(data.get("artifacts", [])),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class RunManifestEvidence:
    manifest_version: str
    run_id: str
    plan_version_id: str
    status: str
    execution_mode: str
    started_at: str = ""
    finished_at: str = ""
    branch_id: str | None = None
    target_step_id: str | None = None
    in_scope_step_ids: list[str] = field(default_factory=list)
    steps: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> RunManifestEvidence:
        from cardre._evidence.schemas import SCHEMA_RUN_MANIFEST
        manifest_version = data.get("schema_version", data.get("manifest_version", ""))
        if not manifest_version:
            manifest_version = SCHEMA_RUN_MANIFEST
        return cls(
            manifest_version=manifest_version,
            run_id=data.get("run_id", ""),
            plan_version_id=data.get("plan_version_id", ""),
            status=data.get("status", ""),
            execution_mode=data.get("execution_mode", ""),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""),
            branch_id=data.get("branch_id"),
            target_step_id=data.get("target_step_id"),
            in_scope_step_ids=list(data.get("in_scope_step_ids", [])),
            steps=list(data.get("steps", [])),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class TechnicalManifestIndex:
    manifests: list[JsonDict]
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> TechnicalManifestIndex:
        return cls(
            manifests=list(data.get("manifests", [])),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class ComparisonArtifact:
    comparison_type: str
    baseline_branch_id: str
    challenger_branch_id: str
    woe_iv: JsonDict = field(default_factory=dict)
    model: JsonDict = field(default_factory=dict)
    validation: JsonDict = field(default_factory=dict)
    cutoff: JsonDict = field(default_factory=dict)
    warnings: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ComparisonArtifact:
        return cls(
            comparison_type=data.get("comparison_type", ""),
            baseline_branch_id=data.get("baseline_branch_id", ""),
            challenger_branch_id=data.get("challenger_branch_id", ""),
            woe_iv=dict(data.get("woe_iv", {})),
            model=dict(data.get("model", {})),
            validation=dict(data.get("validation", {})),
            cutoff=dict(data.get("cutoff", {})),
            warnings=list(data.get("warnings", [])),
            source_artifact_id=artifact_id,
            schema_version=data.get("schema_version", ""),
        )


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
