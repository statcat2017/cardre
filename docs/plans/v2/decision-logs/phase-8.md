# Phase 8 — v2 acceptance completion

## Decisions

- **runs-table request columns (Batch A):** Add `run_scope`, `requested_by`,
  `request_id`, `created_at`, `queued_at` as real columns on the `runs` table.
  `RunRepository.create()` persists them; `execute_created_run()` reads from
  columns, not `metadata_json`. `metadata_json` is now execution metadata only.
- **POST /projects bootstrap (Batch B):** `POST /projects` now accepts a `path`
  field in the body and calls `ProjectStore.initialize()` to bootstrap a fresh
  `.cardre` store. Existing stores via `X-Project-Path` header still work.
- **Manual-binning lifecycle proof (Batch C):** End-to-end API test proving:
  edit → draft version → review row → affected-downstream hint → staleness
  on draft → approve → commit → staleness still missing. Documented
  `affected_downstream_step_ids_json` as non-authoritative UI hint.
- **Full scorecard API acceptance test (Batch D):**
  `test_api_scorecard_launch_pathway.py` drives the 15-node scorecard pathway
  through the project-scoped API. Fixed 4 bugs surfaced by the test:
  - `DefineModellingMetadataNode` was missing from launch tier registration.
  - Parquet media type corrected to `application/vnd.apache.parquet`.
  - Evidence reader `find_optional` catches `AmbiguousEvidenceError`.
  - Executor `_json_ready` handles `numpy.bool_` from logistic regression.
- **Decision logs (Batch E):** Retroactive logs for phases 1–8; update
  `PHASES.md`; add post-merge corrections to original plan doc.

## Rationale

These were Phase 3/4 DoD items that slipped. Without them the v2 branch was
structurally complete but not acceptance-testable through the API.

## Changes Made

- `cardre/store/schema.py` — added 5 columns to `runs` table.
- `cardre/store/run_repo.py` — extended `RunRepository.create()`.
- `cardre/services/run_coordinator.py` — rewrote recovery to read columns.
- `cardre/api/routes/projects.py` — POST /projects bootstraps fresh store.
- `cardre/api/schemas.py` — added `path` field to `ProjectCreateRequest`.
- `cardre/nodes/registry.py` — registered `DefineModellingMetadataNode` in launch tier.
- `cardre/_evidence/reader.py` — catch `AmbiguousEvidenceError`.
- `cardre/execution/executor.py` — `_json_ready` handles `numpy.bool_`.
- `cardre/artifacts.py` — parquet media type fix.
- `tests/test_api_scorecard_launch_pathway.py` — new (the headline deliverable).
- `tests/test_store_runs_request_columns.py` — new schema-column assertion.
- `tests/test_run_repo_request_fields.py` — new create-and-recover assertion.
- `tests/test_api_projects.py` — extended with fresh-bootstrap tests.
- `tests/test_api_manual_binning.py` — extended with lifecycle test.
- `docs/plans/v2/decision-logs/phase-{1..8}.md` — retroactive logs.
- `PHASES.md` — updated to 8-phase retrospective.

## Follow-ups For Next Phase

- Phase 8 completes the v2 plan. The next step is merging `v2` → `main`
  via `scripts/pr-gate.sh --base main`.
