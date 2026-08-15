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

from cardre._evidence.schemas import SCHEMA_MODELLING_METADATA
from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.execution.input_collection import StepInputCollection
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.step import StepSpec
from cardre.nodes.build.models import LogisticRegressionNode
from cardre.nodes.contracts import NodeContext, RuntimeMeta


@pytest.fixture
def provisioned(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("LR Test")
        uow.commit()
    registry.register(project_id, root)
    return project_id, uow_factory, root


@pytest.fixture
def train_parquet(tmp_path: Path) -> Path:
    """Write a tiny training parquet with WOE columns and a binary target."""
    df = pl.DataFrame({
        "age_woe": [0.5, -0.3, 0.1, -0.2, 0.4],
        "income_woe": [-0.1, 0.2, -0.4, 0.3, -0.2],
        "default_flag": ["good", "bad", "good", "bad", "good"],
    })
    path = tmp_path / "train.parquet"
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
    provisioned,
    tmp_path: Path,
    train_parquet: Path,
    modelling_metadata_payload: dict,
) -> None:
    """Run LogisticRegressionNode.run() with known fixtures and assert model artifact shape."""
    project_id, uow_factory, root = provisioned
    artifact_store = FsArtifactStore(root)

    # --- Write modelling metadata artifact ---
    meta_path = tmp_path / "modelling_metadata.json"
    meta_path.write_text(json.dumps(modelling_metadata_payload))
    meta_staged = artifact_store.stage_json(
        role="definition", kind=EvidenceKind.MODELLING_METADATA.value,
        payload=modelling_metadata_payload,
        metadata={"schema_version": SCHEMA_MODELLING_METADATA},
    )
    meta_path_pub = artifact_store.publish(meta_staged)
    meta_art = ArtifactRef(
        artifact_id=meta_staged.provisional_artifact_id,
        artifact_type=meta_staged.artifact_type,
        role=meta_staged.role,
        path=str(meta_path_pub),
        physical_hash=meta_staged.physical_hash,
        logical_hash=meta_staged.logical_hash,
        media_type=meta_staged.media_type,
        metadata=meta_staged.metadata,
    )

    # --- Write train artifact (parquet) ---
    train_staged = artifact_store.stage_table(
        role="train", kind=SCHEMA_MODELLING_METADATA,
        frame=pl.read_parquet(train_parquet),
    )
    train_path_pub = artifact_store.publish(train_staged)
    train_art = ArtifactRef(
        artifact_id=train_staged.provisional_artifact_id,
        artifact_type=train_staged.artifact_type,
        role=train_staged.role,
        path=str(train_path_pub),
        physical_hash=train_staged.physical_hash,
        logical_hash=train_staged.logical_hash,
        media_type=train_staged.media_type,
        metadata=train_staged.metadata,
    )

    with uow_factory.for_project(project_id) as uow:
        uow.artifacts.register(meta_art)
        uow.artifacts.register(train_art)
        uow.commit()

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

    with uow_factory.read_only(project_id) as uow:
        evidence_reader = EvidenceReader(artifact_store, uow.artifacts, uow.run_steps)
        input_collection = StepInputCollection(
            reader=evidence_reader,
            input_artifacts=[train_art, meta_art],
        )
        output_publisher = StagingOutputPublisher(artifact_store)

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

    # Read back the written model artifact payload
    raw = json.loads((root / staged.staging_path).read_bytes())

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
