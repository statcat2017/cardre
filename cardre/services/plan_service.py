"""PlanService — plan query, mutation, and aggregation logic.

Owns all business logic for plan endpoints.  Routes are thin delegates
that resolve a store from the project registry, instantiate this service,
and catch ``PlanValidationError`` to map to HTTP responses.
"""

from __future__ import annotations

import uuid
from typing import Any

from cardre.audit import StepSpec, replace_step_params, utc_now_iso
from cardre.executor import PlanExecutor
from cardre.node_parameters import merge_defaults, validate_against_schema
from cardre.registry import NodeRegistry
from cardre.staleness import compute_staleness
from cardre.store import ProjectStore
from cardre.services.plan_dto import (
    PlanResponse,
    StepStatusItem,
    UpdateStepParamsResponse,
)


class PlanValidationError(Exception):
    """Raised when plan-level business rules are violated.

    Routes catch this and convert it to ``HTTPException`` using the
    ``status_code``, ``code``, and ``message`` fields.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 422,
        extra: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        detail: dict[str, Any] = {"code": code, "message": message}
        if extra:
            detail.update(extra)
        self.detail = detail
        super().__init__(message)


class PlanService:
    """Business logic for plan query, mutation, and validation."""

    def __init__(self, store: ProjectStore):
        self._store = store
        self._registry = NodeRegistry.with_defaults()
        self._executor = PlanExecutor(self._registry)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_plan_with_status(self, plan_id: str, project_id: str) -> PlanResponse:
        """Return plan details with computed staleness and step statuses."""
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise PlanValidationError(
                "PLAN_NOT_FOUND", f"No plan with ID {plan_id}", status_code=404,
            )

        latest_pv_id = self._store.get_latest_plan_version_id(plan_id)
        if latest_pv_id is None:
            raise PlanValidationError(
                "NO_VERSION", "Plan has no versions", status_code=404,
            )

        steps = self._store.get_plan_version_steps(latest_pv_id)
        staleness = compute_staleness(self._store, latest_pv_id)

        # Run steps from the current version's most recent run
        run_steps_map: dict[str, Any] = {}
        all_runs = self._store.list_runs(latest_pv_id)
        if all_runs:
            latest_run_id = all_runs[0]["run_id"]
            for rs in self._store.get_run_steps(latest_run_id):
                run_steps_map[rs.step_id] = rs

        # Fallback: when the current version has no runs, use the most
        # recent successful run from any version of this plan for
        # non-stale steps.
        fallback_run_steps_map: dict[str, Any] = {}
        if not all_runs:
            run_id = self._store.get_latest_successful_run_id_for_plan(plan_id)
            if run_id is not None:
                for rs in self._store.get_run_steps(run_id):
                    fallback_run_steps_map[rs.step_id] = rs

        step_items = []
        for s in steps:
            is_stale = staleness.get(s.step_id, True)
            rs = run_steps_map.get(s.step_id)
            if rs is None and not is_stale:
                rs = fallback_run_steps_map.get(s.step_id)
            status = rs.status if rs else "not_run"
            step_items.append(
                StepStatusItem(
                    step_id=s.step_id,
                    node_type=s.node_type,
                    category=s.category,
                    status=status,
                    is_stale=is_stale,
                    position=s.position,
                    params=s.params,
                    canonical_step_id=s.canonical_step_id,
                    branch_id=s.branch_id,
                )
            )

        return PlanResponse(
            plan_id=plan_id,
            project_id=project_id,
            name=plan["name"],
            latest_version_id=latest_pv_id,
            steps=step_items,
        )

    def update_params(
        self,
        plan_id: str,
        step_id: str,
        base_plan_version_id: str,
        params: dict[str, Any],
    ) -> UpdateStepParamsResponse:
        """Validate params, create a new plan version, return stale steps.

        If the target step is branch-owned, updates the branch head
        and copies branch_step_map entries atomically.
        """
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise PlanValidationError(
                "PLAN_NOT_FOUND", f"No plan with ID {plan_id}", status_code=404,
            )

        latest_pv_id = self._store.get_latest_plan_version_id(plan_id)
        if latest_pv_id is None:
            raise PlanValidationError(
                "NO_VERSION", "Plan has no versions", status_code=404,
            )

        if base_plan_version_id != latest_pv_id:
            raise PlanValidationError(
                "STALE_VERSION",
                "Plan version has changed since your last read. Refresh and retry.",
                status_code=409,
                extra={"latest_version_id": latest_pv_id},
            )

        steps = self._store.get_plan_version_steps(latest_pv_id)
        target_step = None
        for s in steps:
            if s.step_id == step_id:
                target_step = s
                break

        if target_step is None:
            raise PlanValidationError(
                "STEP_NOT_FOUND",
                f"No step {step_id} in plan {plan_id}",
                status_code=404,
            )

        branch_id = target_step.branch_id
        branch = None
        if branch_id:
            branch = self._store.get_branch(branch_id)
            if branch is None:
                raise PlanValidationError(
                    "BRANCH_NOT_FOUND",
                    f"Branch {branch_id} for step {step_id} not found.",
                    status_code=404,
                )
            if branch.get("status") != "active":
                raise PlanValidationError(
                    "BRANCH_INACTIVE",
                    f"Branch {branch_id} is not active.",
                    status_code=400,
                )
            if branch["head_plan_version_id"] != base_plan_version_id:
                raise PlanValidationError(
                    "STALE_BRANCH_VERSION",
                    "Branch head has changed since your last read. Refresh and retry.",
                    status_code=409,
                    extra={"branch_head_version_id": branch["head_plan_version_id"]},
                )

        new_params = dict(params)

        # Validate params against schema (method + parameter) framework
        try:
            node = self._registry.instantiate(target_step.node_type)
            schema = node.parameter_schema()
            new_params = merge_defaults(schema, new_params)
            schema_errors = validate_against_schema(schema, new_params)
            if schema_errors:
                raise PlanValidationError(
                    "PARAMS_VALIDATION_FAILED",
                    "; ".join(schema_errors),
                )
            custom_errors = node.validate_params(new_params)
            if custom_errors:
                raise PlanValidationError(
                    "PARAMS_VALIDATION_FAILED",
                    "; ".join(custom_errors),
                )
        except KeyError:
            pass

        # Manual-binning: validate by canonical step ID or node type
        if target_step.canonical_step_id == "manual-binning" or target_step.node_type == "cardre.manual_binning":
            overrides = list(new_params.get("overrides", []))
            if overrides:
                from cardre.services.manual_binning_service import ManualBinningService
                ManualBinningService(self._store).validate_overrides(
                    plan_id, latest_pv_id, overrides, step_id, branch_id=branch_id,
                )

        new_steps = replace_step_params(steps, step_id, new_params)
        now = utc_now_iso()

        if branch_id and branch is not None:
            # Branch-owned: create plan version inside branch's transaction
            with self._store.transaction() as conn:
                new_pv_id = self._store.create_plan_version_in_transaction(
                    conn=conn, plan_id=plan_id, steps=new_steps,
                    description=f"Updated params for {step_id} (branch {branch_id})",
                )
                # Update branch head
                conn.execute(
                    "UPDATE plan_branches SET head_plan_version_id = ?, updated_at = ? WHERE branch_id = ?",
                    (new_pv_id, now, branch_id),
                )
                # Copy branch_step_map for new plan version
                existing_map = self._store.get_branch_step_map(branch_id, latest_pv_id)
                for row in existing_map:
                    conn.execute(
                        "INSERT INTO branch_step_map "
                        "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
                        " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(uuid.uuid4()),
                            branch_id, new_pv_id, row["canonical_step_id"], row["step_id"],
                            row.get("source_branch_id"), row.get("source_step_id"),
                            row["is_shared_upstream"], row["is_branch_owned"], now,
                        ),
                    )
        else:
            new_pv_id = self._store.create_plan_version(
                plan_id=plan_id, steps=new_steps,
                description=f"Updated params for {step_id}",
            )

        staleness = compute_staleness(
            self._store, new_pv_id,
            branch_id=branch_id,
        )
        stale_ids = [
            sid for sid, is_stale in staleness.items()
            if is_stale and (not branch_id or any(s.branch_id == branch_id for s in new_steps if s.step_id == sid))
        ]

        return UpdateStepParamsResponse(
            plan_id=plan_id,
            new_plan_version_id=new_pv_id,
            changed_step_id=step_id,
            stale_step_ids=stale_ids,
        )


