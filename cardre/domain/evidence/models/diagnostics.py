"""Diagnostics evidence data models — coefficient sign, separation, VIF, calibration."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class CoefficientSignEntry:
    variable_name: str = ""
    feature_name: str = ""
    coefficient: float = 0.0
    coefficient_is_infinite: bool = False
    coefficient_sign: str = ""
    expected_sign: str = ""
    status: str = ""
    reason: str = ""
    woe_variable_status: str = ""

    @classmethod
    def from_dict(cls, data: JsonDict) -> CoefficientSignEntry:
        return cls(
            variable_name=data.get("variable_name", ""),
            feature_name=data.get("feature_name", ""),
            coefficient=float(data.get("coefficient", 0.0)),
            coefficient_is_infinite=bool(data.get("coefficient_is_infinite", False)),
            coefficient_sign=data.get("coefficient_sign", ""),
            expected_sign=data.get("expected_sign", ""),
            status=data.get("status", ""),
            reason=data.get("reason", ""),
            woe_variable_status=data.get("woe_variable_status", "unknown"),
        )


@dataclass(frozen=True)
class CoefficientSignDiagnostics:
    variables: list[CoefficientSignEntry] = field(default_factory=list)
    target_column: str = ""
    conventions: JsonDict = field(default_factory=dict)
    summary: JsonDict = field(default_factory=dict)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> CoefficientSignDiagnostics:
        variables = [CoefficientSignEntry.from_dict(v) for v in data.get("variables", [])]
        return cls(
            variables=variables,
            target_column=data.get("target_column", ""),
            conventions=dict(data.get("conventions", {})),
            summary=dict(data.get("summary", {})),
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class SeparationEntry:
    feature_name: str = ""
    coefficient: float = 0.0
    coefficient_is_infinite: bool = False
    abs_coefficient: float = 0.0
    status: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, data: JsonDict) -> SeparationEntry:
        return cls(
            feature_name=data.get("feature_name", ""),
            coefficient=float(data.get("coefficient", 0.0)),
            coefficient_is_infinite=bool(data.get("coefficient_is_infinite", False)),
            abs_coefficient=float(data.get("abs_coefficient", 0.0)),
            status=data.get("status", ""),
            reason=data.get("reason", ""),
        )


@dataclass(frozen=True)
class SeparationDiagnostics:
    variables: list[SeparationEntry] = field(default_factory=list)
    target_column: str = ""
    threshold: float = 0.0
    model_converged: bool = False
    model_iterations: int = 0
    summary: JsonDict = field(default_factory=dict)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SeparationDiagnostics:
        variables = [SeparationEntry.from_dict(v) for v in data.get("variables", [])]
        return cls(
            variables=variables,
            target_column=data.get("target_column", ""),
            threshold=float(data.get("threshold", 0.0)),
            model_converged=bool(data.get("model_converged", False)),
            model_iterations=int(data.get("model_iterations", 0)),
            summary=dict(data.get("summary", {})),
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class VifEntry:
    feature_name: str = ""
    vif: float | None = None
    vif_is_infinite: bool = False
    r_squared: float | None = None
    status: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, data: JsonDict) -> VifEntry:
        return cls(
            feature_name=data.get("feature_name", ""),
            vif=data.get("vif"),
            vif_is_infinite=bool(data.get("vif_is_infinite", False)),
            r_squared=data.get("r_squared"),
            status=data.get("status", ""),
            reason=data.get("reason", ""),
        )


@dataclass(frozen=True)
class VifDiagnostics:
    variables: list[VifEntry] = field(default_factory=list)
    target_column: str = ""
    threshold: float = 0.0
    summary: JsonDict = field(default_factory=dict)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> VifDiagnostics:
        variables = [VifEntry.from_dict(v) for v in data.get("variables", [])]
        return cls(
            variables=variables,
            target_column=data.get("target_column", ""),
            threshold=float(data.get("threshold", 0.0)),
            summary=dict(data.get("summary", {})),
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class CalibrationBin:
    bin: int = 0
    count: int = 0
    observed_events: int = 0
    expected_events: float = 0.0
    observed_non_events: int = 0
    expected_non_events: float = 0.0
    observed_event_rate: float = 0.0
    predicted_event_rate: float = 0.0
    abs_deviation: float = 0.0

    @classmethod
    def from_dict(cls, data: JsonDict) -> CalibrationBin:
        return cls(
            bin=int(data.get("bin", 0)),
            count=int(data.get("count", 0)),
            observed_events=int(data.get("observed_events", 0)),
            expected_events=float(data.get("expected_events", 0.0)),
            observed_non_events=int(data.get("observed_non_events", 0)),
            expected_non_events=float(data.get("expected_non_events", 0.0)),
            observed_event_rate=float(data.get("observed_event_rate", 0.0)),
            predicted_event_rate=float(data.get("predicted_event_rate", 0.0)),
            abs_deviation=float(data.get("abs_deviation", 0.0)),
        )


@dataclass(frozen=True)
class CalibrationRole:
    role: str = ""
    row_count: int = 0
    known_count: int = 0
    n_bins: int = 0
    hosmer_lemeshow_statistic: float | None = None
    hosmer_lemeshow_statistic_is_infinite: bool = False
    hosmer_lemeshow_degrees_of_freedom: int = 0
    hosmer_lemeshow_p_value: float | None = None
    calibration_error: float = 0.0
    auc: float | None = None
    decile_bins: list[CalibrationBin] = field(default_factory=list)
    status: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, role: str, data: JsonDict) -> CalibrationRole:
        return cls(
            role=role,
            row_count=int(data.get("row_count", 0)),
            known_count=int(data.get("known_count", 0)),
            n_bins=int(data.get("n_bins", 0)),
            hosmer_lemeshow_statistic=data.get("hosmer_lemeshow_statistic"),
            hosmer_lemeshow_statistic_is_infinite=bool(data.get("hosmer_lemeshow_statistic_is_infinite", False)),
            hosmer_lemeshow_degrees_of_freedom=int(data.get("hosmer_lemeshow_degrees_of_freedom", 0)),
            hosmer_lemeshow_p_value=data.get("hosmer_lemeshow_p_value"),
            calibration_error=float(data.get("calibration_error", 0.0)),
            auc=data.get("auc"),
            decile_bins=[CalibrationBin.from_dict(b) for b in data.get("decile_bins", [])],
            status=data.get("status", ""),
            reason=data.get("reason", ""),
        )


@dataclass(frozen=True)
class CalibrationDiagnostics:
    roles: list[CalibrationRole] = field(default_factory=list)
    target_column: str = ""
    model_family: str = ""
    conventions: JsonDict = field(default_factory=dict)
    summary: JsonDict = field(default_factory=dict)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> CalibrationDiagnostics:
        roles_data = data.get("roles", {})
        roles: list[CalibrationRole] = []
        if isinstance(roles_data, dict):
            for role_name, role_data in roles_data.items():
                if isinstance(role_data, dict):
                    roles.append(CalibrationRole.from_dict(role_name, role_data))
        elif isinstance(roles_data, list):
            for role_data in roles_data:
                if isinstance(role_data, dict):
                    role_name = role_data.get("role", "")
                    roles.append(CalibrationRole.from_dict(role_name, role_data))
        return cls(
            roles=roles,
            target_column=data.get("target_column", ""),
            model_family=data.get("model_family", ""),
            conventions=dict(data.get("conventions", {})),
            summary=dict(data.get("summary", {})),
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )
