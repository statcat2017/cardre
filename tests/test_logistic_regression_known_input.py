"""Integration test: LogisticRegressionNode.run() with known fixtures.

Exercises the actual node code path (inputs collection, sklearn fit,
helper functions) against tiny synthetic inputs so we can assert on exact
model artifact output shape: features, source_variables, coefficients,
intercept, class_mapping, probability_column_index, training params, and
convergence metadata.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import polars as pl
import pytest

from cardre._evidence.schemas import SCHEMA_MODELLING_METADATA
from cardre.adapters.evidence.reader import EvidenceReader
from cardre.application.execution.input_collection import StepInputCollection
from cardre.application.ports.unit_of_work import ArtifactRepoPort, RunStepRepoPort
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
from cardre.nodes.build.models import LogisticRegressionNode
from cardre.nodes.contracts import NodeContext, RuntimeMeta
from cardre.store.artifact_repo import ArtifactRepository


def _seed_project_and_plan(store) -> tuple[str, str]:
    """Create a minimal project with one plan version. Returns (project_id, pv_id)."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "LR Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )
    return project_id, pv_id


def _register_artifact(
    store,
    artifact_id: str,
    artifact_type: str,
    role: str,
    path: str,
    media_type: str = "application/json",
    schema_version: str | None = None,
) -> None:
    metadata = {}
    if schema_version:
        metadata["schema_version"] = schema_version
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
        "media_type, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, artifact_type, role, path, "phys_hash", "log_hash",
         media_type, utc_now_iso(), json.dumps(metadata)),
    )


class _TestArtifactReader:
    """Minimal ArtifactReader backed by a ProjectStore for tests."""

    def __init__(self, store):
        self._store = store

    def read_bytes(self, artifact: ArtifactRef) -> bytes:
        return self.resolve_path(artifact).read_bytes()

    def resolve_path(self, artifact: ArtifactRef) -> Path:
        return self._store.artifact_path(artifact)


class _TestStagedArtifactWriter:
    """Minimal StagedArtifactWriter that delegates to write_json_artifact.

    Collects written artifacts so the test can inspect them.
    """

    def __init__(self, store):
        self._store = store
        self._published: list[ArtifactRef] = []

    def stage_json(self, role: str, kind: str, payload: dict,
                   metadata: dict | None = None) -> ArtifactRef:
        from cardre.artifacts import write_json_artifact
        art = write_json_artifact(
            self._store,
            artifact_type=role,
            role=role,
            stem=f"test-{uuid.uuid4().hex[:8]}",
            payload=payload,
            metadata=metadata,
        )
        self._published.append(art)
        return art

    def stage_table(self, role: str, kind: str, frame: object,
                    metadata: dict | None = None) -> ArtifactRef:
        raise NotImplementedError("stage_table not needed in this test")

    def stage_bytes(self, role: str, kind: str, data: bytes,
                    media_type: str, logical_hash: str,
                    metadata: dict | None = None) -> ArtifactRef:
        raise NotImplementedError("stage_bytes not needed in this test")

    def publish(self, staged: ArtifactRef) -> Path:
        return self._store.artifact_path(staged)


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def train_parquet(fixture_dir: Path) -> Path:
    """Write a tiny training parquet with WOE columns and a binary target."""
    df = pl.DataFrame({
        "age_woe": [0.5, -0.3, 0.1, -0.2, 0.4],
        "income_woe": [-0.1, 0.2, -0.4, 0.3, -0.2],
        "default_flag": ["good", "bad", "good", "bad", "good"],
    })
    path = fixture_dir / "train.parquet"
    df.write_parquet(path)
    return path


@pytest.fixture
def modelling_metadata_payload() -> dict:
    """A minimal modelling-metadata JSON payload."""
    return {
        "target_column": "default_flag",
        "good_values": ["good"],
        "bad_values": ["bad"],
        "indeterminate_values": [],
    }


