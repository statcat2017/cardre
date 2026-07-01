"""Tests for the typed ArtifactEvidenceReader."""

from __future__ import annotations

import io
import json

import polars as pl
import pytest

from cardre.audit import (
    ArtifactRef,
    json_logical_hash,
    table_logical_hash,
    physical_hash,
    relative_path,
)
from cardre.evidence import (
    AmbiguousEvidenceError,
    ArtifactEvidenceReader,
    EvidenceKind,
    EvidenceNotFoundError,
    EvidenceParseError,
    SCHEMA_BIN_DEFINITION,
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_MODELLING_METADATA,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_SAMPLE_DEFINITION,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_VALIDATION_EVIDENCE,
    SCHEMA_VALIDATION_METRICS,
    SCHEMA_WOE_IV_EVIDENCE,
    SampleDefinition,
)
from cardre.store import ProjectStore

from tests.helpers import make_store

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_artifact(
    store: ProjectStore,
    payload: dict,
    stem: str = "test",
    role: str = "definition",
    artifact_type: str | None = None,
    schema_version: str | None = None,
) -> ArtifactRef:
    p = store.root / "artifacts" / f"{stem}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, sort_keys=True))
    meta: dict = {}
    if schema_version:
        meta["schema_version"] = schema_version
    art = ArtifactRef(
        artifact_id=f"{stem}_1",
        artifact_type=artifact_type or role,
        role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p),
        logical_hash=json_logical_hash(payload),
        media_type="application/json",
        metadata=meta,
    )
    store.register_artifact(art)
    return art


def _parquet_artifact(
    store: ProjectStore,
    df: pl.DataFrame,
    stem: str = "test",
    role: str = "report",
    artifact_type: str = "report",
    media_type: str = "application/vnd.apache.parquet",
    metadata: dict | None = None,
) -> ArtifactRef:
    buf = io.BytesIO()
    df.write_parquet(buf)
    p = store.root / "datasets" / f"{stem}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id=f"{stem}_1",
        artifact_type=artifact_type,
        role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p),
        logical_hash=table_logical_hash(df),
        media_type=media_type,
        metadata=metadata or {},
    )
    store.register_artifact(art)
    return art


def _run_step(artifact_ids: list[str]) -> object:
    from collections import namedtuple
    return namedtuple("RunStepRecord", "output_artifact_ids")(
        output_artifact_ids=artifact_ids
    )


# ======================================================================
# Schema-version matching (Phase 1)
# ======================================================================


class TestSchemaVersionMatching:
    """Every EvidenceKind with a schema_version should match via Phase 1."""

    @pytest.mark.parametrize("kind,schema_version,payload", [
        (EvidenceKind.MODELLING_METADATA, SCHEMA_MODELLING_METADATA,
         {"target_column": "y", "good_values": ["g"], "bad_values": ["b"]}),
        (EvidenceKind.BIN_DEFINITION, SCHEMA_BIN_DEFINITION,
         {"variables": [{"variable": "x", "kind": "numeric", "bins": []}], "warnings": []}),
        (EvidenceKind.SELECTION_DEFINITION, SCHEMA_SELECTION_DEFINITION,
         {"selected": [{"variable": "x", "reason": ""}], "method": "iv"}),
        (EvidenceKind.MODEL_ARTIFACT, SCHEMA_MODEL_ARTIFACT,
         {"model_family": "logistic_regression", "coefficients": {}, "intercept": 0.0}),
        (EvidenceKind.SCORE_SCALING, SCHEMA_SCORE_SCALING,
         {"factor": 1.0, "offset": 0.0, "base_score": 600, "base_odds": "50:1", "pdo": 20}),
        (EvidenceKind.VALIDATION_METRICS, SCHEMA_VALIDATION_METRICS,
         {"metrics": {"train": {"row_count": 100}}}),
        (EvidenceKind.VALIDATION_METRICS, SCHEMA_VALIDATION_EVIDENCE,
         {"roles": {"train": {"row_count": 100}}, "stability": {}, "gates": [], "warnings": []}),
        (EvidenceKind.VALIDATION_EVIDENCE, SCHEMA_VALIDATION_EVIDENCE,
         {"roles": {"train": {"row_count": 100}}, "stability": {}, "gates": [], "warnings": []}),
        (EvidenceKind.CUTOFF_ANALYSIS, SCHEMA_CUTOFF_ANALYSIS,
         {"cutoff_tables": {"train": [{"score_cutoff": 0.5}]}}),
        (EvidenceKind.WOE_IV_EVIDENCE, SCHEMA_WOE_IV_EVIDENCE,
         {"variables": [], "config": {"smoothing": {}}}),
    ])
    def test_schema_version_matches(self, kind, schema_version, payload):
        store, _ = make_store()
        art = _json_artifact(
            store, payload, stem=kind.value,
            role=list(kind_profile(kind).expected_roles)[0],
            schema_version=schema_version,
        )
        reader = ArtifactEvidenceReader(store)
        result = reader.find([art], kind)
        assert result is not None

    def test_modelling_metadata_preserves_raw_value_types(self):
        store, _ = make_store()
        art = _json_artifact(
            store,
            {
                "target_column": "default_flag",
                "good_values": [0],
                "bad_values": [1],
                "indeterminate_values": [2],
            },
            stem="metadata",
            schema_version=SCHEMA_MODELLING_METADATA,
        )

        result = ArtifactEvidenceReader(store).find([art], EvidenceKind.MODELLING_METADATA)

        assert result.good_values == [0]
        assert result.bad_values == [1]
        assert result.indeterminate_values == [2]

    def test_sample_definition_preserves_default_sample_method(self):
        result = SampleDefinition.from_json({"schema_version": SCHEMA_SAMPLE_DEFINITION})

        assert result.sample_method == "full_population"


