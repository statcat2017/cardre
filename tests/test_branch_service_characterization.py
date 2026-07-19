"""Characterization tests for BranchService.create_branch — pin behavior before extraction.

These tests assert on persisted database state and the returned metadata
dict, not on private method call order.  They must pass against the current
code and must fail if branch/step-map/semantics are accidentally changed
during later extraction of the branch validator, graph remapper, and
transaction writer.
"""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import BranchValidationError
from cardre.domain.step import StepSpec
from cardre.services.branch_service import BranchService
from cardre.store.branch_repo import BranchRepository
from cardre.store.plan_repo import PlanRepository

pytestmark = pytest.mark.governance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_steps(store, plan_id: str, pv_id: str | None = None,
                include_branch_points: bool = True) -> tuple[str, list[StepSpec]]:
    """Create a committed plan version with branch-able steps.

    Steps: sample-definition -> variable-selection -> manual-binning -> logistic-regression.

    Returns ``(plan_version_id, steps)``.
    """
    from cardre.domain.artifacts import json_logical_hash

    if pv_id is None:
        pv_id = str(uuid.uuid4())

    steps = [
        StepSpec(
            step_id="step-sample-def", node_type="cardre.noop",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
            canonical_step_id="sample-definition",
        ),
        StepSpec(
            step_id="step-var-sel", node_type="cardre.variable_selection",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=["step-sample-def"], branch_label="", position=1,
            canonical_step_id="variable-selection",
        ),
        StepSpec(
            step_id="step-manual-bin", node_type="cardre.manual_binning",
            node_version="1", category="refinement",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=["step-var-sel"], branch_label="", position=2,
            canonical_step_id="manual-binning",
        ),
        StepSpec(
            step_id="step-logistic-reg", node_type="cardre.logistic_regression",
            node_version="1", category="fit",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=["step-manual-bin"], branch_label="", position=3,
            canonical_step_id="logistic-regression",
        ),
    ]
    pv_id = PlanRepository(store).create_version(
        plan_id, steps, description="char-branch-base", is_committed=True,
    )
    return pv_id, steps


# =========================================================================
# Descendant closure direction
# =========================================================================


class TestDescendantClosureDirection:

    def test_branch_duplicates_only_downstream_steps(self, store):
        """Branching from manual-binning duplicates steps at and after
        the branch point (descendant closure), not before it."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "desc-test", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "desc-test")
        pv_id, steps = _make_steps(store, plan_id)

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Desc-Test",
            branch_type="binning_challenger",
            branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id,
            created_reason="Descendant closure test.",
        )

        # Created (duplicated) steps should be manual-binning and
        # logistic-regression (at and after branch point).
        created_canonical = set(result["created_step_ids"].keys())
        assert "manual-binning" in created_canonical
        assert "logistic-regression" in created_canonical

        # Shared upstream steps should be sample-definition and
        # variable-selection (before branch point).
        shared = result["shared_upstream_step_ids"]
        assert len(shared) == 2
        assert "step-sample-def" in shared
        assert "step-var-sel" in shared
        assert "step-manual-bin" not in shared
        assert "step-logistic-reg" not in shared


# =========================================================================
# ID remapping rules
# =========================================================================


class TestIDRemapping:

    def test_duplicated_step_ids_contain_branch_id(self, store):
        """Duplicated step IDs are derived from canonical_step_id and branch_id."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "id-test", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "id-test")
        pv_id, steps = _make_steps(store, plan_id)

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="ID-Test",
            branch_type="binning_challenger",
            branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id,
            created_reason="ID remapping test.",
        )

        branch_id = result["branch_id"]
        for _canonical, new_step_id in result["created_step_ids"].items():
            expected_suffix = f"__{branch_id}"
            assert new_step_id.endswith(expected_suffix), (
                f"Created step ID {new_step_id!r} does not end with "
                f"{expected_suffix!r}"
            )

    def test_remapped_parent_step_ids_are_consistent(self, store):
        """Duplicated steps have parent_step_ids pointing at remapped
        parent IDs; shared steps keep original parent IDs."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "parent-test", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "parent-test")
        pv_id, steps = _make_steps(store, plan_id)

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Parent-Test",
            branch_type="binning_challenger",
            branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id,
            created_reason="Parent remap test.",
        )

        new_pv_id = result["new_plan_version_id"]
        new_steps = PlanRepository(store).get_version_steps(new_pv_id)
        new_by_step_id = {s.step_id: s for s in new_steps}

        # The duplicated manual-binning step should have its parent
        # pointing at the ORIGINAL variable-selection step (shared).
        mb_new_id = result["created_step_ids"]["manual-binning"]
        mb_new_spec = new_by_step_id[mb_new_id]
        assert mb_new_spec.parent_step_ids == ["step-var-sel"], (
            f"Duplicated manual-binning should have parent 'step-var-sel', "
            f"got {mb_new_spec.parent_step_ids}"
        )

        # The duplicated logistic-regression step should have its
        # parent pointing at the duplicated manual-binning step.
        lr_new_id = result["created_step_ids"]["logistic-regression"]
        lr_new_spec = new_by_step_id[lr_new_id]
        assert lr_new_spec.parent_step_ids == [mb_new_id], (
            f"Duplicated logistic-regression should have parent {mb_new_id!r}, "
            f"got {lr_new_spec.parent_step_ids}"
        )

        # Shared steps should keep their original parent_step_ids.
        vs_spec = new_by_step_id["step-var-sel"]
        assert vs_spec.parent_step_ids == ["step-sample-def"]


# =========================================================================
# Non-destructive — original plan version unchanged
# =========================================================================


class TestNonDestructive:

    def test_original_plan_version_remains_unchanged(self, store):
        """Branch creation does not modify the original plan version's
        steps, edges, or metadata."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "non-destruct", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "non-destruct")
        pv_id, steps = _make_steps(store, plan_id)

        # Snapshot original step IDs and parent relationships
        original_steps = PlanRepository(store).get_version_steps(pv_id)
        original_ids = {s.step_id: s.parent_step_ids for s in original_steps}

        svc = BranchService(store)
        svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="NonDestruct",
            branch_type="binning_challenger",
            branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id,
            created_reason="Non-destructive test.",
        )

        # Verify original plan version is untouched
        after_steps = PlanRepository(store).get_version_steps(pv_id)
        after_ids = {s.step_id: s.parent_step_ids for s in after_steps}
        assert after_ids == original_ids, (
            f"Original plan version steps changed.\n"
            f"Before: {original_ids}\nAfter: {after_ids}"
        )

        # Verify original edges unchanged (3 edges in the original)
        from cardre.store.step_repo import StepRepository
        orig_edges = StepRepository(store).get_all_edges(pv_id)
        assert len(orig_edges) == 3
        parent_child = {(e["parent_step_id"], e["child_step_id"]) for e in orig_edges}
        assert ("step-sample-def", "step-var-sel") in parent_child
        assert ("step-var-sel", "step-manual-bin") in parent_child
        assert ("step-manual-bin", "step-logistic-reg") in parent_child


