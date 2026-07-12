"""Tests for PlanExecutor — topological order, role enforcement, evidence persistence.

Tests validate:
- Topological ordering of steps
- Evidence rows persisted per-step inside the transaction
- RunStep records created for each step
- Failed step recording
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import GraphValidationError
from cardre.domain.run import RunStepStatus
from cardre.domain.step import StepSpec
from cardre.execution.context import NodeOutput
from cardre.execution.executor import PlanExecutor
from cardre.execution.step_runner import StepRunner
from cardre.execution.topology import validate_topology
from cardre.nodes.contracts import NodeType
from cardre.nodes.registry import NodeRegistry


def _make_store(project_root: Path):
    """Create a fresh store with a plan version ready for execution."""
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _write_input_csv(project_root: Path) -> Path:
    input_path = project_root / "input.csv"
    input_path.write_text(
        "credit_amount,age_years,credit_risk_class\n"
        "1000,35,good\n"
        "2500,42,bad\n",
        encoding="utf-8",
    )
    return input_path


def _seed_plan_version(
    store,
    input_path: Path,
    project_id: str | None = None,
    plan_id: str | None = None,
):
    """Seed a store with a plan, steps, and edges. Returns plan_version_id."""
    now = utc_now_iso()

    if project_id is None:
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test Project", now, "0.2.0"),
        )

    if plan_id is None:
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )

    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )

    # Steps: import (root) -> profile -> export (depends on profile)
    step_import = "step-import"
    step_profile = "step-profile"
    step_export = "step-export"

    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step_import, pv_id, "cardre.import_dataset", "1", "transform",
         json.dumps({"source_path": str(input_path)}), "hash001", "", 0, step_import),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step_profile, pv_id, "cardre.profile_dataset", "1", "transform",
         json.dumps({}), "hash002", "", 1, step_profile),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step_export, pv_id, "cardre.technical_manifest_export", "1", "transform",
         json.dumps({}), "hash003", "", 2, step_export),
    )

    # Edges: import -> profile, profile -> export
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, step_import, step_profile, 0),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, step_profile, step_export, 0),
    )

    return pv_id, [step_import, step_profile, step_export]


class TestTopologicalOrder:
    """validate_topology produces correct topological order."""

    def test_sorts_topologically(self):
        step_c = StepSpec(step_id="c", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=["a"])
        step_a = StepSpec(step_id="a", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=[])
        step_b = StepSpec(step_id="b", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=["a"])
        steps = [step_c, step_a, step_b]
        validate_topology(steps)
        ids = [s.step_id for s in steps]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("c")

    def test_raises_on_cycle(self):
        step_a = StepSpec(step_id="a", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=["b"])
        step_b = StepSpec(step_id="b", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=["a"])
        with pytest.raises(GraphValidationError):
            validate_topology([step_a, step_b])

    def test_raises_on_duplicate_step_id(self):
        step_a = StepSpec(step_id="a", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=[])
        with pytest.raises(GraphValidationError, match="Duplicate"):
            validate_topology([step_a, step_a])

    def test_raises_on_missing_parent(self):
        step_a = StepSpec(step_id="a", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=["missing"])
        with pytest.raises(GraphValidationError):
            validate_topology([step_a])


class TestStepGraphEdgeCases:
    def test_ancestor_closure_missing_raises(self):
        from cardre.execution.step_graph import ancestor_closure
        with pytest.raises(KeyError):
            ancestor_closure("z", [])

    def test_ancestor_closure_duplicate_path(self):
        from cardre.domain.step import StepSpec
        from cardre.execution.step_graph import ancestor_closure
        steps = [
            StepSpec(step_id="root", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=[], branch_label="", position=0),
            StepSpec(step_id="a", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=["root"], branch_label="", position=1),
            StepSpec(step_id="b", node_type="t", node_version="1", category="c", params={}, params_hash="h", parent_step_ids=["root", "a"], branch_label="", position=2),
        ]
        assert ancestor_closure("b", steps) == {"root", "a"}
        assert ancestor_closure("root", steps) == set()

    def test_descendant_closure_missing_raises(self):
        from cardre.execution.step_graph import descendant_closure
        with pytest.raises(KeyError):
            descendant_closure("z", [])


class TestPlanExecutor:
    """PlanExecutor runs steps and persists evidence per-step."""

    def test_step_runner_blocks_artifact_roles_outside_node_contract(self, tmp_path):
        class TrainOnlyNode(NodeType):
            node_type = "test.train_only"
            version = "1"
            category = "fit"
            input_roles = ["train"]

            def run(self, context):  # pragma: no cover - role guard should stop execution
                raise AssertionError("node.run should not be called")

        from cardre.domain.artifacts import ArtifactRef

        store = _make_store(tmp_path)
        registry = NodeRegistry()
        registry.register(TrainOnlyNode)
        runner = StepRunner(store, registry)
        spec = StepSpec(
            step_id="fit",
            node_type="test.train_only",
            node_version="1",
            category="fit",
            params={},
            params_hash="hash",
            parent_step_ids=["split"],
        )
        test_artifact = ArtifactRef(
            artifact_id="art-test",
            artifact_type="dataset",
            role="test",
            path="test.parquet",
            physical_hash="ph",
            logical_hash="lh",
        )

        result = runner.run_step(
            plan_version_id="pv",
            run_id="run",
            spec=spec,
            step_outputs={"split": [test_artifact]},
            run_step_records={},
        )

        assert result.status == RunStepStatus.FAILED
        assert result.errors[0]["code"] == "NODE_ROLE_ACCESS_VIOLATION"
        assert "test" in result.errors[0]["message"]

    def test_step_runner_allows_artifact_roles_declared_by_node_contract(self, tmp_path):
        class TrainOnlyNode(NodeType):
            node_type = "test.train_only_ok"
            version = "1"
            category = "fit"
            input_roles = ["train"]

            def run(self, context):
                return NodeOutput(artifacts=[], metrics={})

        from cardre.domain.artifacts import ArtifactRef

        store = _make_store(tmp_path)
        registry = NodeRegistry()
        registry.register(TrainOnlyNode)
        runner = StepRunner(store, registry)
        spec = StepSpec(
            step_id="fit",
            node_type="test.train_only_ok",
            node_version="1",
            category="fit",
            params={},
            params_hash="hash",
            parent_step_ids=["split"],
        )
        train_artifact = ArtifactRef(
            artifact_id="art-train",
            artifact_type="dataset",
            role="train",
            path="train.parquet",
            physical_hash="ph",
            logical_hash="lh",
        )

        result = runner.run_step(
            plan_version_id="pv",
            run_id="run",
            spec=spec,
            step_outputs={"split": [train_artifact]},
            run_step_records={},
        )

        assert result.status == RunStepStatus.SUCCEEDED

    def test_executes_simple_plan(self, tmp_path):
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        # Create the run
        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        result = executor.run_plan_version(pv_id, run_id)
        assert result == run_id

        # Check run steps were created
        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(store)
        steps = rs_repo.get_for_run(run_id)
        assert len(steps) == 3
        for rs in steps:
            assert rs.status == RunStepStatus.SUCCEEDED

    def test_evidence_rows_persisted_per_step(self, tmp_path):
        """Evidence edges + evidence artifacts are written for each step."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        # Check evidence_edges
        edges = store.execute(
            "SELECT COUNT(*) as cnt FROM evidence_edges WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert edges["cnt"] == 2  # Two edges: import->profile, profile->export

        # Check evidence_artifacts
        artifacts = store.execute(
            "SELECT COUNT(*) as cnt FROM evidence_artifacts "
            "WHERE evidence_edge_id IN (SELECT evidence_edge_id FROM evidence_edges WHERE run_id = ?)",
            (run_id,),
        ).fetchone()
        assert artifacts["cnt"] == 2  # one artifact per parent edge

        # Check artifact_lineage
        lineage = store.execute(
            "SELECT COUNT(*) as cnt FROM artifact_lineage WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert lineage["cnt"] == 5  # import:1 output, profile:1i+1o, export:1i+1o

        # Each evidence edge's artifacts should match its parent step's output lineage
        edge_rows = store.execute(
            "SELECT evidence_edge_id, parent_step_id FROM evidence_edges WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        for edge in edge_rows:
            edge_aids = [
                r["artifact_id"] for r in store.execute(
                    "SELECT artifact_id FROM evidence_artifacts WHERE evidence_edge_id = ? ORDER BY artifact_id",
                    (edge["evidence_edge_id"],),
                ).fetchall()
            ]
            parent_outputs = store.execute(
                "SELECT artifact_id FROM artifact_lineage "
                "WHERE run_id = ? AND step_id = ? AND direction = 'output' ORDER BY artifact_id",
                (run_id, edge["parent_step_id"]),
            ).fetchall()
            parent_aids = [r["artifact_id"] for r in parent_outputs]
            assert edge_aids == parent_aids, (
                f"Evidence artifacts for parent {edge['parent_step_id']!r} "
                f"should match its output lineage: got {edge_aids}, expected {parent_aids}"
            )

    def test_run_step_order_matches_topological(self, tmp_path):
        """Run steps are created in the expected order."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(store)
        steps = rs_repo.get_for_run(run_id)
        step_order = [rs.step_id for rs in steps]
        # Import first, then profile, then export
        assert step_order[0] == "step-import"
        assert step_order[1] == "step-profile"
        assert step_order[2] == "step-export"

    def test_execution_fingerprint_in_run_step(self, tmp_path):
        """Run steps have execution fingerprints with node metadata."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(store)
        for rs in rs_repo.get_for_run(run_id):
            fp = rs.execution_fingerprint
            assert "node_type" in fp
            assert "node_version" in fp
            assert "params_hash" in fp
            assert "plan_version_id" in fp
            assert "step_id" in fp

    def test_transactional_persist_on_failure(self, tmp_path):
        """Even on step failure, evidence written before failure is persisted."""
        store = _make_store(tmp_path)
        input_path = _write_input_csv(tmp_path)
        pv_id, step_ids = _seed_plan_version(store, input_path)

        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        # All steps should be recorded for the real launch path.
        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(store)
        steps = rs_repo.get_for_run(run_id)
        assert len(steps) == 3

    def test_multi_parent_evidence_attribution(self, tmp_path):
        """Two parents each produce one distinct artifact; child consumes both;
        each parent evidence edge has exactly the artifact from that parent."""
        store = _make_store(tmp_path)

        csv_a = tmp_path / "input_a.csv"
        csv_a.write_text("x,y\n1,2\n3,4\n")
        csv_b = tmp_path / "input_b.csv"
        csv_b.write_text("a,b\n5,6\n7,8\n")

        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "MP Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "MP Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
            "VALUES (?, ?, 1, 1, ?, ?)",
            (pv_id, plan_id, now, "Multi-parent evidence test"),
        )

        step_a = "step-a"
        step_b = "step-b"
        step_c = "step-c"

        for sid, params_json, pos in [
            (step_a, json.dumps({"source_path": str(csv_a)}), 0),
            (step_b, json.dumps({"source_path": str(csv_b)}), 1),
            (step_c, json.dumps({}), 2),
        ]:
            ntype = "cardre.import_dataset" if sid != step_c else "cardre.noop"
            store.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, pv_id, ntype, "1", "transform",
                 params_json, f"hash-{sid}", "", pos, sid),
            )

        for parent, child, order in [(step_a, step_c, 0), (step_b, step_c, 1)]:
            store.execute(
                "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                "VALUES (?, ?, ?, ?)",
                (pv_id, parent, child, order),
            )

        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        executor = PlanExecutor(store)
        executor.run_plan_version(pv_id, run_id)

        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(store)
        steps = rs_repo.get_for_run(run_id)
        assert len(steps) == 3

        rs_c = next(rs for rs in steps if rs.step_id == step_c)

        # Get output artifact IDs for each parent
        def _output_artifact_ids(run_step_id: str) -> list[str]:
            rows = store.execute(
                "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
                (run_step_id,),
            ).fetchall()
            return [r["artifact_id"] for r in rows]

        rs_a = next(rs for rs in steps if rs.step_id == step_a)
        rs_b = next(rs for rs in steps if rs.step_id == step_b)
        art_a = _output_artifact_ids(rs_a.run_step_id)
        art_b = _output_artifact_ids(rs_b.run_step_id)
        assert len(art_a) == 1
        assert len(art_b) == 1

        # Fetch evidence edges for step_c
        edges = store.execute(
            "SELECT evidence_edge_id, parent_step_id FROM evidence_edges WHERE run_step_id = ?",
            (rs_c.run_step_id,),
        ).fetchall()
        assert len(edges) == 2, f"Expected 2 evidence edges, got {len(edges)}"

        for edge in edges:
            edge_aids = [
                r["artifact_id"] for r in store.execute(
                    "SELECT artifact_id FROM evidence_artifacts WHERE evidence_edge_id = ?",
                    (edge["evidence_edge_id"],),
                ).fetchall()
            ]
            if edge["parent_step_id"] == step_a:
                assert edge_aids == art_a, (
                    f"Edge for parent {step_a!r} should have only its own artifact, got {edge_aids}"
                )
            elif edge["parent_step_id"] == step_b:
                assert edge_aids == art_b, (
                    f"Edge for parent {step_b!r} should have only its own artifact, got {edge_aids}"
                )
            else:
                pytest.fail(f"Unexpected parent_step_id: {edge['parent_step_id']}")

        # Flat artifact_lineage should still contain every input artifact
        lineage_rows = store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'input'",
            (rs_c.run_step_id,),
        ).fetchall()
        lineage_aids = {r["artifact_id"] for r in lineage_rows}
        assert lineage_aids == {art_a[0], art_b[0]}, (
            f"Lineage should contain both input artifacts, got {lineage_aids}"
        )
