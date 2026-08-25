"""Characterization tests for CreateCanonicalScorecardVersion.

Exercises the launch on-ramp: generating the full canonical scorecard
pathway from a Parquet path through the use case, without direct repository
access to build the step set.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from cardre.application.plans.create_canonical_scorecard_version import (
    CreateCanonicalScorecardVersion,
    CreateCanonicalScorecardVersionCommand,
)
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from cardre.domain.errors import CardreError
from cardre.domain.plans.scorecard_pathway import canonical_scorecard_step_ids


def _write_parquet(path: Path) -> Path:
    pl.DataFrame({
        "x": list(range(10)),
        "credit_risk_class": ["good" if i % 2 else "bad" for i in range(10)],
    }).write_parquet(path)
    return path


def _factory(uow_factory, project_id):
    return lambda: uow_factory.for_project(project_id)


class TestCreateCanonicalScorecardVersion:
    def test_creates_draft_version_with_all_canonical_steps(self, provisioned_project, tmp_path):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        csv_path = _write_parquet(tmp_path / "in.parquet")
        pv = uc(CreateCanonicalScorecardVersionCommand(
            plan_id=plan_id, source_path=str(csv_path),
        ))
        assert pv is not None
        assert pv.is_committed is False
        assert pv.description == "Canonical scorecard pathway"
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv.plan_version_id)
        assert [s.canonical_step_id for s in steps] == canonical_scorecard_step_ids()

    def test_applies_overrides_to_define_metadata(self, provisioned_project, tmp_path):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        csv_path = _write_parquet(tmp_path / "in.parquet")
        pv = uc(CreateCanonicalScorecardVersionCommand(
            plan_id=plan_id, source_path=str(csv_path),
            target_column="y", good_values=["good"], bad_values=["bad"],
        ))
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv.plan_version_id)
        meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
        assert meta.params["target_column"] == "y"
        assert meta.params["good_values"] == ["good"]
        assert meta.params["bad_values"] == ["bad"]
        imp = next(s for s in steps if s.canonical_step_id == "import")
        assert imp.params["source_path"] == str(csv_path)

    def test_target_propagates_to_all_target_dependent_steps(self, provisioned_project, tmp_path):
        """A custom target must reach define-metadata, validate-target AND
        split — the review regression: target was only applied to
        define-metadata, leaving validate-target/split on the hardcoded
        default."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        csv_path = _write_parquet(tmp_path / "in.parquet")
        pv = uc(CreateCanonicalScorecardVersionCommand(
            plan_id=plan_id, source_path=str(csv_path), target_column="outcome",
        ))
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv.plan_version_id)
        for step in steps:
            if step.canonical_step_id in ("define-metadata", "validate-target", "split"):
                assert step.params["target_column"] == "outcome", (
                    f"{step.canonical_step_id} did not receive the target override"
                )

    def test_production_template_is_neutral(self, provisioned_project, tmp_path):
        """The production template must not bake acceptance-fixture decisions:
        no smoothing, no auto-accepted bins, no hardcoded business metadata."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "P")
            uow.commit()
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        csv_path = _write_parquet(tmp_path / "in.parquet")
        pv = uc(CreateCanonicalScorecardVersionCommand(
            plan_id=plan_id, source_path=str(csv_path),
        ))
        with uow_factory.for_project(project_id) as uow:
            steps = uow.plans.get_version_steps(pv.plan_version_id)
        meta = next(s for s in steps if s.canonical_step_id == "define-metadata")
        assert meta.params["product"] == ""
        assert meta.params["segment"] == ""
        assert meta.params["reject_inference_position"] == ""
        manual = next(s for s in steps if s.canonical_step_id == "manual-binning")
        assert manual.params.get("accept_automated") is False
        final = next(s for s in steps if s.canonical_step_id == "final-woe-iv")
        assert "smoothing" not in final.params

    def test_raises_on_unknown_plan(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        catalogue = build_default_catalogue(Settings())
        uc = CreateCanonicalScorecardVersion(_factory(uow_factory, project_id), catalogue)
        with pytest.raises(CardreError, match="not found"):
            uc(CreateCanonicalScorecardVersionCommand(plan_id="nope", source_path="x.csv"))
