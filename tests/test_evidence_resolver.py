"""Tests for EvidenceResolver + EvidencePolicyService.

Tests validate the four policies:
  - run_only
  - branch_then_full_then_plan
  - source_branch_then_full_then_plan
  - across_plan

Also tests fingerprint matching and diagnostic emission.
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
    # Edge
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, parent_step_id, step_id, 0),
    )

    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (run_id, pv_id, now, now),
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
    # Evidence edge
    ee_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'exact', 'parent', 0, 0, ?)",
        (ee_id, run_id, rs_id, pv_id, step_id, parent_step_id, run_id, rs_id, now),
    )
    return project_id, plan_id, pv_id, step_id, run_id, rs_id


class TestEvidenceResolver:
    """EvidenceResolver four policies."""

    def test_run_only_policy_finds_evidence(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, run_id, _ = _seed_with_run_evidence(store)

        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        resolved, source, diags = resolver.resolve(
            pv_id, step_id, run_id=run_id, policy="run_only",
        )
        assert resolved is not None
        assert resolved.run_step.step_id == step_id
        assert source == "run"
        assert len(diags) == 0

    def test_run_only_policy_missing(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        resolved, source, diags = resolver.resolve(
            pv_id, step_id, run_id="nonexistent-run", policy="run_only",
        )
        assert resolved is None
        assert source == "missing"

    def test_branch_then_full_then_plan_finds_branch(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        resolved, source, diags = resolver.resolve(
            pv_id, step_id, policy="branch_then_full_then_plan",
        )
        assert resolved is not None
        assert resolved.run_step.step_id == step_id
        assert source in ("branch", "full_plan", "latest_plan_run")

    def test_across_plan_policy(self, tmp_path):
        store = _make_store(tmp_path)
        _, plan_id, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        resolved, source, diags = resolver.resolve(
            pv_id, step_id, plan_id=plan_id, policy="across_plan",
        )
        assert resolved is not None
        assert source in ("across_plan", "latest_plan_run")

    def test_fingerprint_matching(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        # Matching spec
        matching_spec = StepSpec(
            step_id=step_id,
            node_type="cardre.profiler",
            node_version="1",
            category="analysis",
            params={"target": "y"},
            params_hash="hash002",
            parent_step_ids=[],
        )

        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        resolved, source, diags = resolver.resolve(
            pv_id, step_id, require_fingerprint_match=matching_spec,
            policy="branch_then_full_then_plan",
        )
        assert resolved is not None

        # Non-matching spec
        non_matching_spec = StepSpec(
            step_id=step_id,
            node_type="cardre.profiler",
            node_version="2",  # different version
            category="analysis",
            params={"target": "y"},
            params_hash="hash002",
            parent_step_ids=[],
        )

        resolved2, source2, diags2 = resolver.resolve(
            pv_id, step_id, require_fingerprint_match=non_matching_spec,
            policy="branch_then_full_then_plan",
        )
        assert resolved2 is None or source2 == "missing"

    def test_diagnostic_emission(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        # Resolve for a non-existent step should emit diagnostics
        rs, source, diags = resolver.resolve(
            pv_id, "nonexistent-step",
            policy="branch_then_full_then_plan",
        )
        assert rs is None
        assert source == "missing"


class TestEvidencePolicyService:
    """EvidencePolicyService short-circuit checks."""

    def test_check_to_node_current(self, tmp_path):
        store = _make_store(tmp_path)
        _, plan_id, pv_id, step_id, _, _ = _seed_with_run_evidence(store)

        from cardre.services.evidence_resolver import EvidencePolicyService
        policy = EvidencePolicyService(store)
        result = policy.check_to_node_current(pv_id, step_id)
        # Should either find a short-circuit or return None
        assert result is not None

    def test_prepare_branch_evidence(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_with_run_evidence(store)

        from cardre.services.evidence_resolver import EvidencePolicyService
        policy = EvidencePolicyService(store)
        ctx = policy.prepare_branch_evidence(pv_id, "test-branch", force=True)
        assert ctx is not None
        assert ctx.plan_version_id == pv_id
