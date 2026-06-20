"""Run lifecycle module — generic run mechanics behind the PlanExecutor seam.

PlanExecutor remains the single execution seam.  This module owns generic
run lifecycle: manifest construction, final status, cancellation token
lifecycle, and cleanup.  It does not decide node semantics, role access,
leakage rules, or parent evidence resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from cardre.artifacts import write_json_artifact
from cardre.audit import RunStepRecord, JsonDict
from cardre.cancellation import CancellationToken, register_token, remove_token
from cardre.store import ProjectStore

MANIFEST_VERSION = "1.0.0"

STATUS_CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def step_action(rs: RunStepRecord) -> str:
    """Derive the manifest action label for a run-step record."""
    if rs.status == STATUS_CANCELLED:
        return "cancelled"
    if rs.execution_fingerprint and rs.execution_fingerprint.get("cardre_step_carried_forward"):
        return "reused"
    return "executed"


def build_manifest_payload(
    *,
    run_id: str,
    plan_version_id: str,
    run_record: JsonDict,
    run_steps: list[RunStepRecord],
    execution_mode: str,
    branch_id: str | None = None,
    target_step_id: str | None = None,
    in_scope_step_ids: list[str] | None = None,
) -> JsonDict:
    """Build a run manifest payload from run metadata and step records.
    
    The manifest is a deterministic document describing what was run,
    which steps were executed/reused/cancelled, and their evidence.
    """
    manifest: JsonDict = {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "plan_version_id": plan_version_id,
        "branch_id": branch_id,
        "started_at": run_record["started_at"],
        "finished_at": run_record.get("finished_at", ""),
        "status": run_record["status"],
        "execution_mode": execution_mode,
        "cardre_version": "0.1.0",
        "steps": [
            {
                "step_id": rs.step_id,
                "node_type": rs.execution_fingerprint.get("node_type", ""),
                "node_version": rs.execution_fingerprint.get("node_version", ""),
                "status": rs.status,
                "action": step_action(rs),
                "params_hash": rs.execution_fingerprint.get("params_hash", ""),
                "input_artifact_ids": rs.input_artifact_ids,
                "output_artifact_ids": rs.output_artifact_ids,
                "execution_fingerprint": rs.execution_fingerprint,
                "warnings": rs.warnings,
                "errors": rs.errors,
            }
            for rs in run_steps
        ],
    }

    if target_step_id is not None:
        manifest["target_step_id"] = target_step_id
    if in_scope_step_ids is not None:
        manifest["in_scope_step_ids"] = in_scope_step_ids

    return manifest


def write_manifest(
    store: ProjectStore,
    *,
    run_id: str,
    plan_version_id: str,
    execution_mode: str,
    branch_id: str | None = None,
    target_step_id: str | None = None,
    in_scope_step_ids: list[str] | None = None,
) -> None:
    """Read current run state and write a manifest artifact.

    The manifest is built directly from store state (run record + run
    steps), so *run_step_records* and *steps* are intentionally omitted
    from the signature — they are carried by ``RunFinalisation`` for
    future deterministic manifest construction, not used here yet.
    """
    run_record = store.get_run(run_id)
    if run_record is None:
        return

    run_steps = store.get_run_steps(run_id)

    payload = build_manifest_payload(
        run_id=run_id,
        plan_version_id=plan_version_id,
        run_record=run_record,
        run_steps=run_steps,
        execution_mode=execution_mode,
        branch_id=branch_id,
        target_step_id=target_step_id,
        in_scope_step_ids=in_scope_step_ids,
    )

    write_json_artifact(
        store,
        artifact_type="run_manifest",
        role="audit",
        stem=f"manifest-{run_id}",
        payload=payload,
        metadata={"run_id": run_id},
    )


# ---------------------------------------------------------------------------
# RunFinalisation — consolidated finish-run action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunFinalisation:
    """Captures everything needed to finalise a run (finish + manifest)."""
    run_id: str
    plan_version_id: str
    status: str
    execution_mode: str
    run_step_records: dict[str, RunStepRecord]
    steps: list[Any]

    # Per-mode metadata
    branch_id: str | None = None
    target_step_id: str | None = None
    in_scope_step_ids: list[str] | None = None


def finalise_run(
    store: ProjectStore,
    finalisation: RunFinalisation,
) -> None:
    """Finish a run with the given status and write its manifest.

    This is the single place where a run transitions from 'running'
    to its final state.  The ``run_step_records`` and ``steps`` fields
    on ``RunFinalisation`` are reserved for future deterministic
    manifest construction but are not yet forwarded to
    ``write_manifest``, which reads directly from store state.
    """
    store.finish_run(finalisation.run_id, finalisation.status)
    write_manifest(
        store,
        run_id=finalisation.run_id,
        plan_version_id=finalisation.plan_version_id,
        execution_mode=finalisation.execution_mode,
        branch_id=finalisation.branch_id,
        target_step_id=finalisation.target_step_id,
        in_scope_step_ids=finalisation.in_scope_step_ids,
    )


# ---------------------------------------------------------------------------
# RunLifecycle — stateful run lifecycle wrapper
# ---------------------------------------------------------------------------


class RunLifecycle:
    """Stateful wrapper around a single run's lifecycle lifecycle.

    Owns cancellation token registration/removal and run finalisation.
    The caller (PlanExecutor) checks ``raise_if_cancelled()`` between
    steps and calls ``finalise()`` in the finally block.
    """

    def __init__(
        self,
        store: ProjectStore,
        run_id: str,
        plan_version_id: str,
        token: CancellationToken,
    ) -> None:
        self.store = store
        self.run_id = run_id
        self.plan_version_id = plan_version_id
        self._token = token
        self._finalised = False

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def start(
        cls,
        store: ProjectStore,
        plan_version_id: str,
        run_id: str | None = None,
        branch_id: str | None = None,
    ) -> RunLifecycle:
        """Create or accept a run and register its cancellation token.

        When *run_id* is provided, the run must already exist in
        ``running`` state.
        """
        if run_id is None:
            run_id = store.create_run(plan_version_id, branch_id=branch_id)
        token = register_token(run_id)
        return cls(store=store, run_id=run_id, plan_version_id=plan_version_id, token=token)

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    @property
    def token(self) -> CancellationToken | None:
        return self._token

    def raise_if_cancelled(self) -> None:
        """Check cancellation before each step."""
        if self._token is not None:
            self._token.raise_if_cancelled()

    # ------------------------------------------------------------------
    # Finalisation
    # ------------------------------------------------------------------

    def finalise(
        self,
        status: str,
        execution_mode: str,
        run_step_records: dict[str, RunStepRecord],
        steps: list[Any],
        *,
        branch_id: str | None = None,
        target_step_id: str | None = None,
        in_scope_step_ids: list[str] | None = None,
    ) -> None:
        """Finish the run exactly once, remove the cancellation token,
        and write the run manifest."""
        if self._finalised:
            return
        self._finalised = True
        remove_token(self.run_id)
        finalise_run(self.store, RunFinalisation(
            run_id=self.run_id,
            plan_version_id=self.plan_version_id,
            status=status,
            execution_mode=execution_mode,
            run_step_records=run_step_records,
            steps=steps,
            branch_id=branch_id,
            target_step_id=target_step_id,
            in_scope_step_ids=in_scope_step_ids,
        ))


# ---------------------------------------------------------------------------
# RunScope — what to run, without execution semantics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunScope:
    """Describes which steps belong in a run and how they should be handled.

    This is a *planning* structure — it captures the mode decision
    (full / branch / to-node) and the set of steps in scope, but does
    not carry execution semantics (role enforcement, leakage rules, etc.).
    Those remain in ``PlanExecutor``.
    """
    mode: Literal["full", "branch", "to_node"]
    plan_version_id: str
    steps: list[Any]             # all steps in the plan version
    in_scope_step_ids: frozenset[str]
    force: bool = False
    branch_id: str | None = None
    target_step_id: str | None = None

    @classmethod
    def full_plan(
        cls,
        store: ProjectStore,
        plan_version_id: str,
        force: bool = False,
    ) -> RunScope:
        steps = store.get_plan_version_steps(plan_version_id)
        return cls(
            mode="full", plan_version_id=plan_version_id, steps=steps,
            in_scope_step_ids=frozenset(s.step_id for s in steps), force=force,
        )

    @classmethod
    def to_node(
        cls,
        store: ProjectStore,
        plan_version_id: str,
        target_step_id: str,
        force: bool = False,
    ) -> RunScope:
        steps = store.get_plan_version_steps(plan_version_id)
        from cardre.executor import PlanExecutor
        ancestors = PlanExecutor.find_ancestors(PlanExecutor, target_step_id, steps)  # noqa: SLF001
        closure = ancestors | {target_step_id}
        closure_steps = [s for s in steps if s.step_id in closure]
        return cls(
            mode="to_node", plan_version_id=plan_version_id, steps=closure_steps,
            in_scope_step_ids=frozenset(closure), force=force,
            target_step_id=target_step_id,
        )

    @classmethod
    def branch(
        cls,
        store: ProjectStore,
        plan_version_id: str,
        branch_id: str,
        force: bool = False,
    ) -> RunScope:
        steps = store.get_plan_version_steps(plan_version_id)
        branch = store.get_branch(branch_id)
        if branch is None:
            raise ValueError(f"Branch {branch_id} not found")
        step_map = store.get_branch_step_map(branch_id, plan_version_id)
        owned = {r["step_id"] for r in step_map if r.get("is_branch_owned")}
        return cls(
            mode="branch", plan_version_id=plan_version_id, steps=steps,
            in_scope_step_ids=frozenset(owned), force=force,
            branch_id=branch_id,
        )
