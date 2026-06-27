"""Tests for cardre.staleness — pure staleness computation functions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from cardre.audit import RunStepRecord, StepSpec, json_logical_hash, utc_now_iso
from cardre.errors import GraphValidationError
from cardre.staleness import compute_staleness, staleness_detail, step_is_stale, _find_spec
from tests.helpers import make_store


pytestmark = pytest.mark.unit


def _make_step(
    step_id: str,
    parent_ids: list[str] | None = None,
    params: dict | None = None,
    node_type: str = "cardre.dummy",
    node_version: str = "1",
    position: int = 0,
) -> StepSpec:
    params = params or {}
    return StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version=node_version,
        category="transform",
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=parent_ids or [],
        branch_label="",
        position=position,
    )


def _make_rs(
    step_id: str,
    plan_version_id: str,
    run_id: str,
    params_hash: str,
    node_type: str = "cardre.dummy",
    node_version: str = "1",
    parent_output_hashes: dict[str, list[str]] | None = None,
    output_hashes: list[str] | None = None,
    now: str | None = None,
) -> RunStepRecord:
    now = now or utc_now_iso()
    return RunStepRecord(
        run_step_id=str(uuid.uuid4()),
        run_id=run_id,
        step_id=step_id,
        plan_version_id=plan_version_id,
        status="succeeded",
        started_at=now,
        finished_at=now,
        input_artifact_ids=[],
        output_artifact_ids=[],
        execution_fingerprint={
            "params_hash": params_hash,
            "node_type": node_type,
            "node_version": node_version,
            "parent_output_logical_hashes_by_step": parent_output_hashes or {},
            "output_artifact_logical_hashes": output_hashes or [],
            "plan_version_id": plan_version_id,
        },
        warnings=[],
        errors=[],
    )


# ======================================================================
# _find_spec
# ======================================================================


class FindSpecTests:
    def test_finds_existing_step(self) -> None:
        steps = [_make_step("a"), _make_step("b")]
        assert _find_spec("a", steps).step_id == "a"
        assert _find_spec("b", steps).step_id == "b"

    def test_raises_on_missing_step(self) -> None:
        with pytest.raises(GraphValidationError):
            _find_spec("nonexistent", [_make_step("a")])


# ======================================================================
# step_is_stale (unit tests, direct function call)
# ======================================================================


class StepIsStaleTests:
    def test_no_run_record_is_stale(self) -> None:
        spec = _make_step("a")
        assert step_is_stale(spec, [spec], {}, {})

    def test_params_hash_mismatch_is_stale(self) -> None:
        pv_id = str(uuid.uuid4())
        spec = _make_step("a", params={"x": 1})
        rs = _make_rs("a", pv_id, "r1", params_hash="different_hash")
        assert step_is_stale(spec, [spec], {"a": rs}, {})

    def test_node_type_mismatch_is_stale(self) -> None:
        pv_id = str(uuid.uuid4())
        spec = _make_step("a", node_type="cardre.different")
        rs = _make_rs("a", pv_id, "r1", spec.params_hash)
        assert step_is_stale(spec, [spec], {"a": rs}, {})

    def test_node_version_mismatch_is_stale(self) -> None:
        pv_id = str(uuid.uuid4())
        spec = _make_step("a", node_version="2")
        rs = _make_rs("a", pv_id, "r1", spec.params_hash, node_version="1")
        assert step_is_stale(spec, [spec], {"a": rs}, {})

    def test_all_matching_is_fresh(self) -> None:
        pv_id = str(uuid.uuid4())
        spec = _make_step("a", params={"x": 1})
        rs = _make_rs("a", pv_id, "r1", spec.params_hash)
        assert not step_is_stale(spec, [spec], {"a": rs}, {})

    def test_stale_parent_makes_child_stale(self) -> None:
        pv_id = str(uuid.uuid4())
        parent = _make_step("p", params={"x": 1})
        child = _make_step("c", parent_ids=["p"], params={"y": 2})
        # Parent has a run record, but its params_hash doesn't match
        parent_rs = _make_rs("p", pv_id, "r1", params_hash="wrong_hash")
        child_rs = _make_rs(
            "c", pv_id, "r1", child.params_hash,
            parent_output_hashes={"p": ["hash1"]},
        )
        rs_by_step = {"p": parent_rs, "c": child_rs}
        steps = [parent, child]
        assert step_is_stale(child, steps, rs_by_step, {})

    def test_parent_output_hash_mismatch_makes_child_stale(self) -> None:
        pv_id = str(uuid.uuid4())
        parent = _make_step("p")
        child = _make_step("c", parent_ids=["p"])
        # Child's fingerprint records parent_hashes as ["old_hash"], but parent current is ["new_hash"]
        child_rs = _make_rs(
            "c", pv_id, "r1", child.params_hash,
            parent_output_hashes={"p": ["old_hash"]},
        )
        # Rebuild parent rs with different outputs
        parent_rs2 = _make_rs("p", pv_id, "r1", parent.params_hash, output_hashes=["new_hash"])
        rs_by_step = {"p": parent_rs2, "c": child_rs}
        steps = [parent, child]
        assert step_is_stale(child, steps, rs_by_step, {})

    def test_uses_stale_cache(self) -> None:
        pv_id = str(uuid.uuid4())
        spec = _make_step("a")
        rs = _make_rs("a", pv_id, "r1", spec.params_hash)
        # First call populates cache, second call uses it
        stale_cache: dict[str, bool] = {}
        assert not step_is_stale(spec, [spec], {"a": rs}, stale_cache)
        # Mark cached as stale — function should not re-compute
        stale_cache["a"] = True
        assert step_is_stale(spec, [spec], {"a": rs}, stale_cache)

    def test_no_parent_rs_makes_child_stale(self) -> None:
        pv_id = str(uuid.uuid4())
        parent = _make_step("p")
        child = _make_step("c", parent_ids=["p"])
        child_rs = _make_rs(
            "c", pv_id, "r1", child.params_hash,
            parent_output_hashes={"p": ["hash1"]},
        )
        steps = [parent, child]
        rs_by_step = {"c": child_rs}  # parent has no rs
        assert step_is_stale(child, steps, rs_by_step, {})


# ======================================================================
# compute_staleness (integration with ProjectStore)
# ======================================================================


class ComputeStalenessTests:
    def test_no_run_all_stale(self) -> None:
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("a"), _make_step("b", parent_ids=["a"])]
        pv_id = store.create_plan_version(plan_id, steps)
        staleness = compute_staleness(store, pv_id)
        assert staleness == {"a": True, "b": True}

    def test_all_steps_fresh(self) -> None:
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("a")]
        pv_id = store.create_plan_version(plan_id, steps)
        run_id = store.create_run(pv_id)
        rs = _make_rs("a", pv_id, run_id, steps[0].params_hash)
        store.save_run_step(rs)
        store.finish_run(run_id, "succeeded")

        staleness = compute_staleness(store, pv_id)
        assert staleness == {"a": False}

    def test_mixed_staleness(self) -> None:
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        a = _make_step("a", params={"x": 1})
        b = _make_step("b", parent_ids=["a"], params={"y": 2})
        steps = [a, b]
        pv_id = store.create_plan_version(plan_id, steps)
        run_id = store.create_run(pv_id)
        t0 = datetime.now(timezone.utc).isoformat()
        ra = _make_rs("a", pv_id, run_id, a.params_hash, now=t0)
        rb = _make_rs("b", pv_id, run_id, b.params_hash, parent_output_hashes={"a": ra.execution_fingerprint["output_artifact_logical_hashes"]}, now=t0)
        store.save_run_step(ra)
        store.save_run_step(rb)
        store.finish_run(run_id, "succeeded")

        # Create a new plan version where 'a' params changed
        a2 = _make_step("a", params={"x": 99})
        b2 = _make_step("b", parent_ids=["a"])
        steps2 = [a2, b2]
        pv2_id = store.create_plan_version(plan_id, steps2)
        # Run the new version with a later timestamp
        run2_id = store.create_run(pv2_id)
        t1 = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        ra2 = _make_rs("a", pv2_id, run2_id, a2.params_hash, now=t1)
        rb2 = _make_rs("b", pv2_id, run2_id, b2.params_hash, parent_output_hashes={"a": ra2.execution_fingerprint["output_artifact_logical_hashes"]}, now=t1)
        store.save_run_step(ra2)
        store.save_run_step(rb2)
        store.finish_run(run2_id, "succeeded")

        # Now check staleness of a third version where only params of 'b' changed
        a3 = _make_step("a", params={"x": 99})  # same as a2
        b3 = _make_step("b", parent_ids=["a"], params={"y": 999})  # changed from b2
        steps3 = [a3, b3]
        pv3_id = store.create_plan_version(plan_id, steps3)
        staleness = compute_staleness(store, pv3_id)
        # Cross-plan fallback finds pv2's 'a' (params x=99) which matches pv3's 'a' (x=99)
        assert staleness["a"] == False
        assert staleness["b"] == True

    def test_branch_id_fallback(self) -> None:
        """When branch has no run, falls back to full-plan run."""
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        steps = [_make_step("a")]
        pv_id = store.create_plan_version(plan_id, steps)
        run_id = store.create_run(pv_id)
        rs = _make_rs("a", pv_id, run_id, steps[0].params_hash)
        store.save_run_step(rs)
        store.finish_run(run_id, "succeeded")

        branch_id = store.create_branch(
            project_id, plan_id, "test-br", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )
        # No branch-specific run exists
        staleness = compute_staleness(store, pv_id, branch_id=branch_id)
        # Falls back to full-plan run — step should appear fresh
        assert staleness == {"a": False}

    def test_cross_plan_fallback_when_current_version_has_no_runs(self) -> None:
        """A step in a new plan version with no runs should be fresh if an
        earlier version ran the same step with identical params, node type,
        and node version."""
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        a = _make_step("a", params={"x": 1})
        pv1_id = store.create_plan_version(plan_id, [a])
        run1_id = store.create_run(pv1_id)
        ra = _make_rs("a", pv1_id, run1_id, a.params_hash)
        store.save_run_step(ra)
        store.finish_run(run1_id, "succeeded")

        # New plan version with same step, no runs
        a2 = _make_step("a", params={"x": 1})
        pv2_id = store.create_plan_version(plan_id, [a2])

        staleness = compute_staleness(store, pv2_id)
        assert staleness == {"a": False}, (
            f"Expected step 'a' to be fresh via cross-plan fallback, got {staleness}"
        )

    def test_branch_step_stale_when_shared_upstream_changes(self) -> None:
        """A branch-owned step becomes stale when its shared upstream is re-run with new params."""
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        upstream = _make_step("import", params={"source": "data.csv"})
        branch_step = _make_step("binning", parent_ids=["import"], params={"bins": 10})
        steps = [upstream, branch_step]
        pv_id = store.create_plan_version(plan_id, steps)

        # Full-plan baseline run
        run_id = store.create_run(pv_id)
        rs_up = _make_rs("import", pv_id, run_id, upstream.params_hash)
        rs_br = _make_rs("binning", pv_id, run_id, branch_step.params_hash,
                         parent_output_hashes={"import": rs_up.execution_fingerprint["output_artifact_logical_hashes"]})
        store.save_run_step(rs_up)
        store.save_run_step(rs_br)
        store.finish_run(run_id, "succeeded")

        # Create branch that owns only the binning step
        branch_id = store.create_branch(
            project_id, plan_id, "challenger", "challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="import", step_id="import",
            is_shared_upstream=True, is_branch_owned=False,
        )
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id="binning", step_id="binning",
            is_shared_upstream=False, is_branch_owned=True,
        )

        # Branch run — captures evidence, step is fresh
        branch_run_id = store.create_run(pv_id, branch_id=branch_id)
        rs_br2 = _make_rs("binning", pv_id, branch_run_id, branch_step.params_hash,
                          parent_output_hashes={"import": rs_up.execution_fingerprint["output_artifact_logical_hashes"]})
        store.save_run_step(rs_br2)
        store.finish_run(branch_run_id, "succeeded")

        # Now change upstream params in a new plan version
        upstream2 = _make_step("import", params={"source": "data2.csv"})
        steps2 = [upstream2, branch_step]
        pv2_id = store.create_plan_version(plan_id, steps2)

        # Branch staleness should detect upstream change
        staleness = compute_staleness(store, pv2_id, branch_id=branch_id)
        assert staleness["import"] is True  # upstream changed
        assert staleness["binning"] is True  # branch-owned step stale via parent


class StalenessDetailTests:
    def test_staleness_detail_returns_reasons(self) -> None:
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        a = _make_step("a", params={"x": 1})
        b = _make_step("b", parent_ids=["a"], params={"y": 2})
        steps = [a, b]
        pv_id = store.create_plan_version(plan_id, steps)
        run_id = store.create_run(pv_id)
        ra = _make_rs("a", pv_id, run_id, a.params_hash)
        rb = _make_rs("b", pv_id, run_id, b.params_hash, parent_output_hashes={"a": ra.execution_fingerprint["output_artifact_logical_hashes"]})
        store.save_run_step(ra)
        store.save_run_step(rb)
        store.finish_run(run_id, "succeeded")

        # Change params of 'a' only — creates new version
        a2 = _make_step("a", params={"x": 99})
        b2 = _make_step("b", parent_ids=["a"], params={"y": 2})
        pv2_id = store.create_plan_version(plan_id, [a2, b2])

        details = staleness_detail(store, pv2_id)
        by_step = {d.step_id: d for d in details}

        assert by_step["a"].is_stale
        assert by_step["a"].reason == "params_changed"

        assert by_step["b"].is_stale
        assert by_step["b"].reason == "upstream_stale"

    def test_staleness_detail_never_run(self) -> None:
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        a = _make_step("a")
        pv_id = store.create_plan_version(plan_id, [a])

        details = staleness_detail(store, pv_id)
        assert details[0].is_stale
        assert details[0].reason == "never_run"

    def test_staleness_detail_fresh_has_no_reason(self) -> None:
        store, _ = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        a = _make_step("a")
        steps = [a]
        pv_id = store.create_plan_version(plan_id, steps)
        run_id = store.create_run(pv_id)
        ra = _make_rs("a", pv_id, run_id, a.params_hash)
        store.save_run_step(ra)
        store.finish_run(run_id, "succeeded")

        details = staleness_detail(store, pv_id)
        assert not details[0].is_stale
        assert details[0].reason is None
