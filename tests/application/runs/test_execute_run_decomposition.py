"""Pin the structural invariants of the decomposed ExecuteRun.

These tests do NOT re-prove the R3 lease/cancellation behaviour (that lives in
test_dispatch_fencing_concurrency.py); they prove the decomposition preserved
the same observable structure through a cleaner shape.

Behaviour preservation itself is covered by the full tests/application/runs
and tests/application/execution suites (composed execution, dispatch/fencing,
publication durability, contract/identity), which run the real ExecuteRun.
"""
from __future__ import annotations

import ast
from pathlib import Path


class _FakeClock:
    def now_iso(self) -> str:
        return "2026-01-01T00:00:00Z"

EXEC = Path(__file__).resolve().parents[3] / "cardre" / "application" / "runs" / "execute_run.py"


def _source() -> str:
    return EXEC.read_text()


def _tree() -> ast.Module:
    return ast.parse(_source())


def _function(name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(_tree()) if isinstance(n, ast.FunctionDef) and n.name == name)


# --- structural guards ---


def test_no_run_summary_ref_instance_state() -> None:
    """The _run_summary_ref side-channel must be gone (moved into the hook)."""
    assert "_run_summary_ref" not in _source()


def test_no_inline_node_type_special_case_in_call() -> None:
    """__call__ must not special-case 'cardre.technical_manifest_export'."""
    call = _function("__call__")
    segment = ast.get_source_segment(_source(), call) or ""
    assert "technical_manifest_export" not in segment


def test_run_summary_hook_exists_and_owns_special_case() -> None:
    """The hook class must exist and be the only home of the special case."""
    tree = _tree()
    assert any(isinstance(n, ast.ClassDef) and n.name == "_RunSummaryHook" for n in ast.walk(tree))
    segment = ast.get_source_segment(_source(), next(
        n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "_RunSummaryHook"
    )) or ""
    assert "technical_manifest_export" in segment


def test_fenced_persist_helper_exists() -> None:
    """A module-level fenced-persist context manager must be extracted."""
    tree = _tree()
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_fenced_persist" in names


def test_read_uow_helper_exists() -> None:
    tree = _tree()
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_read_uow" in names


def test_call_body_under_100_lines() -> None:
    call = _function("__call__")
    assert call.end_lineno - call.lineno + 1 <= 100, (
        f"__call__ must stay under 100 lines (got {call.end_lineno - call.lineno + 1})"
    )


def test_call_opens_no_raw_uows() -> None:
    """__call__ must not hand-roll raw UoW blocks; reads go through helpers."""
    call = _function("__call__")
    direct = sum(
        1 for n in ast.walk(call)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_uow_factory"
    )
    assert direct == 0, (
        f"__call__ must not call _uow_factory() directly (got {direct}); "
        "use _read_uow/_fenced_persist/_claim_run"
    )


def test_persist_step_outputs_extracted() -> None:
    assert _function("_persist_step_outputs").end_lineno - _function("_persist_step_outputs").lineno + 1 > 0


def test_execute_steps_extracted() -> None:
    assert _function("_execute_steps").end_lineno - _function("_execute_steps").lineno + 1 > 0


# --- UoW lifecycle spies (RunSummary publication must not leak connections) ---


class _CloseSpy:
    """Records close() calls on a real mutation UoW."""

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


def _spy_write_factory(uow_factory, project_id, captured):
    def factory():
        spy = _CloseSpy(uow_factory.for_project(project_id))
        captured.append(spy)
        return spy
    return factory


def _spy_read_factory(uow_factory, project_id, captured):
    def factory():
        spy = _CloseSpy(uow_factory.read_only(project_id))
        captured.append(spy)
        return spy
    return factory


def _provision_running_run(tmp_path):
    """Provision a project with a committed plan and a running run; returns
    the pieces needed to drive ``ExecuteRun._publish_run_summary``."""
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    from cardre.adapters.system.project_registry import JsonProjectRegistry
    from cardre.application.runs.execute_run import ExecuteRun
    from cardre.domain.run import RunStatus

    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        worker_generation = uow.runs.begin_worker_generation(run_id)
        uow.commit()
    registry.register(project_id, root)

    artifact_store = FsArtifactStore(root / "objects")
    exec_run = ExecuteRun(
        uow_factory=lambda: None,
        read_only_factory=lambda: None,
        node_catalogue=None,
        step_runner=None,
        finalize_run=None,
        artifact_store_factory=lambda: artifact_store,
    )
    return {
        "project_id": project_id,
        "run_id": run_id,
        "pv_id": pv_id,
        "worker_generation": worker_generation,
        "uow_factory": uow_factory,
        "artifact_store": artifact_store,
        "exec_run": exec_run,
    }


