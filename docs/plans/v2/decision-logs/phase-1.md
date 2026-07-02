# Phase 1 — Domain kernel + relational store

## Decisions

- Domain kernel (`cardre/domain/`) has zero I/O dependencies: no node registry,
  store, FastAPI, or modelling deps. `NodeType` lives in `cardre/nodes/contracts.py`.
- `CardreConfig` (reads env vars) lives in `cardre/config.py`, not in domain.
- Store uses `evidence_edges` + `evidence_artifacts` two-level model (not a
  single `evidence_resolution` table) to cleanly represent per-edge staleness.
- `plan_step_edges` replaces v1's `plan_steps.parent_step_ids_json`.
- `store_meta` records `schema_family=cardre-v2`, `schema_version=100`;
  opening incompatible stores is a hard error (no migration code).
- No queryable JSON arrays on relationship tables (principle 5).

## Rationale

Fresh v2 branch with no users means no backwards-compat; clean relational
schema for evidence lineage; hard version check as safety, not migration.

## Changes Made

- Created `cardre/domain/` with `project.py`, `plan.py`, `step.py`, `run.py`,
  `evidence.py`, `manual_binning.py`, `artifacts.py`, `errors.py`,
  `diagnostics.py`, `__init__.py`.
- Created `cardre/store/schema.py` (`STORE_SCHEMA_VERSION=100`) and all repo
  files (project_repo, plan_repo, step_repo, run_repo, etc.).
- Created `cardre/nodes/contracts.py`, `cardre/config.py`,
  `cardre/capabilities.py`, `cardre/execution/context.py`.
- V1 code deleted except reusable infrastructure (nodes/, engine/, etc.).

## Follow-ups For Next Phase

- Phase 1 schema is paper-checked; real acceptance test deferred to Phase 5.
  Phase 2 should read the schema decisions before building mutation service.
