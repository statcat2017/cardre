"""RunService — validates run requests, creates/reuses/short-circuits runs,
dispatches sync/async, and owns stale-run recovery.

Extracted from PlanExecutor, RunOrchestrator, and sidecar/routes/runs.py.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from cardre.audit import utc_now_iso
from cardre.config import CardreConfig
from cardre.errors import CardreError, GovernanceNotEnabled
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.services.evidence_policy import EvidencePolicyService
from cardre.store import ProjectStore


@dataclass
class RunResponse:
    run_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    step_count: int = 0
    branch_id: str | None = None
    executed_step_ids: list[str] | None = None
    diagnostics: list[dict] | None = None
    latest_error: dict | None = None
    heartbeat_at: str | None = None
    is_stale: bool = False


class RunService:

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._config = CardreConfig.from_env()
        self._evidence = EvidencePolicyService(store)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_plan(
        self,
        plan_version_id: str,
        run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan",
        branch_id: str | None = None,
        target_step_id: str | None = None,
        force: bool = False,
        sync: bool = False,
    ) -> RunResponse:
        """Validate, create/reuse, and dispatch a run. Returns RunResponse."""
        pv = self._store.get_plan_version(plan_version_id)
        if pv is None:
            raise CardreError(
                f"Plan version {plan_version_id} not found",
                code="PLAN_VERSION_NOT_FOUND", context={"plan_version_id": plan_version_id},
            )

        if run_scope == "branch" and not self._config.governance_enabled:
            raise GovernanceNotEnabled(
                "Branch execution requires CARDRE_GOVERNANCE=1. "
                "Set the environment variable to enable challenger governance."
            )

        # Preflight short-circuit checks
        if not force:
            if run_scope == "branch" and branch_id:
                result = self._evidence.check_branch_current(plan_version_id, branch_id)
                if result.run_id is not None:
                    return self._build_response(result.run_id)

            if run_scope == "to_node" and target_step_id:
                result = self._evidence.check_to_node_current(
                    plan_version_id, target_step_id, branch_id=branch_id,
                )
                if result.run_id is not None:
                    return self._build_response(result.run_id)

        # Recover stale runs for this plan_version
        for existing_run in self._store.list_runs(plan_version_id=plan_version_id):
            if existing_run.get("status") == "running":
                self._maybe_recover_stale_run(existing_run)

        # Create run
        branch_kw = {"branch_id": branch_id} if branch_id else {}
        run_id = self._store.create_run(plan_version_id, **branch_kw)

        if sync:
            return self._execute_sync(run_id, plan_version_id, run_scope, branch_id, target_step_id, force)

        return self._dispatch_async(run_id, plan_version_id, run_scope, branch_id, target_step_id, force)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _execute_sync(
        self, run_id: str, plan_version_id: str,
        run_scope: str, branch_id: str | None, target_step_id: str | None,
        force: bool,
    ) -> RunResponse:
        executor = PlanExecutor(NodeRegistry.with_defaults())
        try:
            if run_scope == "branch" and branch_id:
                from cardre.services.branch_evidence import BranchEvidenceResolver
                resolver = BranchEvidenceResolver(executor)
                ctx = self._evidence.prepare_branch_evidence(plan_version_id, branch_id, force=force)
                if not force and ctx.short_circuit_run_id is not None:
                    self._store.finish_run(run_id, "cancelled")
                    return self._build_response(ctx.short_circuit_run_id)
                result_id = executor.run_branch(self._store, plan_version_id, branch_id, run_id=run_id, force=force)
            elif run_scope == "to_node" and target_step_id:
                result_id = executor.run_to_node(self._store, plan_version_id, target_step_id, run_id=run_id, force=force, branch_id=branch_id)
            else:
                result_id = executor.run_plan_version(self._store, plan_version_id, run_id=run_id, force=force)
            if result_id != run_id:
                self._store.finish_run(run_id, "cancelled")
                return self._build_response(result_id)
        except CardreError:
            raise
        except ValueError as exc:
            msg = str(exc)
            if ":" in msg:
                code, message = msg.split(":", 1)
                code = code.strip()
                message = message.strip()
            else:
                code = "RUN_VALIDATION_FAILED"
                message = msg
            raise CardreError(message, code=code, context={"plan_version_id": plan_version_id})
        except Exception as exc:
            raise CardreError(
                f"Run execution failed: {exc}",
                code="RUN_EXECUTION_FAILED",
                context={"plan_version_id": plan_version_id, "run_scope": run_scope, "branch_id": branch_id},
            ) from exc

        executed_ids = [rs.step_id for rs in self._store.get_run_steps(run_id)]
        return self._build_response(run_id, executed_ids)

    def _dispatch_async(
        self, run_id: str, plan_version_id: str,
        run_scope: str, branch_id: str | None, target_step_id: str | None,
        force: bool,
    ) -> RunResponse:
        project_path = str(self._store.root)
        try:
            t = threading.Thread(
                target=self._run_async_worker,
                kwargs={
                    "project_path": project_path,
                    "plan_version_id": plan_version_id,
                    "run_id": run_id,
                    "run_scope": run_scope,
                    "branch_id": branch_id,
                    "target_step_id": target_step_id,
                    "force": force,
                },
                name="run-bg",
            )
            t.start()
        except Exception as exc:
            self._store.finish_run(run_id, "failed")
            raise CardreError(
                f"Failed to start background run thread: {exc}",
                code="RUN_DISPATCH_FAILED",
                context={"plan_version_id": plan_version_id, "run_id": run_id, "run_scope": run_scope},
            ) from exc
        return self._build_response(run_id)

    def _run_async_worker(
        self, project_path: str, plan_version_id: str, run_id: str,
        run_scope: str, branch_id: str | None, target_step_id: str | None,
        force: bool,
    ) -> None:
        store = ProjectStore(project_path)
        try:
            store.run_heartbeat(run_id)
            executor = PlanExecutor(NodeRegistry.with_defaults())
            if run_scope == "branch" and branch_id:
                executor.run_branch(store, plan_version_id, branch_id, run_id=run_id, force=force)
            elif run_scope == "to_node" and target_step_id:
                executor.run_to_node(store, plan_version_id, target_step_id, run_id=run_id, force=force, branch_id=branch_id)
            else:
                executor.run_plan_version(store, plan_version_id, run_id=run_id, force=force)
        except Exception:
            import traceback
            import sys
            import logging
            tb = traceback.format_exc()
            exc_type, exc_value, _ = sys.exc_info()
            logger = logging.getLogger(__name__)
            logger.error("_run_async_worker(%s) failed: %s", run_id, tb)
            diag = {
                "code": "RUN_DISPATCH_FAILED",
                "message": f"{exc_type.__name__ if exc_type else 'Exception'}: {exc_value}",
                "severity": "error",
                "category": "execution",
                "exception_type": exc_type.__name__ if exc_type else "Exception",
                "run_id": run_id,
                "plan_version_id": plan_version_id,
                "branch_id": branch_id,
                "traceback": tb,
                "created_at": utc_now_iso(),
            }
            store.append_run_diagnostic(run_id, diag)
            self._fail_run_if_running(store, run_id)

    @staticmethod
    def _fail_run_if_running(store: ProjectStore, run_id: str) -> None:
        try:
            run = store.get_run(run_id)
            if run and run.get("status") == "running":
                store.finish_run(run_id, "failed")
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("_fail_run_if_running failed for run %s: %s", run_id, e)

    def _maybe_recover_stale_run(self, run: dict) -> None:
        if self._is_stale(run):
            self._store.finish_run(run["run_id"], "interrupted")
            self._store.append_run_diagnostic(run["run_id"], {
                "code": "RUN_RECOVERED_STALE",
                "message": f"Run {run['run_id']} was stuck in 'running' with stale heartbeat — recovered as interrupted.",
                "severity": "error",
                "category": "lifecycle",
                "run_id": run["run_id"],
                "plan_version_id": run.get("plan_version_id", ""),
                "created_at": utc_now_iso(),
            })

    def _is_stale(self, run: dict) -> bool:
        if run.get("status") != "running":
            return False
        hb = run.get("heartbeat_at")
        if hb is None:
            return True
        try:
            hb_ts = datetime.fromisoformat(hb).replace(tzinfo=timezone.utc).timestamp()
            now_ts = datetime.now(timezone.utc).timestamp()
            return (now_ts - hb_ts) > self._config.stale_heartbeat_seconds
        except (ValueError, TypeError):
            return True

    def _build_response(self, run_id: str, executed_ids: list[str] | None = None) -> RunResponse:
        run = self._store.get_run(run_id)
        steps = self._store.get_run_steps(run_id)
        diags = self._store.get_run_diagnostics(run_id)
        latest_error = None
        for d in diags:
            if d.get("severity") == "error":
                latest_error = d
        return RunResponse(
            run_id=run["run_id"],
            plan_version_id=run["plan_version_id"],
            status=run["status"],
            started_at=run["started_at"],
            finished_at=run.get("finished_at"),
            step_count=len(steps),
            branch_id=run.get("branch_id"),
            executed_step_ids=executed_ids or [],
            diagnostics=diags,
            latest_error=latest_error,
            heartbeat_at=run.get("heartbeat_at"),
            is_stale=self._is_stale(run),
        )
