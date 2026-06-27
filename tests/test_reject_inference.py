"""Tests for reject inference nodes — population definition, none, augmentation."""

from __future__ import annotations

import json
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    StepSpec,
    json_logical_hash,
)
from cardre.evidence import (
    SCHEMA_MODELLING_METADATA,
    SCHEMA_REJECT_POPULATION_CONFIG,
    SCHEMA_SAMPLE_DEFINITION,
)
from cardre.nodes.reject_inference import (
    DefineRejectPopulationNode,
    RejectInferenceAugmentationNode,
    RejectInferenceNoneNode,
)
from cardre.store import ProjectStore
from tests.helpers import make_store


def _make_modelling_metadata_artifact(
    store: ProjectStore,
    target_column: str = "target",
    good_values: list | None = None,
    bad_values: list | None = None,
) -> Any:
    good_values = good_values or ["good"]
    bad_values = bad_values or ["bad"]
    payload = {
        "schema_version": SCHEMA_MODELLING_METADATA,
        "target_column": target_column,
        "good_values": good_values,
        "bad_values": bad_values,
        "indeterminate_values": [],
    }
    return write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-metadata",
        payload=payload,
        metadata={"schema_version": SCHEMA_MODELLING_METADATA},
    )


def _make_sample_definition_artifact(
    store: ProjectStore,
    sample_domain: str = "ttd",
    rejection_source: str | None = "target_missing",
    rejection_column: str | None = None,
    rejection_values: list[str] | None = None,
) -> Any:
    payload = {
        "schema_version": SCHEMA_SAMPLE_DEFINITION,
        "sample_method": "full_population",
        "sample_domain": sample_domain,
        "rejection_source": rejection_source,
        "rejection_column": rejection_column,
        "rejection_values": rejection_values,
        "total_rows": 0,
        "financed_rows": 0,
        "non_financed_rows": 0,
        "weight_column": None,
        "sample_description": "",
    }
    return write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-sample-def",
        payload=payload,
        metadata={"schema_version": SCHEMA_SAMPLE_DEFINITION},
    )


def _make_input_dataset(
    store: ProjectStore,
    rows: list[dict[str, Any]],
) -> Any:
    df = pl.DataFrame(rows)
    return write_parquet_artifact(
        store, artifact_type="dataset", role="input",
        stem="test-input",
        frame=df,
        metadata={},
    )


def _build_ctx(
    store: ProjectStore,
    node: Any,
    input_artifacts: list,
    params: dict | None = None,
    step_id: str = "test-step",
) -> ExecutionContext:
    params = params or {}
    step_spec = StepSpec(
        step_id=step_id,
        node_type=node.node_type,
        node_version=node.version,
        category=node.category,
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=[],
        branch_label="",
        position=0,
    )
    return ExecutionContext(
        store=store,
        run_id="test-run",
        plan_version_id="test-pv",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=input_artifacts,
        validated_params=params,
        runtime_metadata={},
    )


# ======================================================================
# DefineRejectPopulationNode tests
# ======================================================================


def test_define_reject_population_target_missing() -> None:
    store, _ = make_store()
    dataset = _make_input_dataset(store, [
        {"target": "good", "feat_a": 10},
        {"target": "bad", "feat_a": 20},
        {"target": None, "feat_a": 30},
        {"target": None, "feat_a": 40},
        {"target": "good", "feat_a": 50},
    ])
    meta = _make_modelling_metadata_artifact(store)
    sample_def = _make_sample_definition_artifact(
        store, rejection_source="target_missing",
    )

    node = DefineRejectPopulationNode()
    ctx = _build_ctx(store, node, [dataset, meta, sample_def])
    out = node.run(ctx)

    assert len(out.artifacts) == 2
    config_art = next(a for a in out.artifacts if a.role == "definition")
    ds_art = next(a for a in out.artifacts if a.role == "input")

    config = json.loads(store.artifact_path(config_art).read_text())
    assert config["financed_rows"] == 3
    assert config["non_financed_rows"] == 2
    assert config["total_rows"] == 5

    df = pl.read_parquet(store.artifact_path(ds_art))
    assert df.height == 5  # excluded rows removed
    assert "_ri_financed" in df.columns