def kind_profile(kind: EvidenceKind):
    """Return the profile for a given EvidenceKind (reflection helper)."""
    from cardre.evidence import _EVIDENCE_PROFILES
    return _EVIDENCE_PROFILES[kind]


# ======================================================================
# Legacy payload-key disambiguation (Phase 3)
# ======================================================================


class TestLegacyBinVsSelectionDisambiguation:
    """Legacy artifacts without schema_version must still disambiguate."""

    def test_bin_definition_matches_variables(self):
        store, _ = make_store()
        bin_art = _json_artifact(
            store,
            {"variables": [{"variable": "x", "kind": "numeric", "bins": []}], "warnings": []},
            stem="bins",
        )
        sel_art = _json_artifact(
            store,
            {"selected": [{"variable": "x", "reason": "high_iv"}], "method": "iv"},
            stem="selection",
        )
        reader = ArtifactEvidenceReader(store)
        result = reader.find([bin_art, sel_art], EvidenceKind.BIN_DEFINITION)
        assert result is not None
        assert len(result.variables) == 1

    def test_selection_definition_matches_selected(self):
        store, _ = make_store()
        bin_art = _json_artifact(
            store,
            {"variables": [{"variable": "x", "kind": "numeric", "bins": []}], "warnings": []},
            stem="bins",
        )
        sel_art = _json_artifact(
            store,
            {"selected": [{"variable": "x", "reason": "high_iv"}], "method": "iv"},
            stem="selection",
        )
        reader = ArtifactEvidenceReader(store)
        result = reader.find([bin_art, sel_art], EvidenceKind.SELECTION_DEFINITION)
        assert result is not None
        assert len(result.selected) == 1

    def test_wrong_legacy_definition_does_not_parse_as_bin(self):
        """A selection definition artifact must not match BIN_DEFINITION."""
        store, _ = make_store()
        sel_art = _json_artifact(
            store,
            {"selected": [{"variable": "x", "reason": "high_iv"}], "method": "iv"},
            stem="selection",
        )
        reader = ArtifactEvidenceReader(store)
        with pytest.raises(EvidenceNotFoundError):
            reader.find([sel_art], EvidenceKind.BIN_DEFINITION)

    def test_wrong_legacy_definition_does_not_parse_as_selection(self):
        """A bin definition artifact must not match SELECTION_DEFINITION."""
        store, _ = make_store()
        bin_art = _json_artifact(
            store,
            {"variables": [{"variable": "x", "kind": "numeric", "bins": []}], "warnings": []},
            stem="bins",
        )
        reader = ArtifactEvidenceReader(store)
        with pytest.raises(EvidenceNotFoundError):
            reader.find([bin_art], EvidenceKind.SELECTION_DEFINITION)

    def test_legacy_woe_table_disambiguates_from_iv_ranking(self):
        """Two report parquets: only the one with variable/bin_id/woe columns matches."""
        store, _ = make_store()
        woe_df = pl.DataFrame({
            "variable": ["x", "x"], "bin_id": ["a", "b"], "woe": [0.5, -0.3],
        })
        iv_df = pl.DataFrame({
            "variable": ["x"], "iv": [0.42], "bin_count": [2],
        })
        woe_art = _parquet_artifact(store, woe_df, stem="woe-table")
        iv_art = _parquet_artifact(store, iv_df, stem="iv-ranking")

        reader = ArtifactEvidenceReader(store)
        result = reader.find([woe_art, iv_art], EvidenceKind.WOE_TABLE)
        assert result is not None
        assert result.mapping == {"x": {"a": 0.5, "b": -0.3}}

    def test_woe_table_absent_raises_not_found(self):
        """When only an IV ranking parquet exists, WOE_TABLE raises."""
        store, _ = make_store()
        iv_df = pl.DataFrame({
            "variable": ["x"], "iv": [0.42], "bin_count": [2],
        })
        iv_art = _parquet_artifact(store, iv_df, stem="iv-ranking")

        reader = ArtifactEvidenceReader(store)
        with pytest.raises(EvidenceNotFoundError):
            reader.find([iv_art], EvidenceKind.WOE_TABLE)


