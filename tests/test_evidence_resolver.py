"""Tests for EvidenceResolver fallback policies."""

from __future__ import annotations

from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    StepSpec,
    json_logical_hash,
)
from cardre.artifacts import write_json_artifact
from cardre.evidence_resolver import EvidenceResolver
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry

import pytest

from tests.helpers import make_store


class SimpleSource(NodeType):
    node_type = "cardre.test.evidence_source"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["artifact"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        art = write_json_artifact(
            context.store, artifact_type="report", role="artifact",
            stem=f"src-{context.step_spec.step_id}",
            payload={"step_id": context.step_spec.step_id},
            metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


def _make_step(step_id: str, params: dict | None = None) -> StepSpec:
    p = params or {}
    return StepSpec(
        step_id=step_id, node_type="cardre.test.evidence_source",
        node_version="1", category="transform",
        params=p, params_hash=json_logical_hash(p),
        parent_step_ids=[], branch_label="", position=0,
    )


def _run_plan(store, pv_id) -> str:
    reg = NodeRegistry()
    reg.register(SimpleSource)
    executor = PlanExecutor(reg)
    run_id = executor.run_plan_version(store, pv_id)
    assert store.get_run(run_id)["status"] == "succeeded"
    return run_id


class TestBranchThenFullThenPlan:
    """policy="branch_then_full_then_plan" — branch evidence first,
    then same-version full-plan, then latest plan-level run."""

    def test_branch_evidence_returns_branch_source(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("source")]
        pv_id = store.create_plan_version(plan_id, steps)
        _run_plan(store, pv_id)

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "source", branch_id=None, policy="branch_then_full_then_plan",
        )
        assert rs is not None
        assert source == "branch"
        assert len(diags) == 0

    def test_full_plan_fallback_when_no_branch_evidence(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("source")]
        pv_id = store.create_plan_version(plan_id, steps)
        _run_plan(store, pv_id)

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "source", branch_id="nonexistent-branch",
            policy="branch_then_full_then_plan",
        )
        assert rs is not None
        assert source == "full_plan"
        assert len(diags) == 0

    def test_missing_returns_none(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [_make_step("source")])

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "nonexistent", branch_id=None, policy="branch_then_full_then_plan",
        )
        assert rs is None
        assert source == "missing"


class TestSourceBranchThenFullThenPlan:
    """policy="source_branch_then_full_then_plan" — source branch first,
    baseline fallback emits INHERITED_BASELINE_EVIDENCE."""

    def test_no_source_branch_still_queries_full_plan(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("source")]
        pv_id = store.create_plan_version(plan_id, steps)
        _run_plan(store, pv_id)

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "source", plan_id=plan_id, source_branch_id=None,
            policy="source_branch_then_full_then_plan",
        )
        assert rs is not None
        assert source == "across_plan"

    def test_missing_emits_reuse_not_found(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [_make_step("source")])

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "nonexistent", plan_id=plan_id, source_branch_id="some-branch",
            policy="source_branch_then_full_then_plan",
        )
        assert rs is None
        assert source == "missing"
        codes = [d.code for d in diags]
        assert "REUSE_EVIDENCE_NOT_FOUND" in codes


class TestAcrossPlan:
    """policy="across_plan" — branch and full-plan across-version fallback."""

    def test_full_plan_across_plan_when_branch_id_none(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("source")]
        pv_id = store.create_plan_version(plan_id, steps)
        _run_plan(store, pv_id)

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "source", branch_id=None, plan_id=plan_id,
            policy="across_plan",
        )
        assert rs is not None
        assert source == "across_plan"

    def test_latest_plan_run_fallback(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("source")]
        pv_id = store.create_plan_version(plan_id, steps)
        _run_plan(store, pv_id)

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "source", branch_id="nonexistent", plan_id=plan_id,
            policy="across_plan",
        )
        assert rs is not None
        assert source in ("across_plan", "latest_plan_run")


class TestRunOnly:
    """policy="run_only" ignores latest successful evidence outside the supplied run."""

    def test_run_only_finds_step_in_run(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("source")]
        pv_id = store.create_plan_version(plan_id, steps)
        run_id = _run_plan(store, pv_id)

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "source", run_id=run_id, policy="run_only",
        )
        assert rs is not None
        assert source == "run"

    def test_run_only_returns_missing_wrong_run(self):
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [_make_step("source")])

        resolver = EvidenceResolver(store)
        rs, source, diags = resolver.resolve(
            pv_id, "source", run_id="nonexistent", policy="run_only",
        )
        assert rs is None
        assert source == "missing"
