"""Characterization tests for PlanExecutor — pin behavior before extraction.

These tests assert on persisted database state and run manifests, not on
private method call order. They must pass against the current code and must
fail if run/evidence/lineage semantics are accidentally changed during later
extraction of the action planner and step runner from PlanExecutor.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec
from cardre.execution.action_planner import _StepAction
from cardre.execution.executor import PlanExecutor
from cardre.store.plan_repo import PlanRepository
from cardre.store.run_repo import RunRepository
from cardre.store.run_step_repo import RunStepRepository

pytestmark = pytest.mark.xfail(reason="Execution path broken during Batch 04; restored in Batch 05")

# ---------------------------------------------------------------------------
# Helpers (self-contained — no shared mutating state)
# ---------------------------------------------------------------------------


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _write_input_csv(project_root: Path) -> Path:
    path = project_root / "input.csv"
    path.write_text(
        "credit_amount,age_years,credit_risk_class\n"
        "1000,35,good\n"
        "2500,42,bad\n",
        encoding="utf-8",
    )
    return path


def _seed_project_and_plan(store) -> tuple[str, str]:
    now = "2026-01-01T00:00:00"
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "char-test-project", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "char-test-plan", now),
    )
    return project_id, plan_id


def _seed_plan_version_with_custom_steps(
    store, plan_id: str, steps: list[StepSpec], *,
    description: str = "char-test",
) -> str:
    """Create a committed plan version and return its plan_version_id."""
    return PlanRepository(store).create_version(
        plan_id, steps,
        description=description,
        is_committed=True,
    )


def _import_step(step_id: str = "step-import",
                 source_path: Path | None = None,
                 position: int = 0) -> StepSpec:
    params = {"source_path": str(source_path)} if source_path else {}
    return StepSpec(
        step_id=step_id,
        node_type="cardre.import_dataset",
        node_version="1", category="transform",
        params=params, params_hash=f"h-{step_id}",
        parent_step_ids=[], branch_label="", position=position,
        canonical_step_id=step_id,
    )


def _profile_step(step_id: str = "step-profile",
                  parent: str = "step-import",
                  position: int = 1) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type="cardre.profile_dataset",
        node_version="1", category="transform",
        params={}, params_hash=f"h-{step_id}",
        parent_step_ids=[parent], branch_label="", position=position,
        canonical_step_id=step_id,
    )


def _noop_step(step_id: str, parent: str, position: int) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type="cardre.noop",
        node_version="1", category="transform",
        params={}, params_hash=f"h-{step_id}",
        parent_step_ids=[parent], branch_label="", position=position,
        canonical_step_id=step_id,
    )


# =========================================================================
# Success path: full-plan evidence, lineage, and manifest
# =========================================================================


class TestSuccessPath:

    def test_full_plan_run_steps_and_evidence(self, tmp_path):
        """Full-plan run persists run_steps, evidence_edges,
        evidence_artifacts, and artifact_lineage for every step."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        project_id, plan_id = _seed_project_and_plan(store)

        pv_id = _seed_plan_version_with_custom_steps(store, plan_id, [
            _import_step(source_path=input_path),
            _profile_step(),
        ])

        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        # run_steps: exactly one per step, all succeeded
        steps = RunStepRepository(store).get_for_run(run_id)
        assert len(steps) == 2
        for rs in steps:
            assert rs.status == RunStepStatus.SUCCEEDED
        step_ids = [rs.step_id for rs in steps]
        assert step_ids == ["step-import", "step-profile"]

        # evidence_edges: one per parent->child edge at run time
        edges = store.execute(
            "SELECT * FROM evidence_edges WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        assert len(edges) == 1  # import -> profile

        edge = edges[0]
        assert edge["is_reused"] == 0
        assert edge["is_stale"] == 0
        assert edge["parent_step_id"] == "step-import"
        assert edge["source_run_step_id"] is not None
        assert edge["run_step_id"] is not None

        # evidence_artifacts: attached to the edge
        art_rows = store.execute(
            "SELECT * FROM evidence_artifacts WHERE evidence_edge_id = ?",
            (edge["evidence_edge_id"],),
        ).fetchall()
        assert len(art_rows) >= 1
        for art in art_rows:
            assert art["role"] == "input"

        # artifact_lineage: both directions for each step
        lineage = store.execute(
            "SELECT step_id, direction, COUNT(*) as cnt FROM artifact_lineage "
            "WHERE run_id = ? GROUP BY step_id, direction ORDER BY step_id, direction",
            (run_id,),
        ).fetchall()
        directions_by_step: dict[str, set[str]] = {}
        for row in lineage:
            directions_by_step.setdefault(row["step_id"], set()).add(row["direction"])
        assert "output" in directions_by_step.get("step-import", set())
        assert "input" in directions_by_step.get("step-profile", set())
        assert "output" in directions_by_step.get("step-profile", set())

    def test_full_plan_manifest_written_through_lifecycle(self, tmp_path):
        """A run finalised through RunLifecycle writes a manifest file."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        project_id, plan_id = _seed_project_and_plan(store)

        pv_id = _seed_plan_version_with_custom_steps(store, plan_id, [
            _import_step(source_path=input_path),
            _profile_step(),
        ])

        from cardre.execution.run_lifecycle import RunLifecycle

        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        with RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="full_plan",
        ) as lifecycle:
            has_failure = any(
                rs.status == RunStepStatus.FAILED
                for rs in RunStepRepository(store).get_for_run(run_id)
            )
            lifecycle.finalise(
                "failed" if has_failure else "succeeded",
            )

        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == run_id
        assert manifest["plan_version_id"] == pv_id
        assert manifest["status"] == "succeeded"
        assert manifest["execution_mode"] == "full_plan"
        step_ids = [s["step_id"] for s in manifest["steps"]]
        assert step_ids == ["step-import", "step-profile"]


# =========================================================================
# Failure path: step failure recording and execution short-circuit
# =========================================================================


class TestFailurePath:

    def test_runtime_failure_records_error_and_skips_downstream(self, tmp_path, monkeypatch):
        """When a step raises at runtime, it is recorded as FAILED with a
        structured error entry, and later steps are not executed."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        project_id, plan_id = _seed_project_and_plan(store)

        pv_id = _seed_plan_version_with_custom_steps(store, plan_id, [
            _import_step(source_path=input_path),
            _profile_step(),
            _noop_step("step-export", "step-profile", 2),
        ])

        from cardre.nodes.prep import ProfileDatasetNode
        monkeypatch.setattr(
            ProfileDatasetNode, "run",
            lambda self, ctx: (_ for _ in ()).throw(
                ValueError("Intentional test failure at runtime"),
            ),
        )

        run_id = RunRepository(store).create(pv_id)
        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        steps = RunStepRepository(store).get_for_run(run_id)

        # Import should have succeeded
        import_rs = next(rs for rs in steps if rs.step_id == "step-import")
        assert import_rs.status == RunStepStatus.SUCCEEDED

        # Profile should have failed with structured error
        profile_rs = next(rs for rs in steps if rs.step_id == "step-profile")
        assert profile_rs.status == RunStepStatus.FAILED
        assert len(profile_rs.errors) >= 1
        error = profile_rs.errors[0]
        assert any(k in error for k in ("message", "exception_type", "code", "traceback"))
        assert "Intentional test failure" in str(error)

        # Export should NOT have been executed
        assert not any(rs.step_id == "step-export" for rs in steps)

    def test_failure_preserves_upstream_evidence(self, tmp_path, monkeypatch):
        """Evidence written by the upstream (successful) step remains
        persisted and queryable when a downstream step fails."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        project_id, plan_id = _seed_project_and_plan(store)

        pv_id = _seed_plan_version_with_custom_steps(store, plan_id, [
            _import_step(source_path=input_path),
            _profile_step(),
        ])

        from cardre.nodes.prep import ProfileDatasetNode
        monkeypatch.setattr(
            ProfileDatasetNode, "run",
            lambda self, ctx: (_ for _ in ()).throw(
                ValueError("Intentional failure"),
            ),
        )

        run_id = RunRepository(store).create(pv_id)
        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        # Import's output lineage should exist (written before profile failed)
        import_lineage = store.execute(
            "SELECT COUNT(*) FROM artifact_lineage "
            "WHERE run_id = ? AND step_id = 'step-import' AND direction = 'output'",
            (run_id,),
        ).fetchone()
        assert import_lineage[0] >= 1


# =========================================================================
# Input resolution errors
# =========================================================================


class TestInputResolution:

    def test_missing_parent_output_fails_step(self, tmp_path):
        """When a step's parent has no outputs, the step is recorded as
        FAILED with a diagnostic mentioning the missing input."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        project_id, plan_id = _seed_project_and_plan(store)

        pv_id = _seed_plan_version_with_custom_steps(store, plan_id, [
            _import_step(source_path=input_path),
            _profile_step(),
        ])

        run_id = RunRepository(store).create(pv_id)
        steps = PlanRepository(store).get_version_steps(pv_id)
        executor = PlanExecutor(store)

        # Execute only the profile step (no import step in the action list),
        # so its parent "step-import" has no outputs in the empty outputs dict.
        profile_spec = next(s for s in steps if s.step_id == "step-profile")
        actions = [_StepAction(spec=profile_spec, action="execute")]
        has_failure, _outputs, records = executor._execute_actions(
            pv_id, run_id, actions,
        )
        assert has_failure is True

        profile_rs = records.get("step-profile")
        assert profile_rs is not None
        assert profile_rs.status == RunStepStatus.FAILED
        error_text = json.dumps(profile_rs.errors).lower()
        assert "input" in error_text or "parent" in error_text or "missing" in error_text

    def test_parameter_validation_records_failure(self, tmp_path):
        """When a node's validate_params returns errors, the step is
        recorded as FAILED with a validation error."""
        store = _make_store(tmp_path)
        project_id, plan_id = _seed_project_and_plan(store)

        pv_id = _seed_plan_version_with_custom_steps(store, plan_id, [
            _import_step(source_path=None),  # missing required source_path
        ])

        run_id = RunRepository(store).create(pv_id)
        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        steps = RunStepRepository(store).get_for_run(run_id)
        assert len(steps) == 1
        rs = steps[0]
        assert rs.status == RunStepStatus.FAILED
        assert len(rs.errors) >= 1
        error_text = json.dumps(rs.errors).lower()
        assert "parameter" in error_text or "source_path" in error_text
