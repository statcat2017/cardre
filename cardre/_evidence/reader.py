"""ArtifactEvidenceReader — typed evidence access from immutable artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import JsonDict
from cardre._evidence.kinds import (
    EvidenceKind,
    EvidenceNotFoundError,
    AmbiguousEvidenceError,
    EvidenceParseError,
)
from cardre._evidence.models import (
    ApplyModelEvidence,
    ApplyWoeEvidence,
    ArtifactEvidenceSummary,
    BinDefinition,
    CutoffAnalysis,
    ComparisonArtifact,
    ExclusionSummary,
    ExplainabilityReport,
    FairnessReport,
    FeatureSelectionEvidence,
    HyperparameterTuningEvidence,
    IvTable,
    ModellingMetadata,
    ModelArtifact,
    RejectInferenceResult,
    RejectPopulationConfig,
    ProfileSummary,
    SampleDefinition,
    ScoreScaling,
    ScoredDataset,
    ReportBundleEvidence,
    ResamplingEvidence,
    RunManifestEvidence,
    SelectionDefinition,
    SplitSummary,
    TechnicalManifestIndex,
    ValidationMetrics,
    VariableClusteringEvidence,
    WoeTransformEvidence,
    WoeIvEvidence,
    WoeTable,
    ProxyRiskReport,
)
from cardre._evidence.profiles import EVIDENCE_PROFILES
from cardre.store import ProjectStore


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
            profile = EVIDENCE_PROFILES.get(kind)
            raise EvidenceNotFoundError(
                kind,
                candidate_artifact_ids=[a.artifact_id for a in artifacts],
                expected_schema=profile.schema_version if profile else None,
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        if len(candidates) > 1:
            profile = EVIDENCE_PROFILES.get(kind)
            raise AmbiguousEvidenceError(
                kind,
                candidates,
                expected_schema=profile.schema_version if profile else None,
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        return self._parse(candidates[0], kind)

    def find_optional(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> Any | None:
        """Like ``find`` but returns ``None`` when no match or ambiguity."""
        try:
            return self.find(artifacts, kind)
        except (EvidenceNotFoundError, AmbiguousEvidenceError):
            return None

    def find_model_artifact(self, artifacts: list[ArtifactRef]) -> ModelArtifact:
        return self.find(artifacts, EvidenceKind.MODEL_ARTIFACT)

    def find_bin_definition(self, artifacts: list[ArtifactRef]) -> BinDefinition:
        return self.find(artifacts, EvidenceKind.BIN_DEFINITION)

    def find_selection_definition(self, artifacts: list[ArtifactRef]) -> SelectionDefinition:
        return self.find(artifacts, EvidenceKind.SELECTION_DEFINITION)

    def find_woe_iv_evidence(self, artifacts: list[ArtifactRef]) -> WoeIvEvidence:
        return self.find(artifacts, EvidenceKind.WOE_IV_EVIDENCE)

    def find_score_scaling(self, artifacts: list[ArtifactRef]) -> ScoreScaling:
        return self.find(artifacts, EvidenceKind.SCORE_SCALING)

    def find_validation_evidence(self, artifacts: list[ArtifactRef]) -> ValidationMetrics:
        return self.find(artifacts, EvidenceKind.VALIDATION_EVIDENCE)

    def find_cutoff_analysis(self, artifacts: list[ArtifactRef]) -> CutoffAnalysis:
        return self.find(artifacts, EvidenceKind.CUTOFF_ANALYSIS)

    # ------------------------------------------------------------------
    # Public: read by artifact ID
    # ------------------------------------------------------------------

    def read(self, artifact_id: str, kind: EvidenceKind) -> Any:
        """Read typed evidence from a known artifact ID.

        Raises ``EvidenceNotFoundError`` if the artifact does not exist
        or does not match the expected profile.
        """
        art = self._store.get_artifact(artifact_id)
        if art is None:
            profile = EVIDENCE_PROFILES.get(kind)
            raise EvidenceNotFoundError(
                kind,
                artifact_id=artifact_id,
                expected_schema=profile.schema_version if profile else None,
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        matched = self._match([art], kind)
        if not matched:
            profile = EVIDENCE_PROFILES.get(kind)
            raise EvidenceNotFoundError(
                kind,
                artifact_id=artifact_id,
                expected_schema=profile.schema_version if profile else None,
                actual_schema=art.metadata.get("schema_version", ""),
                expected_role=",".join(sorted(profile.expected_roles)) if profile else None,
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)) if profile else None,
                expected_media_type=",".join(sorted(profile.expected_media_types)) if profile else None,
            )
        return self._parse(matched[0], kind)

    def read_optional(self, artifact_id: str, kind: EvidenceKind) -> Any | None:
        """Like ``read`` but returns ``None`` when no match exists."""
        try:
            return self.read(artifact_id, kind)
        except EvidenceNotFoundError:
            return None

    def read_report_bundle(self, artifact_id: str) -> ReportBundleEvidence:
        return self.read(artifact_id, EvidenceKind.REPORT_BUNDLE)

    def read_run_manifest(self, artifact_id: str) -> RunManifestEvidence:
        return self.read(artifact_id, EvidenceKind.RUN_MANIFEST)

    def read_required_step_output(self, run_step_id: str, kind: EvidenceKind) -> Any:
        result = self.read_step_output_optional(run_step_id, kind)
        if result is None:
            raise EvidenceNotFoundError(
                kind,
                step_id=run_step_id,
            )
        return result

    def read_optional_step_output(self, run_step_id: str, kind: EvidenceKind) -> Any | None:
        return self.read_step_output_optional(run_step_id, kind)

    def read_all_step_outputs(self, run_step: Any, kind: EvidenceKind) -> list[Any]:
        results: list[Any] = []
        rows = self._store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (getattr(run_step, "run_step_id", ""),),
        ).fetchall()
        for row in rows:
            aid = row["artifact_id"]
            value = self.read_optional(aid, kind)
            if value is not None:
                results.append(value)
        return results

    def read_step_output_optional(
        self,
        run_step_id: str,
        kind: EvidenceKind,
    ) -> Any | None:
        """Resolve output artifact IDs via artifact_lineage and scan for the given kind."""
        rows = self._store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (run_step_id,),
        ).fetchall()
        for row in rows:
            result = self.read_optional(row["artifact_id"], kind)
            if result is not None:
                return result
        return None

    def summarise_artifact(self, artifact_id: str, kind: EvidenceKind | None = None) -> ArtifactEvidenceSummary:
        art = self._store.get_artifact(artifact_id)
        if art is None:
            if kind is None:
                raise ValueError(f"Artifact not found: {artifact_id}")
            raise EvidenceNotFoundError(kind, artifact_id=artifact_id)

        matched_kind = kind or self._infer_kind_for_artifact(art)
        source_artifact_id = ""
        if matched_kind is not None:
            typed = self.read_optional(artifact_id, matched_kind)
            source_artifact_id = getattr(typed, "source_artifact_id", "") if typed is not None else ""

        return ArtifactEvidenceSummary(
            artifact_id=art.artifact_id,
            role=art.role,
            artifact_type=art.artifact_type,
            media_type=art.media_type,
            schema_version=art.metadata.get("schema_version", ""),
            kind=matched_kind.value if matched_kind is not None else "",
            source_artifact_id=source_artifact_id,
        )

    def summarise_step_outputs(self, run_step: Any, kind: EvidenceKind | None = None) -> list[ArtifactEvidenceSummary]:
        summaries: list[ArtifactEvidenceSummary] = []
        rows = self._store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (getattr(run_step, "run_step_id", ""),),
        ).fetchall()
        for row in rows:
            aid = row["artifact_id"]
            if self._store.get_artifact(aid) is None:
                continue
            if kind is not None and self.read_optional(aid, kind) is None:
                continue
            summaries.append(self.summarise_artifact(aid, kind))
        return summaries

    def summarise_run_artifacts(self, run_id: str, kind: EvidenceKind | None = None) -> list[ArtifactEvidenceSummary]:
        run_steps = self._store.get_run_steps(run_id)
        summaries: list[ArtifactEvidenceSummary] = []
        for rs in run_steps:
            summaries.extend(self.summarise_step_outputs(rs, kind))
        return summaries

    # ------------------------------------------------------------------
    # Internal: matching
    # ------------------------------------------------------------------

    def _match(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> list[ArtifactRef]:
        """Return artifacts matching the evidence kind's profile.

        Multi-phase matching:
        1. Schema version exact match (most reliable)
        2. Role + artifact_type + media_type fallback
        3. Legacy payload heuristics for ambiguous cases
        """
        profile = EVIDENCE_PROFILES.get(kind)
        if profile is None:
            return []

        # Phase 1: schema_version exact match
        schema_versions = {profile.schema_version} if profile.schema_version else set()
        if profile.legacy_schema_versions:
            schema_versions.update(profile.legacy_schema_versions)
        if schema_versions:
            candidates = [
                a for a in artifacts
                if a.metadata.get("schema_version") in schema_versions
            ]
            if candidates:
                return candidates

        # Phase 2: role + artifact_type + media_type fallback
        candidates = [
            a for a in artifacts
            if a.role in profile.expected_roles
            and a.artifact_type in profile.expected_artifact_types
            and a.media_type in profile.expected_media_types
            and (profile.exclude_key is None or profile.exclude_key not in a.metadata)
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
        return candidates

    def _kind_for_artifact(self, art: ArtifactRef) -> EvidenceKind | None:
        schema_version = art.metadata.get("schema_version", "")
        if schema_version:
            for kind, profile in EVIDENCE_PROFILES.items():
                if profile.schema_version and profile.schema_version == schema_version:
                    return kind
        return None

    def _infer_kind_for_artifact(self, art: ArtifactRef) -> EvidenceKind | None:
        kind = self._kind_for_artifact(art)
        if kind is not None:
            return kind
        for candidate in EVIDENCE_PROFILES:
            if self._match([art], candidate):
                return candidate
        return None

    def _candidate_passes_payload_check(self, art: ArtifactRef, profile: Any) -> bool:
        """Check that a candidate's payload matches the profile requirements."""
        if profile.required_columns is not None:
            if art.media_type == "application/json":
                return False
            return self._parquet_has_columns(art, profile.required_columns)
        if profile.required_keys:
            path = self._store.artifact_path(art)
            if not path.exists():
                return False
            try:
                data = json.loads(path.read_text())
                keys = set(data.keys())
                if profile.required_keys.issubset(keys):
                    return True
                if profile.legacy_required_keys is not None:
                    return profile.legacy_required_keys.issubset(keys)
                return False
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False
        return True

    def _parquet_has_columns(self, art: ArtifactRef, columns: set[str]) -> bool:
        """Check whether the parquet artifact contains all required columns."""
        try:
            import polars as pl
            cols = pl.scan_parquet(self._store.artifact_path(art)).collect_schema().names()
            return columns.issubset(cols)
        except Exception:
            return False

    def _legacy_match(self, artifacts: list[ArtifactRef], kind: EvidenceKind) -> list[ArtifactRef]:
        """Legacy payload heuristics for evidence kinds that share role/type."""
        if kind == EvidenceKind.BIN_DEFINITION:
            defs = [a for a in artifacts if a.role == "definition" and a.media_type == "application/json"]
            return self._match_by_payload_key(defs, {"variables"}, exclude_key="selected")
        if kind == EvidenceKind.SELECTION_DEFINITION:
            defs = [a for a in artifacts if a.role == "definition" and a.media_type == "application/json"]
            return self._match_by_payload_key(defs, {"selected"})
        if kind == EvidenceKind.MODELLING_METADATA:
            return self._match_by_payload_key(artifacts, {"target_column", "good_values", "bad_values"})
        if kind == EvidenceKind.WOE_TABLE:
            return [
                a for a in artifacts
                if a.role == "report"
                and a.media_type == "application/vnd.apache.parquet"
                and self._parquet_has_columns(a, {"variable", "bin_id", "woe"})
            ]
        if kind == EvidenceKind.IV_TABLE:
            return [
                a for a in artifacts
                if a.role == "report"
                and a.media_type == "application/vnd.apache.parquet"
                and self._parquet_has_columns(a, {"iv", "variable"})
            ]
        if kind == EvidenceKind.VARIABLE_CLUSTERING:
            return self._match_by_payload_key(artifacts, {"method", "clusters"})
        if kind == EvidenceKind.SPLIT_SUMMARY:
            return self._match_by_payload_key(artifacts, {"strategy", "row_counts"})
        if kind == EvidenceKind.PROFILE_SUMMARY:
            return self._match_by_payload_key(artifacts, {"profiles"}) or self._match_by_payload_key(
                artifacts,
                {"row_count", "column_count", "columns", "dtypes"},
            )
        if kind == EvidenceKind.EXCLUSION_SUMMARY:
            return self._match_by_payload_key(artifacts, {"rows_before", "rows_after", "rules"})
        if kind == EvidenceKind.WOE_TRANSFORM_EVIDENCE:
            return self._match_by_payload_key(artifacts, {"target_column", "transformed_variables"})
        if kind == EvidenceKind.APPLY_WOE_EVIDENCE:
            return self._match_by_payload_key(artifacts, {"roles", "policy"})
        if kind == EvidenceKind.APPLY_MODEL_EVIDENCE:
            return self._match_by_payload_key(artifacts, {"roles", "model_artifact_id"})
        if kind == EvidenceKind.REPORT_BUNDLE:
            return self._match_by_payload_key(artifacts, {"project_id", "run_id", "summary", "source"})
        if kind == EvidenceKind.RUN_MANIFEST:
            return [
                a for a in artifacts
                if a.artifact_type == "run_manifest"
                and a.media_type == "application/json"
                and self._match_by_payload_key([a], {"manifest_version", "run_id", "steps"})
            ]
        if kind == EvidenceKind.TECHNICAL_MANIFEST_INDEX:
            return self._match_by_payload_key(artifacts, {"manifests"})
        if kind == EvidenceKind.COMPARISON_ARTIFACT:
            return [
                a for a in artifacts
                if a.artifact_type == "branch_comparison"
                and a.media_type == "application/json"
                and self._match_by_payload_key([a], {"comparison_type", "baseline_branch_id", "challenger_branch_id"})
            ]
        if kind == EvidenceKind.FEATURE_SELECTION_EVIDENCE:
            return self._match_by_payload_key(artifacts, {"selected", "rejected"})
        if kind == EvidenceKind.RESAMPLING_EVIDENCE:
            return self._match_by_payload_key(artifacts, {"original", "resampled"})
        if kind == EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE:
            return self._match_by_payload_key(artifacts, {"best_params", "best_score"})
        if kind == EvidenceKind.ENSEMBLE_MODEL_ARTIFACT:
            return self._match_by_payload_key(artifacts, {"model_family", "model_payload"})
        if kind == EvidenceKind.EXPLAINABILITY_REPORT:
            return self._match_by_payload_key(artifacts, {"model_family", "limitations"})
        if kind == EvidenceKind.FAIRNESS_REPORT:
            return self._match_by_payload_key(artifacts, {"roles", "parity_summary"})
        if kind == EvidenceKind.PROXY_RISK_REPORT:
            return self._match_by_payload_key(artifacts, {"proxy_flags", "overall_risk"})
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

    # ------------------------------------------------------------------
    # Internal: parsing
    # ------------------------------------------------------------------

    def _parse(self, art: ArtifactRef, kind: EvidenceKind) -> Any:
        """Parse an artifact into typed evidence."""
        profile = EVIDENCE_PROFILES.get(kind)
        if profile is None:
            raise EvidenceParseError(f"No profile registered for evidence kind {kind.value}")

        path = self._store.artifact_path(art)
        if not path.exists():
            raise EvidenceParseError(f"Artifact file not found: {path}")

        if kind == EvidenceKind.WOE_TABLE:
            return self._parse_woe_table(path, art)
        if kind == EvidenceKind.IV_TABLE:
            lf = pl.scan_parquet(path)
            return IvTable(dataframe=lf, columns=lf.collect_schema().names(), source_artifact_id=art.artifact_id)
        if kind == EvidenceKind.BIN_DEFINITION:
            return self._parse_bin_definition(path, art)

        if profile.expected_media_types == {"application/vnd.apache.parquet"}:
            return self._parse_parquet(path, art, kind, profile)
        return self._parse_json(path, art, kind, profile)

    def _parse_bin_definition(self, path: Path, art: ArtifactRef) -> BinDefinition:
        """Parse a BinDefinition JSON artifact, passing the artifact ID."""
        try:
            data: JsonDict = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvidenceParseError(
                f"Invalid JSON for bin_definition: {exc}",
                kind=EvidenceKind.BIN_DEFINITION,
                artifact_id=art.artifact_id,
                expected_schema=EVIDENCE_PROFILES[EvidenceKind.BIN_DEFINITION].schema_version,
                expected_role=",".join(sorted(EVIDENCE_PROFILES[EvidenceKind.BIN_DEFINITION].expected_roles)),
                expected_artifact_type=",".join(sorted(EVIDENCE_PROFILES[EvidenceKind.BIN_DEFINITION].expected_artifact_types)),
                expected_media_type=",".join(sorted(EVIDENCE_PROFILES[EvidenceKind.BIN_DEFINITION].expected_media_types)),
            ) from exc
        return BinDefinition.from_json(data, artifact_id=art.artifact_id)

    def _parse_woe_table(self, path: Path, art: ArtifactRef) -> WoeTable:
        """Read a Parquet WOE table and build the variable -> bin_id -> woe mapping."""
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

        return WoeTable(mapping=mapping, columns=cols, dataframe=lf, source_artifact_id=art.artifact_id)

    def _parse_json(self, path: Path, art: ArtifactRef, kind: EvidenceKind, profile: Any) -> Any:
        """Parse a JSON artifact into typed evidence."""
        try:
            data: JsonDict = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvidenceParseError(f"Invalid JSON for {kind.value}: {exc}") from exc

        if profile.required_keys:
            missing = profile.required_keys - set(data.keys())
            if missing and not (profile.legacy_required_keys and profile.legacy_required_keys.issubset(set(data.keys()))):
                raise EvidenceParseError(
                    f"Evidence {kind.value} missing required keys: {missing}",
                    kind=kind,
                    artifact_id=art.artifact_id,
                    expected_schema=profile.schema_version,
                    expected_role=",".join(sorted(profile.expected_roles)),
                    expected_artifact_type=",".join(sorted(profile.expected_artifact_types)),
                    expected_media_type=",".join(sorted(profile.expected_media_types)),
                )

        return self._to_typed(data, kind, artifact_id=art.artifact_id)

    def _parse_parquet(self, path: Path, art: ArtifactRef, kind: EvidenceKind, profile: Any) -> Any:
        """Parse a Parquet artifact into typed evidence."""
        try:
            lf = pl.scan_parquet(path)
        except Exception as exc:
            raise EvidenceParseError(
                f"Invalid Parquet for {kind.value}: {exc}",
                kind=kind,
                artifact_id=art.artifact_id,
                expected_schema=profile.schema_version,
                expected_role=",".join(sorted(profile.expected_roles)),
                expected_artifact_type=",".join(sorted(profile.expected_artifact_types)),
                expected_media_type=",".join(sorted(profile.expected_media_types)),
            ) from exc

        if profile.required_columns:
            schema = lf.collect_schema()
            missing = profile.required_columns - set(schema.names())
            if missing:
                raise EvidenceParseError(
                    f"Evidence {kind.value} missing required columns: {missing}",
                    kind=kind,
                    expected_schema=profile.schema_version,
                    expected_role=",".join(sorted(profile.expected_roles)),
                    expected_artifact_type=",".join(sorted(profile.expected_artifact_types)),
                    expected_media_type=",".join(sorted(profile.expected_media_types)),
                )

        return self._to_typed(lf, kind, artifact_id=art.artifact_id)

    def _to_typed(self, data: Any, kind: EvidenceKind, artifact_id: str = "") -> Any:
        """Convert raw data to typed evidence record."""
        if kind == EvidenceKind.MODELLING_METADATA:
            return ModellingMetadata.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.SAMPLE_DEFINITION:
            return SampleDefinition.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.BIN_DEFINITION:
            return BinDefinition.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.SELECTION_DEFINITION:
            return SelectionDefinition.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.REJECT_POPULATION_CONFIG:
            return RejectPopulationConfig.from_json(data)
        if kind == EvidenceKind.REJECT_INFERENCE_RESULT:
            return RejectInferenceResult.from_json(data)
        if kind == EvidenceKind.SPLIT_SUMMARY:
            return SplitSummary.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.PROFILE_SUMMARY:
            return ProfileSummary.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.EXCLUSION_SUMMARY:
            return ExclusionSummary.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.WOE_TRANSFORM_EVIDENCE:
            return WoeTransformEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.WOE_IV_EVIDENCE:
            return WoeIvEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.MODEL_ARTIFACT:
            return ModelArtifact.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.ENSEMBLE_MODEL_ARTIFACT:
            return ModelArtifact.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.SCORE_SCALING:
            return ScoreScaling.from_json(data, artifact_id=artifact_id)
        if kind in (EvidenceKind.VALIDATION_METRICS, EvidenceKind.VALIDATION_EVIDENCE):
            return ValidationMetrics.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.CUTOFF_ANALYSIS:
            return CutoffAnalysis.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.WOE_TABLE:
            return WoeTable(dataframe=data, source_artifact_id=artifact_id)
        if kind == EvidenceKind.IV_TABLE:
            return IvTable(dataframe=data, source_artifact_id=artifact_id)
        if kind == EvidenceKind.SCORED_DATASET:
            return ScoredDataset(dataframe=data)
        if kind == EvidenceKind.VARIABLE_CLUSTERING:
            return VariableClusteringEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.APPLY_WOE_EVIDENCE:
            return ApplyWoeEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.APPLY_MODEL_EVIDENCE:
            return ApplyModelEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.REPORT_BUNDLE:
            return ReportBundleEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.RUN_MANIFEST:
            return RunManifestEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.TECHNICAL_MANIFEST_INDEX:
            return TechnicalManifestIndex.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.COMPARISON_ARTIFACT:
            return ComparisonArtifact.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.FEATURE_SELECTION_EVIDENCE:
            return FeatureSelectionEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.RESAMPLING_EVIDENCE:
            return ResamplingEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE:
            return HyperparameterTuningEvidence.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.EXPLAINABILITY_REPORT:
            return ExplainabilityReport.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.FAIRNESS_REPORT:
            return FairnessReport.from_json(data, artifact_id=artifact_id)
        if kind == EvidenceKind.PROXY_RISK_REPORT:
            return ProxyRiskReport.from_json(data, artifact_id=artifact_id)
        return data