# ======================================================================
# read_step_output_optional skips non-matching artifacts safely
# ======================================================================


class TestReadStepOutputOptional:
    """Must skip artifacts whose role/type/media don't match the kind."""

    def test_skips_json_when_parquet_expected(self):
        store, _ = make_store()
        json_art = _json_artifact(
            store, {"variables": []}, stem="report-json",
            role="report", artifact_type="report",
        )
        reader = ArtifactEvidenceReader(store)
        rs = _run_step([json_art.artifact_id])
        assert reader.read_step_output_optional(rs, EvidenceKind.WOE_TABLE) is None

    def test_skips_parquet_when_json_expected(self):
        store, _ = make_store()
        df = pl.DataFrame({"x": [1]})
        parq_art = _parquet_artifact(store, df, stem="report-parquet")
        reader = ArtifactEvidenceReader(store)
        rs = _run_step([parq_art.artifact_id])
        assert reader.read_step_output_optional(rs, EvidenceKind.BIN_DEFINITION) is None


# ======================================================================
# Parse failures produce useful errors
# ======================================================================


class TestParseErrors:
    """Parse failures must raise EvidenceParseError with the file path."""

    def test_corrupt_json(self):
        store, _ = make_store()
        p = store.root / "artifacts" / "corrupt.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"{bad json\xff")
        art = ArtifactRef(
            artifact_id="corrupt_1", artifact_type="definition", role="definition",
            path=relative_path(p, store.root),
            physical_hash=physical_hash(p),
            logical_hash="xxx",
            media_type="application/json", metadata={},
        )
        store.register_artifact(art)
        reader = ArtifactEvidenceReader(store)
        try:
            reader.find([art], EvidenceKind.BIN_DEFINITION)
        except EvidenceNotFoundError:
            pass
        else:
            raise AssertionError("Expected EvidenceNotFoundError")

    def test_missing_file(self):
        store, _ = make_store()
        art = ArtifactRef(
            artifact_id="missing_1", artifact_type="definition", role="definition",
            path="artifacts/nonexistent.json",
            physical_hash="x",
            logical_hash="x",
            media_type="application/json", metadata={},
        )
        store.register_artifact(art)
        reader = ArtifactEvidenceReader(store)
        with pytest.raises(EvidenceNotFoundError):
            reader.find([art], EvidenceKind.BIN_DEFINITION)

    def test_parse_called_on_known_artifact_raises_parse_error(self):
        """reading a known artifact ID that fails to parse raises EvidenceParseError."""
        store, _ = make_store()
        p = store.root / "artifacts" / "bad.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00\x01\x02")
        art = ArtifactRef(
            artifact_id="bad_1", artifact_type="definition", role="definition",
            path=relative_path(p, store.root),
            physical_hash=physical_hash(p),
            logical_hash="x",
            media_type="application/json", metadata={},
        )
        store.register_artifact(art)
        reader = ArtifactEvidenceReader(store)
        with pytest.raises((EvidenceNotFoundError, EvidenceParseError)):
            reader.read("bad_1", EvidenceKind.BIN_DEFINITION)


# ======================================================================
# Ambiguous match raises AmbiguousEvidenceError
# ======================================================================


class TestAmbiguous:
    def test_two_schema_less_parquet_reports_ambiguous(self):
        store, _ = make_store()
        df1 = pl.DataFrame({
            "variable": ["x", "x"], "bin_id": ["a", "b"], "woe": [0.5, -0.3],
        })
        df2 = pl.DataFrame({
            "variable": ["y", "y"], "bin_id": ["c", "d"], "woe": [0.1, -0.1],
        })
        art1 = _parquet_artifact(store, df1, stem="woe-table-1")
        art2 = _parquet_artifact(store, df2, stem="woe-table-2")
        reader = ArtifactEvidenceReader(store)
        with pytest.raises(AmbiguousEvidenceError):
            reader.find([art1, art2], EvidenceKind.WOE_TABLE)
