"""Manifest and comparison data models."""

from __future__ import annotations

from dataclasses import dataclass, field

from cardre.domain.diagnostics import JsonDict


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
