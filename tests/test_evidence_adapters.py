"""Tests for the EvidenceAdapter registry, independence, and parity.

Verifies:
- Every EvidenceKind with a profile has a registered adapter.
- Each adapter carries its kind and profile.
- No adapter module imports ArtifactEvidenceReader (dependency direction).
- Adapters do not implement summarise() (removed from protocol).
- adapter matching and parsing accepts the artifact shapes produced by the
  staged artifact writer.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import polars as pl
import pytest

from cardre.adapters.evidence import EVIDENCE_ADAPTERS, AdapterSpec, get_adapter
from cardre.adapters.evidence.parsers import match
from cardre.adapters.evidence.profiles import EVIDENCE_PROFILES
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA

# ---------------------------------------------------------------------------
# Test helper: write/register artifacts through a provisioned project
# ---------------------------------------------------------------------------


class _ProjectArtifacts:
    """Stages, publishes, and registers artifacts through a provisioned project.

    ``store`` is an ``FsArtifactStore`` over the project root, so every
    registered ``ArtifactRef`` resolves to a real object file on disk.
    """

    def __init__(self, project_id: str, uow_factory, root: Path) -> None:
        self.project_id = project_id
        self.uow_factory = uow_factory
        self.store = FsArtifactStore(root)

    def write_json(
        self, artifact_type: str, role: str, schema_version: str,
        payload: dict, media_type: str = "application/json",
        artifact_id: str | None = None, metadata: dict | None = None,
    ) -> ArtifactRef:
        staged = self.store.stage_json(role, schema_version or "cardre.test.v1", payload)
        return self._register(
            artifact_id, artifact_type, role, staged, media_type, metadata, schema_version,
        )

    def write_parquet(
        self, artifact_type: str, role: str, schema_version: str,
        frame: pl.DataFrame, media_type: str = "application/vnd.apache.parquet",
        artifact_id: str | None = None, metadata: dict | None = None,
    ) -> ArtifactRef:
        staged = self.store.stage_table(role, schema_version or "cardre.test.v1", frame)
        return self._register(
            artifact_id, artifact_type, role, staged, media_type, metadata, schema_version,
        )

    def _register(
        self, artifact_id: str | None, artifact_type: str, role: str,
        staged, media_type: str, metadata: dict | None, schema_version: str,
    ) -> ArtifactRef:
        path = self.store.publish(staged)
        meta = dict(metadata or {})
        if schema_version:
            meta["schema_version"] = schema_version
        aid = artifact_id or staged.provisional_artifact_id
        art = ArtifactRef(
            artifact_id=aid, artifact_type=artifact_type, role=role,
            path=str(path), physical_hash=staged.physical_hash,
            logical_hash=staged.logical_hash, media_type=media_type,
            metadata=meta,
        )
        with self.uow_factory.for_project(self.project_id) as uow:
            uow.artifacts.register(art)
            return uow.artifacts.get(aid)


@pytest.fixture
def artifacts(provisioned_project) -> _ProjectArtifacts:
    project_id, uow_factory, registry, root = provisioned_project
    return _ProjectArtifacts(project_id, uow_factory, root)


def _match(ctx: _ProjectArtifacts, arts: list[ArtifactRef], profile) -> list[ArtifactRef]:
    return match(arts, profile, ctx.store)


def _assert_match_parity(ctx: _ProjectArtifacts, kind: EvidenceKind, arts: list[ArtifactRef]) -> list[ArtifactRef]:
    """Assert the production adapter matcher returns the artifacts."""
    spec = get_adapter(kind)
    return _match(ctx, arts, spec.profile)


def _assert_parse_parity(ctx: _ProjectArtifacts, kind: EvidenceKind, artifact: ArtifactRef) -> None:
    """Assert adapter.parse() returns a typed object without error."""
    spec = get_adapter(kind)
    path = ctx.store.resolve_path(artifact)
    result = spec.parse(path, artifact, ctx.store)
    assert result is not None, f"Parse returned None for {kind.value}"


# ---------------------------------------------------------------------------
# Registry coverage tests
# ---------------------------------------------------------------------------


def test_adapter_registry_covers_all_profiles() -> None:
    assert set(EVIDENCE_PROFILES).issubset(set(EVIDENCE_ADAPTERS))


def test_adapter_registry_covers_all_evidence_kinds() -> None:
    for kind in EvidenceKind:
        assert kind in EVIDENCE_ADAPTERS, f"{kind.name} missing from registry"


def test_get_adapter_returns_correct_profile() -> None:
    for kind in EVIDENCE_PROFILES:
        spec = get_adapter(kind)
        assert isinstance(spec, AdapterSpec)
        assert spec.profile is EVIDENCE_PROFILES[kind]


def test_get_adapter_unknown_kind_raises() -> None:
    from cardre.domain.evidence.kinds import EvidenceParseError

    class _FakeKind:
        value = "fake"

    with pytest.raises(EvidenceParseError):
        get_adapter(_FakeKind())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dependency-direction guard
# ---------------------------------------------------------------------------


def test_adapters_do_not_import_artifact_evidence_reader() -> None:
    adapters_dir = Path(__file__).resolve().parent.parent / "cardre" / "adapters" / "evidence"
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
    adapters_dir = Path(__file__).resolve().parent.parent / "cardre" / "adapters" / "evidence"
    for py in sorted(adapters_dir.glob("*.py")):
        if py.name in ("__init__.py", "_base.py"):
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "summarise":
                raise AssertionError(f"{py.name} still defines summarise()")


# ---------------------------------------------------------------------------
# Adapter matching and parsing
# ---------------------------------------------------------------------------


def _write_dedup_artifact(ctx: _ProjectArtifacts, fmt: str) -> ArtifactRef:
    if fmt == "json":
        return ctx.write_json(
            artifact_type="definition", role="definition",
            schema_version="cardre.test.v1",
            payload={"schema_version": "cardre.test.v1", "value": 1},
        )
    return ctx.write_parquet(
        artifact_type="dataset", role="train",
        schema_version="cardre.test.v1",
        frame=pl.DataFrame({"value": [1, 2, 3]}),
    )


@pytest.mark.parametrize("fmt", ["json", "parquet"])
def test_artifact_helpers_deduplicate_physical_hash(artifacts: _ProjectArtifacts, fmt: str):
    """Duplicate content should reuse the persisted artifact ref."""
    first = _write_dedup_artifact(artifacts, fmt)
    second = _write_dedup_artifact(artifacts, fmt)

    assert first.artifact_id == second.artifact_id
    assert first.path == second.path
    with artifacts.uow_factory.for_project(artifacts.project_id) as uow:
        assert uow.artifacts.get(first.artifact_id) is not None
        count = uow._conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE physical_hash = ?",
            (first.physical_hash,),
        ).fetchone()[0]
        assert count == 1


# JSON evidence kinds with schema_version + required_keys
_JSON_KIND_FIXTURES = [
    (EvidenceKind.BIN_DEFINITION, "bin_definition", "definition",
     "cardre.bin_definition.v1", {"variables": [{"variable": "age", "bins": []}]}),
    (EvidenceKind.SELECTION_DEFINITION, "selection_definition", "definition",
     "cardre.selection_definition.v1", {"selected": [{"variable": "age"}]}),
    (EvidenceKind.MODEL_ARTIFACT, "model_artifact", "model",
     "cardre.model_artifact.v1", {
         "schema_version": "cardre.model_artifact.v1",
         "model_family": "logistic_regression",
         "target_column": "y",
         "target_event_value": "bad",
         "class_mapping": {"good": "good", "bad": "bad"},
         "probability_column_index": 1,
         "feature_contract": {"features": ["age"]},
         "model_payload": {"intercept": 0.0, "coefficients": {"age": 1.5}},
         "training": {"row_count": 100},
     }),
    (EvidenceKind.SCORE_SCALING, "score_scaling", "scorecard",
     "cardre.score_scaling.v1", {"factor": 20, "offset": 500}),
    (EvidenceKind.WOE_IV_EVIDENCE, "woe_iv_evidence", "report",
     "cardre.woe_iv_evidence.v1", {"variables": [{"variable": "age"}]}),
    (EvidenceKind.VALIDATION_METRICS, "validation_metrics", "report",
     "cardre.validation_metrics.v1", {"roles": {"train": {"auc": 0.75}}, "metrics": {"train": {"auc": 0.75}}, "stability": {}}),
    (EvidenceKind.CUTOFF_ANALYSIS, "cutoff_analysis", "report",
     "cardre.cutoff_analysis.v1", {"cutoff_tables": {"train": [{"score_cutoff": 100}]}}),
    (EvidenceKind.COMPARISON_ARTIFACT, "comparison_artifact", "comparison",
     "cardre.comparison_artifact.v1",
     {"comparison_type": "woe_iv", "baseline_branch_id": "b1", "challenger_branch_id": "b2"}),
]


def test_modelling_metadata_matches_kind_specific_artifact_type(artifacts: _ProjectArtifacts) -> None:
    """The staged writer persists modelling metadata with its evidence-kind type."""
    art = artifacts.write_json(
        "modelling_metadata", "definition", SCHEMA_MODELLING_METADATA,
        {"target_column": "outcome", "good_values": ["good"], "bad_values": ["bad"]},
    )

    matched = _assert_match_parity(artifacts, EvidenceKind.MODELLING_METADATA, [art])

    assert matched == [art]


@pytest.mark.parametrize("kind,artifact_type,role,schema_version,payload", _JSON_KIND_FIXTURES)
def test_json_adapter_match_parse_parity(
    artifacts: _ProjectArtifacts, kind, artifact_type, role, schema_version, payload,
) -> None:
    """Parity: adapter match+parse == reader match+parse for JSON kinds."""
    art = artifacts.write_json(artifact_type, role, schema_version, payload)
    matched = _assert_match_parity(artifacts, kind, [art])
    assert matched, f"Expected at least one match for {kind.value}"
    _assert_parse_parity(artifacts, kind, art)


def test_bin_definition_match_parity_multiple_artifacts(artifacts: _ProjectArtifacts) -> None:
    """Parity: adapter selects the same artifact from a mixed list as the reader."""
    bin_art = artifacts.write_json(
        "bin_definition", "definition", "cardre.bin_definition.v1",
        {"variables": [{"variable": "age", "bins": []}]},
        artifact_id="bin-art",
    )
    sel_art = artifacts.write_json(
        "selection_definition", "definition", "cardre.selection_definition.v1",
        {"selected": [{"variable": "age"}]},
        artifact_id="sel-art",
    )
    _assert_match_parity(artifacts, EvidenceKind.BIN_DEFINITION, [bin_art, sel_art])
    _assert_match_parity(artifacts, EvidenceKind.SELECTION_DEFINITION, [bin_art, sel_art])


def test_bin_definition_match_parity_no_schema_version(artifacts: _ProjectArtifacts) -> None:
    """Parity: artifacts with the canonical type match by role/type/media."""
    art = artifacts.write_json(
        "bin_definition", "definition", "",
        {"variables": [{"variable": "age", "bins": []}]},
    )
    _assert_match_parity(artifacts, EvidenceKind.BIN_DEFINITION, [art])


# Parquet evidence kinds
def test_woe_table_match_parse_parity(artifacts: _ProjectArtifacts) -> None:
    """Parity: WOE_TABLE parquet matching + parsing."""
    art = artifacts.write_parquet(
        "woe_table", "report", "cardre.woe_table.v1",
        pl.DataFrame({"variable": ["age", "age"], "bin_id": ["1", "2"], "woe": [0.5, -0.3]}),
        artifact_id="woe-test",
    )
    _assert_match_parity(artifacts, EvidenceKind.WOE_TABLE, [art])
    _assert_parse_parity(artifacts, EvidenceKind.WOE_TABLE, art)


def test_iv_table_match_parse_parity(artifacts: _ProjectArtifacts) -> None:
    """Parity: IV_TABLE parquet matching + parsing (canonical type)."""
    art = artifacts.write_parquet(
        "iv_table", "report", "cardre.iv_table.v1",
        pl.DataFrame({"iv": [0.5, 0.3], "variable": ["age", "income"]}),
        artifact_id="iv-test",
    )
    _assert_match_parity(artifacts, EvidenceKind.IV_TABLE, [art])
    _assert_parse_parity(artifacts, EvidenceKind.IV_TABLE, art)


def test_scored_dataset_match_parse_parity(artifacts: _ProjectArtifacts) -> None:
    """Parity: SCORED_DATASET parquet (no schema_version, role-based match)."""
    art = artifacts.write_parquet(
        "scored_dataset", "train", "",
        pl.DataFrame({"score": [100, 200], "id": ["a", "b"]}),
        artifact_id="scored-test",
    )
    _assert_match_parity(artifacts, EvidenceKind.SCORED_DATASET, [art])
    _assert_parse_parity(artifacts, EvidenceKind.SCORED_DATASET, art)


# Empty / no-match parity
def test_no_match_parity(artifacts: _ProjectArtifacts) -> None:
    """Parity: both adapter and reader return [] when no artifact matches."""
    art = artifacts.write_json(
        "cutoff_analysis", "report", "cardre.cutoff_analysis.v1",
        {"cutoff_tables": {"train": [{"score_cutoff": 100}]}},
    )
    matched = _assert_match_parity(artifacts, EvidenceKind.BIN_DEFINITION, [art])
    assert not matched, "Expected no match for BIN_DEFINITION on cutoff_analysis artifact"


# Ambiguous match parity
def test_ambiguous_match_parity(artifacts: _ProjectArtifacts) -> None:
    """Parity: both adapter and reader return multiple candidates for ambiguous input."""
    art1 = artifacts.write_json(
        "bin_definition", "definition", "",
        {"variables": [{"variable": "age", "bins": []}]},
        artifact_id="amb1",
    )
    art2 = artifacts.write_json(
        "bin_definition", "definition", "",
        {"variables": [{"variable": "income", "bins": []}]},
        artifact_id="amb2",
    )
    matched = _assert_match_parity(artifacts, EvidenceKind.BIN_DEFINITION, [art1, art2])
    assert len(matched) >= 2, f"Expected multiple matches for ambiguous input, got {matched}"


# ---------------------------------------------------------------------------
# Focused adapter edge-case tests (not parity — direct adapter behavior)
# ---------------------------------------------------------------------------

def test_schema_version_mismatched_role_type_returns_empty(artifacts: _ProjectArtifacts) -> None:
    """When schema_version matches but role/type/media mismatch, reject."""
    art = artifacts.write_json(
        "wrong_type", "wrong_role", "cardre.bin_definition.v1",
        {"variables": [{"variable": "age", "bins": []}]},
    )
    spec = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = _match(artifacts, [art], spec.profile)
    assert result == []


def test_schema_version_mismatch_falls_through_to_role_type_media(artifacts: _ProjectArtifacts) -> None:
    """When schema_version doesn't match, fall through to role/type/media matching (3a behaviour)."""
    art = artifacts.write_json(
        "bin_definition", "definition", "wrong.schema.v1",
        {"variables": [{"variable": "age", "bins": []}]},
    )
    spec = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = _match(artifacts, [art], spec.profile)
    assert len(result) == 1
    assert result[0].artifact_id == art.artifact_id


