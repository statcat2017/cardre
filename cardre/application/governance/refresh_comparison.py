"""RefreshComparison — re-check branch readiness and create a new comparison snapshot.

Ports ``comparison_service.refresh_comparison`` into a single use case.
Uses ``EvidenceReaderPort`` (passed as a dependency) for typed evidence
lookup instead of a persistence store.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cardre.application.evidence.evidence_resolver import resolve_run_step_evidence
from cardre.application.evidence.explain_staleness import step_is_stale
from cardre.application.ports.artifact_store import DurableArtifactWriter
from cardre.application.reporting.contracts import REQUIRED_STEPS_COMPARISON
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError, ErrorCode, GovernanceNotEnabled
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_COMPARISON_ARTIFACT


@runtime_checkable
class ComparisonEvidencePort(Protocol):
    """Port for reading typed evidence needed by the comparison builders.

    Implementations resolve canonical step IDs through the
    branch-step-map, locate the relevant run-step evidence, and read
    the typed payload.
    """

    def find_typed(
        self,
        step_map: list[dict[str, Any]],
        canonical_step_id: str,
        plan_version_id: str,
        evidence_branch_id: str | None,
        kinds: tuple[EvidenceKind, ...],
    ) -> dict[str, Any] | None:
        ...


@dataclass
class RefreshComparisonCommand:
    project_id: str
    comparison_id: str


@dataclass
class RefreshComparisonResult:
    comparison_id: str
    comparison_snapshot_id: str | None = None
    ready: bool = False
    comparison_artifact_id: str | None = None
    refreshed_at: str = ""
    blocked_reason: str | None = None
    missing_or_stale: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ComparisonContentResult:
    content: dict[str, Any]
    artifact_id: str


class RefreshComparison:
    """Re-check branch readiness and create a new snapshot if ready."""

    def __init__(
        self,
        uow_factory: Any,
        evidence_port: ComparisonEvidencePort,
        artifact_writer: DurableArtifactWriter,
        publication_publisher_factory: Callable[[str], Any],
        governance_enabled: bool = True,
    ) -> None:
        self._uow_factory = uow_factory
        self._evidence_port = evidence_port
        self._artifact_writer = artifact_writer
        self._publication_publisher_factory = publication_publisher_factory
        self._governance_enabled = governance_enabled

    def __call__(self, command: RefreshComparisonCommand) -> RefreshComparisonResult:
        if not self._governance_enabled:
            raise GovernanceNotEnabled()

        publisher = self._publication_publisher_factory(command.project_id)

        with self._uow_factory.for_project(command.project_id) as uow:
            comparison = uow.comparisons.get_comparison(command.comparison_id)
            if comparison is None:
                raise CardreError(
                    f"COMPARISON_NOT_FOUND: {command.comparison_id}",
                    code=ErrorCode.COMPARISON_NOT_FOUND,
                    context={"comparison_id": command.comparison_id},
                    status_code=404,
                )

            project_id: str = comparison["project_id"]
            if project_id != command.project_id:
                raise CardreError(
                    "Comparison does not belong to the requested project.",
                    code=ErrorCode.BRANCH_SCOPE_MISMATCH,
                    context={"comparison_id": command.comparison_id, "project_id": command.project_id},
                    status_code=404,
                )
            plan_id: str = comparison["plan_id"]
            baseline_branch_id: str = comparison["baseline_branch_id"]
            spec = json.loads(comparison["comparison_spec_json"])
            challenger_rows = uow.comparisons.get_challenger_branches(command.comparison_id)
            challenger_ids = [r["branch_id"] for r in challenger_rows]

            baseline = uow.branches.get_branch(baseline_branch_id)
            if baseline is None:
                raise CardreError(
                    f"BRANCH_NOT_FOUND: baseline {baseline_branch_id}",
                    code=ErrorCode.BRANCH_NOT_FOUND,
                    context={"branch_id": baseline_branch_id},
                    status_code=404,
                )
            pv_id_baseline: str = baseline["head_plan_version_id"]

            # --- Readiness check ---
            all_missing: list[dict[str, str]] = self._check_readiness(
                uow, baseline_branch_id, pv_id_baseline, is_baseline=True,
            )
            for cid in challenger_ids:
                challenger = uow.branches.get_branch(cid)
                if challenger is None:
                    all_missing.append({"branch_id": cid, "canonical_step_id": "", "step_id": "", "status": "not_found"})
                    continue
                missing = self._check_readiness(uow, cid, challenger["head_plan_version_id"])
                all_missing.extend(missing)

            if all_missing:
                return RefreshComparisonResult(
                    comparison_id=command.comparison_id,
                    ready=False,
                    refreshed_at=utc_now_iso(),
                    blocked_reason="One or more branches have missing or stale evidence.",
                    missing_or_stale=all_missing,
                )

            # --- Build comparison content ---
            now = utc_now_iso()
            last_snapshot_id: str | None = None
            artifact_id: str | None = None
            pending_publishes: list[tuple[Any, str]] = []  # (staged, outbox_id)

            for cid in challenger_ids:
                challenger = uow.branches.get_branch(cid)
                if challenger is None:
                    continue
                pv_id_challenger: str = challenger["head_plan_version_id"]

                content = self._build_content(
                    uow, project_id,
                    pv_id_baseline, pv_id_challenger,
                    baseline_branch_id, cid, spec,
                )
                content["schema_version"] = SCHEMA_COMPARISON_ARTIFACT

                staged = self._artifact_writer.stage_json(
                    role="comparison",
                    kind=EvidenceKind.COMPARISON_ARTIFACT.value,
                    payload=content,
                    metadata={
                        "comparison_id": command.comparison_id,
                        "challenger_branch_id": cid,
                        "schema_version": SCHEMA_COMPARISON_ARTIFACT,
                    },
                )
                # Durable publication protocol: keep the file in staging until
                # the DB mutation commits. Register the descriptor + outbox row
                # in the same transaction as the snapshot rows; finalize the
                # file only after commit.
                dest = self._artifact_writer.dest_path(staged)
                artifact_id = uow.artifacts.register(ArtifactRef(
                    artifact_id=staged.provisional_artifact_id,
                    artifact_type=staged.artifact_type,
                    role=staged.role,
                    path=str(dest),
                    physical_hash=staged.physical_hash,
                    logical_hash=staged.logical_hash,
                    media_type=staged.media_type,
                    metadata=staged.metadata,
                ))
                outbox_id = uow.publications.enqueue_artifact(
                    run_id="",
                    plan_version_id=pv_id_challenger,
                    run_step_id="",
                    artifact_id=artifact_id,
                    physical_hash=staged.physical_hash,
                    storage_key=str(dest),
                    staging_source=str(staged.staging_path),
                )
                pending_publishes.append((staged, outbox_id))

                snapshot_id = uow.comparisons.create_snapshot(
                    command.comparison_id, project_id, plan_id,
                    artifact_id, json.dumps({"ready": True, "missing": []}),
                    created_reason="Comparison refresh",
                )
                uow.comparisons.add_snapshot_plan_version(
                    snapshot_id, pv_id_baseline, baseline_branch_id,
                )
                uow.comparisons.add_snapshot_plan_version(
                    snapshot_id, pv_id_challenger, cid,
                )

                last_snapshot_id = snapshot_id

            if last_snapshot_id is not None:
                uow.comparisons.set_latest_snapshot(
                    command.comparison_id, last_snapshot_id, ready=True,
                )

            uow.commit()

        # After the DB mutation committed, publish each comparison artifact via
        # the publication protocol (publisher owns finalize→mark). A failure
        # on one artifact does not block the others; the failing row is marked
        # 'failed' for reconciliation to retry.
        for staged, outbox_id in pending_publishes:
            try:
                publisher.publish(
                    outbox_id,
                    lambda staged=staged: self._artifact_writer.finalize(staged),
                )
            except Exception:
                continue

        return RefreshComparisonResult(
            comparison_id=command.comparison_id,
            comparison_snapshot_id=last_snapshot_id,
            ready=True,
            comparison_artifact_id=artifact_id,
            refreshed_at=now,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_readiness(
        self,
        uow: Any,
        branch_id: str,
        plan_version_id: str,
        *,
        is_baseline: bool = False,
    ) -> list[dict[str, str]]:
        step_map = uow.branches.get_step_map(branch_id, plan_version_id)
        canon_to_actual: dict[str, str] = {}
        for row in step_map:
            canon_to_actual[row["canonical_step_id"]] = row["step_id"]

        missing: list[dict[str, str]] = []
        plan_id = uow.plans.get_plan_id_for_version(plan_version_id)
        steps = uow.plans.get_version_steps(plan_version_id)
        specs = {step.step_id: step for step in steps}
        for cs in REQUIRED_STEPS_COMPARISON:
            actual_id = canon_to_actual.get(cs, cs)
            resolved = resolve_run_step_evidence(
                uow, plan_version_id, actual_id,
                branch_id=None if is_baseline else branch_id,
                plan_id=plan_id, fingerprint_match=specs.get(actual_id),
            )
            stale = resolved is not None and specs.get(actual_id) is not None and step_is_stale(
                uow, specs[actual_id], steps, plan_version_id,
                None if is_baseline else branch_id, plan_id,
            )
            if resolved is None or stale:
                missing.append({
                    "branch_id": branch_id,
                    "canonical_step_id": cs,
                    "step_id": actual_id,
                    "status": "stale" if stale else "not_run",
                })
        return missing

    def _build_content(
        self,
        uow: Any,
        project_id: str,
        pv_id_baseline: str,
        pv_id_challenger: str,
        branch_id_baseline: str,
        branch_id_challenger: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        from cardre.application.governance.comparison_builders import build_content

        step_map_baseline = uow.branches.get_step_map(branch_id_baseline, pv_id_baseline)
        step_map_challenger = uow.branches.get_step_map(branch_id_challenger, pv_id_challenger)

        return build_content(
            self._evidence_port.find_typed,
            step_map_baseline, step_map_challenger,
            pv_id_baseline, pv_id_challenger,
            branch_id_baseline, branch_id_challenger,
            spec,
        )

