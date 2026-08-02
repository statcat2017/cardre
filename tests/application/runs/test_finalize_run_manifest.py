"""Integration tests for canonical run manifest finalisation.

These tests exercise the real FinalizeRun use case, the FsManifestPublisher
adapter, and the shared manifest hashing/verification domain functions
through the production persistence stack (SqliteProjectProvisioner,
SqliteUnitOfWorkFactory). No mocks around the integrity boundary.
"""

from __future__ import annotations

import json

import pytest

from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.finalize_run import FinalizeDiagnostic, FinalizeRun
from cardre.domain.manifest import (
    MANIFEST_VERSION,
    compute_manifest_hash,
    compute_pathway_hash,
    deserialize_manifest,
    serialize_manifest,
)


class _FakeClock:
    def now_iso(self) -> str:
        return "2026-01-01T00:00:00Z"


@pytest.fixture
def provisioned_project(tmp_path):
    """Provision a real project database using the production stack."""
    from cardre.domain.artifacts import json_logical_hash
    from cardre.domain.step import StepSpec

    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "projects" / "project-1"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test Project")
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        step = StepSpec(
            step_id="step-1", node_type="cardre.noop", node_version="1",
            category="transform", params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0, canonical_step_id="noop",
        )
        pv_id = uow.plans.create_version(plan_id, [step], is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow.commit()

    registry.register(project_id, root)
    return project_id, plan_id, pv_id, run_id, root, uow_factory, registry


def _insert_run_step(uow_factory, project_id, run_id, pv_id, step_id):
    """Insert a run step through the production UoW, after transitioning to running."""
    from cardre.domain.diagnostics import utc_now_iso
    from cardre.domain.run import RunStatus, RunStep, RunStepStatus
    now = utc_now_iso()
    rs_id = f"{run_id}-{step_id}"
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.run_steps.insert(RunStep(
            run_step_id=rs_id, run_id=run_id, step_id=step_id,
            plan_version_id=pv_id, status=RunStepStatus.SUCCEEDED,
            started_at=now, finished_at=now,
            execution_fingerprint={"node_type": "test_node", "node_version": "1", "params_hash": "abc"},
        ))
        uow.commit()
    return rs_id


def _insert_artifact_with_lineage(uow_factory, project_id, run_id, rs_id, pv_id, step_id, artifact_id):
    """Register an artifact and its output lineage through the production UoW."""
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import utc_now_iso
    now = utc_now_iso()
    art = ArtifactRef(
        artifact_id=artifact_id, artifact_type="json", role="output",
        path=f"/objects/{artifact_id}", physical_hash=f"phys_{artifact_id}",
        logical_hash=f"log_{artifact_id}", media_type="application/json",
        created_at=now, metadata={},
    )
    with uow_factory.for_project(project_id) as uow:
        uow.artifacts.register(art)
        uow.artifacts.register_lineage(
            run_id=run_id, run_step_id=rs_id, plan_version_id=pv_id,
            step_id=step_id, artifact_id=artifact_id, direction="output",
        )
        uow.commit()


def _current_generation(uow_factory, project_id, run_id) -> int:
    """Return the run's current worker generation (lease ownership token)."""
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None
    return run.worker_generation


class TestFinalizeRunManifest:
    """End-to-end tests through the production persistence stack."""

    def test_successful_finalisation_publishes_valid_manifest(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        rs_id = _insert_run_step(uow_factory, project_id, run_id, pv_id, "step-1")
        _insert_artifact_with_lineage(uow_factory, project_id, run_id, rs_id, pv_id, "step-1", "art-1")

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))

        result = publisher.verify(run_id)
        assert result["valid"] is True
        manifest = result["manifest"]
        assert manifest["run_id"] == run_id
        assert manifest["plan_version_id"] == pv_id
        assert manifest["status"] == "succeeded"
        assert manifest["manifest_version"] == MANIFEST_VERSION
        assert manifest["manifest_hash"] != ""
        assert manifest["pathway_hash"] != ""
        assert manifest["plan_id"] != ""
        assert manifest["project_id"] != ""
        assert manifest["execution_mode"] == "full_plan"
        assert len(manifest["steps"]) == 1
        assert manifest["steps"][0]["step_id"] == "step-1"
        assert "art-1" in manifest["steps"][0]["output_artifact_ids"]

    def test_manifest_self_hash_matches(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        _insert_run_step(uow_factory, project_id, run_id, pv_id, "step-1")

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))

        data = publisher.read(run_id)
        expected = compute_manifest_hash(data)
        assert data["manifest_hash"] == expected

    def test_tampered_manifest_fails_verification(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        _insert_run_step(uow_factory, project_id, run_id, pv_id, "step-1")

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))

        manifest_path = publisher.manifest_path(run_id)
        data = json.loads(manifest_path.read_text())
        data["status"] = "failed"
        manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

        result = publisher.verify(run_id)
        assert result["valid"] is False
        assert result["error"] == "ARTIFACT_HASH_UNRESOLVED"

    def test_missing_manifest_fails_verification(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        publisher = FsManifestPublisher(root)
        result = publisher.verify(run_id)
        assert result["valid"] is False
        assert result["error"] == "CANONICAL_MANIFEST_MISSING"

    def test_failed_finalisation_publishes_failed_status(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        _insert_run_step(uow_factory, project_id, run_id, pv_id, "step-1")

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "failed", diagnostic=FinalizeDiagnostic(
            code="RUN_EXECUTION_FAILED", message="Step failed",
        ))

        result = publisher.verify(run_id)
        assert result["valid"] is True
        assert result["manifest"]["status"] == "failed"
        diag = result["manifest"]["diagnostics"]
        assert any(d.get("code") == "RUN_EXECUTION_FAILED" for d in diag)

    def test_manifest_is_atomically_written(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        _insert_run_step(uow_factory, project_id, run_id, pv_id, "step-1")

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))

        manifest_path = publisher.manifest_path(run_id)
        assert manifest_path.exists()
        temp_files = list(manifest_path.parent.glob(".manifest.json.tmp.*"))
        assert temp_files == []

    def test_pathway_hash_is_deterministic(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        _insert_run_step(uow_factory, project_id, run_id, pv_id, "step-1")

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))

        data = publisher.read(run_id)
        recomputed = compute_pathway_hash(data["steps"])
        assert data["pathway_hash"] == recomputed

    def test_double_finalisation_raises_without_republishing(self, provisioned_project):
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project
        _insert_run_step(uow_factory, project_id, run_id, pv_id, "step-1")

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))

        first_manifest = publisher.read(run_id)

        with pytest.raises(Exception, match="already finalised"):
            finalize(run_id, "failed")

        second_manifest = publisher.read(run_id)
        assert second_manifest == first_manifest

    def test_pre_execution_failure_finalises_created_run(self, provisioned_project):
        """A run in 'submitted' state can be finalised as failed without transitioning to running."""
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "failed", diagnostic=FinalizeDiagnostic(
            code="RUN_VALIDATION_FAILED", message="Pre-execution validation failed",
        ))

        result = publisher.verify(run_id)
        assert result["valid"] is True
        assert result["manifest"]["status"] == "failed"

        with uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
            assert str(run.status) == "failed"

    def test_created_run_cannot_be_succeeded(self, provisioned_project):
        """A run in 'submitted' state cannot be finalised as succeeded without executing."""
        project_id, plan_id, pv_id, run_id, root, uow_factory, registry = provisioned_project

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())

        with pytest.raises(Exception, match="already finalised"):
            finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))

        result = publisher.verify(run_id)
        assert result["valid"] is False
        assert result["error"] == "CANONICAL_MANIFEST_MISSING"

        with uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
            assert str(run.status) == "submitted"