def test_define_reject_population_flag_column() -> None:
    store, _ = make_store()
    dataset = _make_input_dataset(store, [
        {"target": "good", "was_rejected": "no"},
        {"target": "bad", "was_rejected": "no"},
        {"target": "good", "was_rejected": "yes"},
        {"target": None, "was_rejected": "yes"},
    ])
    meta = _make_modelling_metadata_artifact(store)
    sample_def = _make_sample_definition_artifact(
        store, rejection_source="flag_column",
        rejection_column="was_rejected",
        rejection_values=["yes"],
    )

    node = DefineRejectPopulationNode()
    ctx = _build_ctx(store, node, [dataset, meta, sample_def])
    out = node.run(ctx)

    config_art = next(a for a in out.artifacts if a.role == "definition")
    config = json.loads(store.artifact_path(config_art).read_text())
    assert config["financed_rows"] == 2
    assert config["non_financed_rows"] == 2


def test_define_reject_population_exclusion_categories() -> None:
    store, _ = make_store()
    dataset = _make_input_dataset(store, [
        {"target": "good", "reject_reason": None},
        {"target": "bad", "reject_reason": None},
        {"target": "good", "reject_reason": "fraud"},
        {"target": None, "reject_reason": "KYC"},
    ])
    meta = _make_modelling_metadata_artifact(store)
    sample_def = _make_sample_definition_artifact(
        store, rejection_source="target_missing",
    )

    node = DefineRejectPopulationNode()
    ctx = _build_ctx(store, node, [dataset, meta, sample_def],
                     params={
                         "exclusion_categories": {
                             "fraud": {"column": "reject_reason", "values": ["fraud"]},
                             "policy": {"column": "reject_reason", "values": ["KYC"]},
                         },
                     })
    out = node.run(ctx)

    config_art = next(a for a in out.artifacts if a.role == "definition")
    config = json.loads(store.artifact_path(config_art).read_text())

    # 2 rows excluded (fraud + KYC), 2 remaining: both financed (good + bad)
    assert config["exclusion_categories"]["fraud"] == 1
    assert config["exclusion_categories"]["policy"] == 1
    assert config["total_rows"] == 4
    assert config["financed_rows"] == 2
    assert config["non_financed_rows"] == 0

    ds_art = next(a for a in out.artifacts if a.role == "input")
    df = pl.read_parquet(store.artifact_path(ds_art))
    assert df.height == 2  # 4 original - 2 excluded


def test_define_reject_population_all_financed() -> None:
    store, _ = make_store()
    dataset = _make_input_dataset(store, [
        {"target": "good", "feat_a": 1},
        {"target": "bad", "feat_a": 2},
        {"target": "good", "feat_a": 3},
    ])
    meta = _make_modelling_metadata_artifact(store)
    sample_def = _make_sample_definition_artifact(
        store, rejection_source="target_missing",
    )

    node = DefineRejectPopulationNode()
    ctx = _build_ctx(store, node, [dataset, meta, sample_def])
    out = node.run(ctx)

    config_art = next(a for a in out.artifacts if a.role == "definition")
    config = json.loads(store.artifact_path(config_art).read_text())
    assert config["financed_rows"] == 3
    assert config["non_financed_rows"] == 0


# ======================================================================
# RejectInferenceNoneNode tests
# ======================================================================


def test_none_method_passthrough() -> None:
    store, _ = make_store()
    dataset = _make_input_dataset(store, [
        {"target": "good", "feat_a": 10, "_ri_financed": True},
        {"target": "bad", "feat_a": 20, "_ri_financed": True},
        {"target": None, "feat_a": 30, "_ri_financed": False},
    ])
    config_payload = {
        "schema_version": SCHEMA_REJECT_POPULATION_CONFIG,
        "total_rows": 3,
        "financed_rows": 2,
        "non_financed_rows": 1,
        "indeterminate_rows": 0,
        "rejection_source": "target_missing",
        "rejection_column": None,
        "rejection_values": None,
        "exclusion_categories": {},
        "observation_window_note": "",
    }
    config_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-ri-config",
        payload=config_payload,
        metadata={"schema_version": SCHEMA_REJECT_POPULATION_CONFIG},
    )

    node = RejectInferenceNoneNode()
    ctx = _build_ctx(store, node, [dataset, config_art])
    out = node.run(ctx)

    assert len(out.artifacts) == 2
    ds_art = next(a for a in out.artifacts if a.role == "input")
    report_art = next(a for a in out.artifacts if a.role == "report")

    df = pl.read_parquet(store.artifact_path(ds_art))
    assert df.height == 2  # financed only
    assert "_ri_financed" not in df.columns

    report = json.loads(store.artifact_path(report_art).read_text())
    assert report["method"] == "none"
    assert report["missingness_assumption"] == "MAR"
    assert report["n_financed"] == 2
    assert report["n_non_financed"] == 1


# ======================================================================
# RejectInferenceAugmentationNode tests
# ======================================================================


