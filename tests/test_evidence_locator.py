"""Direct tests for EvidenceLocator — the single evidence lookup path.

Tests the canonical fallback chain (edge-walking → plan-level → across-plan),
fingerprint matching, and ``ResolvedEvidence`` assembly.  Uses a real
``ProjectStore`` + SQLite, mirroring the seeding pattern in
``test_evidence_resolver.py``.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.step import StepSpec


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_with_run_evidence(store, plan_id: str | None = None):
    """Seed a complete plan with run/step/evidence rows.

    Returns (project_id, plan_id, pv_id, step_id, run_id, run_step_id).
    """
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    if plan_id is None:
        plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    step_id = "step-a"
    parent_step_id = "step-root"
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (parent_step_id, pv_id, "cardre.file_import", "1", "load",
         json.dumps({"path": "data.csv"}), "hash001", "", 0, parent_step_id),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step_id, pv_id, "cardre.profiler", "1", "analysis",
         json.dumps({"target": "y"}), "hash002", "", 1, step_id),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, parent_step_id, step_id, 0),
    )

    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )
    rs_root = str(uuid.uuid4())
    fp_root = json.dumps({
        "params_hash": "hash001",
        "node_type": "cardre.file_import",
        "node_version": "1",
        "output_artifact_logical_hashes": ["out1"],
    })
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
        (rs_root, run_id, parent_step_id, pv_id, now, now, fp_root),
    )
    rs_id = str(uuid.uuid4())
    fp = json.dumps({
        "params_hash": "hash002",
        "node_type": "cardre.profiler",
        "node_version": "1",
        "output_artifact_logical_hashes": ["abc123"],
    })
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
        (rs_id, run_id, step_id, pv_id, now, now, fp),
    )
    ee_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'parent', 0, 0, ?)",
        (ee_id, run_id, rs_id, pv_id, step_id, parent_step_id, run_id, rs_root, now),
    )
    return project_id, plan_id, pv_id, step_id, run_id, rs_id


def _matching_spec(step_id: str) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type="cardre.profiler",
        node_version="1",
        category="analysis",
        params={"target": "y"},
        params_hash="hash002",
        parent_step_ids=[],
    )


def _non_matching_spec(step_id: str) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type="cardre.profiler",
        node_version="2",
        category="analysis",
        params={"target": "y"},
        params_hash="hash002",
        parent_step_ids=[],
    )


class TestEvidenceLocatorResolve:
    """Edge-walking fallback, fingerprint matching, ResolvedEvidence assembly."""

    def test_resolves_via_edge_walking(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, rs_id = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, step_id)

        assert resolved is not None
        assert resolved.run_step.step_id == step_id
        assert resolved.run_step.run_step_id == rs_id
        assert len(resolved.edges) >= 1
        assert resolved.edges[0].step_id == step_id

    def test_returns_none_for_missing_step(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, "nonexistent-step")
        assert resolved is None

    def test_fingerprint_match_accepts_current_spec(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, step_id, fingerprint_match=_matching_spec(step_id))
        assert resolved is not None
        assert resolved.run_step.step_id == step_id

    def test_fingerprint_mismatch_skips_candidate(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, step_id, fingerprint_match=_non_matching_spec(step_id))
        assert resolved is None

    def test_fingerprint_none_accepts_anything(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, step_id, fingerprint_match=None)
        assert resolved is not None

    def test_resolved_evidence_bundles_edges_and_artifacts(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, rs_id = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, step_id)

        assert resolved is not None
        assert resolved.run_step_id == rs_id
        assert all(e.run_step_id == rs_id for e in resolved.edges)


class TestEvidenceLocatorFallback:
    """Branch → full-plan → plan-level fallback chain."""

    def test_falls_back_to_plan_level_run_when_no_edge(self, tmp_path):
        """When evidence_edges has no row for (pv_id, step_id),
        the locator falls back to the plan-level run (branch_id IS NULL)
        and scans its run_steps."""
        store = _make_store(tmp_path)
        _, plan_id, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        # Delete the evidence edge so edge-walking finds nothing.
        store.execute("DELETE FROM evidence_edges WHERE step_id = ?", (step_id,))

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, step_id)

        # Should still find the run-step via the plan-level run fallback.
        assert resolved is not None
        assert resolved.run_step.step_id == step_id

    def test_falls_back_to_across_plan_when_no_plan_level_run(self, tmp_path):
        """When the plan_version has no successful run at all, but the plan
        has a successful run on a different plan_version, the across-plan
        fallback finds the run-step."""
        store = _make_store(tmp_path)

        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Plan", now),
        )

        # Two plan versions: pv_old (has a successful run), pv_new (no run).
        pv_old = str(uuid.uuid4())
        pv_new = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_old, plan_id, now),
        )
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 2, 1, ?)",
            (pv_new, plan_id, now),
        )

        step_id = "step-x"
        for pv_id in (pv_old, pv_new):
            store.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                " params_json, params_hash, branch_label, position, canonical_step_id) "
                "VALUES (?, ?, 'cardre.profiler', '1', 'analysis', '{}', 'hx', '', 0, ?)",
                (step_id, pv_id, step_id),
            )

        # Successful run only on pv_old.
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', ?, ?, ?)",
            (run_id, pv_old, now, now, now),
        )
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
            (rs_id, run_id, step_id, pv_old, now, now, json.dumps({"params_hash": "hx"})),
        )

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        # pv_new has no run and no edge; across-plan fallback should find
        # the run-step from pv_old via plan_id.
        resolved = locator.resolve(pv_new, step_id, plan_id=plan_id)
        assert resolved is not None
        assert resolved.run_step.step_id == step_id
        assert resolved.run_step.run_step_id == rs_id

    def test_returns_none_when_no_evidence_anywhere(self, tmp_path):
        store = _make_store(tmp_path)
        _, plan_id, pv_id, _, _, _ = _seed_with_run_evidence(store)

        # Delete all run_steps and runs to simulate no evidence.
        store.execute("DELETE FROM run_steps")
        store.execute("DELETE FROM runs")
        store.execute("DELETE FROM evidence_edges")

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve(pv_id, "step-a", plan_id=plan_id)
        assert resolved is None


class TestEvidenceLocatorResolveForRun:
    """The run_only policy — scoped to a single run, no fallback."""

    def test_resolve_for_run_finds_step(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, run_id, _ = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve_for_run(run_id, step_id)
        assert resolved is not None
        assert resolved.run_step.step_id == step_id

    def test_resolve_for_run_missing_run(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve_for_run("nonexistent-run", step_id)
        assert resolved is None

    def test_resolve_for_run_missing_step(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, run_id, _ = _seed_with_run_evidence(store)

        from cardre.evidence_locator import EvidenceLocator
        locator = EvidenceLocator(store)
        resolved = locator.resolve_for_run(run_id, "nonexistent-step")
        assert resolved is None