class TestManifestHashing:
    """Unit tests for the shared manifest hashing functions."""

    def test_compute_manifest_hash_is_deterministic(self):
        payload = {"manifest_version": MANIFEST_VERSION, "run_id": "r1", "manifest_hash": ""}
        h1 = compute_manifest_hash(payload)
        h2 = compute_manifest_hash(payload)
        assert h1 == h2

    def test_manifest_hash_ignores_manifest_hash_field(self):
        payload = {"run_id": "r1", "manifest_hash": "abc123"}
        h1 = compute_manifest_hash(payload)
        payload2 = {"run_id": "r1", "manifest_hash": "different"}
        h2 = compute_manifest_hash(payload2)
        assert h1 == h2

    def test_manifest_hash_changes_with_content(self):
        h1 = compute_manifest_hash({"run_id": "r1", "manifest_hash": ""})
        h2 = compute_manifest_hash({"run_id": "r2", "manifest_hash": ""})
        assert h1 != h2

    def test_serialize_deserialize_roundtrip(self):
        payload = {"manifest_version": MANIFEST_VERSION, "run_id": "r1", "steps": []}
        text = serialize_manifest(payload)
        restored = deserialize_manifest(text)
        assert restored == payload

    def test_pathway_hash_changes_with_different_steps(self):
        steps1 = [{"step_id": "s1", "node_type": "a", "status": "succeeded"}]
        steps2 = [{"step_id": "s1", "node_type": "b", "status": "succeeded"}]
        assert compute_pathway_hash(steps1) != compute_pathway_hash(steps2)

    def test_pathway_hash_changes_with_different_status(self):
        steps1 = [{"step_id": "s1", "node_type": "a", "status": "succeeded"}]
        steps2 = [{"step_id": "s1", "node_type": "a", "status": "failed"}]
        assert compute_pathway_hash(steps1) != compute_pathway_hash(steps2)


