"""Batch R1 — transaction and UoW ownership proof tests.

Proves two Batch R1 acceptance criteria:

1. **Failure-injection atomicity** — a failed step-persistence mutation leaves
   no partial rows in any related table (artifacts, run steps, lineage,
   evidence), because the mutation UoW holds one explicit transaction that is
   actually rolled back.
2. **Query UoW lifecycle** — every query use case closes its UoW on success
   and on repository exceptions, so no SQLite connection leaks per request.
"""

from __future__ import annotations

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.plans.create_plan import CreatePlan, CreatePlanCommand
from cardre.application.plans.get_plan import GetPlan, GetPlanCommand
from cardre.application.plans.get_plan_version import GetPlanVersion, GetPlanVersionCommand
from cardre.application.plans.list_plan_versions import (
    ListPlanVersions,
    ListPlanVersionsCommand,
)
from cardre.application.plans.list_plans import ListPlans, ListPlansCommand


def _provision(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        uow.commit()
    registry.register(project_id, root)
    return project_id, uow_factory, root


# ---------------------------------------------------------------------------
# 1. Failure-injection atomicity
# ---------------------------------------------------------------------------


class _FailAfterN:
    """Wraps a callable and raises after ``n`` successful calls."""

    def __init__(self, callable, n: int) -> None:
        self._callable = callable
        self._remaining = n

    def __call__(self, *args, **kwargs):
        if self._remaining <= 0:
            raise RuntimeError("injected failure")
        self._remaining -= 1
        return self._callable(*args, **kwargs)


@pytest.mark.parametrize("fail_point", [
    "register", "run_steps.insert", "register_lineage", "evidence.insert_edge",
])
def test_failed_step_persistence_leaves_no_partial_rows(tmp_path, fail_point):
    """Inject a failure at each step-persistence write and assert atomic rollback.

    Each persistence write happens inside one mutation UoW that begins its
    transaction eagerly. A failure at any point must roll back every row the
    step would have written: no artifact, run step, lineage, or evidence row
    may survive.
    """
    project_id, uow_factory, _root = _provision(tmp_path)
    from cardre.domain.run import RunStatus

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            steps=[],
            description="v1",
            is_committed=True,
        )
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING,
                            expected_from=(RunStatus.SUBMITTED, RunStatus.SUBMITTED))
        uow.commit()

    # Persist a minimal step + artifact + lineage + evidence, then force a
    # failure at the requested point and verify nothing remains.
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import utc_now_iso
    from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
    from cardre.domain.run import RunStep, RunStepStatus

    art = ArtifactRef(
        artifact_id="art:role:phys", artifact_type="profile_summary", role="report",
        path="objects/ab/phys", physical_hash="phys", logical_hash="log",
        media_type="application/json",
    )
    run_step_id = f"{run_id}-s1"

    uow = uow_factory.for_project(project_id)
    artifacts_repo = uow.artifacts
    run_steps_repo = uow.run_steps
    evidence_repo = uow.evidence
    try:
        if fail_point == "register":
            artifacts_repo.register = _FailAfterN(artifacts_repo.register, 0)  # type: ignore[method-assign]
        elif fail_point == "run_steps.insert":
            run_steps_repo.insert = _FailAfterN(run_steps_repo.insert, 0)  # type: ignore[method-assign]
        elif fail_point == "register_lineage":
            artifacts_repo.register_lineage = _FailAfterN(  # type: ignore[method-assign]
                artifacts_repo.register_lineage, 0
            )
        elif fail_point == "evidence.insert_edge":
            evidence_repo.insert_edge = _FailAfterN(evidence_repo.insert_edge, 0)  # type: ignore[method-assign]

        artifacts_repo.register(art)
        rs = RunStep(
            run_step_id=run_step_id, run_id=run_id, step_id="s1",
            plan_version_id=pv_id, status=RunStepStatus.SUCCEEDED,
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
        )
        run_steps_repo.insert(rs)
        artifacts_repo.register_lineage(
            run_id=run_id, run_step_id=run_step_id, plan_version_id=pv_id,
            step_id="s1", artifact_id=art.artifact_id, direction="output",
        )
        evidence_repo.insert_edge(EvidenceEdge(
            evidence_edge_id="edge-1", run_id=run_id, run_step_id=run_step_id,
            plan_version_id=pv_id, step_id="s1", parent_step_id="s0",
            source_run_id=run_id, source_run_step_id=run_step_id,
            policy="exact", source_label="test", is_reused=False, is_stale=False,
        ))
        evidence_repo.insert_artifact(EvidenceArtifact(
            evidence_artifact_id="ea-1", evidence_edge_id="edge-1",
            artifact_id=art.artifact_id, role="report",
        ))
        uow.commit()
    except RuntimeError as exc:
        assert "injected failure" in str(exc)
        uow.rollback()
    finally:
        uow.close()

    # Nothing may survive: artifact, run step, lineage, or evidence rows.
    with uow_factory.read_only(project_id) as ro:
        assert ro.artifacts.get(art.artifact_id) is None
        assert ro.run_steps.get(run_step_id) is None
        assert ro.evidence.get_edges_for_run_step(run_step_id) == []
        assert ro.artifacts.artifacts_for_run_step(run_step_id) == []