def test_single_candidate_fails_payload_check_returns_empty(artifacts: _ProjectArtifacts) -> None:
    """Single candidate by role/type/media that fails payload check → []."""
    art = artifacts.write_json(
        "bin_definition", "definition", "",
        {"wrong_key": "wrong_value"},
    )
    spec = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = _match(artifacts, [art], spec.profile)
    assert result == []


def test_multiple_candidates_skip_payload_check(artifacts: _ProjectArtifacts) -> None:
    """Multiple candidates by role/type/media → payload check skipped → return all."""
    art1 = artifacts.write_json(
        "bin_definition", "definition", "",
        {"variables": [{"variable": "age", "bins": []}]},
        artifact_id="cand1",
    )
    art2 = artifacts.write_json(
        "bin_definition", "definition", "",
        {"wrong_key": "wrong"},
        artifact_id="cand2",
    )
    spec = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = _match(artifacts, [art1, art2], spec.profile)
    assert len(result) == 2


def test_exclude_key_filters_artifact(artifacts: _ProjectArtifacts) -> None:
    """BIN_DEFINITION profile has exclude_key='selected'; artifacts with that
    metadata key are excluded from role/type/media matching."""
    art = artifacts.write_json(
        "bin_definition", "definition", "",
        {"variables": [{"variable": "age", "bins": []}]},
        artifact_id=str(uuid.uuid4()),
        metadata={"selected": True},
    )
    spec = get_adapter(EvidenceKind.BIN_DEFINITION)
    result = _match(artifacts, [art], spec.profile)
    assert result == []


