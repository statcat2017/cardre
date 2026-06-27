"""Behaviour tests for the per-step heartbeat watchdog.

These tests specify that a healthy long-running step keeps heartbeat_at
fresh, so a slow step is never misclassified as stale by RunService.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest

from cardre.audit import ExecutionContext, NodeOutput, NodeType, StepSpec, json_logical_hash
from cardre.config import CardreConfig
from cardre.errors import ConcurrentRunError
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.services.run_service import RunService
from cardre.services.run_worker import SyncRunDispatcher, ThreadRunDispatcher
from cardre.store import ProjectStore

from tests.helpers import make_store


# ---------------------------------------------------------------------------
# SlowNode — a node whose run() blocks until released, recording heartbeats
# ---------------------------------------------------------------------------

class SlowNode(NodeType):
    """A node whose run() blocks until SlowNode.release is set.

    Uses class-level attributes so the test can coordinate with the
    executing step without instance registration in the registry.
    """
    node_type = "cardre.test.slow"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["artifact"]

    # Class-level coordination — set before run_plan_version
    release: threading.Event = threading.Event()
    entered: bool = False
    seen_heartbeats: list[str] = []

    def validate_params(self, params: dict) -> list[str]:
        return []

    def run(self, ctx: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import write_json_artifact

        type(self).entered = True
        type(self).seen_heartbeats = []

        # Poll heartbeat_at while blocked; capture distinct advances.
        start = ctx.store.get_run(ctx.run_id)["heartbeat_at"]
        last = start
        deadline = time.time() + 10
        while not self.release.wait(timeout=0.05):
            now = ctx.store.get_run(ctx.run_id)["heartbeat_at"]
            if now != last:
                type(self).seen_heartbeats.append(now)
                last = now
            if time.time() > deadline:
                break

        art = write_json_artifact(
            ctx.store, artifact_type="report", role="artifact",
            stem=f"slow-{ctx.step_spec.step_id}", payload={}, metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_slow_node() -> None:
    SlowNode.release = threading.Event()
    SlowNode.entered = False
    SlowNode.seen_heartbeats = []


def _make_slow_plan(store: ProjectStore) -> tuple[str, str]:
    pid = store.create_project("t")
    plan_id = store.create_plan(pid, "p")
    steps = [StepSpec(
        step_id="slow", node_type="cardre.test.slow", node_version="1",
        category="transform", params={}, params_hash=json_logical_hash({}),
        parent_step_ids=[], branch_label="", position=0,
    )]
    pv_id = store.create_plan_version(plan_id, steps)
    return pid, pv_id


# ======================================================================
# T1 — heartbeat advances during a long step
# ======================================================================

def test_heartbeat_advances_during_long_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """During a long-running step, heartbeat_at advances at least twice
    while node.run(ctx) is still executing."""
    monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "2")
    store, _ = make_store()
    _, pv_id = _make_slow_plan(store)

    reg = NodeRegistry()
    reg.register(SlowNode)
    executor = PlanExecutor(reg)

    result: dict = {}
    def runner() -> None:
        try:
            result["run_id"] = executor.run_plan_version(store, pv_id)
        except Exception as exc:
            result["exc"] = exc

    bg = threading.Thread(target=runner, daemon=True)
    bg.start()

    # Wait until SlowNode.run is entered and at least 2 heartbeats observed.
    deadline = time.time() + 15
    while time.time() < deadline and len(SlowNode.seen_heartbeats) < 2:
        time.sleep(0.05)

    assert len(SlowNode.seen_heartbeats) >= 2, (
        f"heartbeat did not advance during long step; saw {SlowNode.seen_heartbeats}"
    )

    SlowNode.release.set()
    bg.join(timeout=10)

    assert "exc" not in result, f"run failed: {result.get('exc')}"
    run = store.get_run(result["run_id"])
    assert run["status"] == "succeeded"


# ======================================================================
# T2 — active long run is not interrupted by a concurrent run_plan
# ======================================================================

def test_concurrent_run_plan_does_not_interrupt_live_long_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second run_plan while a healthy long step is executing must raise
    ConcurrentRunError, not silently recover the live run as interrupted."""
    monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "2")
    store, _ = make_store()
    _, pv_id = _make_slow_plan(store)

    reg = NodeRegistry()
    reg.register(SlowNode)
    executor = PlanExecutor(reg)

    # Start the long run via PlanExecutor on a background thread.
    holder: dict = {}
    def runner() -> None:
        try:
            holder["run_id"] = executor.run_plan_version(store, pv_id)
        except Exception as exc:
            holder["exc"] = exc

    bg = threading.Thread(target=runner, daemon=True)
    bg.start()
    time.sleep(0.1)

    # Wait until SlowNode.run is entered on the background thread.
    deadline = time.time() + 10
    while time.time() < deadline and not SlowNode.entered:
        time.sleep(0.05)
    assert SlowNode.entered, "slow node never started"

    # A second run_plan while the first is genuinely alive must raise
    # ConcurrentRunError, NOT silently recover the live run as interrupted.
    svc = RunService(store, dispatcher=SyncRunDispatcher())
    with pytest.raises(ConcurrentRunError):
        svc.run_plan(pv_id)

    # The live run must still be running and uninterrupted.
    runs = store.list_runs(plan_version_id=pv_id)
    live = [r for r in runs if r["status"] == "running"]
    assert len(live) == 1, f"expected exactly 1 running run, got {len(live)}"
    diags = store.get_run_diagnostics(live[0]["run_id"])
    assert not any(d.get("code") == "RUN_RECOVERED_STALE" for d in diags), \
        "live long run was wrongly recovered as stale"

    SlowNode.release.set()
    bg.join(timeout=10)
    assert "exc" not in holder, holder.get("exc")


