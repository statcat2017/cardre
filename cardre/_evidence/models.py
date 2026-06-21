"""Typed evidence data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.audit import JsonDict


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

    @classmethod
    def from_json(cls, data: JsonDict) -> SelectionDefinition:
        selected = [
            SelectedVariable(
                variable=s.get("variable", ""),
                reason=s.get("reason", ""),
                extra={k: v for k, v in s.items() if k not in ("variable", "reason")},
            )
            for s in data.get("selected", [])
        ]
        return cls(selected=selected, method=data.get("method", ""))

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

    @classmethod
    def from_json(cls, data: JsonDict) -> ModellingMetadata:
        return cls(
            target_column=data.get("target_column", ""),
            good_values=list(data.get("good_values", [])),
            bad_values=list(data.get("bad_values", [])),
            indeterminate_values=list(data.get("indeterminate_values", [])),
            extra={k: v for k, v in data.items()
                   if k not in ("target_column", "good_values", "bad_values", "indeterminate_values")},
            _raw=data,
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

    @classmethod
    def from_json(cls, data: JsonDict) -> SampleDefinition:
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

    @classmethod
    def from_json(cls, data: JsonDict) -> WoeIvEvidence:
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

    @classmethod
    def from_json(cls, data: JsonDict) -> ModelArtifact:
        coefficients: list[Coefficient] = []
        coefficients_dict: dict[str, float] = {}
        raw_coeffs = data.get("coefficients", [])

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

        return cls(
            model_family=data.get("model_family", ""),
            features=features,
            target_column=data.get("target_column", ""),
            intercept=float(data.get("intercept", 0)),
            coefficients=coefficients,
            coefficients_dict=coefficients_dict,
            training=data.get("training", {}),
            warnings=list(data.get("warnings", [])),
            _raw=data,
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

    @classmethod
    def from_json(cls, data: JsonDict) -> ScoreScaling:
        raw_odds = data.get("base_odds", "50:1")
        base_odds = str(raw_odds) if not isinstance(raw_odds, str) else raw_odds
        return cls(
            base_score=data.get("base_score", 600),
            base_odds=base_odds,
            pdo=data.get("pdo", data.get("points_to_double_odds", 20)),
            factor=float(data.get("factor", 0)),
            offset=float(data.get("offset", 0)),
            score_direction=data.get("score_direction", "higher_is_better"),
            rounding=data.get("rounding", "nearest_integer"),
            min_score=data.get("min_score", 0),
            max_score=data.get("max_score", 0),
            _raw=data,
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
    _raw: JsonDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: JsonDict) -> ValidationMetrics:
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

        return cls(metrics_by_role=metrics_by_role, psi=psi, _raw=data)


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

    @classmethod
    def from_json(cls, data: JsonDict) -> CutoffAnalysis:
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
        return cls(cutoff_tables=tables, _raw=data)


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

    @classmethod
    def from_json(cls, data: JsonDict) -> VariableClusteringEvidence:
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
        )
