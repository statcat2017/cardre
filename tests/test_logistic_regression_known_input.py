"""Integration test: LogisticRegressionNode.run() with known fixtures.

Exercises the actual node code path (inputs collection, sklearn fit,
helper functions) against tiny synthetic inputs so we can assert on exact
model artifact output shape: features, source_variables, coefficients,
intercept, class_mapping, probability_column_index, training params, and
convergence metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.input_collection import StepInputCollection
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA
from cardre.domain.step import StepSpec
from cardre.nodes._params import NodeParams
from cardre.nodes.build.models import LogisticRegressionNode
from cardre.nodes.contracts import NodeContext, RuntimeMeta


def _stage_and_register(
    uow_factory,
    project_id: str,
    store: FsArtifactStore,
    *,
    artifact_id: str,
    artifact_type: str,
    role: str,
    media_type: str,
    staged,
    schema_version: str | None = None,
) -> ArtifactRef:
    """Publish a staged artifact and register it in the project store."""
    path = store.publish(staged)
    metadata = {"schema_version": schema_version} if schema_version else {}
    art = ArtifactRef(
        artifact_id=artifact_id, artifact_type=artifact_type, role=role,
        path=str(path), physical_hash=staged.physical_hash,
        logical_hash=staged.logical_hash, media_type=media_type,
        metadata=metadata,
    )
    with uow_factory.for_project(project_id) as uow:
        uow.artifacts.register(art)
        return uow.artifacts.get(artifact_id)


class _TestStagedArtifactWriter:
    """StagedArtifactWriter that stages and publishes via FsArtifactStore."""

    def __init__(self, store: FsArtifactStore) -> None:
        self._store = store

    def stage_json(self, role, kind, payload, metadata=None):
        staged = self._store.stage_json(role, kind, payload, metadata)
        return self._store.publish(staged)

    def stage_table(self, role, kind, frame, metadata=None):
        staged = self._store.stage_table(role, kind, frame, metadata)
        return self._store.publish(staged)

    def stage_bytes(self, role, kind, data, media_type, logical_hash, metadata=None):
        staged = self._store.stage_bytes(role, kind, data, media_type, logical_hash, metadata)
        return self._store.publish(staged)

    def publish(self, staged) -> Path:
        return self._store.resolve_path(staged)


class _WriterWrapper:
    """Adapts _TestStagedArtifactWriter to the StagedArtifactWriter protocol."""

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
        "schema_version": SCHEMA_MODELLING_METADATA,
        "target_column": "default_flag",
        "good_values": ["good"],
        "bad_values": ["bad"],
        "indeterminate_values": [],
    }


def test_logistic_regression_model_artifact_shape(
    provisioned_project,
    train_parquet: Path,
    modelling_metadata_payload: dict,
) -> None:
    """Run LogisticRegressionNode.run() with known fixtures and assert model artifact shape."""
    project_id, uow_factory, registry, root = provisioned_project
    store = FsArtifactStore(root)

    # --- Write modelling metadata artifact ---
    meta_staged = store.stage_json("definition", SCHEMA_MODELLING_METADATA, modelling_metadata_payload)
    meta_art = _stage_and_register(
        uow_factory, project_id, store,
        artifact_id="meta-art-1", artifact_type="modelling_metadata", role="definition",
        media_type="application/json", staged=meta_staged,
        schema_version=SCHEMA_MODELLING_METADATA,
    )

    # --- Write train artifact (parquet) ---
    train_staged = store.stage_bytes(
        "train", "cardre.train.v1", train_parquet.read_bytes(),
        "application/vnd.apache.parquet", "logical-hash",
    )
    train_art = _stage_and_register(
        uow_factory, project_id, store,
        artifact_id="train-art-1", artifact_type="dataset", role="train",
        media_type="application/vnd.apache.parquet", staged=train_staged,
    )

    assert meta_art is not None
    assert train_art is not None

    # --- Build NodeContext ---
    step_spec = StepSpec(
        step_id="lr-1",
        node_type="cardre.logistic_regression",
        node_version="1",
        category="fit",
        params=NodeParams({
            "solver": "lbfgs",
            "C": 1.0,
            "max_iter": 1000,
            "random_seed": 42,
            "fail_on_non_convergence": True,
        }),
        params_hash="dummy",
        parent_step_ids=[],
        canonical_step_id="lr-1",
    )

    with uow_factory.for_project(project_id) as uow:
        evidence_reader = EvidenceReader(
            artifact_reader=store,
            artifact_repo=uow.artifacts,
            run_step_repo=uow.run_steps,
        )

        input_collection = StepInputCollection(
            reader=evidence_reader,
            input_artifacts=[train_art, meta_art],
        )

        output_publisher = StagingOutputPublisher(writer=_WriterWrapper(_TestStagedArtifactWriter(store)))

        node_context = NodeContext(
            run_id="run-1",
            plan_version_id="pv-1",
            step_spec=step_spec,
            inputs=input_collection,
            outputs=output_publisher,
            params=NodeParams({
                "solver": "lbfgs",
                "C": 1.0,
                "max_iter": 1000,
                "random_seed": 42,
                "fail_on_non_convergence": True,
            }),
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
        model_path = store.resolve_path(staged)
        raw = json.loads(model_path.read_bytes())

    # --- Verify model artifact shape ---
    assert raw["schema_version"] == "cardre.model_artifact.v1"
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
