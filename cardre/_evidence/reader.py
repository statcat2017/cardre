"""ArtifactEvidenceReader — typed evidence access from immutable artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from cardre.audit import ArtifactRef, JsonDict
from cardre._evidence.kinds import (
    EvidenceKind,
    EvidenceNotFoundError,
    AmbiguousEvidenceError,
    EvidenceParseError,
)
from cardre._evidence.models import (
    BinDefinition,
    CutoffAnalysis,
    IvTable,
    ModellingMetadata,
    ModelArtifact,
    RejectInferenceResult,
    RejectPopulationConfig,
    SampleDefinition,
    ScoreScaling,
    ScoredDataset,
    SelectionDefinition,
    ValidationMetrics,
    VariableClusteringEvidence,
    WoeIvEvidence,
    WoeTable,
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
        """Read typed evidence from a known artifact ID.

        Raises ``EvidenceNotFoundError`` if the artifact does not exist
        or does not match the expected profile.
        """
        art = self._store.get_artifact(artifact_id)
        if art is None:
            raise EvidenceNotFoundError(kind)
        matched = self._match([art], kind)
        if not matched:
            raise EvidenceNotFoundError(kind)
        return self._parse(matched[0], kind)

    def read_optional(self, artifact_id: str, kind: EvidenceKind) -> Any | None:
        """Like ``read`` but returns ``None`` when no match exists."""
        try:
            return self.read(artifact_id, kind)
        except EvidenceNotFoundError:
            return None

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
        if profile.schema_version:
            candidates = [
                a for a in artifacts
                if a.metadata.get("schema_version") == profile.schema_version
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
                return profile.required_keys.issubset(data.keys())
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
            return self._parse_parquet(path, kind, profile)
        return self._parse_json(path, kind, profile)

    def _parse_bin_definition(self, path: Path, art: ArtifactRef) -> BinDefinition:
        """Parse a BinDefinition JSON artifact, passing the artifact ID."""
        try:
            data: JsonDict = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvidenceParseError(f"Invalid JSON for bin_definition: {exc}") from exc
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

    def _parse_json(self, path: Path, kind: EvidenceKind, profile: Any) -> Any:
        """Parse a JSON artifact into typed evidence."""
        try:
            data: JsonDict = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EvidenceParseError(f"Invalid JSON for {kind.value}: {exc}") from exc

        if profile.required_keys:
            missing = profile.required_keys - set(data.keys())
            if missing:
                raise EvidenceParseError(
                    f"Evidence {kind.value} missing required keys: {missing}"
                )

        return self._to_typed(data, kind)

    def _parse_parquet(self, path: Path, kind: EvidenceKind, profile: Any) -> Any:
        """Parse a Parquet artifact into typed evidence."""
        try:
            lf = pl.scan_parquet(path)
        except Exception as exc:
            raise EvidenceParseError(f"Invalid Parquet for {kind.value}: {exc}") from exc

        if profile.required_columns:
            schema = lf.collect_schema()
            missing = profile.required_columns - set(schema.names())
            if missing:
                raise EvidenceParseError(
                    f"Evidence {kind.value} missing required columns: {missing}"
                )

        return self._to_typed(lf, kind)

    def _to_typed(self, data: Any, kind: EvidenceKind) -> Any:
        """Convert raw data to typed evidence record."""
        if kind == EvidenceKind.MODELLING_METADATA:
            return ModellingMetadata.from_json(data)
        if kind == EvidenceKind.SAMPLE_DEFINITION:
            return SampleDefinition.from_json(data)
        if kind == EvidenceKind.BIN_DEFINITION:
            return BinDefinition.from_json(data)
        if kind == EvidenceKind.SELECTION_DEFINITION:
            return SelectionDefinition.from_json(data)
        if kind == EvidenceKind.REJECT_POPULATION_CONFIG:
            return RejectPopulationConfig.from_json(data)
        if kind == EvidenceKind.REJECT_INFERENCE_RESULT:
            return RejectInferenceResult.from_json(data)
        if kind == EvidenceKind.WOE_IV_EVIDENCE:
            return WoeIvEvidence.from_json(data)
        if kind == EvidenceKind.MODEL_ARTIFACT:
            return ModelArtifact.from_json(data)
        if kind == EvidenceKind.SCORE_SCALING:
            return ScoreScaling.from_json(data)
        if kind in (EvidenceKind.VALIDATION_METRICS, EvidenceKind.VALIDATION_EVIDENCE):
            return ValidationMetrics.from_json(data)
        if kind == EvidenceKind.CUTOFF_ANALYSIS:
            return CutoffAnalysis.from_json(data)
        if kind == EvidenceKind.WOE_TABLE:
            return WoeTable(dataframe=data)
        if kind == EvidenceKind.IV_TABLE:
            return IvTable(dataframe=data)
        if kind == EvidenceKind.SCORED_DATASET:
            return ScoredDataset(dataframe=data)
        if kind == EvidenceKind.VARIABLE_CLUSTERING:
            return VariableClusteringEvidence.from_json(data)
        return data