class TestManifestIntegrityFailures:
    """P2-3 — manifest assembly must surface integrity failures instead of
    silently substituting empty values."""

    def _finalize_with_broken_uow(self, provisioned_project, break_attr: str):
        project_id, _plan_id, _pv_id, run_id, root, uow_factory, _registry = provisioned_project
        from cardre.domain.diagnostics import utc_now_iso
        from cardre.domain.run import RunStatus, RunStep, RunStepStatus

        # Transition the run to running so success finalization is valid, and
        # add a run step so manifest assembly exercises plan-step edges.
        with uow_factory.for_project(project_id) as uow:
            uow.runs.transition(run_id, RunStatus.RUNNING,
                                expected_from=(RunStatus.SUBMITTED, RunStatus.SUBMITTED))
            uow.run_steps.insert(RunStep(
                run_step_id=f"{run_id}-step-1", run_id=run_id, step_id="step-1",
                plan_version_id=_pv_id, status=RunStepStatus.SUCCEEDED,
                started_at=utc_now_iso(), finished_at=utc_now_iso(),
                execution_fingerprint={"node_type": "test", "node_version": "1"},
            ))
            uow.commit()

        def boom(*args, **kwargs):
            raise RuntimeError("injected integrity failure")

        class _BrokenPlans:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                if name == "get_plan_id_for_version":
                    return boom
                return getattr(self._real, name)

        class _BrokenUow:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                if break_attr == "steps" and name == "steps":
                    return type("BrokenSteps", (), {"get_all_edges": boom})()
                if break_attr == "plans" and name == "plans":
                    return _BrokenPlans(self._inner.plans)
                return getattr(self._inner, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self._inner.__exit__(*exc)

            def close(self):
                self._inner.close()

        publisher = FsManifestPublisher(root)

        def broken_factory():
            return _BrokenUow(uow_factory.for_project(project_id))

        finalize = FinalizeRun(broken_factory, publisher, _FakeClock())
        with pytest.raises(RuntimeError, match="injected integrity failure"):
            finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))
        # The manifest must not be published on integrity failure.
        assert publisher.read(run_id) is None

    def test_finalize_fails_when_step_edges_unavailable(self, provisioned_project):
        self._finalize_with_broken_uow(provisioned_project, break_attr="steps")

    def test_finalize_fails_when_plan_identity_unavailable(self, provisioned_project):
        self._finalize_with_broken_uow(provisioned_project, break_attr="plans")


