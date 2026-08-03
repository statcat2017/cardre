"""Characterization tests for plan use cases — create, get, list, commit, update.

Ported behavioral coverage for the thin plan use cases through the production
persistence stack.
"""

from __future__ import annotations

import pytest

from cardre.application.plans.commit_plan_version import CommitPlanVersion, CommitPlanVersionCommand
from cardre.application.plans.create_plan import CreatePlan, CreatePlanCommand
from cardre.application.plans.get_plan import GetPlan, GetPlanCommand
from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand
from cardre.application.plans.list_plan_versions import ListPlanVersions, ListPlanVersionsCommand
from cardre.application.plans.list_plans import ListPlans, ListPlansCommand
from cardre.application.plans.update_plan_version import UpdatePlanVersion, UpdatePlanVersionCommand
from cardre.application.plans.update_step_params import UpdateStepParams, UpdateStepParamsCommand
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.errors import CardreError

from ..conftest import make_branchable_steps


def _factory(uow_factory, project_id):
    def factory():
        return uow_factory.for_project(project_id)
    return factory


def _catalogue():
    return build_default_catalogue(Settings())


class TestCreatePlan:
    def test_creates_and_returns_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = CreatePlan(_factory(uow_factory, project_id))
        plan = use_case(CreatePlanCommand(project_id=project_id, name="My Plan"))
        assert plan is not None
        assert plan.name == "My Plan"
        assert plan.project_id == project_id


class TestGetPlan:
    def test_returns_plan_when_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        use_case = GetPlan(_factory(uow_factory, project_id))
        plan = use_case(GetPlanCommand(plan_id=plan_id))
        assert plan is not None
        assert plan.plan_id == plan_id

    def test_returns_none_when_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = GetPlan(_factory(uow_factory, project_id))
        assert use_case(GetPlanCommand(plan_id="nonexistent")) is None


