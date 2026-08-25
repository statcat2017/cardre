"""Manifest and technical-index data models."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class ReportBundleEvidence:
    schema_version: str
    project_id: str
    run_id: str
    generated_at: str = ""
    generated_by: JsonDict = field(default_factory=dict)
    source: JsonDict = field(default_factory=dict)
    summary: JsonDict = field(default_factory=dict)
    artifacts: list[JsonDict] = field(default_factory=list)
    source_artifact_id: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> ReportBundleEvidence:
        from cardre.domain.evidence.schemas import SCHEMA_REPORT_BUNDLE
        schema_version = data.get("schema_version", "")
        if schema_version and schema_version != SCHEMA_REPORT_BUNDLE:
            from cardre.domain.evidence.kinds import EvidenceKind, EvidenceParseError
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
            generated_at=data.get("generated_at", ""),
            generated_by=dict(data.get("generated_by", {})),
            source=dict(data.get("source", {})),
            summary=dict(data.get("summary", {})),
            artifacts=list(data.get("artifacts", [])),
            source_artifact_id=artifact_id,
        )


@dataclass(frozen=True)
class TechnicalManifestIndex:
    manifests: list[JsonDict]
    source_artifact_id: str = ""
    schema_version: str = ""

    @classmethod
    def from_json(cls, data: JsonDict, artifact_id: str = "") -> TechnicalManifestIndex:
        from cardre.domain.evidence.kinds import EvidenceKind, EvidenceParseError
        from cardre.domain.evidence.schemas import SCHEMA_TECHNICAL_MANIFEST_INDEX
        schema_version = data.get("schema_version", "")
        if schema_version and schema_version != SCHEMA_TECHNICAL_MANIFEST_INDEX:
            raise EvidenceParseError(
                f"Unexpected technical manifest schema_version {schema_version!r}",
                kind=EvidenceKind.TECHNICAL_MANIFEST_INDEX,
                artifact_id=artifact_id,
                expected_schema=SCHEMA_TECHNICAL_MANIFEST_INDEX,
                actual_schema=schema_version,
            )
        return cls(
            manifests=list(data.get("manifests", [])),
            source_artifact_id=artifact_id,
            schema_version=schema_version or SCHEMA_TECHNICAL_MANIFEST_INDEX,
        )
