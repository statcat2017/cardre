# Extend PlanExecutor — Do Not Rewrite the Execution Core

> **Status: Superseded by [ADR-0014](0014-supersede-0002-authorise-hexagonal-re-encapsulation.md).**
> ADR-0014 authorises the hexagonal re-encapsulation and overturns this ADR's
> "extend, do not rewrite" conclusion. The preserved design commitments
> (dual hashing, computed staleness, build/validate role enforcement, settled
> vocabulary, single execution path) are reaffirmed in ADR-0014 and carried
> forward unchanged. This ADR is retained as a historical record of the
> incremental "deepening" programme and the reasoning that held the
> greenfield rewrite at bay until the structural validation of 2026-07-21
> showed the dependency direction itself was the problem.

A proposal was made to replace Cardre's execution system with a new
`cardre/engine/execution/runner.py` + planner, node registry, artifact store, and
metadata repositories under `cardre/engine/`. That plan frames the existing
execution paths as "scattered" and "ad hoc."

In reality Cardre already has one canonical execution core: `PlanExecutor`
(`cardre/executor.py`, 629 lines), supported by `NodeRegistry`, `ProjectStore`,
`staleness.py`, `topology.py`, a full SQLite schema, and a services layer. It is
used uniformly by tests, sidecar routes, and internal services. It already
delivers most of the proposed plan's acceptance criteria.

This ADR captures the decision to **extend** the existing `PlanExecutor` rather
than build a parallel execution stack.

## Considered Options

- **Greenfield rewrite under `cardre/engine/execution/`**: creates a new runner,
  planner, artifact store, node registry, and metadata repositories alongside
  the existing ones. Introduces competing terminology (`node instance` vs `Step`,
  `node run` vs `RunStepRecord`, `execution run` vs `run`), new DB tables
  (`execution_runs`, `node_runs`, `node_latest_outputs`), and a single-hash
  artifact model. Drops `role`/`category` from the node contract, dismantling
  structural leakage prevention. Migrating all callers and tests would be a
  multi-PR cost the plan does not acknowledge.

- **Extend the existing `PlanExecutor` and surrounding modules**: preserve the
  settled domain language (step, run, plan version), dual hashing
  (physical_hash + logical_hash), computed staleness, and role-enforced
  build/validate split. Add the genuine gaps the rewrite plan identifies: `to_node`
  and `force` run modes, live cancellation, a run-manifest artifact, a staleness
  endpoint, structured error categories, and an optional tighter node contract
  where the runner persists outputs. No schema migration, no terminology split,
  no regression on peer-reviewed design decisions.

## Decision

**Extend `PlanExecutor`.** The rewrite plan is rejected in favour of targeted
additions to the existing core. The rewrite plan shall instead be treated as a
gap-analysis checklist. Items from that checklist that the codebase lacks shall
be added to `PlanExecutor` incrementally.

## Preserved design commitments

These are non-negotiable and must survive all execution-core changes:

1. **Dual hashing** — `ArtifactRef` carries both `physical_hash` (raw file
   bytes, storage dedup) and `logical_hash` (canonical content, reproducibility).
   Single-hash models are a regression (`CONTEXT.md` "Artifact Hashing").

2. **Computed staleness** — `is_stale` is derived from fingerprints and
   parent-output logical hashes at query time. It is never cached as a stored
   column. A `node_latest_outputs` denormalised table would reintroduce the
   state-drift hazard the computed model was designed to eliminate (`CONTEXT.md`
   "Step Status: Stored vs Computed").

3. **Build/validate two-stream + role enforcement** — `NodeType` declares
   `category`, `input_roles`, `output_roles`. `PlanExecutor.validate_leakage_rules`
   hard-blocks fit/refinement/selection nodes from consuming `test`/`oot` dataset
   artifacts. The node executor interface must carry roles; any refactored
   contract must preserve `LEAKAGE_SENSITIVE_CATEGORIES` enforcement (`ADR 0001`).

4. **Settled vocabulary** — `StepSpec` (not "node instance"), `RunStepRecord`
   (not "node run"), `run`/`run_id` (not "execution run"), `plan_version_id`
   (not "pathway_id"), `PlanExecutor` (not "ExecutionRunner"). This vocabulary
   was explicitly settled in `CONTEXT.md`.

5. **Single execution path** — every test, service, and API handler executes
   nodes through `PlanExecutor`. No direct node-instantiation from API handlers
   or UI-specific services.

## Consequences

- **Three ship-immediately items**: `to_node`/`force` modes, staleness endpoint,
  live cancellation + `CancellationToken`. These are small, additive, and
  low-risk.

- **One medium refactor (needs its own ADR)**: tighter node contract where
  `PlanExecutor` persists artifacts on the node's behalf. The node returns
  typed payloads only. This improves contract hygiene but touches all ~40
  `NodeType` subclasses. Requires a migration strategy, not a single-PR rewrite.

- **Four structural items preserved as-is**: the existing DB schema,
  `ArtifactRef` dual hashing, the computed-staleness model, and the role-enforced
  two-stream executor.

- **The `cardre/engine/execution/` module tree is not created.** The existing
  `cardre/engine/binning/` (OptBinning adapter) remains alongside the existing
  `cardre/executor.py` rather than becoming one sub-package in a parallel
  execution tree.

## Subsequent refactor (consistent with this ADR)

A post-merge refactor deepened the PlanExecutor seam by extracting generic
run lifecycle mechanics into a new ``cardre/run_lifecycle.py`` module. This
module owns manifest construction, cancellation token lifecycle, and run
finalisation — concerns that are mode-independent and were previously
duplicated across the three public run methods (full-plan, branch, to-node).

The refactor is consistent with this ADR because:

- ``PlanExecutor`` remains the only public execution seam and is not renamed.
- No new public execution API or vocabulary was introduced (``run_plan_version``,
  ``run_branch``, ``run_to_node`` signatures are unchanged).
- The ``cardre/engine/execution/`` module tree was not created.
- Node execution semantics, role enforcement, leakage rules, and parent
  evidence resolution remain in ``PlanExecutor``.
- Every run still goes through ``PlanExecutor`` (single execution path).
