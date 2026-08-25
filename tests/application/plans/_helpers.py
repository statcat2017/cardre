"""Shared helpers for plan use-case characterization tests.

`factory` wraps a project-scoped unit-of-work factory, `catalogue` builds the
default node catalogue, and `canonical_draft` drives the canonical scorecard
on-ramp to produce a draft plan version that is either commit-ready or missing
the essential modelling decisions.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from cardre.application.plans.create_canonical_scorecard_version import (
    CreateCanonicalScorecardVersion,
    CreateCanonicalScorecardVersionCommand,
)
from cardre.application.plans.update_step_params import (
    UpdateStepParams,
    UpdateStepParamsCommand,
)
from cardre.bootstrap.node_catalogue import build_default_catalogue


def factory(uow_factory, project_id):
    def factory():
        return uow_factory.for_project(project_id)
    return factory


def catalogue():
    return build_default_catalogue()


def canonical_draft(uow_factory, project_id, *, ready: bool, tmp_path: Path):
    """Build a canonical pathway draft that is either commit-ready or
    missing the essential modelling decisions."""
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "P")
        uow.commit()
    parquet_path = tmp_path / "in.parquet"
    pl.DataFrame({
        "x": list(range(6)),
        "outcome": ["good" if i % 2 else "bad" for i in range(6)],
    }).write_parquet(parquet_path)
    cat = catalogue()
    create = CreateCanonicalScorecardVersion(factory(uow_factory, project_id), cat)
    pv = create(CreateCanonicalScorecardVersionCommand(
        plan_id=plan_id, source_path=str(parquet_path), target_column="outcome",
    ))
    pv_id = pv.plan_version_id
    if ready:
        update = UpdateStepParams(factory(uow_factory, project_id), cat)
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
