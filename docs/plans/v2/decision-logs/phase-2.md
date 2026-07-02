# Phase 2 — Delete compat shims + manual-binning domain + minimal API/UI spike

## Decisions

- Delete `cardre/audit.py`, `cardre/evidence.py`, `cardre/evidence_locator.py`,
  `cardre/step_id.py`. Remove `Result/Ok/Degraded` from `cardre/errors.py`.
- Repoint 33+ importers from `cardre.audit` to `cardre.domain.*`.
- Manual-binning edits create a new draft plan version; historical evidence
  rows are **never** mutated.
- `affected_downstream_step_ids_json` on `manual_binning_reviews` is a
  non-authoritative UI hint; authoritative answer is `StalenessService`.
- Minimal API skeleton: `/projects`, `/projects/{id}/manual-binning/reviews`.
- UI spike (`ManualBinningEditorSpike.tsx`) proves end-to-end flow.

## Rationale

Manual binning early validates the domain model against a real UI before the
execution layer exists. No compat shims keep the codebase clean.

## Changes Made

- Deleted 4 compat modules; repointed 33 importers across nodes, readers,
  reporting, readiness, tests.
- Created `cardre/services/plan_mutation_service.py`.
- Created `cardre/api/app.py`, `dependencies.py`, `routes/{health,projects,manual_binning}.py`.
- Created `frontend/src/components/ManualBinningEditorSpike.tsx`.

## Follow-ups For Next Phase

- Phase 2 uses fixture-inserted evidence (no real run layer yet). Integration
  issues with real evidence may surface in Phase 3 or 5 — budget a revisit.
