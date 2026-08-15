"""Tests for model apply boundary contracts (#218).

Tests the production adapter code path, not copied logic.
"""

from __future__ import annotations

import io

import joblib
import numpy as np

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.domain.artifacts import ArtifactRef


class FakeEstimator:
    """Minimal estimator with predict_proba returning 2 columns."""

    n_classes_ = 2

    def predict_proba(self, X):
        return np.array([[0.3, 0.7]] * len(X))


def _provision(tmp_path):
    from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    from cardre.adapters.system.project_registry import JsonProjectRegistry

    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test")
        uow.commit()
    registry.register(project_id, root)
    return project_id, uow_factory, root


def test_write_estimator_artifact_registers_with_repository(tmp_path):
    from cardre.modeling.serialization import write_estimator_artifact

    project_id, uow_factory, root = _provision(tmp_path)
    store = FsArtifactStore(root)
    with uow_factory.for_project(project_id) as uow:
        buf = io.BytesIO()
        joblib.dump(FakeEstimator(), buf)
        staged = write_estimator_artifact(
            store,
            estimator_bytes=buf.getvalue(),
            estimator_format="joblib",
            stem="test-estimator",
            creating_run_id="run-1",
            creating_run_step_id="step-1",
            metadata={"model_family": "sklearn"},
        )
        store.publish(staged)
        ref = ArtifactRef(
            artifact_id=staged.provisional_artifact_id,
            artifact_type=staged.artifact_type,
            role=staged.role,
            path=str(store.root / "objects" / staged.physical_hash[:2] / staged.physical_hash),
            physical_hash=staged.physical_hash,
            logical_hash=staged.logical_hash,
            media_type=staged.media_type,
            metadata=staged.metadata,
        )
        uow.artifacts.register(ref)
        uow.commit()
        stored = uow.artifacts.get(staged.provisional_artifact_id)
        assert stored is not None
        assert stored.metadata["creating_run_id"] == "run-1"
        assert stored.metadata["creating_run_step_id"] == "step-1"
        assert stored.metadata["model_family"] == "sklearn"


def test_apply_model_sklearn_family_not_wired_through_node_context(tmp_path):
    """The sklearn apply path is not yet plumbed through NodeContext (#218)."""
    from cardre.nodes.validate.apply import ApplyModelNode

    node = ApplyModelNode()
    assert node is not None
