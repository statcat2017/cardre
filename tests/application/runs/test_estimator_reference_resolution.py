"""Estimator reference resolution across repeated deterministic runs.

Regression test for the Batch 07f embedded-provisional-ID fix.

A fitted classifier stages a binary estimator and then a model JSON whose
``estimator_reference.artifact_id`` embeds the estimator's staged ID before
persistence.  When the same deterministic fit runs twice, artifact
registration deduplicates by physical hash; the second run's embedded
reference must still resolve to a persisted artifact.

Staged artifact IDs are content-addressed, so identical estimator bytes
produce the same ID in both runs and the deduplicated canonical ID matches
the embedded reference.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.step import StepSpec


def _write_input_csv(path: Path) -> Path:
    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _build_classifier_plan(csv_path: Path, cat) -> list[StepSpec]:
    """Build import → define-metadata → split → decision-tree classifier.

    The classifier is a deferred tier node, so the catalogue must be built
    with ``launch_mode=False`` for it to run.
    """

    def _spec(step_id: str, node_type: str, parents: list[str], params: dict) -> StepSpec:
        return StepSpec(
            step_id=step_id,
            node_type=node_type,
            node_version=cat.resolve(node_type).version,
            category=cat.resolve(node_type).category,
            params=params,
            params_hash=json.dumps(params, sort_keys=True),
            parent_step_ids=parents,
            position=len(parents),
        )

    return [
        _spec("import", "cardre.import_dataset", [], {"source_path": str(csv_path)}),
        _spec(
            "define-metadata",
            "cardre.define_modelling_metadata",
            ["import"],
            {
                "target_column": "credit_risk_class",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
        ),
        _spec(
            "split",
            "cardre.split_train_test_oot",
            ["import", "define-metadata"],
            {"target_column": "credit_risk_class"},
        ),
        _spec(
            "model-fit",
            "cardre.decision_tree_classifier",
            ["split", "define-metadata"],
            {"max_depth": 2, "random_seed": 42, "class_weight": "balanced"},
        ),
    ]


def _submit_run(container, project_id: str, plan_version_id: str):
    return container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=plan_version_id, sync=True),
    )


def _run_twice_and_resolve_second_estimator(tmp_path: Path) -> None:
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Estimator Ref Test")
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        uow.commit()
    registry.register(project_id, root)

    csv_path = _write_input_csv(tmp_path / "input.csv")
    cat = build_default_catalogue(Settings(launch_mode=False))
    steps = _build_classifier_plan(csv_path, cat)

    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(launch_mode=False, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)

    # Run the same deterministic plan twice.
    first = _submit_run(container, project_id, pv_id)
    if first.status != "succeeded":
        with uow_factory.read_only(project_id) as uow:
            steps_dbg = uow.run_steps.get_for_run(first.run_id)
            for rs in steps_dbg:
                print(f"STEP {rs.step_id}: {rs.status.value} {rs.errors} {rs.warnings}")
        raise AssertionError(f"first run: {first.status}")
    second = _submit_run(container, project_id, pv_id)
    assert second.status == "succeeded", f"second run: {second.status}"

    # Locate the second run's model-fit step and read its model artifact.
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore

    art_store = FsArtifactStore(root)
    with uow_factory.read_only(project_id) as uow:
        run_steps = uow.run_steps.get_for_run(second.run_id)
        model_run_step = next(rs for rs in run_steps if rs.step_id == "model-fit")
        model_art = None
        for aid in uow.artifacts.output_artifact_ids_for_run_step(model_run_step.run_step_id):
            art = uow.artifacts.get(aid)
            if art is not None and art.artifact_type == "model_artifact" and art.media_type == "application/json":
                model_art = art
                break
        assert model_art is not None, "Second run model artifact not found"

        payload = json.loads(art_store.read_bytes(model_art))
        estimator_ref = payload["estimator_reference"]
        estimator_id = estimator_ref["artifact_id"]
        assert estimator_id, "estimator_reference.artifact_id is empty"

        # The embedded estimator reference must resolve to a persisted artifact
        # whose physical hash matches the embedded reference.
        persisted = uow.artifacts.get(estimator_id)
        assert persisted is not None, (
            f"Second model's estimator reference {estimator_id!r} does not resolve "
            "to a persisted artifact"
        )
        assert persisted.physical_hash == estimator_ref["physical_hash"], (
            "Resolved estimator artifact physical hash does not match embedded reference"
        )
        assert persisted.media_type == "application/octet-stream"


def test_second_run_estimator_reference_resolves(tmp_path) -> None:
    _run_twice_and_resolve_second_estimator(tmp_path)
