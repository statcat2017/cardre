from __future__ import annotations

import json

import polars as pl
import pytest

from cardre.application.execution.step_runner import StepRunner
from cardre.artifacts import write_parquet_artifact
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec
from cardre.nodes.registry import NodeRegistry
from cardre.store.artifact_repo import ArtifactRepository

pytestmark = pytest.mark.xfail(reason="Old StepRunner/execution path; needs NodeContext update")


def _write_dataset(store, *, role: str):
    return write_parquet_artifact(
        store,
        artifact_type="dataset",
        role=role,
        stem=f"{role}-dataset",
        frame=pl.DataFrame({
            "age": [25, 30, 35, 40, 45, 50],
            "income": [50000, 60000, 70000, 80000, 90000, 100000],
            "credit_risk_class": ["good", "bad", "good", "bad", "good", "bad"],
        }),
    )


def _run_clustering_step(store, *, parent_artifacts, params):
    registry = NodeRegistry.with_defaults()
    node_cls = registry.resolve("cardre.variable_clustering")
    step_spec = StepSpec(
        step_id="variable-clustering",
        node_type="cardre.variable_clustering",
        node_version=node_cls.version,
        category=node_cls.category,
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=["parent"],
        position=0,
        canonical_step_id="variable-clustering",
    )
    runner = StepRunner(store, registry)
    return runner.run_step(
        plan_version_id="pv-1",
        run_id="run-1",
        spec=step_spec,
        step_outputs={"parent": list(parent_artifacts)},
        run_step_records={},
    )


def _read_report_payload(store, result):
    if not result.output_artifact_ids:
        return {}
    art = ArtifactRepository(store).get(result.output_artifact_ids[0])
    if art is None:
        return {}
    path = store.artifact_path(art)
    with open(path) as f:
        return json.load(f)


class TestVariableClusteringNode:
    def test_woe_train_missing_evidence_uses_singleton_pass_through(self, store):
        train_dataset = _write_dataset(store, role="train")

        result = _run_clustering_step(
            store,
            parent_artifacts=[train_dataset],
            params={
                "method": "correlation_threshold",
                "input_representation": "woe_train",
                "threshold": 0.7,
                "candidate_limit": 50,
            },
        )

        assert result.status == RunStepStatus.SUCCEEDED
        report = _read_report_payload(store, result)
        warnings = report.get("warnings", [])
        assert any("WOE_EVIDENCE_MISSING" in str(w) for w in warnings)

    def test_raw_train_succeeds_with_correlation_threshold(self, store):
        train_dataset = _write_dataset(store, role="train")

        result = _run_clustering_step(
            store,
            parent_artifacts=[train_dataset],
            params={
                "method": "correlation_threshold",
                "input_representation": "raw_train",
                "threshold": 0.7,
                "candidate_limit": 50,
            },
        )

        assert result.status == RunStepStatus.SUCCEEDED

    def test_insufficient_candidates_uses_singleton_pass_through(self, store):
        train_dataset = write_parquet_artifact(
            store,
            artifact_type="dataset",
            role="train",
            stem="train-dataset",
            frame=pl.DataFrame({"age": [25, 30]}),
        )

        result = _run_clustering_step(
            store,
            parent_artifacts=[train_dataset],
            params={
                "method": "correlation_threshold",
                "input_representation": "raw_train",
                "threshold": 0.7,
                "candidate_limit": 50,
            },
        )

        assert result.status == RunStepStatus.SUCCEEDED
        report = _read_report_payload(store, result)
        warnings = report.get("warnings", [])
        assert any("INSUFFICIENT_CANDIDATES" in str(w) for w in warnings)
