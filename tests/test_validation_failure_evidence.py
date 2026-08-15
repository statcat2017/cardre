from __future__ import annotations

import json

import polars as pl
import pytest

from cardre._evidence.schemas import SCHEMA_VALIDATION_METRICS
from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec
from cardre.workflows import build_canonical_scorecard_steps


def _write_input_csv(path):
    import csv

    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def provisioned_project(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test Project")
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        uow.commit()
    registry.register(project_id, root)

    csv_path = _write_input_csv(tmp_path / "input.csv")
    steps = build_canonical_scorecard_steps(csv_path)
    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(launch_mode=True, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    return project_id, pv_id, container, root


def test_validation_failure_writes_evidence_artifact(provisioned_project):
    """A failing validation step still writes its evidence artifact."""
    project_id, pv_id, container, root = provisioned_project

    # Run the full canonical workflow so validation-metrics has real inputs.
    from cardre.application.runs.submit_run import SubmitRunCommand

    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )
    assert result.status == "succeeded", f"Run did not succeed: {result}"

    # The canonical workflow's validation-metrics step succeeds; the invariant
    # we pin here is that a failed validation step still writes evidence.
    # Drive validation-metrics directly with a missing-score dataset.
    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.application.execution.input_collection import StepInputCollection
    from cardre.application.execution.output_publisher import StagingOutputPublisher
    from cardre.domain.errors import NodeFailedWithArtifacts
    from cardre.nodes.contracts import NodeContext, RuntimeMeta
    from cardre.nodes.validate.metrics import ValidationMetricsNode

    artifact_store = FsArtifactStore(root)
    with container.uow_factory.for_project(project_id) as uow:
        reader = EvidenceReader(artifact_store, uow.artifacts, uow.run_steps)
        # Build a train dataset with no score column.
        df = pl.DataFrame({
            "credit_risk_class": ["good", "bad", "good", "bad"],
            "predicted_bad_probability": [0.1, 0.8, 0.2, 0.9],
        })
        staged = artifact_store.stage_table(
            role="train", kind="cardre.modelling_metadata.v1", frame=df,
        )
        train_ref = artifact_store.publish(staged)
        from cardre.domain.artifacts import ArtifactRef
        train_art = ArtifactRef(
            artifact_id=staged.provisional_artifact_id,
            artifact_type=staged.artifact_type,
            role=staged.role,
            path=str(train_ref),
            physical_hash=staged.physical_hash,
            logical_hash=staged.logical_hash,
            media_type=staged.media_type,
            metadata=staged.metadata,
        )
        uow.artifacts.register(train_art)
        uow.commit()

        inputs = StepInputCollection(reader, [train_art])
        outputs = StagingOutputPublisher(artifact_store)
        node = ValidationMetricsNode()
        spec = StepSpec(
            step_id="validation-metrics",
            node_type="cardre.validation_metrics",
            node_version="1",
            category="validate",
            params={
                "require_test": False,
                "require_oot": False,
                "fail_on_missing_score": True,
                "fail_on_missing_target": True,
            },
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
        )
        try:
            node.run(NodeContext(
                run_id="run-1",
                plan_version_id=pv_id,
                step_spec=spec,
                inputs=inputs,
                outputs=outputs,
                params=spec.params,
                runtime=RuntimeMeta("run-1", pv_id, "validation-metrics", "cardre.validation_metrics"),
            ))
            raise AssertionError("validation-metrics should have failed on missing score")
        except NodeFailedWithArtifacts as exc:
            assert exc.artifacts, "Failed validation step should carry its evidence artifact"
            report = exc.artifacts[0]
            payload = json.loads((root / report.staging_path).read_text(encoding="utf-8"))
            assert payload.get("schema_version") == SCHEMA_VALIDATION_METRICS
            assert "gates" in payload
            failing_gates = [g for g in payload["gates"] if g.get("status") == "fail"]
            assert failing_gates, "Expected at least one failing gate in the artifact"
            failing_codes = {g["code"] for g in failing_gates}
            assert "NO_MISSING_SCORE" in failing_codes
