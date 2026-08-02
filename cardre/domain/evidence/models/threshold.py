"""Threshold optimization evidence model."""

from __future__ import annotations

from dataclasses import dataclass

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class ThresholdOptimization:
    """Selected probability threshold per role, with the objective that drove it."""

    roles: dict[str, JsonDict]
    selected_threshold: float
    objective: str
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ThresholdOptimization:
        from cardre.domain.evidence.kinds import EvidenceKind, EvidenceParseError
        from cardre.domain.evidence.schemas import SCHEMA_THRESHOLD_OPTIMIZATION

        schema_version = data.get("schema_version", "")
        if schema_version and schema_version != SCHEMA_THRESHOLD_OPTIMIZATION:
            raise EvidenceParseError(
                f"Unexpected threshold optimization schema_version {schema_version!r}",
                kind=EvidenceKind.THRESHOLD_OPTIMIZATION,
                artifact_id=artifact_id,
                expected_schema=SCHEMA_THRESHOLD_OPTIMIZATION,
                actual_schema=schema_version,
            )

        roles = data.get("roles", {})
        if not isinstance(roles, dict) or not roles:
            raise EvidenceParseError(
                "ThresholdOptimization requires a non-empty 'roles' dict",
                kind=EvidenceKind.THRESHOLD_OPTIMIZATION,
                artifact_id=artifact_id,
            )
        selected_threshold = data.get("selected_threshold")
        if not isinstance(selected_threshold, (int, float)):
            raise EvidenceParseError(
                "ThresholdOptimization requires a numeric 'selected_threshold'",
                kind=EvidenceKind.THRESHOLD_OPTIMIZATION,
                artifact_id=artifact_id,
            )
        objective = data.get("objective", "")
        if not objective:
            raise EvidenceParseError(
                "ThresholdOptimization requires a non-empty 'objective'",
                kind=EvidenceKind.THRESHOLD_OPTIMIZATION,
                artifact_id=artifact_id,
            )

        return cls(
            roles=dict(roles),
            selected_threshold=float(selected_threshold),
            objective=str(objective),
            source_artifact_id=artifact_id,
            schema_version=schema_version or SCHEMA_THRESHOLD_OPTIMIZATION,
        )
