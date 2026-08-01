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

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
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


def _run_plan(container, uow_factory, project_id, pv_id, label: str):
    result = _submit_run(container, project_id, pv_id)
    assert result.status == "succeeded", (
        f"{label} run: {result.status}"
    )
    return result.run_id


def _model_fit_outputs(uow_factory, project_id, run_id):
    """Return (model_art, estimator_art) for the model-fit step of a run."""

    with uow_factory.read_only(project_id) as uow:
        run_steps = uow.run_steps.get_for_run(run_id)
        model_run_step = next(rs for rs in run_steps if rs.step_id == "model-fit")
        outputs = []
        for aid in uow.artifacts.output_artifact_ids_for_run_step(model_run_step.run_step_id):
            art = uow.artifacts.get(aid)
            if art is not None:
                outputs.append(art)
    model_art = next(
        (a for a in outputs
         if a.artifact_type == "model_artifact" and a.media_type == "application/json"),
        None,
    )
    estimator_art = next(
        (a for a in outputs
         if a.artifact_type == "model_artifact" and a.media_type == "application/octet-stream"),
        None,
    )
    assert model_art is not None, "Model JSON artifact not found"
    assert estimator_art is not None, "Estimator artifact not found"
    return model_art, estimator_art


def _assert_embedded_reference_resolves(uow_factory, project_id, run_id):
    """Resolve the model JSON's embedded estimator reference the way the
    runtime does: through an input-scoped artifact lookup that falls back to
    physical hash when the embedded content-addressed ID is absent."""
    from cardre.adapters.evidence.reader import EvidenceReader
    from cardre.application.execution.input_collection import StepInputCollection

    model_art, estimator_art = _model_fit_outputs(uow_factory, project_id, run_id)
    root = _project_root(uow_factory, project_id)

    with uow_factory.read_only(project_id) as uow:
        reader = EvidenceReader(FsArtifactStore(root), uow.artifacts, uow.run_steps)
        inputs = StepInputCollection(reader, [model_art, estimator_art])
        payload = json.loads(reader.read_bytes(model_art))
        estimator_ref = payload["estimator_reference"]
        embedded_id = estimator_ref["artifact_id"]
        assert embedded_id, "estimator_reference.artifact_id is empty"

        resolved = inputs.artifact_ref(embedded_id, physical_hash=estimator_ref["physical_hash"])
        assert resolved is not None, (
            f"Embedded estimator reference {embedded_id!r} does not resolve "
            "to an input artifact"
        )
        assert resolved.physical_hash == estimator_ref["physical_hash"], (
            "Resolved estimator artifact physical hash does not match embedded reference"
        )
        return estimator_ref


def _project_root(uow_factory, project_id):
    return uow_factory._registry.resolve_root(project_id)


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
    _run_plan(container, uow_factory, project_id, pv_id, "first")
    second_run = _run_plan(container, uow_factory, project_id, pv_id, "second")

    estimator_ref = _assert_embedded_reference_resolves(uow_factory, project_id, second_run)
    # Cross-check via a direct repo lookup: in the fresh-project case the
    # content-addressed ID equals the persisted canonical ID, so the embedded
    # reference must resolve directly too.
    with uow_factory.read_only(project_id) as uow:
        persisted = uow.artifacts.get(estimator_ref["artifact_id"])
    assert persisted is not None, (
        f"Second model's estimator reference {estimator_ref['artifact_id']!r} "
        "does not resolve to a persisted artifact"
    )
    assert persisted.physical_hash == estimator_ref["physical_hash"]


def test_second_run_estimator_reference_resolves(tmp_path) -> None:
    _run_twice_and_resolve_second_estimator(tmp_path)


def test_legacy_uuid_estimator_embedded_reference_resolves(tmp_path) -> None:
    """Upgrade compatibility: bytes already stored under a legacy UUID must
    still resolve through the embedded content-addressed reference.

    Simulates an existing project whose deterministic estimator bytes were
    stored under a random UUID before content-addressed IDs were introduced.
    A fresh run stages the estimator with its content-addressed ID; physical
    dedup returns the legacy UUID as the canonical ID, so the model JSON's
    embedded reference must resolve via physical-hash fallback.
    """
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Legacy UUID Test")
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

    # Run once to produce the deterministic estimator bytes, then rewrite that
    # artifact row to a legacy UUID (simulating a pre-existing project).
    first_run = _run_plan(container, uow_factory, project_id, pv_id, "first")
    model_art, estimator_art = _model_fit_outputs(uow_factory, project_id, first_run)

    legacy_id = "legacy-estimator-uuid"
    with uow_factory.for_project(project_id) as uow:
        # Delete the content-addressed estimator row and its lineage, then
        # re-insert the identical bytes under a legacy UUID.
        uow._conn.execute("DELETE FROM artifacts WHERE artifact_id = ?", (estimator_art.artifact_id,))
        uow._conn.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, "
            "physical_hash, logical_hash, media_type, schema_version, created_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                legacy_id,
                estimator_art.artifact_type,
                estimator_art.role,
                estimator_art.path,
                estimator_art.physical_hash,
                estimator_art.logical_hash,
                estimator_art.media_type,
                estimator_art.metadata.get("schema_version", ""),
                estimator_art.created_at or "2020-01-01T00:00:00Z",
                json.dumps(estimator_art.metadata),
            ),
        )
        uow.commit()

    # The deterministic rerun stages the estimator with its content-addressed
    # ID; physical dedup returns the legacy UUID. The embedded reference must
    # resolve via physical-hash fallback.
    second_run = _run_plan(container, uow_factory, project_id, pv_id, "second")
    estimator_ref = _assert_embedded_reference_resolves(uow_factory, project_id, second_run)

    # The embedded content-addressed ID now resolves to its own descriptor
    # (finding 3: descriptors are separated from blobs), and the legacy UUID
    # descriptor also exists referencing the same shared blob.
    with uow_factory.read_only(project_id) as uow:
        legacy = uow.artifacts.get(legacy_id)
        by_embedded = uow.artifacts.get(estimator_ref["artifact_id"])
        blob = uow.artifacts.get_blob(estimator_ref["physical_hash"])
    assert legacy is not None
    assert legacy.physical_hash == estimator_ref["physical_hash"]
    assert by_embedded is not None, (
        "The embedded content-addressed ID must resolve to its own descriptor"
    )
    assert by_embedded.physical_hash == estimator_ref["physical_hash"]
    assert blob is not None, "one shared blob must back both descriptors"
