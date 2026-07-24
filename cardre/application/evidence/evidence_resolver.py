"""Evidence Resolver — the 4-stage fallback chain for run-step evidence.

Port of EvidenceLocator.resolve from cardre/evidence_locator.py.
Uses UnitOfWork ports instead of direct store access.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge, ResolvedEvidence
from cardre.domain.run import ExecutionFingerprint, RunStep, RunStepStatus
from cardre.domain.step import StepSpec


def _matches_fingerprint(rs: RunStep | None, spec: StepSpec | None) -> bool:
    if spec is None or rs is None:
        return True
    fp = rs.execution_fingerprint
    fp_typed = ExecutionFingerprint(
        params_hash=fp.get("params_hash", ""),
        node_type=fp.get("node_type", ""),
        node_version=fp.get("node_version", ""),
    )
    if fp_typed.params_hash != spec.params_hash:
        return False
    if fp_typed.node_type != spec.node_type:
        return False
    return fp_typed.node_version == spec.node_version


def _build_evidence_pairs(
    uow: Any,
    rs: RunStep,
) -> list[tuple[EvidenceEdge, list[EvidenceArtifact]]]:
    edges = uow.evidence.get_edges_for_run_step(rs.run_step_id)
    result: list[tuple[EvidenceEdge, list[EvidenceArtifact]]] = []
    for edge in edges:
        if edge.is_stale:
            continue
        artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
        result.append((edge, artifacts))
    return result


def resolve_evidence(
    uow: Any,
    plan_version_id: str,
    step_id: str,
    *,
    branch_id: str | None = None,
    plan_id: str | None = None,
    fingerprint_match: StepSpec | None = None,
) -> list[tuple[EvidenceEdge, list[EvidenceArtifact]]]:
    """Resolve evidence for a step through the 4-stage fallback chain.

    Stage 1: Branch-specific evidence via get_edges_for_plan_step_branch
    Stage 2: Full-plan evidence (fallback when branch_id is provided)
    Stage 3: Latest successful run for this plan_version_id
    Stage 4: Latest successful run across any version of the plan

    Stale edges (``is_stale = 1``) are rejected at each stage; the resolver
    continues to the next eligible candidate.  Edges are returned newest-first
    by the repository query (``ORDER BY r.finished_at DESC, e.created_at DESC``),
    so the first matching candidate is the most recent current evidence.

    Returns a list of (EvidenceEdge, list[EvidenceArtifact]) tuples.
    Returns an empty list if no evidence is found.
    """
    edges = uow.evidence.get_edges_for_plan_step_branch(
        plan_version_id, step_id, branch_id,
    )
    for edge in edges:
        if edge.is_stale:
            continue
        rs = uow.run_steps.get(edge.run_step_id)
        if rs is not None and _matches_fingerprint(rs, fingerprint_match):
            return _build_evidence_pairs(uow, rs)

    if branch_id is not None:
        edges = uow.evidence.get_edges_for_plan_step_branch(
            plan_version_id, step_id, None,
        )
        for edge in edges:
            if edge.is_stale:
                continue
            rs = uow.run_steps.get(edge.run_step_id)
            if rs is not None and _matches_fingerprint(rs, fingerprint_match):
                return _build_evidence_pairs(uow, rs)

    run_id = uow.runs.get_latest_successful_id(plan_version_id, branch_id=None)
    if run_id is not None:
        for rs in uow.run_steps.get_for_run(run_id):
            if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                if _matches_fingerprint(rs, fingerprint_match):
                    pairs = _build_evidence_pairs(uow, rs)
                    if pairs:
                        return pairs

    resolved_plan_id = plan_id
    if resolved_plan_id is None:
        resolved_plan_id = uow.plans.get_plan_id_for_version(plan_version_id)
    if resolved_plan_id is not None:
        run_id = uow.runs.get_latest_successful_id_for_plan(resolved_plan_id)
        if run_id is not None:
            for rs in uow.run_steps.get_for_run(run_id):
                if rs.step_id == step_id and rs.status == RunStepStatus.SUCCEEDED:
                    if _matches_fingerprint(rs, fingerprint_match):
                        pairs = _build_evidence_pairs(uow, rs)
                        if pairs:
                            return pairs

    return []


def resolve_run_step_evidence(
    uow: Any,
    plan_version_id: str,
    step_id: str,
    *,
    branch_id: str | None = None,
    plan_id: str | None = None,
    fingerprint_match: StepSpec | None = None,
) -> ResolvedEvidence | None:
    """Resolve one successful step and preserve how its evidence was found.

    ``resolve_evidence`` predates audit exports and returns only edge/artifact
    pairs.  Audit packs need the selected run step and provenance as well, so
    this companion preserves that information without making callers infer it
    from the returned edges.
    """
    candidates: list[tuple[RunStep | None, str]] = [
        (uow.run_steps.get_latest_successful_step(plan_version_id, step_id, branch_id), "branch")
    ]
    if branch_id is not None:
        candidates.append((uow.run_steps.get_latest_successful_step(plan_version_id, step_id, None), "full_plan"))
    resolved_plan_id = plan_id or uow.plans.get_plan_id_for_version(plan_version_id)
    if resolved_plan_id is not None:
        candidates.append((uow.runs.get_latest_successful_step_across_plan(resolved_plan_id, step_id), "across_plan"))

    for run_step, source_label in candidates:
        if run_step is None or not _matches_fingerprint(run_step, fingerprint_match):
            continue
        edges = uow.evidence.get_edges_for_run_step(run_step.run_step_id)
        non_stale_edges = [e for e in edges if not e.is_stale]
        # If all edges are stale (and there are edges), skip this candidate.
        if edges and not non_stale_edges:
            continue
        artifacts = [
            artifact
            for edge in non_stale_edges
            for artifact in uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
        ]
        return ResolvedEvidence(
            run_step_id=run_step.run_step_id,
            run_step=run_step,
            edges=non_stale_edges,
            artifacts=artifacts,
            source_label=source_label,
        )
    return None


__all__ = ["resolve_evidence", "resolve_run_step_evidence"]
