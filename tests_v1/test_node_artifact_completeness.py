"""Safety-rail tests: every artifact written to the store must be included
in NodeOutput.artifacts. All prep.py nodes include report artifacts in
their return values.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import polars as pl

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.nodes import (
    ApplyExclusionsNode,
    ExplicitMissingOutlierTreatmentNode,
    ImportGermanCreditNode,
    SplitTrainTestOotNode,
)
from cardre.store import ProjectStore

from tests.helpers import make_store

pytestmark = pytest.mark.unit


SAMPLE_GERMAN_CREDIT_LINES_MULTI = [
    "A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1",
    "A12 24 A32 A43 5951 A61 A73 2 A92 A101 4 A121 22 A142 A152 2 A173 1 A191 A201 2",
    "A13 12 A34 A43 2096 A61 A75 3 A93 A101 3 A121 49 A143 A152 1 A173 1 A192 A201 1",
    "A14 30 A32 A43 7882 A61 A73 4 A92 A101 2 A121 45 A142 A152 1 A173 1 A191 A201 2",
    "A15 18 A34 A43 4870 A65 A75 3 A93 A101 3 A121 53 A143 A152 2 A173 1 A192 A201 1",
    "A16 36 A32 A43 9055 A61 A73 4 A92 A101 4 A121 35 A142 A152 1 A173 1 A191 A201 2",
    "A11 9 A34 A43 1436 A65 A75 4 A93 A101 4 A121 68 A143 A152 2 A173 1 A192 A201 1",
    "A12 28 A32 A43 6798 A61 A73 2 A92 A101 4 A121 30 A142 A152 2 A173 1 A191 A201 2",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_sample_german_credit_file(tmp: Path) -> Path:
    p = tmp / "german.data"
    p.write_text("\n".join(SAMPLE_GERMAN_CREDIT_LINES_MULTI))
    return p


def _import_german_credit(store: ProjectStore, tmp: Path) -> ArtifactRef:
    source = make_sample_german_credit_file(tmp)
    params = {"source_path": str(source)}
    spec = StepSpec(
        step_id="import", node_type="cardre.import_fixture_uci_german_credit",
        node_version="1", category="transform",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv",
        step_spec=spec, parent_run_steps=[], input_artifacts=[],
        validated_params=params, runtime_metadata={},
    )
    output = ImportGermanCreditNode().run(ctx)
    assert len(output.artifacts) == 1
    return output.artifacts[0]


def _parquet_artifact(
    store: ProjectStore, df: pl.DataFrame, role: str, artifact_id: str,
) -> ArtifactRef:
    buf = io.BytesIO()
    df.write_parquet(buf)
    p = store.root / "datasets" / f"{artifact_id}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id=artifact_id, artifact_type="dataset", role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p), logical_hash=table_logical_hash(df),
        media_type="application/octet-stream", metadata={},
    )
    store.register_artifact(art)
    return art


def _assert_output_includes_all_artifacts(
    store: ProjectStore,
    artifacts_before: int,
    output,
    expected_created: int,
    label: str,
) -> None:
    artifacts_after = len(store.list_artifacts())
    created = artifacts_after - artifacts_before
    assert created == expected_created, (
        f"{label} should create {expected_created} artifacts, got {created}"
    )
    assert len(output.artifacts) == created, (
        f"{label} NodeOutput.artifacts must include every artifact"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_split_output_includes_report():
    store, tmp = make_store()
    input_artifact = _import_german_credit(store, tmp)
    before = len(store.list_artifacts())

    params = {
        "strategy": "random_stratified", "train_fraction": 0.6,
        "test_fraction": 0.2, "oot_fraction": 0.2,
        "random_seed": 42, "target_column": "credit_risk_class",
    }
    spec = StepSpec(
        step_id="split", node_type="cardre.split_train_test_oot",
        node_version="2", category="transform",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=["import"], branch_label="", position=1,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[input_artifact], validated_params=params,
        runtime_metadata={},
    )
    output = SplitTrainTestOotNode().run(ctx)
    _assert_output_includes_all_artifacts(store, before, output, 4, "Split")


def test_exclusions_output_includes_report():
    store, tmp = make_store()
    input_artifact = _import_german_credit(store, tmp)
    before = len(store.list_artifacts())

    params = {
        "rules": [{
            "column": "age_years", "operator": ">", "value": 200,
            "reason": "Exclude impossible ages",
        }]
    }
    spec = StepSpec(
        step_id="exclude", node_type="cardre.apply_exclusions",
        node_version="1", category="transform",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=["import"], branch_label="", position=1,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[input_artifact], validated_params=params,
        runtime_metadata={},
    )
    output = ApplyExclusionsNode().run(ctx)
    _assert_output_includes_all_artifacts(store, before, output, 2, "Exclusions")


def test_treatment_output_includes_report():
    store, tmp = make_store()
    store.initialize()

    df = pl.DataFrame({
        "credit_risk_class": ["1", "2", "1", "2", "1", "2"],
        "duration_months": [6, 24, 12, 30, 18, 36],
        "age_years": [67, 22, 49, 45, 53, 35],
    })
    _parquet_artifact(store, df, "train", "train-art")
    _parquet_artifact(store, df, "test", "test-art")
    _parquet_artifact(store, df, "oot", "oot-art")

    before = len(store.list_artifacts())

    params = {
        "imputations": {
            "duration_months": {"value": 0, "reason": "Fill missing durations with 0"},
        },
        "caps": {}, "floors": {},
    }
    train_art = next(a for a in store.list_artifacts() if a.role == "train")
    test_art = next(a for a in store.list_artifacts() if a.role == "test")
    oot_art = next(a for a in store.list_artifacts() if a.role == "oot")
    spec = StepSpec(
        step_id="treat", node_type="cardre.explicit_missing_outlier_treatment",
        node_version="1", category="apply",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[train_art, test_art, oot_art],
        validated_params=params, runtime_metadata={},
    )
    output = ExplicitMissingOutlierTreatmentNode().run(ctx)
    _assert_output_includes_all_artifacts(store, before, output, 4, "Treatment")
