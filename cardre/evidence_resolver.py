"""Evidence resolver — consolidated run-step/evidence lookup with diagnostics.

Each policy encodes a fallback chain with typed diagnostics.
"""

from __future__ import annotations

from typing import Literal

from cardre.audit import RunStepRecord, StepSpec
from cardre.errors import Diagnostic
from cardre.store import ProjectStore

STATUS_SUCCEEDED = "succeeded"


class EvidenceResolver:
    """Resolve run-step evidence with a named policy and diagnostics."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def resolve(
        self,
        plan_version_id: str,
        step_id: str,
        *,
        branch_id: str | None = None,
        source_branch_id: str | None = None,
        run_id: str | None = None,
        plan_id: str | None = None,
        require_fingerprint_match: StepSpec | None = None,
        policy: Literal[
            "run_only",
            "branch_then_full_then_plan",
            "source_branch_then_full_then_plan",
            "across_plan",
        ] = "branch_then_full_then_plan",
    ) -> tuple[RunStepRecord | None, str, list[Diagnostic]]:
        """Resolve evidence and return (run_step, source_label, diagnostics).

        Source labels: ``run``, ``branch``, ``full_plan``, ``across_plan``,
        ``latest_plan_run``, ``missing``.
        """
        diagnostics: list[Diagnostic] = []

        if policy == "run_only":
            return self._resolve_run_only(run_id, step_id, diagnostics)

        if policy == "branch_then_full_then_plan":
            return self._resolve_branch_then_full_then_plan(
                plan_version_id, step_id, branch_id, require_fingerprint_match, diagnostics,
            )

        if policy == "source_branch_then_full_then_plan":
            return self._resolve_source_branch_then_full_then_plan(
                plan_id, plan_version_id, step_id, source_branch_id, require_fingerprint_match, diagnostics,
            )

        if policy == "across_plan":
            return self._resolve_across_plan(
                plan_id, plan_version_id, step_id, branch_id, require_fingerprint_match, diagnostics,
            )

        return None, "missing", diagnostics

    def _resolve_run_only(
        self, run_id: str | None, step_id: str, diagnostics: list[Diagnostic],
    ) -> tuple[RunStepRecord | None, str, list[Diagnostic]]:
        if run_id is None:
            return None, "missing", diagnostics
        for rs in self._store.get_run_steps(run_id):
            if rs.step_id == step_id and rs.status == STATUS_SUCCEEDED:
                return rs, "run", diagnostics
        return None, "missing", diagnostics

    def _resolve_branch_then_full_then_plan(
        self, plan_version_id: str, step_id: str, branch_id: str | None,
        require_fingerprint_match: StepSpec | None, diagnostics: list[Diagnostic],
    ) -> tuple[RunStepRecord | None, str, list[Diagnostic]]:
        rs = self._store.get_latest_successful_run_step_for_step(
            plan_version_id, step_id, branch_id=branch_id,
        )
        if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
            return rs, "branch", diagnostics

        if branch_id is not None:
            rs = self._store.get_latest_successful_run_step_for_step(
                plan_version_id, step_id, branch_id=None,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "full_plan", diagnostics

        fallback = self._find_run_step_from_plan_level_run(plan_version_id, step_id)
        if fallback is not None and self._matches_fingerprint(fallback, require_fingerprint_match):
            return fallback, "latest_plan_run", diagnostics

        return None, "missing", diagnostics

    def _resolve_source_branch_then_full_then_plan(
        self, plan_id: str | None, plan_version_id: str, step_id: str,
        source_branch_id: str | None, require_fingerprint_match: StepSpec | None,
        diagnostics: list[Diagnostic],
    ) -> tuple[RunStepRecord | None, str, list[Diagnostic]]:
        if plan_id is None:
            pv = self._store.get_plan_version(plan_version_id)
            if pv is not None:
                plan_id = pv.get("plan_id")

        lookup_branch = source_branch_id or None
        if plan_id:
            rs = self._store.get_latest_successful_run_step_for_step_across_plan(
                plan_id, step_id, branch_id=lookup_branch,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "across_plan", diagnostics

        if plan_id:
            rs = self._store.get_latest_successful_run_step_for_step_across_plan(
                plan_id, step_id, branch_id=None,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                if lookup_branch is not None:
                    diagnostics.append(Diagnostic(
                        code="INHERITED_BASELINE_EVIDENCE",
                        message=(
                            f"Step {step_id}: source branch {source_branch_id} "
                            "has no evidence; fell back to baseline (branch_id=None)."
                        ),
                        source="EvidenceResolver._resolve_source_branch_then_full_then_plan",
                        severity="warning",
                        context={
                            "step_id": step_id,
                            "plan_id": plan_id,
                            "source_branch_id": source_branch_id,
                            "fallback_branch_id": None,
                        },
                    ))
                return rs, "across_plan", diagnostics

            plan_run_id = self._store.get_latest_successful_run_id_for_plan(plan_id)
            if plan_run_id is not None:
                for prs in self._store.get_run_steps(plan_run_id):
                    if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
                        if self._matches_fingerprint(prs, require_fingerprint_match):
                            return prs, "latest_plan_run", diagnostics

        diagnostics.append(Diagnostic(
            code="REUSE_EVIDENCE_NOT_FOUND",
            message=f"No shared evidence found for step {step_id} in plan {plan_id}",
            source="EvidenceResolver._resolve_source_branch_then_full_then_plan",
            severity="warning",
            context={
                "step_id": step_id,
                "plan_version_id": plan_version_id,
                "source_branch_id": source_branch_id,
            },
        ))
        return None, "missing", diagnostics

    def _resolve_across_plan(
        self, plan_id: str | None, plan_version_id: str, step_id: str,
        branch_id: str | None, require_fingerprint_match: StepSpec | None,
        diagnostics: list[Diagnostic],
    ) -> tuple[RunStepRecord | None, str, list[Diagnostic]]:
        if plan_id is None:
            pv = self._store.get_plan_version(plan_version_id)
            if pv is not None:
                plan_id = pv.get("plan_id")

        if plan_id:
            rs = self._store.get_latest_successful_run_step_for_step_across_plan(
                plan_id, step_id, branch_id=branch_id,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "across_plan", diagnostics

            rs = self._store.get_latest_successful_run_step_for_step_across_plan(
                plan_id, step_id, branch_id=None,
            )
            if rs is not None and self._matches_fingerprint(rs, require_fingerprint_match):
                return rs, "across_plan", diagnostics

            plan_run_id = self._store.get_latest_successful_run_id_for_plan(plan_id)
            if plan_run_id is not None:
                for prs in self._store.get_run_steps(plan_run_id):
                    if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
                        if self._matches_fingerprint(prs, require_fingerprint_match):
                            return prs, "latest_plan_run", diagnostics

        return None, "missing", diagnostics

    def _find_run_step_from_plan_level_run(
        self, plan_version_id: str, step_id: str,
    ) -> RunStepRecord | None:
        pv = self._store.get_plan_version(plan_version_id)
        if pv is None:
            return None
        plan_run_id = self._store.get_latest_successful_run_id_for_plan(pv["plan_id"])
        if plan_run_id is None:
            return None
        for prs in self._store.get_run_steps(plan_run_id):
            if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
                return prs
        return None

    def _matches_fingerprint(
        self, rs: RunStepRecord | None, spec: StepSpec | None,
    ) -> bool:
        if spec is None or rs is None:
            return True
        fp = rs.execution_fingerprint
        if fp.get("params_hash", "") != spec.params_hash:
            return False
        if fp.get("node_type", "") != spec.node_type:
            return False
        if fp.get("node_version", "") != spec.node_version:
            return False
        return True