class TestListPlans:
    def test_lists_plans_for_project(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            uow.plans.create_plan(project_id, "A")
            uow.plans.create_plan(project_id, "B")
            uow.commit()
        use_case = ListPlans(_factory(uow_factory, project_id))
        plans = use_case(ListPlansCommand(project_id=project_id))
        assert len(plans) == 2


class TestGetPlanVersion:
    def test_returns_version_when_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            uow.commit()
        use_case = GetPlanVersion(_factory(uow_factory, project_id))
        pv = use_case(GetPlanVersionCommand(plan_version_id=pv_id))
        assert pv is not None
        assert pv.plan_version_id == pv_id

    def test_returns_none_when_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = GetPlanVersion(_factory(uow_factory, project_id))
        assert use_case(GetPlanVersionCommand(plan_version_id="nonexistent")) is None


class TestListPlanVersions:
    def test_lists_versions_for_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.plans.create_version(plan_id, is_committed=True)
            uow.plans.create_version(plan_id, is_committed=False)
            uow.commit()
        use_case = ListPlanVersions(_factory(uow_factory, project_id))
        versions = use_case(ListPlanVersionsCommand(plan_id=plan_id))
        assert len(versions) == 2


class TestCommitPlanVersion:
    def test_commits_draft_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(
                plan_id, make_branchable_steps(), is_committed=False,
            )
            uow.commit()
        use_case = CommitPlanVersion(_factory(uow_factory, project_id), _catalogue())
        committed = use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert committed.is_committed is True

    def test_raises_on_nonexistent_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = CommitPlanVersion(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError, match="not found"):
            use_case(CommitPlanVersionCommand(plan_version_id="nonexistent"))

    def test_raises_on_already_committed(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(
                plan_id, make_branchable_steps(), is_committed=True,
            )
            uow.commit()
        use_case = CommitPlanVersion(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError, match="already committed"):
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))

    def _canonical_draft(self, uow_factory, project_id, *, ready: bool):
        """Build a canonical pathway draft that is either commit-ready or
        missing the essential modelling decisions."""
        import csv
        import tempfile
        from pathlib import Path

        from cardre.application.plans.create_canonical_scorecard_version import (
            CreateCanonicalScorecardVersion,
            CreateCanonicalScorecardVersionCommand,
        )

        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        tmp = Path(tempfile.mkdtemp())
        csv_path = tmp / "in.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["x", "outcome"])
            w.writeheader()
            for i in range(6):
                w.writerow({"x": i, "outcome": "good" if i % 2 else "bad"})
        cat = _catalogue()
        create = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), cat)
        pv = create(CreateCanonicalScorecardVersionCommand(
            plan_id=plan_id, source_path=str(csv_path), target_column="outcome",
        ))
        pv_id = pv.plan_version_id
        if ready:
            update = UpdateStepParams(_factory(uow_factory, project_id), cat)
            with uow_factory.for_project(project_id) as uow:
                steps = uow.plans.get_version_steps(pv_id)
            by_canonical = {s.canonical_step_id: s for s in steps}
            meta = by_canonical["define-metadata"]
            update(UpdateStepParamsCommand(
                plan_version_id=pv_id, step_id=meta.step_id,
                params={**meta.params, "reject_inference_position": "not_applied"},
            ))
            with uow_factory.for_project(project_id) as uow:
                steps = uow.plans.get_version_steps(pv_id)
            by_canonical = {s.canonical_step_id: s for s in steps}
            meta = by_canonical["define-metadata"]
            update(UpdateStepParamsCommand(
                plan_version_id=pv_id, step_id=meta.step_id,
                params={
                    **meta.params,
                    "product": "term_loan",
                    "segment": "retail",
                    "observation_window": "2024-01_to_2024-06",
                    "performance_window": "2024-07_to_2024-12",
                },
            ))
            manual = by_canonical["manual-binning"]
            update(UpdateStepParamsCommand(
                plan_version_id=pv_id, step_id=manual.step_id,
                params={**manual.params, "accept_automated": True},
            ))
        return pv_id

    def test_commit_rejects_incomplete_canonical_draft(self, provisioned_project):
        """A canonical pathway without the essential modelling decisions
        (business metadata, manual-binning outcome) must not become
        immutable."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = self._canonical_draft(uow_factory, project_id, ready=False)
        use_case = CommitPlanVersion(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        messages = []
        for entry in exc.value.context.get("errors", []):
            messages.extend(entry.get("errors", []))
        joined = " ".join(messages)
        assert "product is required" in joined
        assert "manual-binning requires an explicit outcome" in joined

    def test_commit_accepts_complete_canonical_draft(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = self._canonical_draft(uow_factory, project_id, ready=True)
        use_case = CommitPlanVersion(_factory(uow_factory, project_id), _catalogue())
        committed = use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert committed.is_committed is True

    def test_commit_rejects_inconsistent_target(self, provisioned_project):
        """Direct repo writes that diverge the target across steps must be
        rejected at commit (the edit path propagates atomically, but commit
        defensively rejects any inconsistent state)."""
        from cardre.domain.artifacts import json_logical_hash

        project_id, uow_factory, _, _ = provisioned_project
        pv_id = self._canonical_draft(uow_factory, project_id, ready=True)

        # Corrupt validate-target directly through the repo, as a stray write
        # would, leaving it on a different target than define-metadata/split.
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            vt = next(s for s in steps if s.canonical_step_id == "validate-target")
            params = dict(vt.params)
            params["target_column"] = "other"
            uow.plans.update_step_params(pv_id, vt.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(_factory(uow_factory, project_id), _catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "target_column must agree" in joined


class TestUpdatePlanVersion:
    def test_updates_draft_description(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=False)
            uow.commit()
        use_case = UpdatePlanVersion(_factory(uow_factory, project_id))
        use_case(UpdatePlanVersionCommand(
            plan_version_id=pv_id, description="Updated",
        ))
        with uow_factory.for_project(project_id) as uow:
            pv = uow.plans.get_version(pv_id)
        assert pv.description == "Updated"

    def test_rejects_committed_version(self, provisioned_project):
        """A committed plan version is immutable — updating its description
        must fail (F1)."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(plan_id, is_committed=True)
            uow.commit()
        use_case = UpdatePlanVersion(_factory(uow_factory, project_id))
        with pytest.raises(CardreError) as exc:
            use_case(UpdatePlanVersionCommand(
                plan_version_id=pv_id, description="Tampered",
            ))
        assert exc.value.code in ("PLAN_VERSION_ALREADY_COMMITTED", "PLAN_VERSION_IMMUTABLE")

    def test_unknown_version_returns_not_found(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = UpdatePlanVersion(_factory(uow_factory, project_id))
        with pytest.raises(CardreError) as exc:
            use_case(UpdatePlanVersionCommand(
                plan_version_id="nonexistent", description="X",
            ))
        assert exc.value.code == "PLAN_VERSION_NOT_FOUND"
