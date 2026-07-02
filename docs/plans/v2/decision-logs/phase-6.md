# Phase 6 — Governance + deferred nodes + final cleanup

## Decisions

- Branch/comparison/champion services ported from v1 to work against the
  two-level evidence tables (`evidence_edges`, `evidence_artifacts`).
- Deferred ML nodes (boosting, ensembles, ML models, tuning, explainability,
  fairness, reject-inference) registered as `tier="deferred"` — visible as
  schemas, non-executable in launch mode.
- `tests_v1/` reference directory deleted.
- No test reads env vars directly; all go through `CardreConfig.from_env()`.
- No queryable JSON relationship arrays remain (`grep` zero).

## Rationale

Governance features need to work against the new evidence tables (not JSON).
Full `make preflight` is the merge gate; this phase gets it green.

## Changes Made

- Created `cardre/services/{branch,comparison,champion}_service.py`.
- Ported deferred nodes; registered with `tier="deferred"`.
- Deleted `tests_v1/` reference directory.
- Updated `CONTEXT.md` with v2 domain language.
- Ran `grep` sweeps for env-var-in-test and JSON-array-column violations.

## Follow-ups For Next Phase

- Full `make preflight` green. The v2 branch is structurally ready for main,
  but three Phase 3/4 DoD items were deferred: (1) runs-table request columns
  as real columns, (2) POST /projects bootstraps a fresh store, (3) full
  scorecard API-level acceptance test. These are Phase 7/8.
