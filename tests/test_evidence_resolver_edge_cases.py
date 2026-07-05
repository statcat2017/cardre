from __future__ import annotations

import json
import uuid
from pathlib import Path

from cardre.domain.diagnostics import utc_now_iso


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_basic_evidence(store):
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
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
        "VALUES (?, ?, ?, 0)",
        (pv_id, parent_step_id, step_id),
    )
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )
    rs_root = str(uuid.uuid4())
    fp_root = json.dumps({
        "params_hash": "hash001", "node_type": "cardre.file_import",
        "node_version": "1", "output_artifact_logical_hashes": ["out1"],
    })
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?)",
        (rs_root, run_id, parent_step_id, pv_id, now, now, fp_root),
    )
    rs_id = str(uuid.uuid4())
    fp = json.dumps({
        "params_hash": "hash002", "node_type": "cardre.profiler",
        "node_version": "1", "output_artifact_logical_hashes": ["abc123"],
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


class TestEvidenceResolverEdgeCases:
    def test_resolve_missing_step(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(pv_id, "nonexistent", policy="branch_then_full_then_plan")
        assert rs is None
        assert source == "missing"

    def test_resolve_with_run_only_missing(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(pv_id, "step-a", run_id="nonexistent", policy="run_only")
        assert rs is None
        assert source == "missing"

    def test_source_branch_then_full_then_plan(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(pv_id, step_id, policy="source_branch_then_full_then_plan")
        assert rs is not None
        assert source in ("full_plan", "branch", "latest_plan_run", "across_plan")

    def test_resolve_with_branch_id(self, tmp_path):
        store = _make_store(tmp_path)
        project_id, plan_id, pv_id, step_id, _, _ = _seed_basic_evidence(store)

        from cardre.store.branch_repo import BranchRepository
        branches_repo = BranchRepository(store)
        branch_id = branches_repo.create_branch(
            project_id, plan_id, "test-branch", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, step_id, branch_id=branch_id, policy="branch_then_full_then_plan",
        )
        assert rs is not None


class TestEvidencePolicyService:
    def test_check_branch_current_no_branch(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidencePolicyService
        policy = EvidencePolicyService(store)
        result = policy.check_branch_current(pv_id, "nonexistent-branch")
        assert result.status in ("not_found", "missing")

    def test_prepare_branch_context_with_force(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidencePolicyService
        policy = EvidencePolicyService(store)
        ctx = policy.prepare_branch_evidence(pv_id, "test-branch", force=True)
        assert ctx is not None
        assert ctx.plan_version_id == pv_id

    def test_check_to_node_current_no_evidence(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidencePolicyService
        policy = EvidencePolicyService(store)
        result = policy.check_to_node_current(pv_id, "nonexistent-step")
        assert result is not None

    def test_prepare_branch_context_no_force(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidencePolicyService
        policy = EvidencePolicyService(store)
        ctx = policy.prepare_branch_evidence(pv_id, "test-branch", force=False)
        assert ctx is not None


class TestEvidenceResolverAdvancedPolicies:
    def test_resolve_across_plan_with_plan_id(self, tmp_path):
        store = _make_store(tmp_path)
        _, plan_id, pv_id, step_id, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, step_id, plan_id=plan_id, policy="across_plan",
        )
        assert rs is not None
        assert source in ("across_plan", "latest_plan_run")

    def test_resolve_source_branch_with_source_branch_id(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, step_id, source_branch_id="nonexistent-branch",
            policy="source_branch_then_full_then_plan",
        )
        # Should fall back to full plan or across_plan since branch has no evidence
        assert rs is not None or source == "missing"

    def test_resolve_unknown_policy_returns_missing(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(pv_id, "step", policy="unknown_policy")
        assert rs is None
        assert source == "missing"

    def test_resolve_run_only_none_run_id(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, _, _, _ = _seed_basic_evidence(store)
        from cardre.services.evidence_resolver import EvidenceResolver
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(pv_id, "step", run_id=None, policy="run_only")
        assert rs is None
        assert source == "missing"

    def test_resolve_with_fingerprint_match(self, tmp_path):
        store = _make_store(tmp_path)
        _, _, pv_id, step_id, _, _ = _seed_basic_evidence(store)
        from cardre.domain.step import StepSpec
        from cardre.services.evidence_resolver import EvidenceResolver
        matching_spec = StepSpec(
            step_id=step_id, node_type="cardre.profiler", node_version="1",
            category="analysis", params={"target": "y"}, params_hash="hash002",
            parent_step_ids=[],
        )
        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, step_id, require_fingerprint_match=matching_spec,
            policy="branch_then_full_then_plan",
        )
        assert rs is not None
