"""Tests for the EvidenceAdapter registry, independence, and parity.

Verifies:
- Every EvidenceKind with a profile has a registered adapter.
- Each adapter carries its kind and profile.
- No adapter module imports ArtifactEvidenceReader (dependency direction).
- Adapters do not implement summarise() (removed from protocol).
- adapter.match() + adapter.parse() produce the same results as
  ArtifactEvidenceReader._match() + ._parse() for representative kinds.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import pytest

from cardre._evidence.adapters import EVIDENCE_ADAPTERS, EvidenceAdapter, get_adapter
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.profiles import EVIDENCE_PROFILES
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.domain.artifacts import ArtifactRef


# ---------------------------------------------------------------------------
# Registry coverage tests
# ---------------------------------------------------------------------------


def test_adapter_registry_covers_all_profiles() -> None:
    assert set(EVIDENCE_PROFILES).issubset(set(EVIDENCE_ADAPTERS))


def test_adapter_registry_covers_all_evidence_kinds() -> None:
    for kind in EvidenceKind:
        assert kind in EVIDENCE_ADAPTERS, f"{kind.name} missing from registry"


def test_get_adapter_returns_correct_kind_and_profile() -> None:
    for kind in EVIDENCE_PROFILES:
        adapter = get_adapter(kind)
        assert isinstance(adapter, EvidenceAdapter)
        assert adapter.kind == kind
        assert adapter.profile is EVIDENCE_PROFILES[kind]


def test_get_adapter_unknown_kind_raises() -> None:
    from cardre._evidence.kinds import EvidenceParseError

    class _FakeKind:
        value = "fake"

    with pytest.raises(EvidenceParseError):
        get_adapter(_FakeKind())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dependency-direction guard
# ---------------------------------------------------------------------------


def test_adapters_do_not_import_artifact_evidence_reader() -> None:
    adapters_dir = Path(__file__).resolve().parent.parent / "cardre" / "_evidence" / "adapters"
    banned = "ArtifactEvidenceReader"
    for py in sorted(adapters_dir.glob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert banned not in alias.name, f"{py.name} imports {banned}"
                    if alias.asname:
                        assert banned not in alias.asname, f"{py.name} imports {banned} as {alias.asname}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert banned not in alias.name, f"{py.name} imports {banned}"


def test_adapters_do_not_implement_summarise() -> None:
    """summarise() was removed from the EvidenceAdapter protocol; adapters
    must not carry a stub that could be called unsafely."""
    adapters_dir = Path(__file__).resolve().parent.parent / "cardre" / "_evidence" / "adapters"
    for py in sorted(adapters_dir.glob("*.py")):
        if py.name in ("__init__.py", "_base.py"):
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "summarise":
                raise AssertionError(f"{py.name} still defines summarise()")


# ---------------------------------------------------------------------------
# Parity tests: adapter.match() + adapter.parse() vs ArtifactEvidenceReader
# ---------------------------------------------------------------------------

def _write_json_artifact(
    store, tmp_path: Path, artifact_type: str, role: str,
    schema_version: str, payload: dict, media_type: str = "application/json",
    artifact_id: str | None = None,
) -> ArtifactRef:
    """Write a JSON artifact to disk and register it in the store.

    schema_version goes into metadata_json (ArtifactRef.metadata), matching
    how the real store registers artifacts.
    """
    aid = artifact_id or str(uuid.uuid4())
    art_path = tmp_path / f"{aid}.json"
    art_path.write_text(json.dumps(payload))
    metadata = {"schema_version": schema_version} if schema_version else {}
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, artifact_type, role, str(art_path), "phys_hash", "log_hash", media_type, "", json.dumps(metadata)),
    )
    return store.get_artifact(aid)


def _write_parquet_artifact(
    store, tmp_path: Path, artifact_type: str, role: str,
    schema_version: str, columns: dict[str, list], media_type: str = "application/vnd.apache.parquet",
    artifact_id: str | None = None,
) -> ArtifactRef:
    """Write a parquet artifact to disk and register it in the store."""
    import polars as pl
    aid = artifact_id or str(uuid.uuid4())
    art_path = tmp_path / f"{aid}.parquet"
    pl.DataFrame(columns).write_parquet(art_path)
    metadata = {"schema_version": schema_version} if schema_version else {}
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, artifact_type, role, str(art_path), "phys_hash", "log_hash", media_type, "", json.dumps(metadata)),
    )
    return store.get_artifact(aid)


def _assert_match_parity(store, kind: EvidenceKind, artifacts: list[ArtifactRef]) -> None:
    """Assert adapter.match() returns the same artifact IDs as reader._match()."""
    reader = ArtifactEvidenceReader(store)
    reader_result = reader._match(artifacts, kind)
    adapter = get_adapter(kind)
    adapter_result = adapter.match(artifacts, store)
    reader_ids = [a.artifact_id for a in reader_result]
    adapter_ids = [a.artifact_id for a in adapter_result]
    assert reader_ids == adapter_ids, (
        f"match parity failed for {kind.value}: reader={reader_ids} adapter={adapter_ids}"
    )


def _assert_parse_parity(store, kind: EvidenceKind, artifact: ArtifactRef) -> None:
    """Assert adapter.parse() returns the same typed object as reader._parse()."""
    reader = ArtifactEvidenceReader(store)
    reader_result = reader._parse(artifact, kind)
    adapter = get_adapter(kind)
    path = store.artifact_path(artifact)
    adapter_result = adapter.parse(path, artifact, store)
    assert type(adapter_result) is type(reader_result), (
        f"parse parity failed for {kind.value}: reader type={type(reader_result)}, adapter type={type(adapter_result)}"
    )
    if hasattr(reader_result, "source_artifact_id"):
        assert reader_result.source_artifact_id == adapter_result.source_artifact_id, (
            f"parse parity failed for {kind.value}: "
            f"reader source_artifact_id={reader_result.source_artifact_id}, "
            f"adapter source_artifact_id={adapter_result.source_artifact_id}"
        )


# JSON evidence kinds with schema_version + required_keys
_JSON_KIND_FIXTURES = [
    (EvidenceKind.BIN_DEFINITION, "definition", "definition",
     "cardre.bin_definition.v1", {"variables": [{"variable": "age", "bins": []}]}),
    (EvidenceKind.SELECTION_DEFINITION, "definition", "definition",
     "cardre.selection_definition.v1", {"selected": [{"variable": "age"}]}),
    (EvidenceKind.MODEL_ARTIFACT, "model", "model",
     "cardre.model_artifact.v1", {"model_family": "logistic_regression", "coefficients": {"age": 1.5}}),
    (EvidenceKind.SCORE_SCALING, "scorecard", "scorecard",
     "cardre.score_scaling.v1", {"factor": 20, "offset": 500}),
    (EvidenceKind.WOE_IV_EVIDENCE, "report", "report",
     "cardre.woe_iv_evidence.v1", {"variables": [{"variable": "age"}]}),
    (EvidenceKind.VALIDATION_METRICS, "report", "report",
     "cardre.validation_metrics.v1", {"metrics": {"train": {"auc": 0.75}}}),
    (EvidenceKind.CUTOFF_ANALYSIS, "report", "report",
     "cardre.cutoff_analysis.v1", {"cutoff_tables": {"train": [{"score": 100}]}}),
    (EvidenceKind.RUN_MANIFEST, "run_manifest", "audit",
     "cardre.run_manifest.v1", {"manifest_version": "1", "run_id": "r1", "steps": []}),
    (EvidenceKind.COMPARISON_ARTIFACT, "branch_comparison", "comparison",
     "cardre.comparison_artifact.v1",
     {"comparison_type": "woe_iv", "baseline_branch_id": "b1", "challenger_branch_id": "b2"}),
]


@pytest.mark.parametrize("kind,artifact_type,role,schema_version,payload", _JSON_KIND_FIXTURES)
def test_json_adapter_match_parse_parity(
    store, tmp_path, kind, artifact_type, role, schema_version, payload,
) -> None:
    """Parity: adapter match+parse == reader match+parse for JSON kinds."""
    art = _write_json_artifact(store, tmp_path, artifact_type, role, schema_version, payload)
    _assert_match_parity(store, kind, [art])
    _assert_parse_parity(store, kind, art)


def test_bin_definition_match_parity_multiple_artifacts(store, tmp_path) -> None:
    """Parity: adapter selects the same artifact from a mixed list as the reader."""
    bin_art = _write_json_artifact(
        store, tmp_path, "definition", "definition", "cardre.bin_definition.v1",
        {"variables": [{"variable": "age", "bins": []}]},
        artifact_id="bin-art",
    )
    sel_art = _write_json_artifact(
        store, tmp_path, "definition", "definition", "cardre.selection_definition.v1",
        {"selected": [{"variable": "age"}]},
        artifact_id="sel-art",
    )
    _assert_match_parity(store, EvidenceKind.BIN_DEFINITION, [bin_art, sel_art])
    _assert_match_parity(store, EvidenceKind.SELECTION_DEFINITION, [bin_art, sel_art])


def test_bin_definition_match_parity_no_schema_version(store, tmp_path) -> None:
    """Parity: artifacts without schema_version match by role/type/media."""
    art = _write_json_artifact(
        store, tmp_path, "definition", "definition", "",
        {"variables": [{"variable": "age", "bins": []}]},
    )
    _assert_match_parity(store, EvidenceKind.BIN_DEFINITION, [art])


# Parquet evidence kinds
def test_woe_table_match_parse_parity(store, tmp_path) -> None:
    """Parity: WOE_TABLE parquet matching + parsing."""
    art = _write_parquet_artifact(
        store, tmp_path, "report", "report", "cardre.woe_table.v1",
        {"variable": ["age", "age"], "bin_id": ["1", "2"], "woe": [0.5, -0.3]},
        artifact_id="woe-test",
    )
    _assert_match_parity(store, EvidenceKind.WOE_TABLE, [art])
    _assert_parse_parity(store, EvidenceKind.WOE_TABLE, art)


def test_iv_table_match_parse_parity(store, tmp_path) -> None:
    """Parity: IV_TABLE parquet matching + parsing (no schema_version)."""
    art = _write_parquet_artifact(
        store, tmp_path, "report", "report", "",
        {"iv": [0.5, 0.3], "variable": ["age", "income"]},
        artifact_id="iv-test",
    )
    _assert_match_parity(store, EvidenceKind.IV_TABLE, [art])
    _assert_parse_parity(store, EvidenceKind.IV_TABLE, art)


def test_scored_dataset_match_parse_parity(store, tmp_path) -> None:
    """Parity: SCORED_DATASET parquet (no schema_version, role-based match)."""
    art = _write_parquet_artifact(
        store, tmp_path, "dataset", "train", "",
        {"score": [100, 200], "id": ["a", "b"]},
        artifact_id="scored-test",
    )
    _assert_match_parity(store, EvidenceKind.SCORED_DATASET, [art])
    _assert_parse_parity(store, EvidenceKind.SCORED_DATASET, art)


# Empty / no-match parity
def test_no_match_parity(store, tmp_path) -> None:
    """Parity: both adapter and reader return [] when no artifact matches."""
    art = _write_json_artifact(
        store, tmp_path, "report", "report", "cardre.cutoff_analysis.v1",
        {"cutoff_tables": {"train": [{"score": 100}]}},
    )
    _assert_match_parity(store, EvidenceKind.BIN_DEFINITION, [art])


# Ambiguous match parity
def test_ambiguous_match_parity(store, tmp_path) -> None:
    """Parity: both adapter and reader return multiple candidates for ambiguous input."""
    art1 = _write_json_artifact(
        store, tmp_path, "definition", "definition", "",
        {"variables": [{"variable": "age", "bins": []}]},
        artifact_id="amb1",
    )
    art2 = _write_json_artifact(
        store, tmp_path, "definition", "definition", "",
        {"variables": [{"variable": "income", "bins": []}]},
        artifact_id="amb2",
    )
    _assert_match_parity(store, EvidenceKind.BIN_DEFINITION, [art1, art2])
