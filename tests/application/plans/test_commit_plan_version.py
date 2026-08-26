"""Characterization tests for CommitPlanVersion."""

from __future__ import annotations

import pytest

from cardre.application.plans.commit_plan_version import (
    CommitPlanVersion,
    CommitPlanVersionCommand,
)
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError

from ..conftest import make_branchable_steps
from ._helpers import canonical_draft, catalogue, factory


class TestCommitPlanVersion:
    def test_commits_draft_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            pv_id = uow.plans.create_version(
                plan_id, make_branchable_steps(), is_committed=False,
            )
            uow.commit()
        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        committed = use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert committed.is_committed is True

    def test_raises_on_nonexistent_version(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
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
        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError, match="already committed"):
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))

    def test_commit_rejects_incomplete_canonical_draft(self, provisioned_project, tmp_path):
        """A canonical pathway without the essential modelling decisions
        (business metadata, manual-binning outcome) must not become
        immutable."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=False, tmp_path=tmp_path)
        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        messages = []
        for entry in exc.value.context.get("errors", []):
            messages.extend(entry.get("errors", []))
        joined = " ".join(messages)
        assert "product must be non-whitespace text" in joined
        assert "manual-binning requires an explicit outcome" in joined

    def test_commit_accepts_complete_canonical_draft(self, provisioned_project, tmp_path):
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)
        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        committed = use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert committed.is_committed is True

    def test_commit_rejects_inconsistent_target(self, provisioned_project, tmp_path):
        """Direct repo writes that diverge the target across steps must be
        rejected at commit (the edit path propagates atomically, but commit
        defensively rejects any inconsistent state)."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        # Corrupt validate-target directly through the repo, as a stray write
        # would, leaving it on a different target than define-metadata/split.
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            vt = next(s for s in steps if s.canonical_step_id == "validate-target")
            params = dict(vt.params)
            params["target_column"] = "other"
            uow.plans.update_step_params(pv_id, vt.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "target_column must match exactly" in joined

    def test_commit_rejects_overlapping_good_bad(self, provisioned_project, tmp_path):
        """A semantically contradictory target definition (good and bad share
        a value) must not become immutable — it would fail at first run."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
            params = dict(meta.params)
            params["good_values"] = ["default"]
            params["bad_values"] = ["default"]
            uow.plans.update_step_params(pv_id, meta.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "must be disjoint" in joined

    def test_commit_rejects_blank_good_values(self, provisioned_project, tmp_path):
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
            params = dict(meta.params)
            params["good_values"] = ["  "]
            uow.plans.update_step_params(pv_id, meta.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "good_values must contain at least one non-blank value" in joined

    def test_commit_rejects_missing_target_key(self, provisioned_project, tmp_path):
        """A legacy/direct-repo state where a target-dependent step has no
        target_column key at all must be rejected: schema normalization would
        supply the default, so readiness must not see a bare absent key as
        consistent."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            vt = next(s for s in steps if s.canonical_step_id == "validate-target")
            params = dict(vt.params)
            params.pop("target_column", None)
            uow.plans.update_step_params(pv_id, vt.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "target_column must match exactly" in joined

    def test_commit_rejects_empty_dependent_target(self, provisioned_project, tmp_path):
        """An empty target on a dependent step must be rejected even when the
        others agree — it would index a different column than the others at
        runtime."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            vt = next(s for s in steps if s.canonical_step_id == "validate-target")
            params = dict(vt.params)
            params["target_column"] = ""
            uow.plans.update_step_params(pv_id, vt.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "validate-target.target_column must be non-whitespace text" in joined

    def test_commit_rejects_whitespace_different_target(self, provisioned_project, tmp_path):
        """A target differing only by whitespace must be rejected: execution
        does not strip the value."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            vt = next(s for s in steps if s.canonical_step_id == "validate-target")
            params = dict(vt.params)
            params["target_column"] = " outcome "
            uow.plans.update_step_params(pv_id, vt.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "target_column must match exactly" in joined

    def test_commit_rejects_blank_member_in_good_values(self, provisioned_project, tmp_path):
        """A list containing a valid member and a blank member must be
        rejected: runtime consumes each member verbatim, so the blank would
        become a spurious declared category."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
            params = dict(meta.params)
            params["good_values"] = ["good", "   "]
            uow.plans.update_step_params(pv_id, meta.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "good_values[1] must not be blank" in joined

    def test_commit_rejects_whitespace_only_essential_metadata(self, provisioned_project, tmp_path):
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
            params = dict(meta.params)
            params["product"] = "   "
            uow.plans.update_step_params(pv_id, meta.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "product must be non-whitespace text" in joined

    def test_commit_rejects_explicit_null_indeterminate_values(self, provisioned_project, tmp_path):
        """An explicit null for an optional target list must be rejected at
        commit — runtime iterates the value, so a null would crash after the
        version became immutable."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
            params = dict(meta.params)
            params["indeterminate_values"] = None
            uow.plans.update_step_params(pv_id, meta.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "indeterminate_values must be a list" in joined

    def test_commit_accepts_empty_indeterminate_values(self, provisioned_project, tmp_path):
        """An empty (but present) indeterminate list commits and runs
        successfully."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
            params = dict(meta.params)
            params["indeterminate_values"] = []
            uow.plans.update_step_params(pv_id, meta.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        committed = use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert committed.is_committed is True

    def test_commit_rejects_manual_overrides_with_accept_automated(self, provisioned_project, tmp_path):
        """accept_automated=True contradicting the binning actually executed
        (manual overrides present) must be rejected before commit."""
        project_id, uow_factory, _, _ = provisioned_project
        pv_id = canonical_draft(uow_factory, project_id, ready=True, tmp_path=tmp_path)

        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv_id)
            manual = next(s for s in steps if s.canonical_step_id == "manual-binning")
            params = dict(manual.params)
            params["overrides"] = [{
                "variable": "x",
                "action": "merge_bins",
                "reason": "manual change",
                "source_bin_ids": ["a", "b"],
            }]
            uow.plans.update_step_params(pv_id, manual.step_id, params, json_logical_hash(params))
            uow.commit()

        use_case = CommitPlanVersion(factory(uow_factory, project_id), catalogue())
        with pytest.raises(CardreError) as exc:
            use_case(CommitPlanVersionCommand(plan_version_id=pv_id))
        assert exc.value.code == "PARAMETER_VALIDATION_ERROR"
        joined = " ".join(
            msg for e in exc.value.context.get("errors", []) for msg in e.get("errors", [])
        )
        assert "accept_automated cannot be true when overrides" in joined
