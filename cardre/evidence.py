"""Typed Artifact Evidence Module.

Provides typed access to Artifact contents so callers (Node types, reporting,
comparison, Plan service) ask for evidence by meaning rather than by inspecting
file bytes, JSON keys, and column names.

Typical usage::

    reader = ArtifactEvidenceReader(store)

    # From a mixed list of artifacts (e.g. Node's input_artifacts):
    bin_def = reader.find(input_artifacts, EvidenceKind.BIN_DEFINITION)
    model  = reader.find_optional(input_artifacts, EvidenceKind.MODEL_ARTIFACT)

    # From a known artifact (e.g. resolved from a Run):
    woe = reader.read_optional(artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import polars as pl

from cardre.audit import ArtifactRef, JsonDict
from cardre.store import ProjectStore


# ---------------------------------------------------------------------------
# Schema version constants
# ---------------------------------------------------------------------------

SCHEMA_MODELLING_METADATA = "cardre.modelling_metadata.v1"
SCHEMA_BIN_DEFINITION = "cardre.bin_definition.v1"
SCHEMA_SELECTION_DEFINITION = "cardre.selection_definition.v1"
SCHEMA_WOE_TABLE = "cardre.woe_table.v1"
SCHEMA_WOE_IV_EVIDENCE = "cardre.woe_iv_evidence.v1"
SCHEMA_MODEL_ARTIFACT = "cardre.model_artifact.v1"
SCHEMA_SCORE_SCALING = "cardre.score_scaling.v1"
SCHEMA_VALIDATION_METRICS = "cardre.validation_metrics.v1"
SCHEMA_CUTOFF_ANALYSIS = "cardre.cutoff_analysis.v1"
SCHEMA_MANUAL_BINNING_OVERRIDES = "cardre.manual_binning_overrides.v1"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EvidenceError(Exception):
    """Base for evidence-module errors."""


class EvidenceNotFoundError(EvidenceError):
    """No artifact matched the requested evidence kind."""

    def __init__(self, kind: EvidenceKind) -> None:
        self.kind = kind
        super().__init__(f"No artifact found for evidence kind: {kind.value}")


class AmbiguousEvidenceError(EvidenceError):
    """Multiple artifacts matched the requested evidence kind."""

    def __init__(self, kind: EvidenceKind, candidates: list[ArtifactRef]) -> None:
        self.kind = kind
        self.candidates = candidates
        super().__init__(
            f"Multiple artifacts ({len(candidates)}) matched evidence kind "
            f"{kind.value}"
        )


class EvidenceParseError(EvidenceError):
    """Artifact contents could not be parsed as the expected evidence kind."""


# ---------------------------------------------------------------------------
# EvidenceKind
# ---------------------------------------------------------------------------


class EvidenceKind(Enum):
    MODELLING_METADATA = "modelling_metadata"
    BIN_DEFINITION = "bin_definition"
    SELECTION_DEFINITION = "selection_definition"
    WOE_TABLE = "woe_table"
    WOE_IV_EVIDENCE = "woe_iv_evidence"
    MODEL_ARTIFACT = "model_artifact"
    SCORE_SCALING = "score_scaling"
    VALIDATION_METRICS = "validation_metrics"
    CUTOFF_ANALYSIS = "cutoff_analysis"
    SCORED_DATASET = "scored_dataset"
    MANUAL_BINNING_OVERRIDES = "manual_binning_overrides"
    IV_TABLE = "iv_table"


# ---------------------------------------------------------------------------
# Typed evidence records
# ---------------------------------------------------------------------------


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

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> BinDefinition:
        variables = [
            BinVariable(
                variable=v.get("variable", ""),
                dtype=v.get("dtype", ""),
                kind=v.get("kind", ""),
                bins=list(v.get("bins", [])),
            )
            for v in data.get("variables", [])
        ]
        return cls(variables=variables, source_artifact_id=artifact_id)

    def to_dict(self) -> JsonDict:
        return {"variables": [v.to_dict() for v in self.variables]}


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


@dataclass(frozen=True)
class ModellingMetadata:
    target_column: str
    good_values: list[Any] = field(default_factory=list)
    bad_values: list[Any] = field(default_factory=list)
    indeterminate_values: list[Any] = field(default_factory=list)
    extra: JsonDict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: JsonDict) -> ModellingMetadata:
        return cls(
            target_column=data.get("target_column", ""),
            good_values=list(data.get("good_values", [])),
            bad_values=list(data.get("bad_values", [])),
            indeterminate_values=list(data.get("indeterminate_values", [])),
            extra={k: v for k, v in data.items()
                   if k not in ("target_column", "good_values", "bad_values",
                                "indeterminate_values")},
        )


@dataclass(frozen=True)
class WoeTable:
    mapping: dict[str, dict[str, float]]
    columns: list[str]
    dataframe: pl.LazyFrame | None = None
    source_artifact_id: str = ""


@dataclass(frozen=True)
class IvTable:
    dataframe: pl.LazyFrame
    columns: list[str]
    source_artifact_id: str = ""


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
            affected = [
                AffectedBin(bin_id=ab.get("bin_id", ""), detail=ab)
                for ab in v.get("affected_bins", [])
            ]
            variables.append(WoeIvVariable(
                variable_name=v.get("variable_name", ""),
                iv=v.get("iv", 0.0),
                status=v.get("status", "included"),
                bins=bins,
                affected_bins=affected,
                smoothing_applied=v.get("smoothing_applied", False),
                zero_cell_encountered=v.get("zero_cell_encountered", False),
                warnings=list(v.get("warnings", [])),
            ))

        return cls(
            variables=variables,
            smoothing=smoothing,
            schema_version=data.get("schema_version", ""),
        )


@dataclass(frozen=True)
class Coefficient:
    variable_name: str
    coefficient: float = 0.0
    standard_error: float | None = None
    p_value: float | None = None


@dataclass(frozen=True)
class ModelArtifact:
    model_family: str = "logistic_regression"
    coefficients: list[Coefficient] = field(default_factory=list)
    coefficients_dict: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    features: list[str] = field(default_factory=list)
    target_column: str = ""
    schema_version: str = ""
    training: JsonDict = field(default_factory=dict)
    warnings: list[JsonDict] = field(default_factory=list)
    model_payload: JsonDict = field(default_factory=dict)
    interpretability: JsonDict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: JsonDict) -> ModelArtifact:
        coefficients: list[Coefficient] = []
        coeffs_dict: dict[str, float] = {}
        raw_coeffs = data.get("coefficients", [])

        if isinstance(raw_coeffs, dict):
            coeffs_dict = raw_coeffs
            coefficients = [
                Coefficient(variable_name=k, coefficient=v)
                for k, v in raw_coeffs.items()
                if isinstance(v, (int, float))
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
                        coeffs_dict[var_name] = c["coefficient"]

        features = data.get("features", [])
        if not features and coefficients:
            features = [c.variable_name for c in coefficients]

        return cls(
            model_family=data.get("model_family", "logistic_regression"),
            coefficients=coefficients,
            coefficients_dict=coeffs_dict,
            intercept=data.get("intercept", 0.0),
            features=features,
            target_column=data.get("target_column", ""),
            schema_version=data.get("schema_version", ""),
            training=data.get("training", {}),
            warnings=list(data.get("warnings", [])),
            model_payload=data.get("model_payload", {}),
            interpretability=data.get("interpretability", {}),
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

    @classmethod
    def from_json(cls, data: JsonDict) -> ScoreScaling:
        raw_odds = data.get("base_odds", "50:1")
        base_odds = str(raw_odds) if not isinstance(raw_odds, str) else raw_odds
        return cls(
            base_score=data.get("base_score", 600),
            base_odds=base_odds,
            pdo=data.get("pdo", data.get("points_to_double_odds", 20)),
            factor=data.get("factor", 0.0),
            offset=data.get("offset", 0.0),
            score_direction=data.get("score_direction", "higher_is_better"),
            rounding=data.get("rounding", "nearest_integer"),
            min_score=data.get("min_score", 0),
            max_score=data.get("max_score", 0),
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

    @classmethod
    def from_json(cls, data: JsonDict) -> ValidationMetrics:
        metrics_by_role: dict[str, RoleMetrics] = {}
        raw_metrics = data.get("metrics", {})
        for role, m in raw_metrics.items():
            if isinstance(m, dict):
                metrics_by_role[role] = RoleMetrics(
                    row_count=m.get("row_count", 0),
                    auc=m.get("auc"),
                    gini=m.get("gini"),
                    ks=m.get("ks"),
                    bad_rate=m.get("bad_rate"),
                )

        psi: dict[str, float] = {}
        raw_psi = data.get("psi", {})
        if isinstance(raw_psi, dict):
            for k, v in raw_psi.items():
                if isinstance(v, (int, float)):
                    psi[k] = float(v)

        return cls(metrics_by_role=metrics_by_role, psi=psi)


@dataclass(frozen=True)
class CutoffRow:
    score_cutoff: float = 0.0
    approval_rate: float = 0.0
    bad_rate: float = 0.0
    capture_rate: float = 0.0


@dataclass(frozen=True)
class CutoffAnalysis:
    cutoff_tables: dict[str, list[CutoffRow]] = field(default_factory=dict)

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
        return cls(cutoff_tables=tables)


# ---------------------------------------------------------------------------
# Matching profiles
# ---------------------------------------------------------------------------


@dataclass
class _Profile:
    expected_roles: set[str]
    expected_artifact_types: set[str]
    schema_version: str
    expected_media_types: set[str] = field(default_factory=lambda: {"application/json"})
    required_keys: set[str] | None = None
    exclude_key: str | None = None
    required_columns: set[str] | None = None


_EVIDENCE_PROFILES: dict[EvidenceKind, _Profile] = {
    EvidenceKind.MODELLING_METADATA: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_MODELLING_METADATA,
        required_keys={"target_column", "good_values", "bad_values"},
    ),
    EvidenceKind.BIN_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_BIN_DEFINITION,
        required_keys={"variables"},
        exclude_key="selected",
    ),
    EvidenceKind.SELECTION_DEFINITION: _Profile(
        expected_roles={"definition"},
        expected_artifact_types={"definition"},
        schema_version=SCHEMA_SELECTION_DEFINITION,
        required_keys={"selected"},
    ),
    EvidenceKind.WOE_TABLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "dataset"},
        schema_version=SCHEMA_WOE_TABLE,
        expected_media_types={"application/vnd.apache.parquet"},
        required_columns={"variable", "bin_id", "woe"},
    ),
    EvidenceKind.IV_TABLE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report", "dataset"},
        schema_version="",
        expected_media_types={"application/vnd.apache.parquet"},
        required_columns={"iv", "variable"},
    ),
    EvidenceKind.WOE_IV_EVIDENCE: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_WOE_IV_EVIDENCE,
        required_keys={"variables"},
    ),
    EvidenceKind.SCORED_DATASET: _Profile(
        expected_roles={"train", "test", "oot"},
        expected_artifact_types={"dataset"},
        schema_version="",
        expected_media_types={"application/vnd.apache.parquet"},
    ),
    EvidenceKind.MODEL_ARTIFACT: _Profile(
        expected_roles={"model", "report", "definition"},
        expected_artifact_types={"model", "definition", "report"},
        schema_version=SCHEMA_MODEL_ARTIFACT,
        required_keys={"model_family"},
    ),
    EvidenceKind.SCORE_SCALING: _Profile(
        expected_roles={"scorecard", "report"},
        expected_artifact_types={"scorecard", "report"},
        schema_version=SCHEMA_SCORE_SCALING,
        required_keys={"factor", "offset"},
    ),
    EvidenceKind.VALIDATION_METRICS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_VALIDATION_METRICS,
        required_keys={"metrics"},
    ),
    EvidenceKind.CUTOFF_ANALYSIS: _Profile(
        expected_roles={"report"},
        expected_artifact_types={"report"},
        schema_version=SCHEMA_CUTOFF_ANALYSIS,
        required_keys={"cutoff_tables"},
    ),
    EvidenceKind.MANUAL_BINNING_OVERRIDES: _Profile(
        expected_roles={"definition", "report"},
        expected_artifact_types={"definition", "report"},
        schema_version=SCHEMA_MANUAL_BINNING_OVERRIDES,
    ),
}


# ---------------------------------------------------------------------------
# ArtifactEvidenceReader
# ---------------------------------------------------------------------------


class ArtifactEvidenceReader:
    """Reads typed evidence from immutable Artifacts through a ProjectStore.

    Two usage patterns::

        # 1) Find evidence within a mixed list (Node input_artifacts):
        reader.find(artifacts, EvidenceKind.BIN_DEFINITION)

        # 2) Read a known artifact by ID (reporting/comparison):
        reader.read(artifact_id, EvidenceKind.WOE_IV_EVIDENCE)
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public: find
    # ------------------------------------------------------------------

    def find(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any:
        """Return typed evidence from the single matching Artifact.

        Raises ``EvidenceNotFoundError`` or ``AmbiguousEvidenceError``.
        """
        candidates = self._match(artifacts, kind)
        if not candidates:
            raise EvidenceNotFoundError(kind)
        if len(candidates) > 1:
            raise AmbiguousEvidenceError(kind, candidates)
        return self._parse(candidates[0], kind)

    def find_optional(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any | None:
        """Like ``find`` but returns ``None`` when no match exists."""
        try:
            return self.find(artifacts, kind)
        except EvidenceNotFoundError:
            return None

    # ------------------------------------------------------------------
    # Public: read by artifact ID
    # ------------------------------------------------------------------

    def read(self, artifact_id: str, kind: EvidenceKind) -> Any:
        """Return typed evidence from a known Artifact ID.

        Raises ``EvidenceNotFoundError`` if the ID doesn't exist or the
        artifact's media/role doesn't match the expected profile.
        """
        artifact = self._store.get_artifact(artifact_id)
        if artifact is None:
            raise EvidenceNotFoundError(kind)
        matched = self._match([artifact], kind)
        if not matched:
            raise EvidenceNotFoundError(kind)
        return self._parse(matched[0], kind)

    def read_optional(self, artifact_id: str, kind: EvidenceKind) -> Any | None:
        """Like ``read`` but returns ``None`` when no match exists."""
        try:
            return self.read(artifact_id, kind)
        except EvidenceNotFoundError:
            return None

    # ------------------------------------------------------------------
    # Reference resolution helpers
    # ------------------------------------------------------------------

    def read_step_output_optional(
        self,
        run_step: Any,
        kind: EvidenceKind,
    ) -> Any | None:
        """Scan a RunStepRecord's output artifact IDs for the given kind."""
        for aid in run_step.output_artifact_ids:
            result = self.read_optional(aid, kind)
            if result is not None:
                return result
        return None

    # ------------------------------------------------------------------
    # Internal: matching
    # ------------------------------------------------------------------

    def _match(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> list[ArtifactRef]:
        profile = _EVIDENCE_PROFILES[kind]

        # Phase 1: schema_version exact match
        if profile.schema_version:
            candidates = [
                a for a in artifacts
                if a.metadata.get("schema_version") == profile.schema_version
            ]
            if candidates:
                return candidates

        # Phase 2: role + artifact_type + media_type fallback (only when
        # unambiguous — multiple evidence kinds share the same role/type/media).
        candidates = [
            a for a in artifacts
            if a.role in profile.expected_roles
            and a.artifact_type in profile.expected_artifact_types
            and a.media_type in profile.expected_media_types
        ]
        if len(candidates) == 1:
            if self._candidate_passes_payload_check(candidates[0], profile):
                return candidates
            candidates = []

        # Phase 3: legacy payload heuristics for ambiguous cases
        legacy = self._legacy_match(artifacts, kind)
        if legacy:
            return legacy

        # Last resort: return Phase 2 candidates even if ambiguous
        # (caller's `find()` will raise AmbiguousEvidenceError).
        return candidates

    def _candidate_passes_payload_check(
        self, artifact: ArtifactRef, profile: _Profile,
    ) -> bool:
        """Check whether *artifact* satisfies *profile*'s constraints."""
        if profile.required_columns is not None:
            if artifact.media_type != "application/json":
                return self._parquet_has_columns(artifact, profile.required_columns)
            try:
                payload = json.loads(self._store.artifact_path(artifact).read_text())
                if profile.required_keys is not None:
                    return profile.required_keys.issubset(payload.keys())
                return True
            except Exception:
                return False
        if profile.required_keys is None and profile.exclude_key is None:
            return True
        try:
            payload = json.loads(self._store.artifact_path(artifact).read_text())
        except Exception:
            return False
        if profile.required_keys is not None and not profile.required_keys.issubset(payload.keys()):
            return False
        if profile.exclude_key is not None and profile.exclude_key in payload:
            return False
        return True

    def _legacy_match(
        self, artifacts: list[ArtifactRef], kind: EvidenceKind,
    ) -> list[ArtifactRef]:
        """Payload-based fallback for pre-schema_version artifacts."""
        if kind == EvidenceKind.MODELLING_METADATA:
            return self._match_by_payload_key(artifacts, {"target_column", "good_values", "bad_values"})
        if kind in (EvidenceKind.BIN_DEFINITION, EvidenceKind.SELECTION_DEFINITION):
            defs = [a for a in artifacts if a.role == "definition" and a.media_type == "application/json"]
            if kind == EvidenceKind.BIN_DEFINITION:
                return self._match_by_payload_key(defs, {"variables"}, exclude_key="selected")
            return self._match_by_payload_key(defs, {"selected"})
        if kind == EvidenceKind.WOE_TABLE:
            parquet_reports = [
                a for a in artifacts
                if a.role == "report"
                and a.media_type == "application/vnd.apache.parquet"
                and self._parquet_has_columns(a, {"variable", "bin_id", "woe"})
            ]
            return parquet_reports
        if kind == EvidenceKind.IV_TABLE:
            return [
                a for a in artifacts
                if a.role == "report"
                and a.media_type == "application/vnd.apache.parquet"
                and self._parquet_has_columns(a, {"iv", "variable"})
            ]
        return []

    def _match_by_payload_key(
        self,
        artifacts: list[ArtifactRef],
        required_keys: set[str],
        exclude_key: str | None = None,
    ) -> list[ArtifactRef]:
        result: list[ArtifactRef] = []
        for a in artifacts:
            try:
                payload = json.loads(self._store.artifact_path(a).read_text())
            except Exception:
                continue
            if required_keys.issubset(payload.keys()):
                if exclude_key is None or exclude_key not in payload:
                    result.append(a)
        return result

    def _parquet_has_columns(
        self, artifact: ArtifactRef, columns: set[str],
    ) -> bool:
        """Check whether the parquet artifact contains all required columns."""
        try:
            cols = pl.scan_parquet(self._store.artifact_path(artifact)).collect_schema().names()
            return columns.issubset(cols)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal: parsing
    # ------------------------------------------------------------------

    def _parse(self, artifact: ArtifactRef, kind: EvidenceKind) -> Any:
        path = self._store.artifact_path(artifact)
        if not path.exists():
            raise EvidenceParseError(f"Artifact file not found: {path}")

        if kind == EvidenceKind.WOE_TABLE:
            return self._parse_woe_table(path, artifact)

        if kind == EvidenceKind.SCORED_DATASET:
            return pl.scan_parquet(path)

        if kind == EvidenceKind.IV_TABLE:
            lf = pl.scan_parquet(path)
            return IvTable(dataframe=lf, columns=lf.collect_schema().names(), source_artifact_id=artifact.artifact_id)

        # JSON-based evidence
        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvidenceParseError(f"Cannot parse {path}: {exc}") from exc

        parsers = {
            EvidenceKind.MODELLING_METADATA: ModellingMetadata.from_json,
            EvidenceKind.BIN_DEFINITION: lambda d: BinDefinition.from_json(d, artifact.artifact_id),
            EvidenceKind.SELECTION_DEFINITION: SelectionDefinition.from_json,
            EvidenceKind.WOE_IV_EVIDENCE: WoeIvEvidence.from_json,
            EvidenceKind.MODEL_ARTIFACT: ModelArtifact.from_json,
            EvidenceKind.SCORE_SCALING: ScoreScaling.from_json,
            EvidenceKind.VALIDATION_METRICS: ValidationMetrics.from_json,
            EvidenceKind.CUTOFF_ANALYSIS: CutoffAnalysis.from_json,
            EvidenceKind.MANUAL_BINNING_OVERRIDES: lambda d: d,
        }

        parser = parsers.get(kind)
        if parser is None:
            raise EvidenceParseError(f"No parser registered for {kind.value}")
        return parser(data)

    def _parse_woe_table(self, path: Path, artifact: ArtifactRef) -> WoeTable:
        """Read a Parquet WOE table and build the variable→bin_id→woe mapping."""
        try:
            lf = pl.scan_parquet(path)
            cols = lf.collect_schema().names()
            df = lf.select(["variable", "bin_id", "woe"]).collect()
        except Exception as exc:
            raise EvidenceParseError(f"Cannot read WOE table at {path}: {exc}") from exc

        mapping: dict[str, dict[str, float]] = {}
        for row in df.iter_rows():
            var = str(row[0])
            bid = str(row[1])
            wv = row[2]
            if wv is not None:
                mapping.setdefault(var, {})[bid] = float(wv)

        return WoeTable(mapping=mapping, columns=cols, dataframe=lf, source_artifact_id=artifact.artifact_id)


__all__ = [
    "AffectedBin",
    "AmbiguousEvidenceError",
    "ArtifactEvidenceReader",
    "BinDefinition",
    "BinVariable",
    "Coefficient",
    "CutoffAnalysis",
    "CutoffRow",
    "EvidenceError",
    "EvidenceKind",
    "EvidenceNotFoundError",
    "EvidenceParseError",
    "ModellingMetadata",
    "ModelArtifact",
    "RoleMetrics",
    "ScoreScaling",
    "SCHEMA_BIN_DEFINITION",
    "SCHEMA_CUTOFF_ANALYSIS",
    "SCHEMA_MANUAL_BINNING_OVERRIDES",
    "SCHEMA_MODELLING_METADATA",
    "SCHEMA_MODEL_ARTIFACT",
    "SCHEMA_SCORE_SCALING",
    "SCHEMA_SELECTION_DEFINITION",
    "SCHEMA_VALIDATION_METRICS",
    "SCHEMA_WOE_IV_EVIDENCE",
    "SCHEMA_WOE_TABLE",
    "SelectedVariable",
    "SelectionDefinition",
    "ValidationMetrics",
    "WoeBin",
    "WoeIvEvidence",
    "WoeIvVariable",
    "WoeSmoothing",
    "WoeTable",
]
