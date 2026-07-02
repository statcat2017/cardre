# Phase 5 — Launch scorecard pathway + reporting + exports

## Decisions

- Wire 13 launch node types from `cardre/nodes/registry.py` into the full
  import-to-export pathway.
- `test_launch_pathway.py` is the executor-driven acceptance test: asserts
  `evidence_edges` + `evidence_artifacts` rows for every step, staleness
  explanation correct, manifest complete.
- Report services (`report_service.py`, `export_service.py`) ported from v1.
- `EvidenceResolver` extended to return `ResolvedEvidence` with run_step +
  edges + artifacts (from Phase 4's extended contract).

## Rationale

The real running-code pressure test for the Phase 1 evidence schema. Phase 1's
paper abort criterion (can `evidence_edges` + `evidence_artifacts` represent
multi-artifact per-parent staleness?) is now validated against a real run.

## Changes Made

- Ported launch nodes from v1 `cardre/nodes/build/` and `cardre/nodes/validate/`.
- Wired 13-node DAG: import → profile → validate-target → split →
  fine-classing → calculate-woe-iv → variable-selection → manual-binning →
  woe-transform → logistic-regression → score-scaling → validation-metrics →
  cutoff-analysis → technical-manifest-export.
- Created `cardre/services/report_service.py`, `export_service.py`.
- Created `tests/test_launch_pathway.py`, `tests/test_node_registry_tiers.py`.

## Follow-ups For Next Phase

- Phase 5 completes the full launch pathway but without governance services
  or deferred nodes. Phase 6 adds those and runs the full `make preflight`.