# ======================================================================
# T3 — genuinely dead run is still recovered
# ======================================================================

def test_dead_run_with_stale_heartbeat_is_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run with a stale heartbeat (no watchdog) is still recovered as
    interrupted when a new run_plan is requested."""
    monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "2")
    store, _ = make_store()
    _, pv_id = _make_slow_plan(store)

    # A run that died without ever finishing (simulated by direct insert
    # + backdated heartbeat).
    dead_id = store.create_run(pv_id)
    old = "2020-01-01T00:00:00"
    conn = store._connect()
    conn.execute("UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (old, dead_id))
    conn.commit()

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id)

    dead = store.get_run(dead_id)
    assert dead["status"] == "interrupted", f"expected interrupted, got {dead['status']}"
    diags = store.get_run_diagnostics(dead_id)
    assert any(d.get("code") == "RUN_RECOVERED_STALE" for d in diags), \
        "dead run should have RUN_RECOVERED_STALE diagnostic"
    assert resp.run_id != dead_id, "must create a new run ID"


# ======================================================================
# T4 — active step id is set during run and cleared after
# ======================================================================

def test_active_step_id_is_set_during_run_and_cleared_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """While a step executes, get_active_step returns the step id; after
    the step finishes it returns None."""
    monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "2")
    store, _ = make_store()
    _, pv_id = _make_slow_plan(store)

    reg = NodeRegistry()
    reg.register(SlowNode)
    executor = PlanExecutor(reg)

    holder: dict = {}
    def runner() -> None:
        holder["run_id"] = executor.run_plan_version(store, pv_id)

    bg = threading.Thread(target=runner, daemon=True)
    bg.start()

    # Wait until SlowNode.run is entered.
    deadline = time.time() + 10
    while time.time() < deadline and not SlowNode.entered:
        time.sleep(0.02)
    assert SlowNode.entered, "slow node never started"

    run_id = store.list_runs(plan_version_id=pv_id)[0]["run_id"]
    assert store.get_active_step(run_id) == "slow", \
        f"expected active_step_id='slow', got {store.get_active_step(run_id)!r}"

    SlowNode.release.set()
    bg.join(timeout=10)

    # After the step finishes, active_step_id is cleared.
    assert store.get_active_step(run_id) is None, \
        f"expected active_step_id=None after step, got {store.get_active_step(run_id)!r}"


# ======================================================================
# T5 — recovery diagnostic includes active step id
# ======================================================================

def test_stale_recovery_diagnostic_includes_active_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a run is recovered as stale, the diagnostic includes the
    active_step_id that was set before the run died."""
    monkeypatch.setenv("CARDRE_STALE_HEARTBEAT_SECONDS", "2")
    store, _ = make_store()
    _, pv_id = _make_slow_plan(store)

    dead_id = store.create_run(pv_id)
    store.set_active_step(dead_id, "binning")  # pretend it died mid-step
    old = "2020-01-01T00:00:00"
    conn = store._connect()
    conn.execute("UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (old, dead_id))
    conn.commit()

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    svc.run_plan(pv_id)

    diags = store.get_run_diagnostics(dead_id)
    rec = [d for d in diags if d.get("code") == "RUN_RECOVERED_STALE"]
    assert len(rec) == 1, "expected exactly one RUN_RECOVERED_STALE diagnostic"
    assert rec[0].get("active_step_id") == "binning", \
        f"expected active_step_id='binning', got {rec[0].get('active_step_id')!r}"