class TestSuccessFinalizationCancellationRace:
    """P1-A — success finalization must not beat a concurrent cancellation.

    ``FinalizeRun("succeeded")`` transitions only while the run is running,
    cancellation is not requested, and the caller's worker generation owns the
    lease. A cancellation committed between the caller's final read and the
    terminal UPDATE therefore wins: the run ends cancelled, never succeeded.
    """

    def test_success_finalization_defers_to_pending_cancellation(self, provisioned_project):
        project_id, _plan_id, _pv_id, run_id, root, uow_factory, _registry = provisioned_project
        from cardre.domain.run import RunStatus

        with uow_factory.for_project(project_id) as uow:
            uow.runs.transition(run_id, RunStatus.RUNNING,
                                expected_from=(RunStatus.SUBMITTED, RunStatus.SUBMITTED))
            generation = uow.runs.begin_worker_generation(run_id)
            # A cancellation was committed after the worker's final read but
            # before the terminal update.
            uow.runs.set_cancel_requested(run_id)
            uow.commit()

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        finalize(run_id, "succeeded", worker_generation=generation)

        with uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
        assert str(run.status) == "cancelled", f"final status: {run.status}"
        manifest = publisher.read(run_id)
        assert manifest is not None
        assert manifest["status"] == "cancelled"

    def test_success_finalization_rejects_stale_generation(self, provisioned_project):
        """A success finalization with a stale worker generation is rejected."""
        project_id, _plan_id, _pv_id, run_id, root, uow_factory, _registry = provisioned_project
        from cardre.domain.run import RunStatus

        with uow_factory.for_project(project_id) as uow:
            uow.runs.transition(run_id, RunStatus.RUNNING,
                                expected_from=(RunStatus.SUBMITTED, RunStatus.SUBMITTED))
            stale = uow.runs.begin_worker_generation(run_id)
            # A recovery bumps the generation, fencing the original worker.
            uow.runs.begin_worker_generation(run_id)
            uow.commit()

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        with pytest.raises(Exception, match="already finalised"):
            finalize(run_id, "succeeded", worker_generation=stale)

        with uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
        assert str(run.status) == "running", "stale generation must not transition"


class TestManifestMissingIntegrityData:
    """P2-C — absent plan/version/project records and missing run-step specs
    are manifest-integrity failures, not silently-empty canonical fields."""

    def test_missing_plan_version_record_fails(self, provisioned_project):
        project_id, _plan_id, _pv_id, run_id, root, uow_factory, _registry = provisioned_project
        from cardre.domain.run import RunStatus

        with uow_factory.for_project(project_id) as uow:
            uow.runs.transition(run_id, RunStatus.RUNNING,
                                expected_from=(RunStatus.SUBMITTED, RunStatus.SUBMITTED))
            uow.commit()

        class _NoPlanPlans:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def get_plan_id_for_version(self, plan_version_id):
                return None

        class _NoPlanUow:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                if name == "plans":
                    return _NoPlanPlans(self._inner.plans)
                return getattr(self._inner, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self._inner.__exit__(*exc)

            def close(self):
                self._inner.close()

        publisher = FsManifestPublisher(root)

        def factory():
            return _NoPlanUow(uow_factory.for_project(project_id))

        finalize = FinalizeRun(factory, publisher, _FakeClock())
        with pytest.raises(Exception, match="no plan record"):
            finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))
        assert publisher.read(run_id) is None

    def test_missing_run_step_spec_fails(self, provisioned_project):
        project_id, _plan_id, _pv_id, run_id, root, uow_factory, _registry = provisioned_project
        from cardre.domain.diagnostics import utc_now_iso
        from cardre.domain.run import RunStatus, RunStep, RunStepStatus

        with uow_factory.for_project(project_id) as uow:
            uow.runs.transition(run_id, RunStatus.RUNNING,
                                expected_from=(RunStatus.SUBMITTED, RunStatus.SUBMITTED))
            # Insert a run step whose step_id is NOT in the plan spec.
            uow.run_steps.insert(RunStep(
                run_step_id=f"{run_id}-ghost", run_id=run_id, step_id="ghost-step",
                plan_version_id=_pv_id, status=RunStepStatus.SUCCEEDED,
                started_at=utc_now_iso(), finished_at=utc_now_iso(),
                execution_fingerprint={"node_type": "test", "node_version": "1"},
            ))
            uow.commit()

        publisher = FsManifestPublisher(root)
        finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), publisher, _FakeClock())
        with pytest.raises(Exception, match="no plan specification"):
            finalize(run_id, "succeeded", worker_generation=_current_generation(uow_factory, project_id, run_id))
        assert publisher.read(run_id) is None