def test_run_summary_publication_closes_all_uows_on_success(tmp_path):
    """_publish_run_summary must close every UoW it opens on the success path
    (summary read UoW, registration UoW, and mark-published UoW)."""
    from cardre.application.runs.execute_run import ExecuteRunCommand

    ctx = _provision_running_run(tmp_path)
    captured: list[_CloseSpy] = []
    ctx["exec_run"]._uow_factory = _spy_write_factory(
        ctx["uow_factory"], ctx["project_id"], captured,
    )
    ctx["exec_run"]._read_only_factory = _spy_read_factory(
        ctx["uow_factory"], ctx["project_id"], captured,
    )

    ref = ctx["exec_run"]._publish_run_summary(
        ExecuteRunCommand(run_id=ctx["run_id"]),
        ctx["pv_id"],
        run=None,
        step_outputs={},
        run_step_records={},
        worker_generation=ctx["worker_generation"],
        artifact_store=ctx["artifact_store"],
    )

    assert ref is not None
    assert len(captured) >= 2, "expected summary read + registration + mark UoWs"
    assert all(spy.closed for spy in captured), (
        "RunSummary publication leaked a UoW connection (not all closed)"
    )


def test_run_summary_publication_closes_all_uows_on_failure(tmp_path):
    """If mark_published fails, the mark UoW is rolled back AND closed; the
    exception propagates."""
    from cardre.application.runs.execute_run import ExecuteRunCommand

    ctx = _provision_running_run(tmp_path)
    captured: list[_CloseSpy] = []
    ctx["exec_run"]._uow_factory = _spy_write_factory(
        ctx["uow_factory"], ctx["project_id"], captured,
    )
    ctx["exec_run"]._read_only_factory = _spy_read_factory(
        ctx["uow_factory"], ctx["project_id"], captured,
    )
    ctx["exec_run"]._artifact_store = ctx["artifact_store"]

    # Inject a publication repo whose mark_published raises.
    class _FailingPublications:
        def __init__(self, inner):
            self._inner = inner

        def mark_published(self, outbox_id):
            raise RuntimeError("injected mark_published failure")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class _FailMarkCloseSpy(_CloseSpy):
        @property
        def publications(self):
            return _FailingPublications(self._inner.publications)

    fail_captured: list[_FailMarkCloseSpy] = []

    def failing_write_factory():
        spy = _FailMarkCloseSpy(ctx["uow_factory"].for_project(ctx["project_id"]))
        fail_captured.append(spy)
        return spy

    ctx["exec_run"]._uow_factory = failing_write_factory
    ctx["exec_run"]._read_only_factory = _spy_read_factory(
        ctx["uow_factory"], ctx["project_id"], captured,
    )

    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="injected mark_published failure"):
        ctx["exec_run"]._publish_run_summary(
            ExecuteRunCommand(run_id=ctx["run_id"]),
            ctx["pv_id"],
            run=None,
            step_outputs={},
            run_step_records={},
            worker_generation=ctx["worker_generation"],
            artifact_store=ctx["artifact_store"],
        )

    assert fail_captured, "expected the mark-published UoW to be opened"
    assert all(spy.closed for spy in fail_captured), (
        "mark UoW leaked its connection on publication failure"
    )


def test_initial_reads_and_cancellation_use_read_only_uow(tmp_path):
    """Pure lifecycle reads must never construct a mutation UoW.

    ExecuteRun's initial run/plan lookup and per-step cancellation checks are
    reads; routing them through the write factory would eagerly begin
    ``BEGIN IMMEDIATE`` transactions (R1 invariant, read/mutation split)."""
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    from cardre.adapters.system.project_registry import JsonProjectRegistry
    from cardre.application.runs.execute_run import ExecuteRun, ExecuteRunCommand
    from cardre.domain.run import RunStatus, RunStepStatus

    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        from cardre.domain.step import StepSpec

        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash="h",
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        run_id = uow.runs.create(pv_id)
        uow.commit()
    registry.register(project_id, root)

    class _NoopRunner:
        def run_step(self, *args, **kwargs):
            return type("R", (), {
                "status": RunStepStatus.SUCCEEDED, "staged_artifacts": [],
                "input_artifact_ids": [], "warnings": [], "errors": [],
                "fingerprint": {}, "parent_run_steps": [],
                "input_artifact_ids_by_parent": {},
            })()

    class _NoopCatalogue:
        def availability(self, node_type):
            return type("Av", (), {"available": True})()

    from cardre.application.runs.finalize_run import FinalizeRun

    finalize = FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        type("Pub", (), {"publish": lambda self, run_id, payload: None})(),
        _FakeClock(),
    )

    read_created: list[object] = []
    write_created: list[object] = []

    def spying_read():
        uow = uow_factory.read_only(project_id)
        read_created.append(uow)
        return uow

    def spying_write():
        uow = uow_factory.for_project(project_id)
        write_created.append(uow)
        return uow

    executor = ExecuteRun(
        spying_write,
        spying_read,
        _NoopCatalogue(),
        _NoopRunner(),
        finalize,
        lambda: FsArtifactStore(root / "objects"),
        heartbeat_interval_seconds=0.1,
    )
    executor(ExecuteRunCommand(run_id=run_id))

    assert read_created, "expected at least one read-only UoW for run/plan lookup"
    assert all(not isinstance(u, __import__("cardre.adapters.sqlite.connection", fromlist=["SqliteUnitOfWork"]).SqliteUnitOfWork) for u in read_created), (
        "pure lifecycle reads must not construct SqliteUnitOfWork (BEGIN IMMEDIATE)"
    )

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None and run.status == RunStatus.SUCCEEDED.value
