"""Run lifecycle module — generic run mechanics behind the PlanExecutor seam.

PlanExecutor remains the single execution seam.  This module owns generic
run lifecycle: manifest construction, final status, and guaranteed
finalisation.  It does not decide node semantics, role access,
leakage rules, or parent evidence resolution.

Cancellation was removed in the launch-simplification pass: no bundled
node polls the cancellation token during execution, so the mechanism
was deferred until long-running nodes need it.
"""

from __future__ import annotations

from dataclasses import dataclass


from cardre.artifacts import write_json_artifact
from cardre.audit import RunStepRecord, JsonDict, json_logical_hash, utc_now_iso
from cardre.errors import RunLifecycleError
from cardre.reporting.schema import RunManifest, RunManifestStep
from cardre.store import ProjectStore

MANIFEST_VERSION = "1.0.0"


def compute_manifest_hash(manifest: RunManifest) -> str:
    """Compute SHA-256 hash of the canonical manifest JSON with the hash field blanked."""
    payload = manifest.model_dump(mode="json", by_alias=False)
    payload["manifest_hash"] = ""
    return json_logical_hash(payload)

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
    final_status: str,
    finished_at: str,
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
        "finished_at": finished_at,
        "status": final_status,
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
    final_status: str,
    finished_at: str,
    branch_id: str | None = None,
    target_step_id: str | None = None,
    in_scope_step_ids: list[str] | None = None,
) -> None:
    """Read current run state and write a manifest artifact.

    The manifest is built directly from store state (run record + run
    steps).  ``RunFinalisation`` carries only the metadata needed for
    finalisation (status, mode, scope); the manifest payload is
    constructed from the store, not from the finalisation struct.
    """
    run_record = store.get_run(run_id)
    if run_record is None:
        raise RunLifecycleError(
            "Run record missing during manifest write.",
            code="RUN_RECORD_MISSING",
            context={"run_id": run_id},
        )

    run_steps = store.get_run_steps(run_id)

    payload = build_manifest_payload(
        run_id=run_id,
        plan_version_id=plan_version_id,
        run_record=run_record,
        run_steps=run_steps,
        execution_mode=execution_mode,
        final_status=final_status,
        finished_at=finished_at,
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

    _write_canonical_manifest(store, run_id, plan_version_id, run_record, run_steps,
                              execution_mode, final_status, finished_at, branch_id,
                              target_step_id, in_scope_step_ids, payload)


def _write_canonical_manifest(
    store: ProjectStore,
    run_id: str,
    plan_version_id: str,
    run_record: JsonDict,
    run_steps: list[RunStepRecord],
    execution_mode: str,
    final_status: str,
    finished_at: str,
    branch_id: str | None,
    target_step_id: str | None,
    in_scope_step_ids: list[str] | None,
    legacy_payload: JsonDict,
) -> None:
    """Write a canonical manifest.json (Pydantic-validated) alongside the legacy artifact.

    The manifest.json is the authoritative audit artefact with a self-referential
    manifest_hash.  The legacy run_manifest artifact continues to be written for
    backwards compatibility.
    """
    plan_id = legacy_payload.get("plan_id") or store.get_plan_id_for_version(plan_version_id) or ""
    pv = store.get_plan_version(plan_version_id)
    plan = store.get_plan(pv["plan_id"]) if pv else None
    project_id = plan.get("project_id", "") if plan else ""

    steps_model = []
    legacy_steps = legacy_payload.get("steps", [])
    for idx, rs in enumerate(run_steps):
        action = "unknown"
        if idx < len(legacy_steps):
            action = legacy_steps[idx].get("action", "unknown")
        step = RunManifestStep(
            step_id=rs.step_id,
            canonical_step_id=rs.execution_fingerprint.get("canonical_step_id", rs.step_id),
            node_type=rs.execution_fingerprint.get("node_type", ""),
            node_version=rs.execution_fingerprint.get("node_version", ""),
            status=rs.status,
            action=action,
            is_carried_forward=rs.is_carried_forward,
            started_at=rs.started_at,
            finished_at=rs.finished_at,
            params_hash=rs.execution_fingerprint.get("params_hash", ""),
            parent_step_ids=rs.execution_fingerprint.get("parent_step_ids", []),
            input_artifact_ids=rs.input_artifact_ids,
            output_artifact_ids=rs.output_artifact_ids,
            warnings=rs.warnings,
            errors=rs.errors,
            execution_fingerprint=rs.execution_fingerprint,
        )
        steps_model.append(step)

    manifest = RunManifest(
        manifest_version="cardre.run_manifest.v1",
        run_id=run_id,
        plan_version_id=plan_version_id,
        plan_id=plan_id,
        project_id=project_id,
        branch_id=branch_id,
        started_at=run_record.get("started_at", ""),
        finished_at=finished_at,
        status=final_status,
        execution_mode=execution_mode,
        cardre_version="0.1.0",
        pathway_hash="",
        artifact_root=str(store.root / "artifacts"),
        target_step_id=target_step_id,
        in_scope_step_ids=in_scope_step_ids or [],
        steps=steps_model,
        diagnostics=[],
    )
    manifest.manifest_hash = compute_manifest_hash(manifest)

    manifest_dir = store.root / "exports" / f"manifest-{run_id}"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2, by_alias=False)
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
    finished_at: str

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
    to its final state.  The manifest is written *before* the status
    transition so that a manifest write failure does not leave a run
    marked succeeded without audit material.
    """
    write_manifest(
        store,
        run_id=finalisation.run_id,
        plan_version_id=finalisation.plan_version_id,
        execution_mode=finalisation.execution_mode,
        final_status=finalisation.status,
        finished_at=finalisation.finished_at,
        branch_id=finalisation.branch_id,
        target_step_id=finalisation.target_step_id,
        in_scope_step_ids=finalisation.in_scope_step_ids,
    )
    store.finish_run(finalisation.run_id, finalisation.status)


# ---------------------------------------------------------------------------
# RunLifecycle — stateful run lifecycle wrapper
# ---------------------------------------------------------------------------


class RunLifecycle:
    """Stateful wrapper around a single run's lifecycle.

    Owns run finalisation and manifest writing. The caller (PlanExecutor)
    calls ``finalise()`` in a ``finally`` block or relies on the context
    manager to guarantee finalisation.

    Can be used as a context manager to guarantee finalisation::

        with RunLifecycle.start(store, pv_id) as lifecycle:
            ...
            lifecycle.finalise(status="succeeded", ...)

    If the body raises before ``finalise()`` is called, ``__exit__``
    finalises the run as ``failed`` using the execution mode and scope
    metadata supplied at construction time.
    """

    def __init__(
        self,
        store: ProjectStore,
        run_id: str,
        plan_version_id: str,
        execution_mode: str = "unknown",
        branch_id: str | None = None,
        target_step_id: str | None = None,
        in_scope_step_ids: list[str] | None = None,
    ) -> None:
        self.store = store
        self.run_id = run_id
        self.plan_version_id = plan_version_id
        self._finalised = False
        self._execution_mode = execution_mode
        self._branch_id = branch_id
        self._target_step_id = target_step_id
        self._in_scope_step_ids = in_scope_step_ids

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> RunLifecycle:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool | None:
        if not self._finalised:
            if exc_val is not None:
                import traceback
                self.store.append_run_diagnostic(self.run_id, {
                    "code": "RUN_BODY_EXCEPTION",
                    "message": f"{type(exc_val).__name__}: {exc_val}",
                    "severity": "error",
                    "category": "lifecycle",
                    "exception_type": type(exc_val).__name__,
                    "run_id": self.run_id,
                    "plan_version_id": self.plan_version_id,
                    "branch_id": self._branch_id,
                    "traceback": "".join(traceback.format_exception(type(exc_val), exc_val, exc_tb)),
                    "created_at": utc_now_iso(),
                })
            self.finalise(
                status="failed",
                execution_mode=self._execution_mode,
                branch_id=self._branch_id,
                target_step_id=self._target_step_id,
                in_scope_step_ids=self._in_scope_step_ids,
            )
        return None

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
        execution_mode: str = "unknown",
        target_step_id: str | None = None,
        in_scope_step_ids: list[str] | None = None,
        force: bool = False,
    ) -> RunLifecycle:
        """Create or accept a run.

        When *run_id* is provided, the run must already exist in
        ``running`` state.
        When *force* is True, the concurrent-run check is skipped.
        """
        if run_id is None:
            run_id = store.create_run(plan_version_id, branch_id=branch_id, force=force)
        else:
            existing_run = store.get_run(run_id)
            if existing_run is None:
                raise ValueError(f"Run {run_id} not found")
            if existing_run.get("status") != "running":
                raise ValueError(f"Run {run_id} is not in 'running' state (status={existing_run.get('status')})")
            if existing_run.get("plan_version_id") != plan_version_id:
                raise ValueError(f"Run {run_id} belongs to plan version {existing_run.get('plan_version_id')}, expected {plan_version_id}")
        return cls(
            store=store, run_id=run_id, plan_version_id=plan_version_id,
            execution_mode=execution_mode,
            branch_id=branch_id, target_step_id=target_step_id,
            in_scope_step_ids=in_scope_step_ids,
        )

    # ------------------------------------------------------------------
    # Finalisation
    # ------------------------------------------------------------------

    def finalise(
        self,
        status: str,
        execution_mode: str,
        *,
        branch_id: str | None = None,
        target_step_id: str | None = None,
        in_scope_step_ids: list[str] | None = None,
    ) -> None:
        """Finish the run exactly once and write the run manifest.

        ``_finalised`` is set only *after* ``finalise_run`` succeeds.
        If ``finalise_run`` raises, the run is marked ``failed`` directly
        so it is never left ``running``.
        """
        if self._finalised:
            return
        now = utc_now_iso()
        try:
            finalise_run(self.store, RunFinalisation(
                run_id=self.run_id,
                plan_version_id=self.plan_version_id,
                status=status,
                execution_mode=execution_mode,
                finished_at=now,
                branch_id=branch_id,
                target_step_id=target_step_id,
                in_scope_step_ids=in_scope_step_ids,
            ))
        except Exception:
            import traceback
            tb = traceback.format_exc()
            self.store.append_run_diagnostic(self.run_id, {
                "code": "RUN_FINALISATION_FAILED",
                "message": "Run finalisation failed.",
                "severity": "error",
                "category": "lifecycle",
                "run_id": self.run_id,
                "plan_version_id": self.plan_version_id,
                "branch_id": branch_id,
                "traceback": tb,
                "created_at": utc_now_iso(),
            })
            self.store.finish_run(self.run_id, "failed")
            raise
        self._finalised = True


