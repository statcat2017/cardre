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
from cardre.artifacts import write_json_artifact, write_parquet_artifact
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


@pytest.mark.parametrize(
    "writer,kwargs",
    [
        (
            write_json_artifact,
            {
                "artifact_type": "definition",
                "role": "definition",
                "payload": {"schema_version": "cardre.test.v1", "value": 1},
                "metadata": {"schema_version": "cardre.test.v1"},
            },
        ),
        (
            write_parquet_artifact,
            {
                "artifact_type": "dataset",
                "role": "train",
                "frame": None,
                "metadata": {"schema_version": "cardre.test.v1"},
            },
        ),
    ],
)
def test_artifact_helpers_deduplicate_physical_hash(store, writer, kwargs):
    """Duplicate content should reuse the persisted artifact ref."""
    import polars as pl

    first_kwargs = dict(kwargs)
    first_kwargs["stem"] = "first"
    if writer is write_parquet_artifact:
        first_kwargs["frame"] = pl.DataFrame({"value": [1, 2, 3]})
    first = writer(store, **first_kwargs)

    second_kwargs = dict(first_kwargs)
    second_kwargs["stem"] = "second"
    second = writer(store, **second_kwargs)

    assert first.artifact_id == second.artifact_id
    assert first.path == second.path
    assert store.get_artifact(first.artifact_id) is not None
    count = store.execute(
        "SELECT COUNT(*) FROM artifacts WHERE physical_hash = ?",
        (first.physical_hash,),
    ).fetchone()[0]
    assert count == 1


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


# ---------------------------------------------------------------------------
# Focused adapter edge-case tests (not parity — direct adapter behavior)
# ---------------------------------------------------------------------------

def test_schema_version_takes_priority_over_role_type_media(store, tmp_path) -> None:
    """When schema_version matches, it takes priority even if role/type differ."""
    art = _write_json_artifact(
        store, tmp_path, "wrong_type", "wrong_role", "cardre.bin_definition.v1",
        {"variables": [{"variable": "age", "bins": []}]},
    )
    adapter = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = adapter.match([art], store)
    assert len(result) == 1
    assert result[0].artifact_id == art.artifact_id


def test_schema_version_mismatch_falls_through_to_role_type_media(store, tmp_path) -> None:
    """When schema_version doesn't match, fall through to role/type/media matching."""
    art = _write_json_artifact(
        store, tmp_path, "definition", "definition", "wrong.schema.v1",
        {"variables": [{"variable": "age", "bins": []}]},
    )
    adapter = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = adapter.match([art], store)
    assert len(result) == 1
    assert result[0].artifact_id == art.artifact_id


def test_single_candidate_fails_payload_check_returns_empty(store, tmp_path) -> None:
    """Single candidate by role/type/media that fails payload check → []."""
    art = _write_json_artifact(
        store, tmp_path, "definition", "definition", "",
        {"wrong_key": "wrong_value"},
    )
    adapter = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = adapter.match([art], store)
    assert result == []


def test_multiple_candidates_skip_payload_check(store, tmp_path) -> None:
    """Multiple candidates by role/type/media → payload check skipped → return all."""
    art1 = _write_json_artifact(
        store, tmp_path, "definition", "definition", "",
        {"variables": [{"variable": "age", "bins": []}]},
        artifact_id="cand1",
    )
    art2 = _write_json_artifact(
        store, tmp_path, "definition", "definition", "",
        {"wrong_key": "wrong"},
        artifact_id="cand2",
    )
    adapter = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = adapter.match([art1, art2], store)
    assert len(result) == 2


def test_exclude_key_filters_artifact(store, tmp_path) -> None:
    """BIN_DEFINITION profile has exclude_key='selected'; artifacts with that
    metadata key are excluded from role/type/media matching."""
    aid = str(uuid.uuid4())
    art_path = tmp_path / f"{aid}.json"
    art_path.write_text(json.dumps({"variables": [{"variable": "age", "bins": []}]}))
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, "definition", "definition", str(art_path), "ph", "lh", "application/json", "", json.dumps({"schema_version": "", "selected": True})),
    )
    art = store.get_artifact(aid)
    adapter = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = adapter.match([art], store)
    assert result == []


def test_woe_table_no_schema_wrong_columns_returns_empty(store, tmp_path) -> None:
    """WOE_TABLE without schema_version and wrong columns: single candidate
    fails payload check (required_columns) → returns empty."""
    import polars as pl
    aid = "woe-no-schema-wrong-cols"
    art_path = tmp_path / f"{aid}.parquet"
    pl.DataFrame({"wrong_col": [1, 2]}).write_parquet(art_path)
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, "report", "report", str(art_path), "ph", "lh", "application/vnd.apache.parquet", "", json.dumps({})),
    )
    art = store.get_artifact(aid)
    adapter = get_adapter(EvidenceKind.WOE_TABLE)
    result = adapter.match([art], store)
    assert result == []


def test_parse_missing_file_raises(store, tmp_path) -> None:
    """parse() on a non-existent path raises FileNotFoundError (the reader's
    _parse wrapper checks path existence and raises EvidenceParseError; the
    adapter's parse() delegates to read_json_payload which raises directly)."""
    from cardre.domain.artifacts import ArtifactRef as ARef

    fake_art = ARef(
        artifact_id="fake", artifact_type="definition", role="definition",
        path="/nonexistent/path.json", physical_hash="x", logical_hash="y",
        media_type="application/json",
    )
    adapter = get_adapter(EvidenceKind.BIN_DEFINITION)
    with pytest.raises(FileNotFoundError):
        adapter.parse(Path("/nonexistent/path.json"), fake_art, store)


def test_parse_invalid_json_raises(store, tmp_path) -> None:
    """parse() on invalid JSON should raise."""
    aid = "invalid-json"
    art_path = tmp_path / f"{aid}.json"
    art_path.write_text("not valid json {{{")
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, "definition", "definition", str(art_path), "ph", "lh", "application/json", "", json.dumps({"schema_version": "cardre.bin_definition.v1"})),
    )
    art = store.get_artifact(aid)
    adapter = get_adapter(EvidenceKind.BIN_DEFINITION)
    with pytest.raises(json.JSONDecodeError):
        adapter.parse(art_path, art, store)


def test_iv_table_empty_schema_skips_schema_phase(store, tmp_path) -> None:
    """IV_TABLE has empty schema_version; matching skips to role/type/media."""
    import polars as pl
    aid = "iv-empty-schema"
    art_path = tmp_path / f"{aid}.parquet"
    pl.DataFrame({"iv": [0.5], "variable": ["age"]}).write_parquet(art_path)
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, "report", "report", str(art_path), "ph", "lh", "application/vnd.apache.parquet", "", json.dumps({})),
    )
    art = store.get_artifact(aid)
    adapter = get_adapter(EvidenceKind.IV_TABLE)
    result = adapter.match([art], store)
    assert len(result) == 1


def test_scored_dataset_role_based_match(store, tmp_path) -> None:
    """SCORED_DATASET matches by role (train/test/oot) + type + media."""
    import polars as pl
    aid = "scored-train-edge"
    art_path = tmp_path / f"{aid}.parquet"
    pl.DataFrame({"score": [100], "id": ["a"]}).write_parquet(art_path)
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, "dataset", "train", str(art_path), "ph", "lh", "application/vnd.apache.parquet", "", json.dumps({})),
    )
    art = store.get_artifact(aid)
    adapter = get_adapter(EvidenceKind.SCORED_DATASET)
    result = adapter.match([art], store)
    assert len(result) == 1
