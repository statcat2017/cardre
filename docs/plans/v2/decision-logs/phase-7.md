# Phase 7 — Project scope guards + launch execution restoration

## Decisions

- Add registry-accessible fields to the health endpoint (`registry_accessible`,
  `registered_node_count`, `checked_at`); health check actually calls
  `load_registry()` so corrupt JSON is reported as inaccessible.
- Restore `store.finish_run()` backstop in background exception handlers via
  `_fail_run_if_running(store, run_id)` — the new helper checks run status
  before writing, preventing double-finish when the executor already wrote
  the final state.
- Align policy/architecture docs with current evidence and node module layout.
- Reformat manual-binning review and run-watch hooks.

## Rationale

Phase 7 was added post-hoc when the sidecar desktop integration revealed gaps:
the health endpoint didn't detect a corrupt registry, and background exception
handlers could double-finish a run. The finish-run backstop restores v1's
safety pattern without reintroducing the v1 run lifecycle.

## Changes Made

- Updated `cardre/api/routes/health.py` — added registry check fields.
- Restored finish_run backstop in `cardre/execution/run_lifecycle.py`.
- Regenerated OpenAPI types to include new health fields.
- Updated architecture docs (`docs/adr/`).

## Follow-ups For Next Phase

- Phase 8 closes the remaining Phase 3/4 DoD gaps: runs-table request columns,
  POST /projects bootstrap, manual-binning end-to-end proof, and the full
  scorecard API acceptance test.
