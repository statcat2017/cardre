# Phase 6 — Facade Removal (DEFERRED — Not This Sprint)

**Sprint:** `docs/plans/legacy-compat-removal-sprint.md`
**Phase goal:** *Recorded for sequencing only.* This phase is deliberately
out of scope for the legacy-compat-removal sprint. It documents the migration
path so a future sprint can execute it without re-doing the audit.

## Why deferred

The source report explicitly says **do not immediately delete**
`cardre/evidence.py`, and recommends the `cardre/nodes/__init__.py` facade be
refactored **gradually**. Both facades have very large fan-in: deleting them
without migrating every consumer first would break the build across nodes,
reporting, readiness, sidecar, and services.

This sprint (Phases 1-5) removes all the *low-fan-in* compatibility code. The
two high-fan-in facades are left intact and are captured here as a sequenced
follow-up.

## 6.A — `cardre/evidence.py` facade removal

### Current state
`cardre/evidence.py` (171 lines) re-exports the `cardre/_evidence/*` subpackage:
- 35 `SCHEMA_*` constants from `cardre._evidence.schemas` (+ `SCHEMA_BIN_DEFINITION`
  from `cardre.engine.binning.definition`).
- `EvidenceKind` and error classes from `cardre._evidence.kinds`.
- 29 evidence model classes from `cardre._evidence.models`.
- `ArtifactEvidenceReader` from `cardre._evidence.reader`.
- `EVIDENCE_PROFILES` from `cardre._evidence.profiles` (re-exported as private
  `_EVIDENCE_PROFILES`).

It is purely re-exports — zero implementation.

### Fan-in (from the pre-sprint audit)
**62 import sites**: 30 in production code, 32 in tests.

Production consumers (each imports multiple names from `cardre.evidence`):
- `cardre/nodes/calibrate.py`, `cardre/nodes/build/models.py`,
  `cardre/nodes/build/bins.py`, `cardre/nodes/build/clustering.py`,
  `cardre/nodes/build/features.py`, `cardre/nodes/build/selection.py`,
  `cardre/nodes/build/export.py`, `cardre/nodes/build/freeze.py`,
  `cardre/nodes/build/auto_binning_fit.py`, `cardre/nodes/prep.py`,
  `cardre/nodes/validate/apply.py`, `cardre/nodes/validate/analyse.py`,
  `cardre/nodes/explainability.py`, `cardre/nodes/fairness.py`,
  `cardre/nodes/ensembles.py`, `cardre/nodes/feature_selection.py`,
  `cardre/nodes/reject_inference.py`, `cardre/nodes/_training_utils.py`,
  `cardre/reporting/collector.py`, `cardre/readiness/check.py`,
  `cardre/modeling/adapters.py`, `sidecar/routes/runs.py`,
  `sidecar/routes/artifacts.py`, `sidecar/routes/evidence.py`,
  `sidecar/routes/method_summary.py`, `cardre/services/comparison_service.py`,
  `cardre/services/manual_binning_service.py`.

### Migration path (for a future sprint)
1. **Per-area migration PRs.** Migrate one node area at a time (e.g. all
   `cardre/nodes/build/*.py` in one PR; `cardre/nodes/validate/*.py` in
   another; sidecar routes in another). Each PR rewrites
   `from cardre.evidence import X, Y` → `from cardre._evidence.<submodule>
   import X, Y`, using the direct subpackage paths:
   - schemas → `cardre._evidence.schemas` (and `cardre.engine.binning.definition`
     for `SCHEMA_BIN_DEFINITION`)
   - kinds/errors → `cardre._evidence.kinds`
   - models → `cardre._evidence.models`
   - reader → `cardre._evidence.reader`
   - profiles → `cardre._evidence.profiles`
2. **Tests.** Migrate the 32 test import sites in the same PRs (or a dedicated
   test-migration PR at the end).
3. **Verify zero internal consumers.** After all migrations, `rg "from
   cardre.evidence import|import cardre.evidence"` must return zero matches
   in `cardre/`, `sidecar/`, and `tests/`.
4. **Decision point.** Once zero internal consumers remain, either:
   - **(a)** keep `cardre/evidence.py` as a thin *public* API surface (document
     it as the supported import path for external integrators), or
   - **(b)** delete it entirely. Under ADR 0003 (no external consumers yet),
     deletion is safe.
5. **`make preflight`** + `scripts/pr-gate.sh` per PR.

