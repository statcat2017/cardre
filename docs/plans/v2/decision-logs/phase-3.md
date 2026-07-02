# Phase 3 — Execution layer: RunCoordinator + EvidenceResolver + StalenessService

## Decisions

- `RunCoordinator` is the single run entrypoint (renamed from v1 `RunService`).
  Sync and async dispatch produce equivalent `evidence_edges`/`evidence_artifacts`.
- `execute_created_run(run_id)` recovers `run_scope`, `branch_id`,
  `target_step_id`, `force` from `runs` table columns, not `metadata_json`.
- Evidence rows are persisted **per run-step inside the run transaction**, not
  just at finalisation (crash safety).
- `RunStep` (domain) owns only execution metadata; artifact arrays are derived
  via `RunStepEvidenceView` from `evidence_artifacts` + `artifact_lineage`.
- Staleness reads from `evidence_edges` + `evidence_artifacts`, not
  `run_steps.execution_fingerprint_json`.
- Clean up dead store-repo methods (`save_step`, `get_artifact_ids_for_run`,
  `get_artifact_ids_for_producing_step`); remove v1 column-introspection
  branches from `plan_repo.py`; move concurrent-run rejection to `RunCoordinator`.

## Rationale

Persisting request fields in `runs` columns enables async recovery without
requiring a `RunExecutionRequest` argument at resume. Per-step evidence
persistence inside the transaction means finalisation failure doesn't lose
evidence. The `RunStep`/`RunStepEvidenceView` split keeps the domain clean.

## Changes Made

- Created `cardre/execution/{executor,run_lifecycle,worker,action_planner,dispatcher}.py`.
- Created `cardre/services/run_coordinator.py`, `evidence_resolver.py`,
  `staleness_service.py`.
- Cleaned up `cardre/store/run_repo.py` (dead methods) and `plan_repo.py`
  (v1 branches).
- Ported characterization tests from `tests_v1/`.

## Follow-ups For Next Phase

- Real sync/async equivalence test and per-step evidence persistence test
  are in place. Phase 4 builds the full API on this execution layer.
