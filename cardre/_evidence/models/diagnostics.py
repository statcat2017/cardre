"""Diagnostics evidence data models — coefficient sign, separation, VIF, calibration."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class CoefficientSignEntry:
    variable: str
    feature_name: str
    coefficient: float = 0.0
    sign: str = ""
    expected_sign: str = ""
    sign_match: bool = False

    @classmethod
    def from_dict(cls, data: JsonDict) -> CoefficientSignEntry:
        return cls(
            variable=data.get("variable", ""),
            feature_name=data.get("feature_name", ""),
            coefficient=float(data.get("coefficient", 0.0)),
            sign=data.get("sign", ""),
            expected_sign=data.get("expected_sign", ""),
            sign_match=bool(data.get("sign_match", False)),
        )


@dataclass(frozen=True)
class CoefficientSignDiagnostics:
    variables: list[CoefficientSignEntry] = field(default_factory=list)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> CoefficientSignDiagnostics:
        variables = [CoefficientSignEntry.from_dict(v) for v in data.get("variables", [])]
        return cls(
            variables=variables,
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class SeparationEntry:
    variable: str
    feature_name: str
    separation: bool = False
    separation_type: str = ""

    @classmethod
    def from_dict(cls, data: JsonDict) -> SeparationEntry:
        return cls(
            variable=data.get("variable", ""),
            feature_name=data.get("feature_name", ""),
            separation=bool(data.get("separation", False)),
            separation_type=data.get("separation_type", ""),
        )


@dataclass(frozen=True)
class SeparationDiagnostics:
    variables: list[SeparationEntry] = field(default_factory=list)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> SeparationDiagnostics:
        variables = [SeparationEntry.from_dict(v) for v in data.get("variables", [])]
        return cls(
            variables=variables,
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class VifEntry:
    variable: str
    vif: float = 0.0
    tolerance: float = 0.0

    @classmethod
    def from_dict(cls, data: JsonDict) -> VifEntry:
        return cls(
            variable=data.get("variable", ""),
            vif=float(data.get("vif", 0.0)),
            tolerance=float(data.get("tolerance", 0.0)),
        )


@dataclass(frozen=True)
class VifDiagnostics:
    variables: list[VifEntry] = field(default_factory=list)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> VifDiagnostics:
        variables = [VifEntry.from_dict(v) for v in data.get("variables", [])]
        return cls(
            variables=variables,
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class CalibrationRole:
    role: str
    observed_mean: float = 0.0
    predicted_mean: float = 0.0
    calibration_error: float = 0.0
    bin_count: int = 0

    @classmethod
    def from_dict(cls, data: JsonDict) -> CalibrationRole:
        return cls(
            role=data.get("role", ""),
            observed_mean=float(data.get("observed_mean", 0.0)),
            predicted_mean=float(data.get("predicted_mean", 0.0)),
            calibration_error=float(data.get("calibration_error", 0.0)),
            bin_count=int(data.get("bin_count", 0)),
        )


@dataclass(frozen=True)
class CalibrationDiagnostics:
    roles: list[CalibrationRole] = field(default_factory=list)
    schema_version: str = ""
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> CalibrationDiagnostics:
        roles = [CalibrationRole.from_dict(r) for r in data.get("roles", [])]
        return cls(
            roles=roles,
            schema_version=data.get("schema_version", ""),
            source_artifact_id=artifact_id,
        )