### Risk
Low per-PR (mechanical import rewrite), but high total churn across ~62 sites.
The danger is a typo'd import or a missed re-export name. Mitigate with the
focused test suite per area.

## 6.B — `cardre/nodes/__init__.py` facade removal

### Current state
`cardre/nodes/__init__.py` (152 lines) re-exports ~55 node classes and 2
helper functions from 11 submodules (`cardre.nodes.prep`, `cardre.nodes.build`,
`cardre.nodes.ml_models`, `cardre.nodes.boosting`, `cardre.nodes.calibrate`,
`cardre.nodes.explainability`, `cardre.nodes.ensembles`, `cardre.nodes.tuning`,
`cardre.nodes.reject_inference`, `cardre.nodes.fairness`,
`cardre.nodes.feature_selection`, `cardre.nodes.validate`).

### Fan-in
**41+ import sites**, notably:
- `cardre/registry.py:172` (`_register_launch_nodes`) and `:251`
  (`_register_deferred_nodes`) — import *all* node classes from the facade.
- `cardre/__init__.py:32-58` — re-exports a subset of launch-tier nodes from
  the facade.
- `cardre/services/manual_binning_service.py`, `cardre/services/plan_service.py`,
  and others.

### Migration path (for a future sprint)
1. **Rewrite `registry.py`** to import each node class from its direct
   submodule path:
   - `ProfileDatasetNode` → `cardre.nodes.prep`
   - `LogisticRegressionNode` → `cardre.nodes.build.models`
   - `ApplyModelNode` → `cardre.nodes.validate.apply`
   - `XGBoostClassifierNode` → `cardre.nodes.boosting`
   - `VotingEnsembleNode` → `cardre.nodes.ensembles`
   - etc.
   The full mapping is derivable from the `__all__` in `cardre/nodes/__init__.py`.
2. **Rewrite `cardre/__init__.py`** re-exports to direct submodule paths.
3. **Rewrite remaining service/consumer imports** the same way.
4. **Verify** `rg "from cardre.nodes import|from cardre import .*Node"`
   returns zero matches (outside `cardre/nodes/__init__.py` itself).
5. **Delete `cardre/nodes/__init__.py`** (or reduce it to a minimal package
   docstring) once zero consumers remain.
6. **`make preflight`** + `scripts/pr-gate.sh`.

### Risk
Medium. `registry.py` is load-bearing for node discovery; a wrong import path
breaks node registration. Mitigate by running the full node-registration test
suite after each rewrite.

## 6.C — Remaining `_legacy_match()` branches (deferred-tier kinds)

The following kinds were not audited for writer `schema_version` emission in
this sprint (their writers live in deferred-tier nodes not yet covered):
`REPORT_BUNDLE`, `COMPARISON_ARTIFACT`, `FEATURE_SELECTION_EVIDENCE`,
`RESAMPLING_EVIDENCE`, `HYPERPARAMETER_TUNING_EVIDENCE`, `ENSEMBLE_MODEL_ARTIFACT`,
`EXPLAINABILITY_REPORT`, `FAIRNESS_REPORT`, `PROXY_RISK_REPORT`,
`MANUAL_BINNING_OVERRIDES`.

A future sprint should:
1. Audit each kind's writer(s) for `schema_version` emission (same method as
   Phase 4).
2. Fix any gaps (add `schema_version` to metadata).
3. Add Phase-1 regression tests.
4. Remove the corresponding `_legacy_match()` branch.

## Definition of done for this phase (when eventually executed)

- [ ] Zero `from cardre.evidence import` / `import cardre.evidence` in
      `cardre/`, `sidecar/`, `tests/`.
- [ ] Zero `from cardre.nodes import` / facade re-exports in consumers.
- [ ] `cardre/evidence.py` deleted or explicitly retained as a documented
      public API.
- [ ] `cardre/nodes/__init__.py` deleted or reduced to a package marker.
- [ ] All deferred-tier `_legacy_match()` branches removed after their writer
      audits.
- [ ] `make preflight` green; CI green.

## How this relates to the current sprint

Phases 1-5 of the legacy-compat-removal sprint deliberately do **not** touch
`cardre/evidence.py` or `cardre/nodes/__init__.py`. Any new code written in
Phases 1-5 should prefer the canonical `cardre._evidence.*` import path
(where a file already imports it) to avoid increasing the facade's fan-in —
but do **not** add a new `cardre.evidence` import to a file that doesn't
already use it, and do **not** migrate existing facade imports as part of
Phases 1-5 (that's this phase's job, in a separate sprint).