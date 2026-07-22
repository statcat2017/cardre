"""Integration test: LogisticRegressionNode.run() — production ExecutionContext path.

Exercises the node through the legacy ``ExecutionContext`` path that the
production ``PlanExecutor`` still uses.  This test must be kept until the
production runner is wired to ``NodeContext`` (Batch 05).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import polars as pl

from cardre._evidence.schemas import SCHEMA_MODELLING_METADATA
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec
from cardre.execution.context import ExecutionContext
from cardre.nodes.build.models import LogisticRegressionNode
from cardre.store.artifact_repo import ArtifactRepository


def _seed_project_and_plan(store) -> tuple[str, str]:
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


def _register_artifact(store, artifact_type, role, path, logical_hash, metadata=None):
    from cardre.domain.artifacts import ArtifactRef, physical_hash
    phys = physical_hash(path)
    # Convert the path to a relative string (as the store expects)
    from cardre.domain.artifacts import relative_path
    rel = relative_path(path, store.root)
    art = ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type=artifact_type,
        role=role,
        path=rel,
        physical_hash=phys,
        logical_hash=logical_hash,
        media_type="application/json",
        metadata=metadata or {},
    )
    repo = ArtifactRepository(store)
    repo.register(art)
    return art


def _write_training_csv(root: Path) -> Path:
    """Write a minimal CSV with WOE-transformed columns and a binary target."""
    df = pl.DataFrame({
        "age_woe": [0.5, -0.3, 0.1, -0.7, 0.2],
        "income_woe": [0.8, -0.2, 0.3, -0.5, 0.4],
        "target_bad": [0, 1, 0, 1, 0],
    })
    dest = root / "datasets" / "train.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(dest)
    return dest


def test_logistic_regression_known_input_legacy_execution_context(store: Path) -> None:
    """Production path: LogisticRegressionNode receives ``ExecutionContext``
    and returns ``NodeOutput``.  The legacy dispatch in ``models.py`` routes
    this to ``_run_execution_context()``."""
    from cardre.domain.artifacts import json_logical_hash

    project_id, pv_id = _seed_project_and_plan(store)

    train_csv = _write_training_csv(store.root)

    # Register modelling-metadata artifact
    meta_payload = {
        "schema_version": SCHEMA_MODELLING_METADATA,
        "target_column": "target_bad",
        "good_values": [0],
        "bad_values": [1],
        "indeterminate_values": [],
        "all_known": [0, 1],
        "reject_inference_position": "not_applied",
    }
    meta_path = store.root / "artifacts" / "modelling_metadata.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta_payload))
    meta_art = _register_artifact(
        store, "definition", "definition", meta_path,
        json_logical_hash(meta_payload),
        metadata={"schema_version": SCHEMA_MODELLING_METADATA},
    )

    # Register train dataset artifact
    train_art = _register_artifact(
        store, "dataset", "train", train_csv,
        "known-train-hash",
        metadata={"schema_version": ""},
    )

    # Build ExecutionContext
    spec = StepSpec(
        step_id="lr-step",
        node_type="cardre.logistic_regression",
        node_version="1",
        category="fit",
        params={"C": 1.0, "max_iter": 1000, "random_seed": 42, "solver": "lbfgs", "method": "standard_logit"},
        params_hash="",
        parent_step_ids=[],
    )

    ctx = ExecutionContext(
        store=store,
        run_id=str(uuid.uuid4()),
        plan_version_id=pv_id,
        step_spec=spec,
        parent_run_steps=[],
        input_artifacts=[train_art, meta_art],
        validated_params={
            "C": 1.0, "max_iter": 1000, "random_seed": 42,
            "solver": "lbfgs", "method": "standard_logit",
        },
        runtime_metadata={},
    )

    node = LogisticRegressionNode()
    result = node.run(ctx)

    # Assert output shape
    from cardre.execution.context import NodeOutput
    assert isinstance(result, NodeOutput), f"Expected NodeOutput, got {type(result)}"
    assert len(result.artifacts) == 1, "Expected one model artifact"
    model_art = result.artifacts[0]
    assert model_art.role == "model"
    assert model_art.artifact_type == "model"

    # Verify the payload was written to disk
    payload_path = store.artifact_path(model_art)
    assert payload_path.exists()
    model = json.loads(payload_path.read_text())

    assert model["schema_version"] == "cardre.model_artifact.v1"
    assert model["model_family"] == "logistic_regression"
    assert len(model["feature_contract"]["features"]) > 0
    assert "intercept" in model["model_payload"]
    assert "coefficients" in model["model_payload"]
    assert model["training"]["converged"] is True