# =========================================================================
# Return contract shape
# =========================================================================


class TestReturnContract:

    def test_create_branch_returns_all_expected_keys(self, store):
        """The return dict carries all keys documented in the contract."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "contract", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "contract")
        pv_id, steps = _make_steps(store, plan_id)

        svc = BranchService(store)
        result = svc.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="Contract-Test",
            branch_type="binning_challenger",
            branch_point_step_id="manual-binning",
            base_plan_version_id=pv_id,
            created_reason="Contract check.",
        )

        expected_keys = {"branch_id", "new_plan_version_id", "name",
                         "branch_type", "branch_point_step_id",
                         "branch_point_canonical_step_id",
                         "created_step_ids", "shared_upstream_step_ids",
                         "status", "warnings"}
        assert set(result.keys()) == expected_keys, (
            f"Return keys mismatch. Missing: {expected_keys - set(result.keys())}. "
            f"Extra: {set(result.keys()) - expected_keys}."
        )
        assert result["status"] == "not_run"
        assert isinstance(result["warnings"], list)
        assert isinstance(result["created_step_ids"], dict)
        assert isinstance(result["shared_upstream_step_ids"], list)


# =========================================================================
# Validation edge cases
# =========================================================================


class TestValidationEdgeCases:

    def test_branch_point_not_in_plan_raises(self, store):
        """A branch point step ID not present in any plan version raises
        BRANCH_POINT_NOT_IN_PLAN."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "bp-missing", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "bp-missing")
        pv_id, _steps = _make_steps(store, plan_id)

        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            # Use an ALLOWED branch point that is NOT present in our plan's steps.
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="No-BP",
                branch_type="cutoff_strategy_challenger",
                branch_point_step_id="cutoff-analysis",
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )
        assert exc_info.value.code == "BRANCH_POINT_NOT_IN_PLAN"

    def test_base_branch_inactive_raises(self, store):
        """Creating a branch from an inactive base branch raises
        BASE_BRANCH_INACTIVE."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "inactive", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "inactive")
        pv_id, steps = _make_steps(store, plan_id)

        # Create an inactive base branch
        branches_repo = BranchRepository(store)
        base_branch_id = branches_repo.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Inactive-Base", branch_type="baseline",
            base_plan_version_id=pv_id,
            head_plan_version_id=pv_id,
            created_reason="Base for inactive test.",
        )
        # Mark it inactive
        store.execute(
            "UPDATE plan_branches SET status = 'inactive' WHERE branch_id = ?",
            (base_branch_id,),
        )

        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="From-Inactive",
                branch_type="model_challenger",
                branch_point_step_id="logistic-regression",
                base_branch_id=base_branch_id,
                base_plan_version_id=pv_id,
                created_reason="Should fail.",
            )
        assert exc_info.value.code == "BASE_BRANCH_INACTIVE"

    def test_reject_inference_requires_ttd_sample_domain(self, store):
        """A reject-inference challenger requires a sample-definition
        step with sample_domain='ttd'."""
        from cardre.domain.artifacts import json_logical_hash

        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "reject-inf", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "reject-inf")
        reject_pv_id = PlanRepository(store).create_version(
            plan_id,
            steps=[
                StepSpec(
                    step_id="step-sample-def", node_type="cardre.noop",
                    node_version="1", category="transform",
                    params={"sample_domain": "otb"},  # not 'ttd'
                    params_hash=json_logical_hash({}),
                    parent_step_ids=[], branch_label="", position=0,
                    canonical_step_id="sample-definition",
                ),
                StepSpec(
                    step_id="step-reject", node_type="cardre.noop",
                    node_version="1", category="transform",
                    params={}, params_hash=json_logical_hash({}),
                    parent_step_ids=["step-sample-def"],
                    branch_label="", position=1,
                    canonical_step_id="define-reject-population",
                ),
            ],
            description="reject-test", is_committed=True,
        )

        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="Reject-Inf",
                branch_type="reject_inference_challenger",
                branch_point_step_id="define-reject-population",
                base_plan_version_id=reject_pv_id,
                created_reason="Should fail (sample_domain must be ttd).",
            )
        assert exc_info.value.code == "REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD"


# =========================================================================
# Segment filter validation at service level
# =========================================================================


class TestSegmentFilterServiceLevel:

    def test_invalid_segment_filter_operator_rejected(self, store):
        """An invalid segment filter operator is rejected at the service level."""
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "filter-op", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "filter-op")
        pv_id, steps = _make_steps(store, plan_id)

        svc = BranchService(store)
        with pytest.raises(BranchValidationError) as exc_info:
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="Bad-Filter",
                branch_type="segment_challenger",
                branch_point_step_id="sample-definition",
                base_plan_version_id=pv_id,
                created_reason="Segment filter test.",
                segment_filter_spec={
                    "rules": [
                        {"column": "age", "operator": "~=",
                         "value": 18, "reason": "Bad operator"},
                    ]
                },
            )
        assert exc_info.value.code == "SEGMENT_FILTER_UNSUPPORTED_OPERATOR"


# =========================================================================
# Transactional rollback
# =========================================================================


class TestTransactionalRollback:

    def test_failure_after_plan_version_does_not_leave_partial_branch(self, store, monkeypatch):
        """If a write fails partway through branch creation, no partial
        branch or step map rows remain."""  # noqa: E501
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "tx-test", now, "0.2.0"),
        )
        plan_id = PlanRepository(store).create_plan(project_id, "tx-test")
        pv_id, steps = _make_steps(store, plan_id)

        svc = BranchService(store)

        # Count branches and step maps before
        branch_count_before = store.execute(
            "SELECT COUNT(*) FROM plan_branches WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        step_map_count_before = store.execute(
            "SELECT COUNT(*) FROM branch_step_map "
            "WHERE branch_id IN (SELECT branch_id FROM plan_branches WHERE project_id = ?)",
            (project_id,),
        ).fetchone()[0]

        # Monkeypatch the plan repository's create_version to fail
        # partway through the transaction
        original_create_version = PlanRepository.create_version

        def _failing_create_version(self, plan_id_, steps_, **kwargs):
            pv_result = original_create_version(self, plan_id_, steps_, **kwargs)
            # Simulate a failure after plan version is created but
            # before the branch transaction commits
            raise RuntimeError("Simulated transaction failure")
            return pv_result

        monkeypatch.setattr(PlanRepository, "create_version", _failing_create_version)

        with pytest.raises(RuntimeError, match="Simulated transaction failure"):
            svc.create_branch(
                project_id=project_id,
                plan_id=plan_id,
                name="TX-Fail",
                branch_type="binning_challenger",
                branch_point_step_id="manual-binning",
                base_plan_version_id=pv_id,
                created_reason="TX rollback test.",
            )

        # Verify no branch or step map rows leaked
        branch_count_after = store.execute(
            "SELECT COUNT(*) FROM plan_branches WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        step_map_count_after = store.execute(
            "SELECT COUNT(*) FROM branch_step_map "
            "WHERE branch_id IN (SELECT branch_id FROM plan_branches WHERE project_id = ?)",
            (project_id,),
        ).fetchone()[0]
        assert branch_count_after == branch_count_before, (
            "Branch row leaked despite transaction failure"
        )
        assert step_map_count_after == step_map_count_before, (
            "Step map row leaked despite transaction failure"
        )