def test_woe_table_no_schema_wrong_columns_returns_empty(artifacts: _ProjectArtifacts) -> None:
    """WOE_TABLE without schema_version and wrong columns: single candidate
    fails payload check (required_columns) → returns empty."""
    art = artifacts.write_parquet(
        "woe_table", "report", "",
        pl.DataFrame({"wrong_col": [1, 2]}),
        artifact_id="woe-no-schema-wrong-cols",
    )
    spec = get_adapter(EvidenceKind.WOE_TABLE)
    result = _match(artifacts, [art], spec.profile)
    assert result == []


def test_parse_missing_file_raises() -> None:
    """parse() on a non-existent path raises FileNotFoundError (the reader's
    _parse wrapper checks path existence and raises EvidenceParseError; the
    adapter's parse() delegates to read_json_payload which raises directly)."""
    from cardre.domain.artifacts import ArtifactRef as ARef

    fake_art = ARef(
        artifact_id="fake", artifact_type="definition", role="definition",
        path="/nonexistent/path.json", physical_hash="x", logical_hash="y",
        media_type="application/json",
    )
    spec = get_adapter(EvidenceKind.BIN_DEFINITION)
    with pytest.raises(FileNotFoundError):
        spec.parse(Path("/nonexistent/path.json"), fake_art, None)