def test_augmentation_resample_produces_expected_count() -> None:
    store, _ = make_store()
    n_financed = 100
    n_non_financed = 50
    rows = []
    for i in range(n_financed):
        rows.append({"target": "bad" if i % 3 == 0 else "good",
                     "feat_a": float(20 + i * 0.1), "_ri_financed": True})
    for i in range(n_non_financed):
        rows.append({"target": None,
                     "feat_a": float(30 + i * 0.1), "_ri_financed": False})
    dataset = _make_input_dataset(store, rows)

    config_payload = {
        "schema_version": SCHEMA_REJECT_POPULATION_CONFIG,
        "total_rows": n_financed + n_non_financed,
        "financed_rows": n_financed,
        "non_financed_rows": n_non_financed,
        "indeterminate_rows": 0,
        "rejection_source": "target_missing",
        "rejection_column": None,
        "rejection_values": None,
        "exclusion_categories": {},
        "observation_window_note": "",
    }
    config_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-ri-config",
        payload=config_payload,
        metadata={"schema_version": SCHEMA_REJECT_POPULATION_CONFIG},
    )
    meta = _make_modelling_metadata_artifact(store)

    node = RejectInferenceAugmentationNode()
    ctx = _build_ctx(store, node, [dataset, config_art, meta],
                     params={"random_seed": 42})
    out = node.run(ctx)

    ds_art = next(a for a in out.artifacts if a.role == "input")
    report_art = next(a for a in out.artifacts if a.role == "report")

    df = pl.read_parquet(store.artifact_path(ds_art))
    assert df.height == n_financed  # resampled to n_financed

    report = json.loads(store.artifact_path(report_art).read_text())
    assert report["method"] == "augmentation"
    assert report["n_financed"] == n_financed
    assert report["n_non_financed"] == n_non_financed
    assert report["weight_summary"] is not None
    assert report["weight_summary"]["min"] > 0


def test_augmentation_band_estimation() -> None:
    store, _ = make_store()
    rows = []
    for i in range(200):
        financed = i < 150
        target_val = "good" if financed else None
        if financed and i % 5 == 0:
            target_val = "bad"
        rows.append({
            "target": target_val,
            "feat_a": float(10 + (i // 20) * 5),
            "_ri_financed": financed,
        })
    dataset = _make_input_dataset(store, rows)

    config_payload = {
        "schema_version": SCHEMA_REJECT_POPULATION_CONFIG,
        "total_rows": 200,
        "financed_rows": 150,
        "non_financed_rows": 50,
        "indeterminate_rows": 0,
        "rejection_source": "target_missing",
        "rejection_column": None,
        "rejection_values": None,
        "exclusion_categories": {},
        "observation_window_note": "",
    }
    config_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-ri-config",
        payload=config_payload,
        metadata={"schema_version": SCHEMA_REJECT_POPULATION_CONFIG},
    )
    meta = _make_modelling_metadata_artifact(store)

    node = RejectInferenceAugmentationNode()
    ctx = _build_ctx(store, node, [dataset, config_art, meta],
                     params={"n_score_bands": 5, "random_seed": 42})
    out = node.run(ctx)

    report_art = next(a for a in out.artifacts if a.role == "report")
    report = json.loads(store.artifact_path(report_art).read_text())
    assert report["n_financed"] == 150
    assert report["n_non_financed"] == 50


def test_augmentation_min_p_financed_floor() -> None:
    store, _ = make_store()
    rows = []
    for i in range(100):
        financed = i < 2
        target_val = "good" if financed else None
        if financed and i == 1:
            target_val = "bad"
        rows.append({
            "target": target_val,
            "feat_a": float(i),
            "_ri_financed": financed,
        })
    dataset = _make_input_dataset(store, rows)

    config_payload = {
        "schema_version": SCHEMA_REJECT_POPULATION_CONFIG,
        "total_rows": 100,
        "financed_rows": 2,
        "non_financed_rows": 98,
        "indeterminate_rows": 0,
        "rejection_source": "target_missing",
        "rejection_column": None,
        "rejection_values": None,
        "exclusion_categories": {},
        "observation_window_note": "",
    }
    config_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-ri-config",
        payload=config_payload,
        metadata={"schema_version": SCHEMA_REJECT_POPULATION_CONFIG},
    )
    meta = _make_modelling_metadata_artifact(store)

    node = RejectInferenceAugmentationNode()
    ctx = _build_ctx(store, node, [dataset, config_art, meta],
                     params={"band_min_p_financed": 0.02, "random_seed": 42})
    out = node.run(ctx)

    report_art = next(a for a in out.artifacts if a.role == "report")
    report = json.loads(store.artifact_path(report_art).read_text())
    assert report["method"] == "augmentation"
    assert report["n_financed"] == 2
