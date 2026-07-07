from __future__ import annotations

import json

import polars as pl

from cardre._evidence.schemas import SCHEMA_MODELLING_METADATA, SCHEMA_VALIDATION_METRICS
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec
from cardre.execution.step_runner import StepRunner
from cardre.nodes.registry import NodeRegistry


def _write_modelling_metadata(store):
    return write_json_artifact(
        store,
        artifact_type="definition",
        role="definition",
        stem="modelling-metadata",
        payload={
            "schema_version": SCHEMA_MODELLING_METADATA,
            "target_column": "credit_risk_class",
            "good_values": ["good"],
            "bad_values": ["bad"],
        },
        metadata={"schema_version": SCHEMA_MODELLING_METADATA},
    )


def _write_dataset(store, *, role: str, include_score: bool, include_probability: bool):
    payload: dict[str, list[object]] = {
        "credit_risk_class": ["good", "bad", "good", "bad"],
    }
    if include_probability:
        payload["predicted_bad_probability"] = [0.1, 0.8, 0.2, 0.9]
    if include_score:
        payload["score"] = [700.0, 550.0, 680.0, 530.0]
    return write_parquet_artifact(
        store,
        artifact_type="dataset",
        role=role,
        stem=f"{role}-dataset",
        frame=pl.DataFrame(payload),
    )


def _run_validation_step(store, *, parent_artifacts, params):
    registry = NodeRegistry.with_defaults()
    node_cls = registry.resolve("cardre.validation_metrics")
    step_spec = StepSpec(
        step_id="validation-metrics",
        node_type="cardre.validation_metrics",
        node_version=node_cls.version,
        category=node_cls.category,
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=["parent"],
        position=0,
        canonical_step_id="validation-metrics",
    )
    runner = StepRunner(store, registry)
    return runner.run_step(
        plan_version_id="pv-1",
        run_id="run-1",
        spec=step_spec,
        step_outputs={"parent": list(parent_artifacts)},
        run_step_records={},
    )


def test_validation_failure_writes_evidence_artifact(store):
    modelling_metadata = _write_modelling_metadata(store)
    train_dataset = _write_dataset(
        store,
        role="train",
        include_score=False,
        include_probability=True,
    )
    test_dataset = _write_dataset(
        store,
        role="test",
        include_score=False,
        include_probability=True,
    )

    result = _run_validation_step(
        store,
        parent_artifacts=[train_dataset, test_dataset, modelling_metadata],
        params={
            "require_test": True,
            "require_oot": False,
            "fail_on_missing_score": True,
            "fail_on_missing_target": True,
        },
    )

    assert result.status == RunStepStatus.FAILED
    assert "NO_MISSING_SCORE" in result.errors[0]["message"]

    # Verify the artifact is linked to the failed run step via output_artifact_ids
    assert len(result.output_artifact_ids) > 0, (
        "Failed validation step should have output artifact IDs in StepExecutionResult"
    )

    rows = store.execute(
        """SELECT a.artifact_id, a.path, a.metadata_json
           FROM artifacts a
           WHERE a.role = 'report'
           AND a.path LIKE '%validation-metrics%'""",
    ).fetchall()
    assert rows, "No validation-metrics artifact found in store"

    failed_payload = None
    for row in rows:
        p = json.loads((store.root / row["path"]).read_text(encoding="utf-8"))
        if p.get("status") == "failed":
            failed_payload = p
            break
    assert failed_payload is not None, "No validation-metrics artifact with status 'failed' found"
    assert failed_payload.get("schema_version") == SCHEMA_VALIDATION_METRICS
    assert "gates" in failed_payload
    failing_gates = [g for g in failed_payload["gates"] if g.get("status") == "fail"]
    assert failing_gates, "Expected at least one failing gate in the artifact"
    failing_codes = {g["code"] for g in failing_gates}
    assert "NO_MISSING_SCORE" in failing_codes