def test_commit_makes_mutation_durable(tmp_path):
    """A committed mutation is visible from a subsequent read-only UoW."""
    project_id, uow_factory, _root = _provision(tmp_path)
    use_case = CreatePlan(
        lambda: uow_factory.for_project(project_id),
    )
    plan = use_case(CreatePlanCommand(project_id=project_id, name="Durable"))
    with uow_factory.read_only(project_id) as ro:
        fetched = ro.plans.get_plan(plan.plan_id)
    assert fetched is not None
    assert fetched.name == "Durable"


def test_close_without_commit_rolls_back(tmp_path):
    """A mutation UoW closed without commit must not persist its writes."""
    project_id, uow_factory, _root = _provision(tmp_path)
    uow = uow_factory.for_project(project_id)
    try:
        uow.plans.create_plan(project_id, "Gone")
    finally:
        uow.close()  # must roll back the uncommitted transaction

    with uow_factory.read_only(project_id) as ro:
        assert ro.plans.list_for_project(project_id) == []


def test_read_only_uow_never_commits(tmp_path):
    """A read-only UoW never begins a transaction and never commits."""
    project_id, uow_factory, _root = _provision(tmp_path)
    ro = uow_factory.read_only(project_id)
    try:
        with pytest.raises(AttributeError):
            ro.commit()  # read-only contract has no commit
        with pytest.raises(AttributeError):
            ro.rollback()
    finally:
        ro.close()


# ---------------------------------------------------------------------------
# 2. Query UoW lifecycle (connection-spy)
# ---------------------------------------------------------------------------


class _CloseSpy:
    """Records close() calls on a real UoW."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self) -> None:
        self.closed = True
        self._inner.close()

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, *exc):
        self.closed = True
        return self._inner.__exit__(*exc)


def _spy_factory(uow_factory, project_id, captured):
    def factory():
        spy = _CloseSpy(uow_factory.read_only(project_id))
        captured.append(spy)
        return spy
    return factory


def test_query_use_cases_close_uow_on_success(tmp_path):
    """Each plan query use case closes its UoW after a successful call."""
    project_id, uow_factory, _root = _provision(tmp_path)
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps=[], is_committed=False)
        uow.commit()

    captured: list[_CloseSpy] = []
    factory = _spy_factory(uow_factory, project_id, captured)

    GetPlan(factory)(GetPlanCommand(plan_id=plan_id))
    ListPlans(factory)(ListPlansCommand(project_id=project_id))
    GetPlanVersion(factory)(GetPlanVersionCommand(plan_version_id=pv_id))
    ListPlanVersions(factory)(ListPlanVersionsCommand(plan_id=plan_id))

    assert len(captured) == 4, "each query should open exactly one UoW"
    assert all(spy.closed for spy in captured), "query UoW was not closed"


def test_query_use_case_closes_uow_on_repository_exception(tmp_path):
    """A query use case closes its UoW even when the repository raises."""
    project_id, uow_factory, _root = _provision(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("repo failure")

    from cardre.application.plans.get_plan import GetPlan, GetPlanCommand

    closed = {"value": False}

    def fake_close():
        closed["value"] = True

    broken_repo = type("BrokenRepo", (), {"get_plan": boom})()
    broken = type("BrokenUoW", (), {
        "plans": broken_repo,
        "close": lambda *a, **k: fake_close(),
        "__enter__": lambda s: s,
        "__exit__": lambda s, *a: s.close(),
    })()
    get_plan = GetPlan(lambda: broken)

    with pytest.raises(RuntimeError, match="repo failure"):
        get_plan(GetPlanCommand(plan_id="missing"))
    assert closed["value"], "query UoW leaked its connection on repository exception"


def test_explain_staleness_closes_uow(tmp_path):
    """ExplainStaleness closes its UoW (was leaking one per request)."""
    project_id, uow_factory, _root = _provision(tmp_path)
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps=[], is_committed=True)
        uow.commit()

    from cardre.application.evidence.explain_staleness import (
        ExplainStaleness,
        ExplainStalenessCommand,
    )

    captured: list[_CloseSpy] = []
    factory = _spy_factory(uow_factory, project_id, captured)
    ExplainStaleness(factory)(ExplainStalenessCommand(
        plan_version_id=pv_id, step_id="s1", plan_id=plan_id,
    ))
    assert len(captured) == 1
    assert captured[0].closed
