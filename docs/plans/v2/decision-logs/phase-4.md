# Phase 4 — Full project-scoped API + generated frontend types

## Decisions

- All routes under `/projects/{project_id}/...`. Plans and plan-versions are
  distinct route concepts (`/plans/{plan_id}/versions`, `/plan-versions/{pv_id}`).
- Governance gating via `Depends(require_governance)` returning 403, not via
  conditional router registration.
- `frontend/src/types.ts` removed; generated types from OpenAPI only.
- Error envelope consistent across all routes (`CardreApiError` with `detail.code`).
- `EvidenceResolver` return type extended to `ResolvedEvidence` bundling
  `EvidenceEdge`/`EvidenceArtifact` objects; executor consumes pre-built evidence.

## Rationale

Consistent project-scoped API with generated types eliminates drift between
backend and frontend schemas. Governance is a DI concern, not routing.

## Changes Made

- Expanded `cardre/api/routes/` to 13 route modules (projects, plans, runs,
  artifacts, evidence, manual_binning, branches, comparisons, champion,
  exports, reports, node_types, health).
- Extended `cardre/api/schemas.py` and `cardre/api/errors.py`.
- Removed `frontend/src/types.ts`; regenerated `schema.d.ts` from OpenAPI.
- Extended `EvidenceResolver` return type.

## Follow-ups For Next Phase

- Phase 5 wires the launch nodes and tests the full pathway. The API skeleton
  is ready; routing needs no structural changes.