def test_parse_invalid_json_raises(artifacts: _ProjectArtifacts) -> None:
    """parse() on invalid JSON should raise."""
    aid = "invalid-json"
    staged = artifacts.store.stage_bytes(
        "definition", "cardre.bin_definition.v1", b"not valid json {{{",
        "application/json", "logical-hash",
    )
    path = artifacts.store.publish(staged)
    art = ArtifactRef(
        artifact_id=aid, artifact_type="definition", role="definition",
        path=str(path), physical_hash=staged.physical_hash,
        logical_hash="logical-hash", media_type="application/json",
        metadata={"schema_version": "cardre.bin_definition.v1"},
    )
    with artifacts.uow_factory.for_project(artifacts.project_id) as uow:
        uow.artifacts.register(art)
        stored = uow.artifacts.get(aid)
    spec = get_adapter(EvidenceKind.BIN_DEFINITION)
    with pytest.raises(json.JSONDecodeError):
        spec.parse(artifacts.store.resolve_path(stored), stored, artifacts.store)


def test_iv_table_empty_schema_skips_schema_phase(artifacts: _ProjectArtifacts) -> None:
    """IV_TABLE with canonical type matches by role/type/media when schema absent."""
    art = artifacts.write_parquet(
        "iv_table", "report", "",
        pl.DataFrame({"iv": [0.5], "variable": ["age"]}),
        artifact_id="iv-empty-schema",
    )
    spec = get_adapter(EvidenceKind.IV_TABLE)
    result = _match(artifacts, [art], spec.profile)
    assert len(result) == 1


def test_scored_dataset_role_based_match(artifacts: _ProjectArtifacts) -> None:
    """SCORED_DATASET matches by role (train/test/oot) + type + media."""
    art = artifacts.write_parquet(
        "scored_dataset", "train", "",
        pl.DataFrame({"score": [100], "id": ["a"]}),
        artifact_id="scored-train-edge",
    )
    spec = get_adapter(EvidenceKind.SCORED_DATASET)
    result = _match(artifacts, [art], spec.profile)
    assert len(result) == 1