def test_logistic_regression_model_artifact_shape(
    store,
    fixture_dir: Path,
    train_parquet: Path,
    modelling_metadata_payload: dict,
) -> None:
    """Run LogisticRegressionNode.run() with known fixtures and assert model artifact shape."""
    _seed_project_and_plan(store)

    # --- Write modelling metadata artifact ---
    meta_path = fixture_dir / "modelling_metadata.json"
    meta_path.write_text(json.dumps(modelling_metadata_payload))
    meta_art_id = "meta-art-1"
    _register_artifact(
        store, meta_art_id, "definition", "definition",
        str(meta_path), schema_version=SCHEMA_MODELLING_METADATA,
    )

    # --- Write train artifact (parquet) ---
    train_art_id = "train-art-1"
    _register_artifact(
        store, train_art_id, "dataset", "train",
        str(train_parquet), media_type="application/vnd.apache.parquet",
    )

    # --- Retrieve ArtifactRefs from the store ---
    repo = ArtifactRepository(store)
    meta_art = repo.get(meta_art_id)
    assert meta_art is not None
    train_art = repo.get(train_art_id)
    assert train_art is not None

    # --- Build NodeContext ---
    step_spec = StepSpec(
        step_id="lr-1",
        node_type="cardre.logistic_regression",
        node_version="1",
        category="fit",
        params={
            "solver": "lbfgs",
            "C": 1.0,
            "max_iter": 1000,
            "random_seed": 42,
            "fail_on_non_convergence": True,
        },
        params_hash="dummy",
        parent_step_ids=[],
    )

    artifact_reader = _TestArtifactReader(store)
    artifact_repo: ArtifactRepoPort = repo
    from cardre.store.run_step_repo import RunStepRepository
    run_step_repo: RunStepRepoPort = RunStepRepository(store)

    evidence_reader = EvidenceReader(
        artifact_reader=artifact_reader,
        artifact_repo=artifact_repo,
        run_step_repo=run_step_repo,
    )

    input_collection = StepInputCollection(
        reader=evidence_reader,
        input_artifacts=[train_art, meta_art],
    )

    staged_writer = _TestStagedArtifactWriter(store)

    # Wrap the staging writer to match the OutputPublisher protocol.
    # We need to implement it in the test or use StagingOutputPublisher.
    # For simplicity, we build the OutputPublisher inline.
    from cardre.application.execution.output_publisher import StagingOutputPublisher

    # Re-wrap staged_writer as a StagedArtifactWriter
    class _WriterWrapper:
        def __init__(self, sw):
            self._sw = sw
        def stage_json(self, role, kind, payload, metadata=None):
            return self._sw.stage_json(role, kind, payload, metadata)
        def stage_table(self, role, kind, frame, metadata=None):
            return self._sw.stage_table(role, kind, frame, metadata)
        def stage_bytes(self, role, kind, data, media_type, logical_hash, metadata=None):
            return self._sw.stage_bytes(role, kind, data, media_type, logical_hash, metadata)
        def publish(self, staged):
            return self._sw.publish(staged)

    output_publisher = StagingOutputPublisher(writer=_WriterWrapper(staged_writer))

    node_context = NodeContext(
        run_id="run-1",
        plan_version_id="pv-1",
        step_spec=step_spec,
        inputs=input_collection,
        outputs=output_publisher,
        params={
            "solver": "lbfgs",
            "C": 1.0,
            "max_iter": 1000,
            "random_seed": 42,
            "fail_on_non_convergence": True,
        },
        runtime=RuntimeMeta(
            run_id="run-1",
            plan_version_id="pv-1",
            step_id="lr-1",
            node_type="cardre.logistic_regression",
        ),
    )

    # --- Run the node ---
    node = LogisticRegressionNode()
    result = node.run(node_context)

    # --- Assert on NodeResult ---
    assert len(result.staged_artifacts) == 1
    staged = result.staged_artifacts[0]

    # Read back the written model artifact payload via the store
    model_path = store.artifact_path(staged)
    raw = json.loads(model_path.read_bytes())

    # --- Verify model artifact shape ---
    assert raw["schema_version"] == "cardre.model_artifact.v1"
    assert raw["model_family"] == "logistic_regression"
    assert raw["target_column"] == "default_flag"

    # Features: the two WOE columns (in feature_contract)
    assert raw["feature_contract"]["features"] == ["age_woe", "income_woe"]

    # Source variables: derived from WOE column names (no selection definition)
    assert raw["source_variables"] == ["age", "income"]

    # Intercept and coefficients: in model_payload, rounded to 6 decimal places
    assert isinstance(raw["model_payload"]["intercept"], float)
    assert len(str(raw["model_payload"]["intercept"]).split(".")[1]) <= 6
    assert set(raw["model_payload"]["coefficients"].keys()) == {"age_woe", "income_woe"}
    for coef in raw["model_payload"]["coefficients"].values():
        assert isinstance(coef, float)
        assert len(str(coef).split(".")[1]) <= 6

    # Class mapping: good/bad labels
    assert raw["class_mapping"] == {"good": "good", "bad": "bad"}
    assert raw["bad_class_label"] == "bad"
    assert raw["target_event_value"] == "bad"

    # Probability column index: should be 1 (bad class is second in sklearn classes_)
    assert raw["probability_column_index"] == 1

    # Feature contract
    assert raw["feature_contract"]["features"] == ["age_woe", "income_woe"]
    assert raw["feature_contract"]["transformation_strategy"] == "woe"
    assert raw["feature_contract"]["missing_policy"] == "error"
    assert raw["feature_contract"]["unknown_category_policy"] == "error"
    assert "order_hash" in raw["feature_contract"]
    assert raw["feature_order_hash"] == raw["feature_contract"]["order_hash"]

    # Training block
    assert raw["training"]["row_count"] == 5
    assert raw["training"]["converged"] is True
    assert raw["training"]["iterations"] >= 1
    assert raw["training"]["params"]["C"] == 1.0
    assert raw["training"]["params"]["solver"] == "lbfgs"
    assert raw["training"]["params"]["max_iter"] == 1000
    assert raw["training"]["params"]["random_state"] == 42
    assert raw["training"]["params"]["penalty"] == "l2"

    # Warnings: should be empty for a converged model
    assert raw["warnings"] == []

    # Metrics
    assert result.metrics["feature_count"] == 2
    assert bool(result.metrics["converged"]) is True
